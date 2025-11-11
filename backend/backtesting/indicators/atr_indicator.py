import pandas as pd
import pandas_ta as ta
from typing import Dict, Any, List, Optional, Tuple
from .base_indicator import BaseIndicator


class ATRIndicator(BaseIndicator):
    """Average True Range (ATR) indicator."""
    
    def __init__(self, length: int = 14, scalar: float = 1, offset: int = 0):
        super().__init__(
            name="ATR",
            params={
                "length": length,
                "scalar": scalar,
                "offset": offset
            }
        )
    
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate ATR and add to DataFrame."""
        if not self.validate_data(data):
            raise ValueError(f"Data missing required columns: {self.get_required_columns()}")
        
        atr = ta.atr(
            high=data["high"],
            low=data["low"],
            close=data["close"],
            length=self.params["length"],
            scalar=self.params["scalar"],
            offset=self.params["offset"]
        )
        data[self.column_name] = atr
        return data
    
    def get_plot_config(self) -> Dict[str, Any]:
        """Return ATR plot configuration."""
        return {
            "plot_type": "line",
            "subplot_row": 1,  # Separate subplot
            "color": "orange",
            "additional_config": {
                "line": {"width": 2},
                "hovertemplate": f"{self.name}: %{{y:.4f}}<extra></extra>"
            }
        }
    
    def get_required_columns(self) -> List[str]:
        """ATR requires high, low, and close prices."""
        return ["high", "low", "close"]
    
    def get_subplot_title(self) -> str:
        return f"ATR ({self.params['length']})"