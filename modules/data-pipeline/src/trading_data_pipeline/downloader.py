"""Utilities for downloading Polygon.io aggregates and maintaining local CSV archives."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

import pandas as pd
import requests
from dotenv import load_dotenv
from polygon import RESTClient

load_dotenv()
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"


@dataclass(slots=True)
class DownloadSettings:
    """Controls interval, window sizes, and destination for downloads."""

    interval_minutes: int = 1440
    chunk_size_days: int = 30
    lookback_years: int = 5
    output_dir: Path = DEFAULT_DATA_DIR


class PolygonDownloader:
    """Thin wrapper around the Polygon REST client with convenience helpers."""

    def __init__(self, api_key: str | None = None, *, request_session: requests.Session | None = None) -> None:
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise RuntimeError("POLYGON_API_KEY environment variable is not set.")
        self.client = RESTClient(self.api_key)
        self.session = request_session or requests.Session()

    def download_watchlist(
        self,
        symbols: Sequence[str],
        *,
        settings: DownloadSettings | None = None,
        minimum_market_cap: int = 0,
        limit: int | None = None,
    ) -> list[Path]:
        """Download data for every symbol that passes the market-cap filter."""

        resolved_settings = settings or DownloadSettings()
        downloaded: list[Path] = []

        for symbol in symbols:
            if limit is not None and len(downloaded) >= limit:
                break
            if minimum_market_cap and not self._passes_market_cap(symbol, minimum_market_cap):
                continue
            result = self.download_symbol(symbol, settings=resolved_settings)
            if result:
                downloaded.append(result)
        return downloaded

    def download_symbol(
        self,
        symbol: str,
        *,
        settings: DownloadSettings | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        throttle_seconds: float = 0.25,
    ) -> Path | None:
        """Download a symbol into the configured CSV archive.

        Returns the path to the CSV if at least one aggregate was downloaded.
        """

        resolved_settings = settings or DownloadSettings()
        end = end_date or datetime.utcnow()
        start = start_date or end - timedelta(days=resolved_settings.lookback_years * 365)
        if start >= end:
            raise ValueError("start_date must be earlier than end_date")

        frames: list[pd.DataFrame] = []
        current = start
        chunk = timedelta(days=resolved_settings.chunk_size_days)
        while current < end:
            window_end = min(current + chunk, end)
            frame = self._fetch_range(symbol, current, window_end, resolved_settings.interval_minutes)
            if not frame.empty:
                frames.append(frame)
            current = window_end
            if throttle_seconds:
                time.sleep(throttle_seconds)

        if not frames:
            return None

        df = pd.concat(frames)
        df = df[~df.index.duplicated()].sort_index()
        df["ticker"] = symbol

        timeframe_dir = resolved_settings.output_dir / str(resolved_settings.interval_minutes)
        timeframe_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._sanitize_symbol(symbol)}-{resolved_settings.interval_minutes}M.csv"
        output_path = timeframe_dir / filename
        df.to_csv(output_path)
        return output_path

    def fetch_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval_minutes: int,
    ) -> pd.DataFrame:
        """Return an in-memory DataFrame for ad-hoc use (no persistence)."""

        frame = self._fetch_range(symbol, start_date, end_date, interval_minutes)
        return frame

    def _fetch_range(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval_minutes: int,
    ) -> pd.DataFrame:
        multiplier, timespan = self._interval_to_polygon(interval_minutes)
        aggs = self.client.get_aggs(
            symbol,
            multiplier=multiplier,
            timespan=timespan,
            from_=start_date.strftime("%Y-%m-%d"),
            to=end_date.strftime("%Y-%m-%d"),
            limit=50000,
        )
        df = pd.DataFrame(aggs)
        if df.empty:
            return df
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
        return df

    def _passes_market_cap(self, symbol: str, minimum_market_cap: int) -> bool:
        url = f"https://api.polygon.io/v3/reference/tickers/{symbol}"
        params = {"apiKey": self.api_key}
        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "OK":
            return False
        market_cap = (payload.get("results") or {}).get("market_cap")
        if market_cap is None:
            return False
        return int(market_cap) >= int(minimum_market_cap)

    @staticmethod
    def _interval_to_polygon(interval_minutes: int) -> tuple[int, str]:
        if interval_minutes % 1440 == 0:
            return max(interval_minutes // 1440, 1), "day"
        if interval_minutes % 60 == 0:
            return max(interval_minutes // 60, 1), "hour"
        if interval_minutes % 15 == 0:
            return max(interval_minutes // 15, 1), "minute"
        return max(interval_minutes, 1), "minute"

    @staticmethod
    def _sanitize_symbol(symbol: str) -> str:
        return symbol.replace(":", "_").replace("/", "-")


def download_historical_data(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    interval: int | str,
) -> pd.DataFrame:
    """Compatibility helper for the Flask routes.

    This mirrors the original `download_historical_data` signature but delegates
    to :class:`PolygonDownloader`.  ``interval`` may be an ``int`` or a string
    representation of minutes.
    """

    interval_minutes = int(interval)
    downloader = PolygonDownloader()
    return downloader.fetch_bars(symbol, start_date, end_date, interval_minutes)


__all__ = [
    "DownloadSettings",
    "PolygonDownloader",
    "download_historical_data",
    "DEFAULT_DATA_DIR",
]
