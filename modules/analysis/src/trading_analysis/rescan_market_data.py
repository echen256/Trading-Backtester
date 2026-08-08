"""Rescan Polygon-errored underlyings / option symbols with a slow throttle."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from .display_common import extract_underlying_symbol
from .export_tpo_grades import grade_realized_trade, load_tpo_grades
from .market_data import (
    DEFAULT_OPTION_DAILY_CACHE_DIR,
    DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    PolygonHttpError,
    fetch_option_daily_bars,
    fetch_sessions_minute_bars,
)
from .market_data.cache import load_json, option_daily_cache_path
from .market_data.option_dailies import option_symbols_with_cache_errors
from .parse_orders import (
    DEFAULT_WEBULL_ORDERS_CSV,
    ORDER_DATA_DIR,
    RealizedTrade,
    analyze_orders,
    filter_orders_by_date,
    filter_trades_by_close_date,
    load_orders,
)
from .tpo.schema import TpoGradeRecord, TpoGradesDocument, make_trade_id
from .tpo.sessions import attach_fill_to_session, expand_session_window

UNAUTHORIZED_RE = re.compile(r"403|NOT_AUTHORIZED|Unauthorized", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Slowly re-query Polygon for symbols that previously failed "
            "(403 / NOT_AUTHORIZED / cache errors) and refresh TPO grades "
            "and/or option daily caches."
        )
    )
    parser.add_argument(
        "--target",
        choices=["tpo", "hold", "both"],
        default="both",
        help="Which errored datasets to rescan (default: both)",
    )
    parser.add_argument(
        "--tpo-grades",
        type=Path,
        default=ORDER_DATA_DIR / "trade-tpo-grades-2026-01-01_to_2026-06-30.json",
        help="TPO grades JSON to patch",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_WEBULL_ORDERS_CSV,
        help="Orders CSV used to rebuild realized trades for TPO regrade",
    )
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-06-30")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
        help="Underlying 1m cache dir",
    )
    parser.add_argument(
        "--option-cache-dir",
        type=Path,
        default=DEFAULT_OPTION_DAILY_CACHE_DIR,
        help="Option 1d cache dir",
    )
    parser.add_argument(
        "--throttle-seconds",
        type=float,
        default=1.5,
        help="Delay between Polygon range/symbol requests (default: 1.5s)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max errored underlyings / option symbols to rescan",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List errored symbols without fetching",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)

    if args.target in {"tpo", "both"}:
        _rescan_tpo(
            grades_path=args.tpo_grades,
            csv_path=args.csv,
            start_date=start,
            end_date=end,
            cache_dir=args.cache_dir,
            throttle_seconds=args.throttle_seconds,
            limit=args.limit,
            dry_run=args.dry_run,
        )

    if args.target in {"hold", "both"}:
        _rescan_hold_option_cache(
            csv_path=args.csv,
            start_date=start,
            end_date=end,
            option_cache_dir=args.option_cache_dir,
            throttle_seconds=args.throttle_seconds,
            limit=args.limit,
            dry_run=args.dry_run,
        )


def collect_tpo_error_underlyings(doc: TpoGradesDocument) -> list[str]:
    underlyings: set[str] = set()
    for record in doc.trades:
        grade = record.grade or {}
        error = str(grade.get("error") or "")
        status = grade.get("status")
        if status == "error" and (UNAUTHORIZED_RE.search(error) or error):
            name = (record.underlying or extract_underlying_symbol(record.symbol) or "").upper()
            if name:
                underlyings.add(name)
    return sorted(underlyings)


def _rescan_tpo(
    *,
    grades_path: Path,
    csv_path: Path,
    start_date: date,
    end_date: date,
    cache_dir: Path,
    throttle_seconds: float,
    limit: int | None,
    dry_run: bool,
) -> None:
    if not grades_path.exists():
        print(f"TPO grades not found: {grades_path}")
        return

    doc = load_tpo_grades(grades_path)
    errored = collect_tpo_error_underlyings(doc)
    if limit is not None:
        errored = errored[:limit]
    print(f"TPO errored underlyings: {len(errored)}")
    for name in errored:
        print(f"  {name}")
    if dry_run or not errored:
        return

    orders = load_orders(csv_path)
    orders = filter_orders_by_date(orders, None, end_date)
    result = analyze_orders(orders)
    trades = filter_trades_by_close_date(result.realized_trades, start_date, end_date)
    trades_by_id = {make_trade_id(trade): trade for trade in trades}

    error_records = [
        record
        for record in doc.trades
        if (record.grade or {}).get("status") == "error"
        and (record.underlying or "").upper() in set(errored)
    ]
    print(f"Regrading {len(error_records)} TPO error trades (throttle={throttle_seconds}s)...")

    # Prefetch the full ±10 session window per trade so regrade is cache-hit only.
    # Fetch day-by-day: multi-day minute ranges often 403 on limited Polygon plans.
    sessions_by_underlying: dict[str, set[date]] = defaultdict(set)
    for record in error_records:
        trade = trades_by_id.get(record.trade_id) or _trade_from_grade_record(record)
        underlying = (trade.underlying or extract_underlying_symbol(trade.symbol) or "").upper()
        if not underlying:
            continue
        open_dt = trade.open_datetime or datetime.combine(trade.open_date, datetime.min.time())
        close_dt = trade.trade_datetime or datetime.combine(trade.trade_date, datetime.min.time())
        entry_session, _ = attach_fill_to_session(open_dt)
        exit_session, _ = attach_fill_to_session(close_dt)
        if exit_session < entry_session:
            exit_session = entry_session
        for session in expand_session_window(entry_session, exit_session, before=10, after=10):
            sessions_by_underlying[underlying].add(session)

    from .market_data import fetch_session_minute_bars
    from .market_data.cache import load_underlying_day_bars

    for index, (underlying, sessions) in enumerate(sorted(sessions_by_underlying.items()), start=1):
        missing = [
            session
            for session in sorted(sessions)
            if load_underlying_day_bars(underlying, session, cache_dir=cache_dir) is None
        ]
        print(
            f"[{index}/{len(sessions_by_underlying)}] prefetch {underlying} "
            f"({len(missing)} missing / {len(sessions)} window days)"
        )
        for day_index, session in enumerate(missing, start=1):
            try:
                fetch_session_minute_bars(
                    underlying,
                    session,
                    cache_dir=cache_dir,
                    throttle_seconds=0.0,
                    force_refresh=False,
                )
                print(f"  [{day_index}/{len(missing)}] {session} ok")
            except Exception as exc:
                print(f"  [{day_index}/{len(missing)}] {session} failed: {exc}")
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)

    updated: dict[str, TpoGradeRecord] = {}
    for index, record in enumerate(error_records, start=1):
        trade = trades_by_id.get(record.trade_id)
        if trade is None:
            trade = _trade_from_grade_record(record)
        print(
            f"[{index}/{len(error_records)}] regrade {trade.symbol} "
            f"{trade.open_date}→{trade.trade_date}"
        )
        # Prefer cache; only fetch remaining misses one day at a time via features path.
        refreshed = grade_realized_trade(
            trade,
            cache_dir=cache_dir,
            throttle_seconds=throttle_seconds,
            use_llm=False,
        )
        updated[record.trade_id] = refreshed
        status = (refreshed.grade or {}).get("status")
        print(f"  -> {status}")
        if throttle_seconds > 0:
            time.sleep(min(throttle_seconds, 0.5))

    new_trades: list[TpoGradeRecord] = []
    for record in doc.trades:
        new_trades.append(updated.get(record.trade_id, record))
    patched = TpoGradesDocument(metadata=dict(doc.metadata), trades=new_trades)
    patched.metadata["rescanned_at"] = datetime.now(timezone.utc).isoformat()
    patched.metadata["rescan_underlyings"] = errored
    grades_path.write_text(json.dumps(patched.to_dict(), indent=2), encoding="utf-8")
    still_error = sum(1 for t in new_trades if (t.grade or {}).get("status") == "error")
    print(f"Wrote patched grades to {grades_path} (remaining errors: {still_error})")


def _trade_from_grade_record(record: TpoGradeRecord) -> RealizedTrade:
    open_date = date.fromisoformat(record.open_date)
    close_date = date.fromisoformat(record.close_date)
    open_dt = datetime.fromisoformat(record.open_datetime) if record.open_datetime else None
    close_dt = datetime.fromisoformat(record.close_datetime) if record.close_datetime else None
    return RealizedTrade(
        trade_date=close_date,
        symbol=record.symbol,
        quantity=record.quantity,
        price=record.close_price,
        pnl=record.realized_pnl,
        open_date=open_date,
        open_price=record.open_price,
        direction=record.direction,
        trade_datetime=close_dt,
        open_datetime=open_dt,
        underlying=record.underlying,
        instrument_type=record.instrument_type,
        option_type=record.option_type,
    )


def _rescan_hold_option_cache(
    *,
    csv_path: Path,
    start_date: date,
    end_date: date,
    option_cache_dir: Path,
    throttle_seconds: float,
    limit: int | None,
    dry_run: bool,
) -> None:
    from .display_common import extract_contract_expiration
    from .parse_orders import analyze_orders, filter_trades_by_close_date

    orders = load_orders(csv_path)
    orders = filter_orders_by_date(orders, None, end_date)
    result = analyze_orders(orders)
    trades = [
        trade
        for trade in filter_trades_by_close_date(result.realized_trades, start_date, end_date)
        if trade.direction == "long" and trade.instrument_type == "OPTION"
    ]
    symbols = sorted({trade.symbol for trade in trades})
    errored = option_symbols_with_cache_errors(symbols, cache_dir=option_cache_dir)
    # Also include symbols with no cache file yet that we previously couldn't fetch —
    # for hold, focus on explicit cache errors.
    if limit is not None:
        errored = errored[:limit]
    print(f"Hold option cache errors: {len(errored)}")
    for symbol in errored:
        payload = load_json(option_daily_cache_path(symbol, option_cache_dir)) or {}
        print(f"  {symbol}: {str(payload.get('error') or '')[:120]}")
    if dry_run or not errored:
        return

    trades_by_symbol: dict[str, list[RealizedTrade]] = defaultdict(list)
    for trade in trades:
        trades_by_symbol[trade.symbol].append(trade)

    ok = fail = 0
    for index, symbol in enumerate(errored, start=1):
        expiration = extract_contract_expiration(symbol)
        symbol_trades = trades_by_symbol.get(symbol) or []
        if expiration is None or not symbol_trades:
            continue
        start = min(trade.open_date for trade in symbol_trades)
        print(f"[{index}/{len(errored)}] refetch {symbol} {start}→{expiration}")
        try:
            fetch_option_daily_bars(
                symbol,
                start_date=start,
                end_date=expiration,
                cache_dir=option_cache_dir,
                throttle_seconds=0.0,
                force_refresh=True,
            )
            ok += 1
            print("  ok")
        except PolygonHttpError as exc:
            fail += 1
            print(f"  still failing: {exc}")
        if throttle_seconds > 0 and index < len(errored):
            time.sleep(throttle_seconds)
    print(f"Hold rescan done: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
