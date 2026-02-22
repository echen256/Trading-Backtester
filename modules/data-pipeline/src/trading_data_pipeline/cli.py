"""Command-line interface for the data download workflow."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_WATCHLIST_PATH,
    DownloadConfig,
    load_download_config,
    read_watchlist,
)
from .downloader import DEFAULT_DATA_DIR, DownloadSettings, PolygonDownloader


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download historical bars from Polygon.io")
    parser.add_argument("ticker", nargs="?", help="Single ticker (overrides watchlist when provided)")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the JSON config file (default: %(default)s)",
    )
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=DEFAULT_WATCHLIST_PATH,
        help="CSV file containing tickers to download (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Destination directory for CSV files (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=1440,
        help="Bar size in minutes (default: %(default)s)",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=30,
        help="Number of days per API request (default: %(default)s)",
    )
    parser.add_argument(
        "--lookback-years",
        type=int,
        default=5,
        help="How many years of history to download when start/end are omitted",
    )
    parser.add_argument(
        "--start-date",
        help="Optional YYYY-MM-DD override for the download window start",
    )
    parser.add_argument(
        "--end-date",
        help="Optional YYYY-MM-DD override for the download window end",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of tickers to download from the watchlist",
    )
    parser.add_argument(
        "--minimum-market-cap",
        type=int,
        help="Override the market-cap filter from the config file",
    )
    parser.add_argument(
        "--skip-filter",
        action="store_true",
        help="Ignore market-cap checks (useful for crypto tickers)",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=0.25,
        help="Seconds to wait between API calls (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_download_config(args.config)
    downloader = PolygonDownloader()
    settings = DownloadSettings(
        interval_minutes=args.interval,
        chunk_size_days=args.chunk_days,
        lookback_years=args.lookback_years,
        output_dir=args.output_dir,
    )

    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)

    if args.ticker:
        downloader.download_symbol(
            args.ticker,
            settings=settings,
            start_date=start_date,
            end_date=end_date,
            throttle_seconds=args.throttle,
        )
        return

    watchlist = read_watchlist(args.watchlist)
    limit = args.limit if args.limit is not None else config.limit
    minimum_cap = (
        0
        if args.skip_filter
        else args.minimum_market_cap
        if args.minimum_market_cap is not None
        else config.minimum_market_cap
    )
    print(f"Downloading watchlist: {watchlist}")
    downloader.download_watchlist(
        watchlist,
        settings=settings,
        minimum_market_cap=minimum_cap,
        limit=limit,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
