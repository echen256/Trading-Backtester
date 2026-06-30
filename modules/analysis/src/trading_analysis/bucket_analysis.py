"""Analyze trade profitability bucketed by DTE at open and moneyness at open."""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .display_common import extract_contract_expiration, extract_underlying_symbol
from .parse_orders import (
    DEFAULT_ORDERS_CSV,
    RealizedTrade,
    compute_realized_trades,
    filter_orders_by_date,
    filter_trades_by_close_date,
    load_orders,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REVIEW_INPUT_PATH = (
    REPO_ROOT / "modules" / "analysis" / "order-data" / "trade-hold-review-2025-01-01-to-2026-05-15.json"
)
DEFAULT_WEBULL_BRIDGE_INPUT_PATH = REPO_ROOT / "modules" / "analysis" / "order-data" / "orders.csv"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
POLYGON_API_BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

DTE_BUCKETS: list[tuple[str, int, int]] = [
    ("0DTE",   0,   0),
    ("1-4",    1,   4),
    ("5-14",   5,  14),
    ("15-44", 15,  44),
    ("45+",   45, 9999),
]

MONEYNESS_BUCKETS: list[tuple[str, float, float]] = [
    # (label, min_pct_otm_exclusive, max_pct_otm_inclusive)
    # positive = OTM, negative = ITM
    ("Deep OTM", 10.0,  9999.0),
    ("OTM",       2.0,    10.0),
    ("ATM",      -2.0,     2.0),
    ("ITM",     -10.0,    -2.0),
    ("Deep ITM",-9999.0, -10.0),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=_default_input_path(),
        help="Path to Webull orders CSV or trade-hold-review JSON",
    )
    parser.add_argument(
        "--start-date",
        help="Only include CSV realized trades closed on/after YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        help="Only include CSV realized trades closed on/before YYYY-MM-DD",
    )
    parser.add_argument(
        "--include-all-trades",
        action="store_true",
        help="For CSV input, include short option and non-option realized trades instead of long options only",
    )
    parser.add_argument(
        "--no-moneyness", action="store_true",
        help="Skip moneyness bucketing (no Polygon calls needed)",
    )
    parser.add_argument(
        "--throttle", type=float, default=0.2,
        help="Seconds to wait between Polygon requests (default: 0.2)",
    )
    return parser


def _default_input_path() -> Path:
    for path in (DEFAULT_WEBULL_BRIDGE_INPUT_PATH, DEFAULT_ORDERS_CSV):
        if path.exists():
            return path
    return DEFAULT_REVIEW_INPUT_PATH


def main() -> None:
    args = build_parser().parse_args()

    trades = _load_input_trades(
        args.input,
        start_date=_parse_cli_date(args.start_date),
        end_date=_parse_cli_date(args.end_date),
        long_options_only=not args.include_all_trades,
    )

    spot_map: dict[tuple[str, str], float | None] = {}
    if not args.no_moneyness:
        api_key = _get_polygon_api_key()
        if api_key:
            spot_map = _fetch_spot_prices(trades, api_key, args.throttle)
        else:
            print("No POLYGON_API_KEY found — skipping moneyness bucketing.\n")

    _print_dte_table(trades)
    print()
    if not args.no_moneyness and spot_map:
        _print_moneyness_table(trades, spot_map)
        print()
        _print_crosstab(trades, spot_map)


def _load_input_trades(
    input_path: Path,
    *,
    start_date: date | None,
    end_date: date | None,
    long_options_only: bool,
) -> list[dict[str, Any]]:
    if input_path.suffix.lower() == ".json":
        return _load_review_json(input_path)
    return _load_orders_csv(
        input_path,
        start_date=start_date,
        end_date=end_date,
        long_options_only=long_options_only,
    )


def _load_review_json(input_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    return (
        list(payload.get("profitable_trades") or [])
        + list(payload.get("unprofitable_trades") or [])
    )


def _load_orders_csv(
    input_path: Path,
    *,
    start_date: date | None,
    end_date: date | None,
    long_options_only: bool,
) -> list[dict[str, Any]]:
    orders = load_orders(input_path)
    orders = filter_orders_by_date(orders, None, end_date)
    realized_trades = filter_trades_by_close_date(
        compute_realized_trades(orders),
        start_date,
        end_date,
    )
    if long_options_only:
        realized_trades = [
            trade for trade in realized_trades
            if trade.direction == "long" and extract_contract_expiration(trade.symbol) is not None
        ]
    return [_serialize_realized_trade(trade) for trade in realized_trades]


def _serialize_realized_trade(trade: RealizedTrade) -> dict[str, Any]:
    expiration = extract_contract_expiration(trade.symbol)
    return {
        "symbol": trade.symbol,
        "underlying_symbol": trade.underlying or extract_underlying_symbol(trade.symbol),
        "direction": trade.direction,
        "quantity": trade.quantity,
        "open_date": trade.open_date.isoformat(),
        "open_price": trade.open_price,
        "close_date": trade.trade_date.isoformat(),
        "close_price": trade.price,
        "realized_pnl": trade.pnl,
        "expiration_date": expiration.isoformat() if expiration else None,
    }


def _parse_cli_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from exc


# ---------------------------------------------------------------------------
# DTE bucketing
# ---------------------------------------------------------------------------

def _dte_at_open(trade: dict[str, Any]) -> int | None:
    open_date = _parse_date(trade.get("open_date"))
    exp_date  = _parse_date(trade.get("expiration_date"))
    if open_date is None or exp_date is None:
        return None
    return (exp_date - open_date).days


def _dte_bucket(dte: int | None) -> str:
    if dte is None:
        return "unknown"
    for label, lo, hi in DTE_BUCKETS:
        if lo <= dte <= hi:
            return label
    return "45+"


def _print_dte_table(trades: list[dict[str, Any]]) -> None:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        buckets[_dte_bucket(_dte_at_open(t))].append(t)

    order = [label for label, _, _ in DTE_BUCKETS] + ["unknown"]
    print("=== By DTE at Open ===")
    _print_table([(k, buckets[k]) for k in order if k in buckets])


# ---------------------------------------------------------------------------
# Moneyness bucketing
# ---------------------------------------------------------------------------

def _strike_from_symbol(symbol: str) -> float | None:
    m = re.match(r"^[A-Z]+\d{6}[CP](\d{8})$", symbol)
    if not m:
        return None
    return int(m.group(1)) / 1000.0


def _is_call(symbol: str) -> bool | None:
    m = re.search(r"\d{6}([CP])\d{8}$", symbol)
    if not m:
        return None
    return m.group(1) == "C"


def _otm_pct(spot: float, strike: float, is_call: bool) -> float:
    """Positive = OTM, negative = ITM, in percentage points."""
    if is_call:
        return (strike - spot) / spot * 100.0
    else:
        return (spot - strike) / spot * 100.0


def _moneyness_bucket(otm_pct: float) -> str:
    for label, lo, hi in MONEYNESS_BUCKETS:
        if lo < otm_pct <= hi:
            return label
    # edge: exactly Deep OTM boundary
    return "Deep OTM" if otm_pct > 10 else "Deep ITM"


def _print_moneyness_table(
    trades: list[dict[str, Any]],
    spot_map: dict[tuple[str, str], float | None],
) -> None:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        symbol   = t.get("symbol", "")
        open_date = t.get("open_date", "")
        strike   = _strike_from_symbol(symbol)
        is_call  = _is_call(symbol)
        spot     = spot_map.get((t.get("underlying_symbol", ""), open_date))
        if strike is None or is_call is None or not spot:
            buckets["unknown"].append(t)
            continue
        buckets[_moneyness_bucket(_otm_pct(spot, strike, is_call))].append(t)

    order = [label for label, _, _ in MONEYNESS_BUCKETS] + ["unknown"]
    print("=== By Moneyness at Open ===")
    _print_table([(k, buckets[k]) for k in order if k in buckets])


# ---------------------------------------------------------------------------
# Cross-tab
# ---------------------------------------------------------------------------

def _print_crosstab(
    trades: list[dict[str, Any]],
    spot_map: dict[tuple[str, str], float | None],
) -> None:
    cell: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        dte_b = _dte_bucket(_dte_at_open(t))
        symbol   = t.get("symbol", "")
        open_date = t.get("open_date", "")
        strike   = _strike_from_symbol(symbol)
        is_call  = _is_call(symbol)
        spot     = spot_map.get((t.get("underlying_symbol", ""), open_date))
        if strike is None or is_call is None or not spot:
            mon_b = "unknown"
        else:
            mon_b = _moneyness_bucket(_otm_pct(spot, strike, is_call))
        cell[(dte_b, mon_b)].append(t)

    dte_labels = [label for label, _, _ in DTE_BUCKETS if any(k[0] == label for k in cell)]
    mon_labels = [label for label, _, _ in MONEYNESS_BUCKETS if any(k[1] == label for k in cell)]

    col_w = 16
    header = f"{'DTE \\ Moneyness':<12}" + "".join(f"{m:>{col_w}}" for m in mon_labels)
    print("=== Cross-tab: Win Rate (count) ===")
    print(header)
    print("-" * len(header))
    for dte_b in dte_labels:
        row = f"{dte_b:<12}"
        for mon_b in mon_labels:
            ts = cell.get((dte_b, mon_b), [])
            if not ts:
                row += f"{'—':>{col_w}}"
            else:
                wins = sum(1 for t in ts if (t.get("realized_pnl") or 0) > 0)
                row += f"{wins/len(ts):>6.0%} ({len(ts):>3}){' '*(col_w-12)}"
        print(row)


# ---------------------------------------------------------------------------
# Shared table printer
# ---------------------------------------------------------------------------

def _bucket_stats(ts: list[dict[str, Any]]) -> dict[str, Any]:
    if not ts:
        return {}
    pnls = [t.get("realized_pnl") or 0.0 for t in ts]
    wins = sum(1 for p in pnls if p > 0)
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls)

    # Among winning trades: what % of the pre-exit peak did you actually capture?
    # <100% = you had a better price available before you exited (left money on table)
    peak_ratios = []
    for t in ts:
        pnl  = t.get("realized_pnl") or 0.0
        peak = t.get("pre_exit_peak_pnl")
        if pnl > 0 and peak and peak > 0:
            peak_ratios.append(min(pnl / peak, 1.0))  # cap at 100% (exit at/after peak)

    # Among winning trades with later data: what % of best post-exit PnL did you capture?
    # <100% = you exited before the best opportunity (held too short)
    later_ratios = []
    for t in ts:
        pnl   = t.get("realized_pnl") or 0.0
        later = t.get("best_case_later_pnl")
        if pnl > 0 and later and later > 0:
            later_ratios.append(pnl / later)

    # Reversals: trades where there was a profitable peak before exit but you ended at a loss
    reversals = sum(
        1 for t in ts
        if (t.get("realized_pnl") or 0) <= 0
        and (t.get("pre_exit_peak_pnl") or 0) > 0
    )

    return {
        "count":        len(ts),
        "win_rate":     wins / len(ts),
        "total_pnl":    total_pnl,
        "avg_pnl":      avg_pnl,
        "reversals":    reversals,
        "avg_peak_capture":  sum(peak_ratios) / len(peak_ratios) if peak_ratios else None,
        "avg_later_capture": sum(later_ratios) / len(later_ratios) if later_ratios else None,
    }


def _print_table(rows: list[tuple[str, list[dict[str, Any]]]]) -> None:
    # Peak%     = of winning trades: % of pre-exit peak captured (lower = left money on table before exit)
    # EarlyExit = of winning trades w/ later data: % of best post-exit PnL captured (lower = exited too early)
    # Reversals = trades where a profitable peak turned into a realized loss (held past the peak)
    header = (
        f"{'Bucket':<12} {'N':>5} {'Win%':>6} {'Avg PnL':>10} {'Total PnL':>12}"
        f" {'Reversal':>9} {'Peak%':>7} {'EarlyExit%':>11}"
    )
    print(header)
    print("-" * len(header))
    for label, ts in rows:
        if not ts:
            continue
        s = _bucket_stats(ts)
        rev_str   = f"{s['reversals']:>5} ({s['reversals']/s['count']:>3.0%})"
        peak_str  = f"{s['avg_peak_capture']:>6.0%}" if s["avg_peak_capture"] is not None else "   N/A"
        later_str = f"{s['avg_later_capture']:>10.0%}" if s["avg_later_capture"] is not None else "       N/A"
        print(
            f"{label:<12} {s['count']:>5} {s['win_rate']:>6.1%}"
            f" {s['avg_pnl']:>10,.0f} {s['total_pnl']:>12,.0f}"
            f" {rev_str} {peak_str} {later_str}"
        )


# ---------------------------------------------------------------------------
# Polygon helpers
# ---------------------------------------------------------------------------

def _fetch_spot_prices(
    trades: list[dict[str, Any]],
    api_key: str,
    throttle: float,
) -> dict[tuple[str, str], float | None]:
    needed: set[tuple[str, str]] = set()
    for t in trades:
        sym  = t.get("underlying_symbol", "")
        dt   = t.get("open_date", "")
        if sym and dt:
            needed.add((sym, dt))

    result: dict[tuple[str, str], float | None] = {}
    pairs = sorted(needed)
    print(f"Fetching spot prices for {len(pairs)} (symbol, date) pairs from Polygon…")
    for i, (sym, dt) in enumerate(pairs, 1):
        result[(sym, dt)] = _fetch_close(sym, dt, api_key)
        if i < len(pairs):
            time.sleep(throttle)
    return result


def _fetch_close(ticker: str, iso_date: str, api_key: str) -> float | None:
    query = urllib.parse.urlencode({"apiKey": api_key, "limit": 1})
    url = f"{POLYGON_API_BASE_URL}/{ticker}/range/1/day/{iso_date}/{iso_date}?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results") or []
            if results:
                return float(results[0].get("c") or results[0].get("o") or 0) or None
            return None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
    return None


def _get_polygon_api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "")
    if not key and DEFAULT_ENV_PATH.exists():
        for line in DEFAULT_ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("POLYGON_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return key


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


if __name__ == "__main__":
    main()
