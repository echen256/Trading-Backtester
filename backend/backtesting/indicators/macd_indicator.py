import pandas as pd
import pandas_ta as ta
from typing import Dict, Any, List, Optional, Tuple
from .base_indicator import BaseIndicator


class MACDIndicator(BaseIndicator):
    """MACD (Moving Average Convergence Divergence) indicator."""
    
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(
            name="MACD",
            params={
                "fast": fast,
                "slow": slow,
                "signal": signal
            }
        )
        # MACD returns multiple columns
        self.macd_col = f"macd_{fast}_{slow}_{signal}"
        self.signal_col = f"macds_{fast}_{slow}_{signal}"
        self.hist_col = f"macdh_{fast}_{slow}_{signal}"
    
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate MACD and add to DataFrame."""
        if not self.validate_data(data):
            raise ValueError(f"Data missing required columns: {self.get_required_columns()}")
        
        macd_result = ta.macd(
            data["close"],
            fast=self.params["fast"],
            slow=self.params["slow"],
            signal=self.params["signal"]
        )
        
        # Add MACD columns to data
        data[self.macd_col] = macd_result[self.macd_col]
        data[self.signal_col] = macd_result[self.signal_col]
        data[self.hist_col] = macd_result[self.hist_col]
        
        return data
    
    def get_plot_config(self) -> Dict[str, Any]:
        """Return MACD plot configuration."""
        return {
            "plot_type": "multi",  # Special type for multiple traces
            "subplot_row": 1,  # Separate subplot
            "traces": [
                {
                    "column": self.macd_col,
                    "name": "MACD",
                    "type": "line",
                    "color": "blue",
                    "line": {"width": 2}
                },
                {
                    "column": self.signal_col,
                    "name": "Signal",
                    "type": "line", 
                    "color": "red",
                    "line": {"width": 2}
                },
                {
                    "column": self.hist_col,
                    "name": "Histogram",
                    "type": "bar",
                    "color": "gray",
                    "opacity": 0.6
                }
            ]
        }
    
    def get_required_columns(self) -> List[str]:
        """MACD requires close prices."""
        return ["close"]
    
    def get_subplot_title(self) -> str:
        return f"MACD ({self.params['fast']},{self.params['slow']},{self.params['signal']})"