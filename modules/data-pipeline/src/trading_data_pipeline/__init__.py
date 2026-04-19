"""Trading data download and synchronization helpers."""

from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_WATCHLIST_PATH,
    DownloadConfig,
    load_download_config,
    read_watchlist,
)

try:
    from .downloader import DEFAULT_DATA_DIR, DownloadSettings, PolygonDownloader, download_historical_data
except ModuleNotFoundError:  # Allows lighter subcommands to run without full optional runtime deps installed.
    DEFAULT_DATA_DIR = None
    DownloadSettings = None
    PolygonDownloader = None
    download_historical_data = None

from .strategies.fisher_adaptive_macd import (
    StrategyConfig,
    StrategyResult,
    build_chart_payload,
    compute_archived_indicator_payload,
    compute_fisher_adaptive_macd_strategy,
)
from .strategy_metrics import StrategyTrade, build_trade, compute_strategy_statistics, serialize_trades

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_WATCHLIST_PATH",
    "DEFAULT_DATA_DIR",
    "DownloadConfig",
    "DownloadSettings",
    "PolygonDownloader",
    "StrategyConfig",
    "StrategyTrade",
    "StrategyResult",
    "build_chart_payload",
    "build_trade",
    "compute_strategy_statistics",
    "compute_archived_indicator_payload",
    "compute_fisher_adaptive_macd_strategy",
    "download_historical_data",
    "load_download_config",
    "read_watchlist",
    "serialize_trades",
]
