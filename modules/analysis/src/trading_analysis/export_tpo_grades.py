"""Batch export of TPO execution grades for realized trades."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from .dashboard import StudyArtifactWriter
from .display_common import extract_underlying_symbol
from .parse_orders import (
    DEFAULT_WEBULL_ORDERS_CSV,
    ORDER_DATA_DIR,
    RealizedTrade,
    analyze_orders,
    filter_orders,
    filter_orders_by_date,
    filter_trades_by_close_date,
    load_orders,
)
from .tpo.bars import DEFAULT_CACHE_DIR
from .tpo.features import extract_features_for_trade
from .tpo.grade import get_grade_model, get_grade_provider, grade_trade_record
from .tpo.render import summarize_quality_buckets
from .tpo.schema import TpoGradeRecord, TpoGradesDocument


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build underlying Market Profile (TPO) features and optional LLM grades."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_WEBULL_ORDERS_CSV,
        help=f"Orders CSV (default: {DEFAULT_WEBULL_ORDERS_CSV})",
    )
    parser.add_argument("--start-date", help="Filter realized closes on/after YYYY-MM-DD")
    parser.add_argument("--end-date", help="Filter realized closes on/before YYYY-MM-DD")
    parser.add_argument("--symbol", help="Filter by underlying or exact symbol")
    parser.add_argument(
        "--instrument-type",
        default="ALL",
        choices=["ALL", "OPTION", "EQUITY"],
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output path (default: order-data/trade-tpo-grades-{start}_to_{end}.json)",
    )
    parser.add_argument("--context-before", type=int, default=10)
    parser.add_argument("--context-after", type=int, default=10)
    parser.add_argument("--tpo-period-minutes", type=int, default=30)
    parser.add_argument("--throttle-seconds", type=float, default=0.12)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--limit", type=int, help="Max trades to grade (debug)")
    parser.add_argument(
        "--grade-llm",
        action="store_true",
        help=(
            "Call OpenAI-compatible LLM grader (DeepSeek or OpenAI). "
            "Uses DEEPSEEK_API_KEY / OPENAI_API_KEY / TPO_GRADE_API_KEY"
        ),
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print execution quality bucket summary after export",
    )
    parser.add_argument(
        "--rescan-errors",
        action="store_true",
        help=(
            "Only regrade trades that previously failed (e.g. Polygon 403), "
            "with a slow throttle. Patches the existing grades JSON in place."
        ),
    )
    parser.add_argument(
        "--rescan-throttle-seconds",
        type=float,
        default=1.5,
        help="Throttle for --rescan-errors (default: 1.5s)",
    )
    return parser


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _default_output_path(start: date | None, end: date | None) -> Path:
    start_label = start.isoformat() if start else "all"
    end_label = end.isoformat() if end else "all"
    return ORDER_DATA_DIR / f"trade-tpo-grades-{start_label}_to_{end_label}.json"


def grade_realized_trade(
    trade: RealizedTrade,
    *,
    context_before: int = 10,
    context_after: int = 10,
    period_minutes: int = 30,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    throttle_seconds: float = 0.12,
    use_llm: bool = False,
) -> TpoGradeRecord:
    try:
        (
            features,
            entry_summary,
            exit_summary,
            context,
            entry_px,
            exit_px,
            _profiles,
        ) = extract_features_for_trade(
            trade,
            context_before=context_before,
            context_after=context_after,
            period_minutes=period_minutes,
            cache_dir=cache_dir,
            throttle_seconds=throttle_seconds,
        )
    except Exception as exc:
        underlying = extract_underlying_symbol(trade.symbol) or trade.underlying
        from .tpo.schema import ContextSummary, TpoFeatures, TpoGrade, make_trade_id

        empty_features = TpoFeatures(
            entry_vs_prior_va="unknown",
            entry_vs_day_va="unknown",
            entry_vs_poc_pct=0.0,
            entry_extreme_score=0.0,
            short_bottom_flag=False,
            long_top_flag=False,
            ib_break_context="unknown",
            exit_vs_va="unknown",
            exit_vs_poc_pct=0.0,
            gave_back_to_value=False,
            hold_session_count=0,
            profile_shape_tags=[],
            intraday_round_trip=trade.open_date == trade.trade_date,
            entry_session_attachment="unknown",
            exit_session_attachment="unknown",
            entry_price_source="error",
            exit_price_source="error",
            deterministic_score=0.0,
            rule_hits=[],
        )
        return TpoGradeRecord(
            trade_id=make_trade_id(trade),
            symbol=trade.symbol,
            underlying=underlying,
            direction=trade.direction,
            instrument_type=trade.instrument_type,
            option_type=trade.option_type,
            quantity=trade.quantity,
            open_datetime=trade.open_datetime.isoformat() if trade.open_datetime else None,
            close_datetime=trade.trade_datetime.isoformat() if trade.trade_datetime else None,
            open_date=trade.open_date.isoformat(),
            close_date=trade.trade_date.isoformat(),
            open_price=trade.open_price,
            close_price=trade.price,
            realized_pnl=trade.pnl,
            underlying_entry_price=None,
            underlying_exit_price=None,
            features=empty_features.to_dict(),
            profiles={
                "entry_session": None,
                "exit_session": None,
                "context_summary": ContextSummary(
                    poc_migration="balance",
                    balance_days=0,
                    trend_days=0,
                    session_count=0,
                ).to_dict(),
            },
            grade=TpoGrade(status="error", error=str(exc)).to_dict(),
        )

    underlying = extract_underlying_symbol(trade.symbol) or trade.underlying
    trade_payload = {
        "symbol": trade.symbol,
        "underlying": underlying,
        "direction": trade.direction,
        "instrument_type": trade.instrument_type,
        "quantity": trade.quantity,
        "open_price": trade.open_price,
        "close_price": trade.price,
        "realized_pnl": trade.pnl,
        "open_datetime": trade.open_datetime.isoformat() if trade.open_datetime else trade.open_date.isoformat(),
        "close_datetime": trade.trade_datetime.isoformat() if trade.trade_datetime else trade.trade_date.isoformat(),
        "underlying_entry_price": entry_px,
        "underlying_exit_price": exit_px,
    }
    grade = grade_trade_record(
        features=features,
        trade_payload=trade_payload,
        entry_ascii=entry_summary.tpo_ascii if entry_summary else None,
        exit_ascii=exit_summary.tpo_ascii if exit_summary else None,
        context_summary=context.to_dict(),
        use_llm=use_llm,
    )
    return TpoGradeRecord.from_trade(
        trade,
        underlying=underlying,
        underlying_entry_price=entry_px,
        underlying_exit_price=exit_px,
        features=features,
        entry_profile=entry_summary,
        exit_profile=exit_summary,
        context=context,
        grade=grade,
    )


def export_tpo_grades(
    trades: Sequence[RealizedTrade],
    *,
    start_date: date | None,
    end_date: date | None,
    context_before: int = 10,
    context_after: int = 10,
    period_minutes: int = 30,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    throttle_seconds: float = 0.12,
    use_llm: bool = False,
    limit: int | None = None,
) -> TpoGradesDocument:
    selected = list(trades)
    if limit is not None:
        selected = selected[:limit]

    records: list[TpoGradeRecord] = []
    for index, trade in enumerate(selected, start=1):
        print(
            f"[{index}/{len(selected)}] grading {trade.symbol} "
            f"{trade.open_date}→{trade.trade_date} pnl={trade.pnl:.2f}"
        )
        records.append(
            grade_realized_trade(
                trade,
                context_before=context_before,
                context_after=context_after,
                period_minutes=period_minutes,
                cache_dir=cache_dir,
                throttle_seconds=throttle_seconds,
                use_llm=use_llm,
            )
        )

    metadata = {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "tpo_period_minutes": period_minutes,
        "context_sessions_before": context_before,
        "context_sessions_after": context_after,
        "bar_source": "polygon_minute",
        "grader_provider": get_grade_provider() if use_llm else None,
        "grader_model": get_grade_model() if use_llm else None,
        "rubric_version": "1.0",
        "trade_count": len(records),
        "grade_llm": use_llm,
    }
    return TpoGradesDocument(metadata=metadata, trades=records)


def load_tpo_grades(path: Path) -> TpoGradesDocument:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TpoGradesDocument.from_dict(payload)


def discover_tpo_grades_file(
    order_data_dir: Path = ORDER_DATA_DIR,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Path | None:
    candidates = sorted(order_data_dir.glob("trade-tpo-grades-*.json"), reverse=True)
    candidates = [path for path in candidates if "smoke" not in path.name.lower()]
    if not candidates:
        return None
    if start_date and end_date:
        exact = order_data_dir / f"trade-tpo-grades-{start_date.isoformat()}_to_{end_date.isoformat()}.json"
        if exact.exists():
            return exact
    # Prefer dated exports over ad-hoc filenames.
    dated = [path for path in candidates if any(ch.isdigit() for ch in path.name)]
    return (dated or candidates)[0]


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date and end_date and start_date > end_date:
        raise SystemExit("start-date must be on or before end-date")

    output = args.output or _default_output_path(start_date, end_date)

    if args.rescan_errors:
        from .rescan_market_data import main as rescan_main

        rescan_argv = [
            "--target",
            "tpo",
            "--tpo-grades",
            str(output),
            "--csv",
            str(args.csv),
            "--cache-dir",
            str(args.cache_dir),
            "--throttle-seconds",
            str(args.rescan_throttle_seconds),
        ]
        if args.start_date:
            rescan_argv.extend(["--start-date", args.start_date])
        if args.end_date:
            rescan_argv.extend(["--end-date", args.end_date])
        if args.limit is not None:
            rescan_argv.extend(["--limit", str(args.limit)])
        rescan_main(rescan_argv)
        if args.print_summary and output.exists():
            print(summarize_quality_buckets(load_tpo_grades(output).trades))
        return

    orders = load_orders(args.csv)
    orders = filter_orders(orders, symbol=args.symbol, instrument_type=args.instrument_type)
    # Keep warmup opens through end_date for lot matching
    orders = filter_orders_by_date(orders, None, end_date)
    result = analyze_orders(orders)
    trades = filter_trades_by_close_date(result.realized_trades, start_date, end_date)
    if not trades:
        raise SystemExit("No realized trades in the selected window.")

    doc = export_tpo_grades(
        trades,
        start_date=start_date,
        end_date=end_date,
        context_before=args.context_before,
        context_after=args.context_after,
        period_minutes=args.tpo_period_minutes,
        cache_dir=args.cache_dir,
        throttle_seconds=args.throttle_seconds,
        use_llm=args.grade_llm,
        limit=args.limit,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc.to_dict(), indent=2), encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="trade-tpo-grades",
        study_name="Trade TPO Execution Grades",
        version="1.0",
        generator="trading_analysis.export_tpo_grades",
        files={"grades": output},
        parameters={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        metrics=[{"label": "Trades graded", "value": len(doc.trades)}],
    )
    print(f"Wrote {len(doc.trades)} TPO grades to {output}")
    print(f"Published dashboard study {dashboard_output}")
    if args.grade_llm:
        print(f"LLM grader: provider={get_grade_provider()} model={get_grade_model()}")
    if args.print_summary:
        print(summarize_quality_buckets(doc.trades))


if __name__ == "__main__":
    main()
