"""Polygon minute-bar fetch with per-day on-disk cache.

Thin compatibility wrapper around :mod:`trading_analysis.market_data`.
New code should import from ``trading_analysis.market_data`` directly.
"""

from __future__ import annotations

from ..market_data import (
    DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    REPO_ROOT,
    fetch_session_minute_bars,
    fetch_sessions_minute_bars,
    filter_rth_bars,
    get_polygon_api_key,
    load_env_value,
    parse_bar_timestamp,
    underlying_price_at,
)
from ..market_data.cache import (
    LEGACY_TPO_CACHE_DIR,
    load_underlying_day_bars,
    save_underlying_day_bars,
    underlying_minute_cache_path,
)
from ..market_data.env import DEFAULT_ENV_PATH

# Historical default used by older CLI invocations / docs.
DEFAULT_CACHE_DIR = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR

# Back-compat private aliases used by tpo.grade
_get_polygon_api_key = get_polygon_api_key
_load_env_value = load_env_value


def cache_path_for(underlying: str, session, cache_dir=DEFAULT_CACHE_DIR):
    return underlying_minute_cache_path(underlying, session, cache_dir)


def load_cached_day_bars(underlying: str, session, *, cache_dir=DEFAULT_CACHE_DIR):
    return load_underlying_day_bars(underlying, session, cache_dir=cache_dir)


def save_day_bars(underlying: str, session, bars, *, cache_dir=DEFAULT_CACHE_DIR):
    return save_underlying_day_bars(underlying, session, bars, cache_dir=cache_dir)


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_ENV_PATH",
    "LEGACY_TPO_CACHE_DIR",
    "REPO_ROOT",
    "_get_polygon_api_key",
    "_load_env_value",
    "cache_path_for",
    "fetch_session_minute_bars",
    "fetch_sessions_minute_bars",
    "filter_rth_bars",
    "load_cached_day_bars",
    "parse_bar_timestamp",
    "save_day_bars",
    "underlying_price_at",
]
