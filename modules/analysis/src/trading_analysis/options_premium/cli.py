"""CLI for options premium discovery / fetch / chart (agent-facing)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from trading_analysis.parse_orders import ORDER_DATA_DIR

from .api import PLOT_SERIES_CAP, build_premium_payload, default_lookback_window
from .chart import write_premium_chart_html
from .contracts import (
    DEFAULT_DTE_MAX,
    DEFAULT_DTE_MIN,
    DEFAULT_MIN_OI,
    DEFAULT_MIN_VOLUME,
    DEFAULT_MONEYNESS_BAND,
    list_liquid_contracts,
)
from .watchlist import DEFAULT_WATCHLIST_PATH, load_watchlist


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Options premium vs underlying — agent/CLI API. "
            "Discovers liquid 15–60 DTE contracts via Polygon and exports JSON/HTML."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        src = p.add_mutually_exclusive_group()
        src.add_argument("--symbol", help="Underlying ticker (overrides watchlist)")
        src.add_argument(
            "--watchlist",
            type=Path,
            default=None,
            help=f"Txt watchlist path (default for list-all: {DEFAULT_WATCHLIST_PATH})",
        )
        p.add_argument("--asof", type=_parse_date, help="DTE as-of date (YYYY-MM-DD)")
        p.add_argument("--dte-min", type=int, default=DEFAULT_DTE_MIN)
        p.add_argument("--dte-max", type=int, default=DEFAULT_DTE_MAX)
        p.add_argument("--min-volume", type=int, default=DEFAULT_MIN_VOLUME)
        p.add_argument("--min-oi", type=int, default=DEFAULT_MIN_OI)
        p.add_argument(
            "--type",
            choices=("call", "put"),
            dest="option_type",
            default=None,
            help="Restrict to calls or puts",
        )
        p.add_argument("--strike-min", type=float, default=None)
        p.add_argument("--strike-max", type=float, default=None)
        p.add_argument(
            "--expiry",
            action="append",
            default=None,
            help="Expiration YYYY-MM-DD (repeatable)",
        )
        p.add_argument(
            "--contract",
            action="append",
            default=None,
            help="OCC symbol filter (repeatable)",
        )
        p.add_argument("--force-refresh", action="store_true")
        p.add_argument(
            "--throttle-seconds",
            type=float,
            default=0.05,
            help="Delay between option bar fetches",
        )
        p.add_argument(
            "--skip-volume-attach",
            action="store_true",
            help="Skip per-contract volume lookup (faster list; ignores min-volume)",
        )
        p.add_argument(
            "--moneyness-band",
            type=float,
            default=DEFAULT_MONEYNESS_BAND,
            help=(
                "Limit volume scan to strikes within ±band of spot "
                f"(default: {DEFAULT_MONEYNESS_BAND}; 0 = no band)"
            ),
        )

    list_p = sub.add_parser("list", help="List liquid contracts as JSON")
    add_common(list_p)
    list_p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write JSON to path (default: stdout)",
    )

    fetch_p = sub.add_parser("fetch", help="Fetch underlying + premium series JSON")
    add_common(fetch_p)
    fetch_p.add_argument("--start-date", type=_parse_date, help="Series start YYYY-MM-DD")
    fetch_p.add_argument("--end-date", type=_parse_date, help="Series end YYYY-MM-DD")
    fetch_p.add_argument(
        "--lookback-days",
        type=int,
        default=60,
        help="Used when start/end omitted (default: 60)",
    )
    fetch_p.add_argument(
        "--select",
        action="append",
        default=None,
        help="OCC symbol to include in series (repeatable; default: all liquid up to cap)",
    )
    fetch_p.add_argument("--series-cap", type=int, default=PLOT_SERIES_CAP)
    fetch_p.add_argument("--no-high", action="store_true", help="Omit daily high series")
    fetch_p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write JSON to path (default: stdout)",
    )

    chart_p = sub.add_parser("chart", help="Write Plotly HTML chart")
    add_common(chart_p)
    chart_p.add_argument("--start-date", type=_parse_date)
    chart_p.add_argument("--end-date", type=_parse_date)
    chart_p.add_argument("--lookback-days", type=int, default=60)
    chart_p.add_argument("--select", action="append", default=None)
    chart_p.add_argument("--series-cap", type=int, default=PLOT_SERIES_CAP)
    chart_p.add_argument("--no-close", action="store_true")
    chart_p.add_argument("--no-high", action="store_true")
    chart_p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ORDER_DATA_DIR / "options-premium-chart.html",
        help="HTML output path",
    )
    chart_p.add_argument("--open", action="store_true", help="Open HTML in browser")

    return parser


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbol:
        return [args.symbol.upper()]
    path = args.watchlist if args.watchlist is not None else DEFAULT_WATCHLIST_PATH
    symbols = load_watchlist(path)
    if not symbols:
        raise SystemExit(
            f"No symbols: pass --symbol or add tickers to {path}"
        )
    return symbols


def _dump(payload: object, output: Path | None) -> None:
    text = json.dumps(payload, indent=2, default=str)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {output}", file=sys.stderr)
    else:
        print(text)


def _cmd_list(args: argparse.Namespace) -> int:
    symbols = _resolve_symbols(args)
    attach = not args.skip_volume_attach
    min_volume = 0 if args.skip_volume_attach else args.min_volume
    rows: list[dict] = []
    for ticker in symbols:
        band = None if args.moneyness_band == 0 else args.moneyness_band
        contracts = list_liquid_contracts(
            ticker,
            asof=args.asof,
            dte_min=args.dte_min,
            dte_max=args.dte_max,
            min_volume=min_volume,
            min_oi=args.min_oi,
            option_type=args.option_type,
            strike_min=args.strike_min,
            strike_max=args.strike_max,
            expirations=set(args.expiry) if args.expiry else None,
            symbols=set(s.upper() for s in args.contract) if args.contract else None,
            attach_volume=attach,
            throttle_seconds=args.throttle_seconds,
            force_refresh=args.force_refresh,
            moneyness_band=band,
        )
        rows.append(
            {
                "ticker": ticker,
                "count": len(contracts),
                "contracts": [c.to_dict() for c in contracts],
            }
        )
    payload = rows[0] if len(rows) == 1 else {"tickers": rows}
    _dump(payload, args.output)
    return 0


def _build_payload_from_args(args: argparse.Namespace, ticker: str) -> dict:
    if args.start_date and args.end_date:
        start, end = args.start_date, args.end_date
    elif args.start_date or args.end_date:
        raise SystemExit("Provide both --start-date and --end-date, or neither")
    else:
        start, end = default_lookback_window(end=args.asof, days=args.lookback_days)
    band = None if args.moneyness_band == 0 else args.moneyness_band
    return build_premium_payload(
        ticker,
        start_date=start,
        end_date=end,
        asof=args.asof or end,
        dte_min=args.dte_min,
        dte_max=args.dte_max,
        min_volume=0 if args.skip_volume_attach else args.min_volume,
        min_oi=args.min_oi,
        option_type=args.option_type,
        strike_min=args.strike_min,
        strike_max=args.strike_max,
        expirations=args.expiry,
        symbols=args.contract,
        selected_symbols=args.select,
        include_high=not args.no_high,
        attach_volume=not args.skip_volume_attach,
        throttle_seconds=args.throttle_seconds,
        force_refresh=args.force_refresh,
        series_cap=args.series_cap,
        moneyness_band=band,
    )


def _cmd_fetch(args: argparse.Namespace) -> int:
    symbols = _resolve_symbols(args)
    if len(symbols) != 1:
        raise SystemExit("fetch requires a single --symbol (or a one-ticker watchlist)")
    payload = _build_payload_from_args(args, symbols[0])
    _dump(payload, args.output)
    return 0


def _cmd_chart(args: argparse.Namespace) -> int:
    symbols = _resolve_symbols(args)
    if len(symbols) != 1:
        raise SystemExit("chart requires a single --symbol (or a one-ticker watchlist)")
    payload = _build_payload_from_args(args, symbols[0])
    path = write_premium_chart_html(
        payload,
        args.output,
        selected_symbols=args.select,
        show_close=not args.no_close,
        show_high=not args.no_high,
        auto_open=args.open,
    )
    print(f"Wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "fetch":
        return _cmd_fetch(args)
    if args.command == "chart":
        return _cmd_chart(args)
    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
