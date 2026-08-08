"""Underlying daily bars with shared on-disk cache."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from .cache import (
    DEFAULT_UNDERLYING_DAILY_CACHE_DIR,
    load_underlying_daily_bars,
    save_underlying_daily_bars,
)
from .polygon import PolygonHttpError, fetch_aggs


def fetch_underlying_daily_bars(
    underlying: str,
    *,
    start_date: date,
    end_date: date,
    cache_dir: Path = DEFAULT_UNDERLYING_DAILY_CACHE_DIR,
    api_key: str | None = None,
    throttle_seconds: float = 0.0,
    force_refresh: bool = False,
) -> list[dict[str, object]]:
    """Cache-first daily aggregates for an underlying ticker."""
    symbol = underlying.upper()
    if not force_refresh:
        cached = load_underlying_daily_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            cache_dir=cache_dir,
        )
        if cached is not None:
            return cached

    try:
        results = fetch_aggs(
            symbol,
            multiplier=1,
            timespan="day",
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            timeout=30.0,
        )
    except PolygonHttpError as exc:
        save_underlying_daily_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            bars=[],
            cache_dir=cache_dir,
            error=str(exc),
        )
        raise

    save_underlying_daily_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        bars=results,
        cache_dir=cache_dir,
    )
    if throttle_seconds > 0:
        time.sleep(throttle_seconds)
    return results
