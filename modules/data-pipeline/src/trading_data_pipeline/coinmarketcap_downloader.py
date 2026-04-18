"""Standalone CoinMarketCap downloader for crypto OHLCV history."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from dotenv import find_dotenv, load_dotenv

from .downloader import DEFAULT_DATA_DIR

load_dotenv(find_dotenv(usecwd=True))

CMC_OHLCV_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical"
DEFAULT_CMC_DATA_DIR = DEFAULT_DATA_DIR / "cmc"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download historical OHLCV from CoinMarketCap")
    parser.add_argument("ticker", help="Crypto symbol (e.g. BTC, ETH, SOL)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_CMC_DATA_DIR,
        help="Destination directory for CoinMarketCap CSV files (default: %(default)s)",
    )
    parser.add_argument(
        "--convert",
        default="USD",
        help="Quote currency for returned OHLCV values (default: %(default)s)",
    )
    parser.add_argument(
        "--time-period",
        default="daily",
        help="CMC time_period value (examples: daily, hourly) (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        help="Optional CMC interval sampling value (examples: 1h, 6h, daily, weekly)",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date/time in YYYY-MM-DD or ISO 8601 format",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date/time in YYYY-MM-DD or ISO 8601 format",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Optional max number of periods to return",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: %(default)s)",
    )
    return parser


def _parse_datetime(value: str) -> datetime:
    if "T" not in value:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_for_api(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _flatten_quotes(payload: dict[str, Any], convert: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    convert_key = convert.upper()

    def walk(node: Any, fallback_symbol: str | None = None) -> None:
        if isinstance(node, dict):
            symbol = node.get("symbol") or fallback_symbol
            quotes = node.get("quotes")
            if isinstance(quotes, list):
                for quote in quotes:
                    if not isinstance(quote, dict):
                        continue
                    quote_block = quote.get("quote") or {}
                    value_block = quote_block.get(convert_key) if isinstance(quote_block, dict) else None
                    if value_block is None and isinstance(quote_block, dict) and len(quote_block) == 1:
                        value_block = next(iter(quote_block.values()))
                    if not isinstance(value_block, dict):
                        continue
                    timestamp = (
                        quote.get("time_open")
                        or quote.get("time_close")
                        or quote.get("timestamp")
                    )
                    if not timestamp:
                        continue
                    rows.append(
                        {
                            "timestamp": timestamp,
                            "open": value_block.get("open"),
                            "high": value_block.get("high"),
                            "low": value_block.get("low"),
                            "close": value_block.get("close"),
                            "volume": value_block.get("volume"),
                            "market_cap": value_block.get("market_cap"),
                            "ticker": symbol,
                            "source": "coinmarketcap",
                        }
                    )

            for value in node.values():
                walk(value, symbol)
            return

        if isinstance(node, list):
            for item in node:
                walk(item, fallback_symbol)

    walk(payload.get("data", payload))
    return rows


def _resolve_cmc_api_key() -> str:
    api_key = (os.getenv("COIN_MARKET_CAP") or os.getenv("CMC_PRO_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("COIN_MARKET_CAP environment variable is required")
    return api_key


def fetch_ohlcv(
    ticker: str,
    *,
    api_key: str,
    convert: str,
    time_period: str,
    start_date: datetime,
    end_date: datetime,
    interval: str | None = None,
    count: int | None = None,
    timeout_seconds: int = 30,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if start_date >= end_date:
        raise ValueError("start-date must be earlier than end-date")

    params: dict[str, Any] = {
        "symbol": ticker.upper(),
        "convert": convert.upper(),
        "time_period": time_period,
        "time_start": _format_for_api(start_date),
        "time_end": _format_for_api(end_date),
    }
    if interval:
        params["interval"] = interval
    if count:
        params["count"] = count

    headers = {
        "Accept": "application/json",
        "X-CMC_PRO_API_KEY": api_key,
    }
    http = session or requests.Session()
    response = http.get(CMC_OHLCV_URL, params=params, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()

    status = payload.get("status", {})
    error_code = status.get("error_code", 0)
    if error_code:
        raise RuntimeError(f"CoinMarketCap error {error_code}: {status.get('error_message', 'unknown error')}")

    rows = _flatten_quotes(payload, convert)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "market_cap", "ticker", "source"])

    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close", "volume", "market_cap"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["ticker"] = frame["ticker"].fillna(ticker.upper()).astype(str).str.upper()
    frame["source"] = "coinmarketcap"

    frame = frame.dropna(subset=["timestamp"])
    frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp", "ticker"], keep="last")
    return frame[["timestamp", "open", "high", "low", "close", "volume", "market_cap", "ticker", "source"]]


def _sanitize_symbol(symbol: str) -> str:
    return symbol.replace(":", "_").replace("/", "-")


def write_csv(frame: pd.DataFrame, ticker: str, output_dir: Path, timeframe: str) -> Path:
    target_dir = output_dir / timeframe
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize_symbol(ticker.upper())}-CMC-{timeframe}.csv"
    output_path = target_dir / filename
    frame.to_csv(output_path, index=False)
    return output_path


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    api_key = _resolve_cmc_api_key()

    start_date = _parse_datetime(args.start_date)
    end_date = _parse_datetime(args.end_date)
    frame = fetch_ohlcv(
        args.ticker,
        api_key=api_key,
        convert=args.convert,
        time_period=args.time_period,
        start_date=start_date,
        end_date=end_date,
        interval=args.interval,
        count=args.count,
        timeout_seconds=args.timeout,
    )
    if frame.empty:
        raise SystemExit(
            f"No OHLCV rows returned for {args.ticker.upper()} "
            f"between {start_date.isoformat()} and {end_date.isoformat()}"
        )

    timeframe_label = args.interval or args.time_period
    output_path = write_csv(frame, args.ticker, args.output_dir, timeframe_label)
    print(f"Wrote {len(frame)} rows to {output_path}")


if __name__ == "__main__":  # pragma: no cover
    main()
