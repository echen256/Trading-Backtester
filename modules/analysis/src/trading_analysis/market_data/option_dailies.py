"""Option daily bars with shared on-disk cache (trade-hold)."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Sequence

from .cache import (
    DEFAULT_OPTION_DAILY_CACHE_DIR,
    load_option_daily_bars,
    save_option_daily_bars,
)
from .polygon import PolygonHttpError, fetch_aggs


def fetch_option_daily_bars(
    option_symbol: str,
    *,
    start_date: date,
    end_date: date,
    cache_dir: Path = DEFAULT_OPTION_DAILY_CACHE_DIR,
    api_key: str | None = None,
    throttle_seconds: float = 0.0,
    force_refresh: bool = False,
) -> list[dict[str, object]]:
    """
    Cache-first option daily bars for O:{symbol} over [start_date, end_date].

    Raises PolygonHttpError on non-retryable API failures (caller may record
    per-symbol errors and continue).
    """
    symbol = option_symbol.upper()
    if not force_refresh:
        cached = load_option_daily_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            cache_dir=cache_dir,
        )
        if cached is not None:
            return cached

    try:
        results = fetch_aggs(
            f"O:{symbol}",
            multiplier=1,
            timespan="day",
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            timeout=30.0,
        )
    except PolygonHttpError as exc:
        # Persist the failure so rescan can target it without re-hitting every symbol.
        save_option_daily_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            bars=[],
            cache_dir=cache_dir,
            error=str(exc),
        )
        raise

    save_option_daily_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        bars=results,
        cache_dir=cache_dir,
    )
    if throttle_seconds > 0:
        time.sleep(throttle_seconds)
    return results


def option_symbols_with_cache_errors(
    option_symbols: Sequence[str],
    *,
    cache_dir: Path = DEFAULT_OPTION_DAILY_CACHE_DIR,
) -> list[str]:
    from .cache import load_json, option_daily_cache_path

    errored: list[str] = []
    for symbol in option_symbols:
        payload = load_json(option_daily_cache_path(symbol, cache_dir))
        if payload and payload.get("error"):
            errored.append(symbol.upper())
    return sorted(set(errored))
