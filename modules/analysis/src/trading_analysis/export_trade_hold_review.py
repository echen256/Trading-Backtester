"""Export trade hold / hold-longer counterfactual review using shared market data."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Sequence

from .dashboard import StudyArtifactWriter
from .display_common import describe_contract, extract_contract_expiration, extract_underlying_symbol
from .market_data import (
    DEFAULT_OPTION_DAILY_CACHE_DIR,
    PolygonHttpError,
    fetch_option_daily_bars,
    get_polygon_api_key,
)
from .parse_orders import (
    DEFAULT_WEBULL_ORDERS_CSV,
    ORDER_DATA_DIR,
    RealizedTrade,
    analyze_orders,
    filter_orders_by_date,
    filter_trades_by_close_date,
    load_orders,
)

DEFAULT_OUTPUT_PATH = ORDER_DATA_DIR / "trade-hold-review-2026-01-01-to-2026-06-30.json"


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
    fetch_error: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export trade hold-longer review JSON. Uses the same analyze_orders "
            "pipeline as TPO grading and the shared option daily cache under "
            "order-data/market-data-cache/options/1d/."
        )
    )
    parser.add_argument("--start-date", default="2026-01-01", help="Inclusive close-date filter start")
    parser.add_argument("--end-date", default="2026-06-30", help="Inclusive close-date filter end")
    parser.add_argument("--csv", type=Path, default=DEFAULT_WEBULL_ORDERS_CSV, help="Orders CSV path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="JSON output path")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_OPTION_DAILY_CACHE_DIR,
        help="Option daily bar cache directory",
    )
    parser.add_argument(
        "--throttle-seconds",
        type=float,
        default=0.12,
        help="Delay between Polygon option fetches for cache misses",
    )
    parser.add_argument(
        "--exclude-same-day-trades",
        action="store_true",
        help="Exclude trades where open_date and close_date are the same day.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore option daily cache and refetch from Polygon",
    )
    parser.add_argument(
        "--rescan-errors",
        action="store_true",
        help=(
            "Only refetch option symbols whose cache entry has an error "
            "(slow throttle). Implies force-refresh for those symbols."
        ),
    )
    parser.add_argument(
        "--rescan-throttle-seconds",
        type=float,
        default=1.5,
        help="Throttle used with --rescan-errors (default: 1.5s)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date > end_date:
        raise ValueError("start-date must be on or before end-date")

    # Same realized-trade pipeline as TPO: keep warmup opens, filter by close date.
    orders = load_orders(args.csv)
    orders = filter_orders_by_date(orders, None, end_date)
    analysis = analyze_orders(orders)
    all_realized_trades = filter_trades_by_close_date(analysis.realized_trades, start_date, end_date)

    excluded_short_trade_count = sum(1 for trade in all_realized_trades if trade.direction == "short")
    candidate_trades = [trade for trade in all_realized_trades if _should_analyze_trade(trade)]
    excluded_same_day_trade_count = sum(1 for trade in candidate_trades if _is_same_day_trade(trade))
    realized_trades = [
        trade
        for trade in candidate_trades
        if not (args.exclude_same_day_trades and _is_same_day_trade(trade))
    ]

    grouped_trades = _group_trades_by_symbol(realized_trades)
    api_key = get_polygon_api_key()
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY is not set.")

    option_bars_by_symbol: dict[str, list[dict[str, object]] | None] = {}
    fetch_errors: dict[str, str] = {}
    symbols = sorted(grouped_trades.keys())

    from .market_data.option_dailies import option_symbols_with_cache_errors

    rescan_set: set[str] = set()
    if args.rescan_errors:
        rescan_set = set(option_symbols_with_cache_errors(symbols, cache_dir=args.cache_dir))
        print(f"Rescanning {len(rescan_set)} option symbols with cache errors...")

    for index, symbol in enumerate(symbols, start=1):
        expiration = extract_contract_expiration(symbol)
        if not symbol or expiration is None:
            option_bars_by_symbol[symbol] = None
            continue

        if args.rescan_errors:
            # Cache-only for healthy symbols; slow force-refresh for errored ones.
            force = symbol in rescan_set
            throttle = args.rescan_throttle_seconds if force else 0.0
        else:
            force = args.force_refresh
            throttle = args.throttle_seconds

        start = min(trade.open_date for trade in grouped_trades[symbol])
        try:
            option_bars_by_symbol[symbol] = fetch_option_daily_bars(
                symbol,
                start_date=start,
                end_date=expiration,
                cache_dir=args.cache_dir,
                api_key=api_key,
                throttle_seconds=throttle,
                force_refresh=force,
            )
        except PolygonHttpError as exc:
            option_bars_by_symbol[symbol] = None
            fetch_errors[symbol] = str(exc)
            print(f"  fetch error {symbol}: {exc}")
            if throttle and index < len(symbols):
                time.sleep(throttle)

    profitable_trades: list[dict[str, object]] = []
    unprofitable_trades: list[dict[str, object]] = []

    for trade in _sort_trades(realized_trades):
        outcome = _analyze_later_outcome(
            trade,
            option_bars_by_symbol.get(trade.symbol),
            fetch_error=fetch_errors.get(trade.symbol),
        )
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
            "bar_source": "polygon_option_daily",
            "cache_dir": str(args.cache_dir),
            "orders_pipeline": "analyze_orders",
            "fetch_error_symbol_count": len(fetch_errors),
            "rescan_errors": args.rescan_errors,
        },
        "profitable_trades": profitable_trades,
        "unprofitable_trades": unprofitable_trades,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="trade-hold-review",
        study_name="Trade Hold-longer Review",
        version="1.0",
        generator="trading_analysis.export_trade_hold_review",
        files={"review": args.output},
        parameters={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        metrics=[
            {"label": "Analyzed trades", "value": len(realized_trades)},
            {"label": "Profitable trades", "value": len(profitable_trades)},
            {"label": "Unprofitable trades", "value": len(unprofitable_trades)},
            {"label": "Fetch errors", "value": len(fetch_errors)},
        ],
    )
    print(f"Wrote trade hold review to {args.output}")
    print(f"Profitable trades: {len(profitable_trades)}")
    print(f"Unprofitable trades: {len(unprofitable_trades)}")
    print(f"Option fetch errors: {len(fetch_errors)}")
    print(f"Published dashboard study {dashboard_output}")


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _group_trades_by_symbol(trades: Sequence[RealizedTrade]) -> dict[str, list[RealizedTrade]]:
    grouped: dict[str, list[RealizedTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol].append(trade)
    return grouped


def _analyze_later_outcome(
    trade: RealizedTrade,
    bars: list[dict[str, object]] | None,
    *,
    fetch_error: str | None = None,
) -> LaterOutcome:
    expiration = extract_contract_expiration(trade.symbol)
    if not trade.symbol:
        return LaterOutcome(False, None, None, None, None, None, None, None, None, None, None, "missing_symbol")
    if expiration is None:
        return LaterOutcome(False, None, None, None, None, None, None, None, None, None, None, "non_option_symbol")
    if fetch_error:
        return LaterOutcome(
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            expiration.isoformat(),
            "polygon_fetch_error",
            fetch_error=fetch_error,
        )
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
        return LaterOutcome(
            False, None, None, None, None, None, None, None, None, None, expiration.isoformat(), "no_later_option_data"
        )

    pre_exit_peak = _analyze_pre_exit_peak(trade, bars)

    later_bars = [
        bar
        for bar in bars
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
    trade_payload: dict[str, object] = {
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
    if outcome.fetch_error:
        trade_payload["polygon_fetch_error"] = outcome.fetch_error
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
        bar for bar in bars if trade.open_date <= _parse_bar_date(bar.get("t")) <= trade.trade_date
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
