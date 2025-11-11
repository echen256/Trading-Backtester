import pandas as pd
import pandas_ta as ta
import os
from .indicators import get_indicator, BaseIndicator
from typing import List, Union, Dict, Any

# Default indicator configurations
default_indicators = [
    {"name": "rsi", "params": {"length": 14}},
    {"name": "atr", "params": {"length": 14}},
    {"name": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}}
]


def execute_strategy(
    file_name: str, 
    start_date=None, 
    end_date=None, 
    strategy_name: str = "Default", 
    indicators: Union[List[str], List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Execute trading strategy with configurable indicators.
    
    Args:
        file_name: CSV file name to process
        start_date: Start date for data filtering (optional)
        end_date: End date for data filtering (optional) 
        strategy_name: Name of the strategy
        indicators: List of indicator names or config dicts
    
    Returns:
        Dict with data, indicator_objects, and strategy_name
    """
    # Get the correct path to the data directory from the backend root
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = os.path.join(backend_root, "app", "data_download", "data", "1440", file_name)
    data = pd.read_csv(data_path)
    
    # Use default indicators if none provided
    if indicators is None:
        indicators = [{"name": "rsi", "params": {"length": 14}}]
    
    # Convert string indicators to dict format
    indicator_configs = []
    for ind in indicators:
        if isinstance(ind, str):
            indicator_configs.append({"name": ind, "params": {}})
        else:
            indicator_configs.append(ind)
    
    # Create and apply indicators
    indicator_objects = []
    for config in indicator_configs:
        try:
            indicator = get_indicator(config["name"], **config.get("params", {}))
            data = indicator.calculate(data)
            indicator_objects.append(indicator)
            print(f"Applied {indicator.name} indicator")
        except Exception as e:
            print(f"Warning: Failed to apply {config['name']} indicator: {e}")
    
    # Filter by date range if provided
    if start_date or end_date:
        if 'timestamp' in data.columns:
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            if start_date:
                data = data[data['timestamp'] >= pd.to_datetime(start_date)]
            if end_date:
                data = data[data['timestamp'] <= pd.to_datetime(end_date)]
    
    # Save processed data
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", f"strategy_{strategy_name}")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, file_name)
    data.to_csv(output_path, index=False)
    
    return {
        "data": data, 
        "indicator_objects": indicator_objects,
        "strategy_name": strategy_name
    }


def get_default_indicators() -> List[BaseIndicator]:
    """Get list of default indicator instances."""
    return [get_indicator(config["name"], **config["params"]) for config in default_indicators]