from __future__ import annotations

import argparse
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import re
from typing import Sequence

from .display_common import describe_contract, extract_contract_expiration, extract_underlying_symbol
from .parse_orders import DEFAULT_ORDERS_CSV, RealizedTrade, compute_realized_trades, filter_orders_by_date, load_orders

POLYGON_API_BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT / "modules" / "analysis" / "order-data" / "trade-hold-review-2025-01-01-to-2026-05-15.json"
)


@dataclass
class LaterOutcome:
    had_later_data: bool
    later_became_profitable: bool | None
    later_improved_pnl: bool | None
    later_beat_pre_exit_peak_pnl: bool | None
    pre_exit_peak_date: str | None
    pre_exit_peak_price: float | None
    pre_exit_peak_pnl: float | None
    best_case_exit_date: str | None
    best_case_exit_price: float | None
    best_case_pnl: float | None
    data_window_end: str | None
    analysis_status: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export trade profitability review JSON.")
    parser.add_argument("--start-date", default="2025-01-01", help="Inclusive trade open/close filter start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2026-05-15", help="Inclusive trade open/close filter end date (YYYY-MM-DD)")
    parser.add_argument("--csv", type=Path, default=DEFAULT_ORDERS_CSV, help="Orders CSV path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="JSON output path")
    parser.add_argument("--throttle-seconds", type=float, default=0.0, help="Delay between Polygon requests")
    parser.add_argument(
        "--exclude-same-day-trades",
        action="store_true",
        help="Exclude trades where open_date and close_date are the same day.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date > end_date:
        raise ValueError("start-date must be on or before end-date")

    orders = load_orders(args.csv)
    filtered_orders = filter_orders_by_date(orders, start_date, end_date)
    all_realized_trades = compute_realized_trades(filtered_orders)
    excluded_short_trade_count = sum(1 for trade in all_realized_trades if trade.direction == "short")
    candidate_trades = [trade for trade in all_realized_trades if _should_analyze_trade(trade)]
    excluded_same_day_trade_count = sum(1 for trade in candidate_trades if _is_same_day_trade(trade))
    realized_trades = [
        trade
        for trade in candidate_trades
        if not (args.exclude_same_day_trades and _is_same_day_trade(trade))
    ]

    grouped_trades = _group_trades_by_symbol(realized_trades)
    api_key = _get_polygon_api_key()
    option_bars_by_symbol: dict[str, list[dict[str, object]] | None] = {}

    symbols = sorted(grouped_trades.keys())
    for index, symbol in enumerate(symbols, start=1):
        if not symbol or extract_contract_expiration(symbol) is None:
            option_bars_by_symbol[symbol] = None
            continue
        option_bars_by_symbol[symbol] = _fetch_option_bars(symbol, grouped_trades[symbol], api_key)
        if args.throttle_seconds and index < len(symbols):
            time.sleep(args.throttle_seconds)

    profitable_trades: list[dict[str, object]] = []
    unprofitable_trades: list[dict[str, object]] = []

    for trade in _sort_trades(realized_trades):
        outcome = _analyze_later_outcome(trade, option_bars_by_symbol.get(trade.symbol))
        payload = _serialize_trade(trade, outcome)
        if trade.pnl >= 0:
            profitable_trades.append(payload)
        else:
            unprofitable_trades.append(payload)

    output = {
        "metadata": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_realized_trade_count": len(all_realized_trades),
            "analyzed_trade_count": len(realized_trades),
            "excluded_short_trade_count": excluded_short_trade_count,
            "excluded_same_day_trade_count": (
                excluded_same_day_trade_count if args.exclude_same_day_trades else 0
            ),
            "exclude_same_day_trades": args.exclude_same_day_trades,
            "analysis_scope": "Only long option contracts are included. Short option legs are excluded.",
        },
        "profitable_trades": profitable_trades,
        "unprofitable_trades": unprofitable_trades,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote trade hold review to {args.output}")
    print(f"Profitable trades: {len(profitable_trades)}")
    print(f"Unprofitable trades: {len(unprofitable_trades)}")


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _group_trades_by_symbol(trades: Sequence[RealizedTrade]) -> dict[str, list[RealizedTrade]]:
    grouped: dict[str, list[RealizedTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol].append(trade)
    return grouped


def _fetch_option_bars(symbol: str, trades: Sequence[RealizedTrade], api_key: str) -> list[dict[str, object]]:
    expiration = extract_contract_expiration(symbol)
    if expiration is None:
        return []
    start_date = min(trade.open_date for trade in trades)
    end_date = expiration
    ticker = f"O:{symbol}"
    encoded_ticker = urllib.parse.quote(ticker, safe="")
    query = urllib.parse.urlencode({"apiKey": api_key, "limit": 50000})
    url = (
        f"{POLYGON_API_BASE_URL}/{encoded_ticker}/range/1/day/"
        f"{start_date.isoformat()}/{end_date.isoformat()}?{query}"
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            results = payload.get("results")
            if not isinstance(results, list):
                return []
            return results
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Polygon option request failed for {symbol}: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Polygon option request failed for {symbol}: {exc}") from exc
        except TimeoutError as exc:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Polygon option request timed out for {symbol}: {exc}") from exc
        except socket.timeout as exc:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Polygon option request timed out for {symbol}: {exc}") from exc
    return []


def _analyze_later_outcome(trade: RealizedTrade, bars: list[dict[str, object]] | None) -> LaterOutcome:
    expiration = extract_contract_expiration(trade.symbol)
    if not trade.symbol:
        return LaterOutcome(False, None, None, None, None, None, None, None, None, None, None, "missing_symbol")
    if expiration is None:
        return LaterOutcome(False, None, None, None, None, None, None, None, None, None, None, "non_option_symbol")
    if trade.trade_date >= expiration:
        pre_exit_peak = _analyze_pre_exit_peak(trade, bars or [])
        return LaterOutcome(
            False,
            None,
            None,
            None,
            pre_exit_peak["date"],
            pre_exit_peak["price"],
            pre_exit_peak["pnl"],
            None,
            None,
            None,
            expiration.isoformat(),
            "exited_on_or_after_expiration",
        )
    if not bars:
        return LaterOutcome(False, None, None, None, None, None, None, None, None, None, expiration.isoformat(), "no_later_option_data")

    pre_exit_peak = _analyze_pre_exit_peak(trade, bars)

    later_bars = [
        bar for bar in bars
        if _parse_bar_date(bar.get("t")) > trade.trade_date and _parse_bar_date(bar.get("t")) <= expiration
    ]
    if not later_bars:
        return LaterOutcome(
            False,
            None,
            None,
            None,
            pre_exit_peak["date"],
            pre_exit_peak["price"],
            pre_exit_peak["pnl"],
            None,
            None,
            None,
            expiration.isoformat(),
            "no_later_option_data",
        )

    best_exit_date: date | None = None
    best_exit_price: float | None = None
    best_case_pnl: float | None = None

    for bar in later_bars:
        bar_date = _parse_bar_date(bar.get("t"))
        candidate_price = _best_case_exit_price(trade, bar)
        candidate_pnl = _calculate_pnl(trade, candidate_price)
        if best_case_pnl is None or candidate_pnl > best_case_pnl:
            best_case_pnl = candidate_pnl
            best_exit_price = candidate_price
            best_exit_date = bar_date

    assert best_case_pnl is not None
    return LaterOutcome(
        had_later_data=True,
        later_became_profitable=best_case_pnl > 0,
        later_improved_pnl=best_case_pnl > trade.pnl,
        later_beat_pre_exit_peak_pnl=(
            best_case_pnl > pre_exit_peak["pnl"] if pre_exit_peak["pnl"] is not None else None
        ),
        pre_exit_peak_date=pre_exit_peak["date"],
        pre_exit_peak_price=pre_exit_peak["price"],
        pre_exit_peak_pnl=pre_exit_peak["pnl"],
        best_case_exit_date=best_exit_date.isoformat() if best_exit_date else None,
        best_case_exit_price=best_exit_price,
        best_case_pnl=best_case_pnl,
        data_window_end=expiration.isoformat(),
        analysis_status="ok",
    )


def _best_case_exit_price(trade: RealizedTrade, bar: dict[str, object]) -> float:
    contract_type = _extract_contract_type(trade.symbol)
    if trade.direction == "long" and contract_type in {"C", "P"}:
        return float(bar["h"])
    if trade.direction == "short":
        return float(bar["l"])
    return float(bar["c"])


def _calculate_pnl(trade: RealizedTrade, exit_price: float) -> float:
    multiplier = 100
    if trade.direction == "long":
        return (exit_price - trade.open_price) * trade.quantity * multiplier
    return (trade.open_price - exit_price) * trade.quantity * multiplier


def _serialize_trade(trade: RealizedTrade, outcome: LaterOutcome) -> dict[str, object]:
    expiration = extract_contract_expiration(trade.symbol)
    trade_payload = {
        "symbol": trade.symbol,
        "contract_description": describe_contract(trade.symbol),
        "underlying_symbol": extract_underlying_symbol(trade.symbol),
        "direction": trade.direction,
        "quantity": trade.quantity,
        "open_date": trade.open_date.isoformat(),
        "open_price": trade.open_price,
        "close_date": trade.trade_date.isoformat(),
        "close_price": trade.price,
        "realized_pnl": trade.pnl,
        "expiration_date": expiration.isoformat() if expiration else None,
        "would_have_been_profitable_if_held_longer": outcome.later_became_profitable,
        "would_have_improved_pnl_if_held_longer": outcome.later_improved_pnl,
        "would_have_beaten_pre_exit_peak_pnl_if_held_longer": outcome.later_beat_pre_exit_peak_pnl,
        "pre_exit_peak_date": outcome.pre_exit_peak_date,
        "pre_exit_peak_price": outcome.pre_exit_peak_price,
        "pre_exit_peak_pnl": outcome.pre_exit_peak_pnl,
        "best_case_later_exit_date": outcome.best_case_exit_date,
        "best_case_later_exit_price": outcome.best_case_exit_price,
        "best_case_later_pnl": outcome.best_case_pnl,
        "hold_longer_analysis_status": outcome.analysis_status,
        "hold_longer_data_window_end": outcome.data_window_end,
    }
    return trade_payload


def _parse_bar_date(raw_timestamp: object) -> date:
    if not isinstance(raw_timestamp, (int, float)):
        raise ValueError(f"Unsupported bar timestamp: {raw_timestamp!r}")
    return datetime.fromtimestamp(raw_timestamp / 1000, UTC).date()


def _sort_trades(trades: Sequence[RealizedTrade]) -> list[RealizedTrade]:
    return sorted(
        trades,
        key=lambda trade: (
            trade.open_date.isoformat(),
            trade.trade_date.isoformat(),
            trade.symbol,
            trade.open_price,
            trade.price,
            trade.quantity,
            trade.pnl,
        ),
    )


def _analyze_pre_exit_peak(trade: RealizedTrade, bars: Sequence[dict[str, object]]) -> dict[str, str | float | None]:
    pre_exit_bars = [
        bar
        for bar in bars
        if trade.open_date <= _parse_bar_date(bar.get("t")) <= trade.trade_date
    ]
    if not pre_exit_bars:
        return {"date": None, "price": None, "pnl": None}

    peak_date: date | None = None
    peak_price: float | None = None
    peak_pnl: float | None = None
    for bar in pre_exit_bars:
        bar_date = _parse_bar_date(bar.get("t"))
        candidate_price = _best_case_exit_price(trade, bar)
        candidate_pnl = _calculate_pnl(trade, candidate_price)
        if peak_pnl is None or candidate_pnl > peak_pnl:
            peak_date = bar_date
            peak_price = candidate_price
            peak_pnl = candidate_pnl
    return {
        "date": peak_date.isoformat() if peak_date else None,
        "price": peak_price,
        "pnl": peak_pnl,
    }


def _get_polygon_api_key() -> str:
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key:
        return api_key
    loaded = _load_env_value(DEFAULT_ENV_PATH, "POLYGON_API_KEY")
    if loaded:
        return loaded
    raise RuntimeError(
        f"POLYGON_API_KEY is not set. Expected it in the environment or {DEFAULT_ENV_PATH}."
    )


def _load_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            os.environ[key] = cleaned
            return cleaned
    return None


def _should_analyze_trade(trade: RealizedTrade) -> bool:
    return trade.direction == "long" and _extract_contract_type(trade.symbol) in {"C", "P"}


def _extract_contract_type(symbol: str) -> str | None:
    match = re.match(r"^[A-Z]+(?:\d{6})([CP])(?:\d{8})$", symbol)
    if not match:
        return None
    return match.group(1)


def _is_same_day_trade(trade: RealizedTrade) -> bool:
    return trade.open_date == trade.trade_date


if __name__ == "__main__":
    main()
