"""
Configuration settings for the trading backtester
"""
from datetime import timedelta

# Default data range for historical data downloads
DEFAULT_DATA_RANGE_YEARS = 10

# Default timeframe for backtesting
DEFAULT_TIMEFRAME = '5m'

# Data directory configuration
DATA_DIR = 'data'
RESULTS_DIR = 'results'

# Supported timeframes for backtesting
SUPPORTED_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '1d']

# Maximum API request chunk size (days)
MAX_CHUNK_SIZE_DAYS = 30