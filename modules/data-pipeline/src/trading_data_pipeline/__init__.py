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
from .chart_annotations import (
    SCHEMA_VERSION as CHART_ANNOTATION_SCHEMA_VERSION,
    empty_annotation_document,
    load_annotation_document,
    normalize_annotation_document,
)
from .chart_workspace import (
    SCHEMA_VERSION as CHART_WORKSPACE_SCHEMA_VERSION,
    WorkspaceView,
    render_chart_workspace_html,
)
from .dealing_ranges import compute_dealing_ranges

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_WATCHLIST_PATH",
    "DEFAULT_DATA_DIR",
    "DownloadConfig",
    "DownloadSettings",
    "CHART_ANNOTATION_SCHEMA_VERSION",
    "CHART_WORKSPACE_SCHEMA_VERSION",
    "PolygonDownloader",
    "StrategyConfig",
    "StrategyTrade",
    "StrategyResult",
    "WorkspaceView",
    "build_chart_payload",
    "build_trade",
    "compute_strategy_statistics",
    "compute_archived_indicator_payload",
    "compute_dealing_ranges",
    "compute_fisher_adaptive_macd_strategy",
    "download_historical_data",
    "empty_annotation_document",
    "load_annotation_document",
    "load_download_config",
    "read_watchlist",
    "render_chart_workspace_html",
    "normalize_annotation_document",
    "serialize_trades",
]
