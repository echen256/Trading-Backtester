"""Shared Polygon market-data fetch + on-disk cache for TPO and trade-hold."""

from .cache import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_OPTION_CONTRACTS_CACHE_DIR,
    DEFAULT_OPTION_DAILY_CACHE_DIR,
    DEFAULT_UNDERLYING_DAILY_CACHE_DIR,
    DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    LEGACY_TPO_CACHE_DIR,
)
from .env import REPO_ROOT, get_polygon_api_key, load_env_value
from .option_dailies import fetch_option_daily_bars
from .polygon import PolygonHttpError, fetch_aggs
from .underlying_dailies import fetch_underlying_daily_bars
from .underlying_minutes import (
    fetch_session_minute_bars,
    fetch_sessions_minute_bars,
    filter_rth_bars,
    parse_bar_timestamp,
    underlying_price_at,
)

__all__ = [
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_OPTION_CONTRACTS_CACHE_DIR",
    "DEFAULT_OPTION_DAILY_CACHE_DIR",
    "DEFAULT_UNDERLYING_DAILY_CACHE_DIR",
    "DEFAULT_UNDERLYING_MINUTE_CACHE_DIR",
    "LEGACY_TPO_CACHE_DIR",
    "PolygonHttpError",
    "REPO_ROOT",
    "fetch_aggs",
    "fetch_option_daily_bars",
    "fetch_session_minute_bars",
    "fetch_sessions_minute_bars",
    "fetch_underlying_daily_bars",
    "filter_rth_bars",
    "get_polygon_api_key",
    "load_env_value",
    "parse_bar_timestamp",
    "underlying_price_at",
]
