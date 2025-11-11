import pandas as pd
import pandas_ta as ta
from typing import Dict, Any, List, Optional, Tuple
from .base_indicator import BaseIndicator


class RSIIndicator(BaseIndicator):
    """Relative Strength Index (RSI) indicator."""
    
    def __init__(self, length: int = 14, scalar: float = 100, offset: int = 0):
        super().__init__(
            name="RSI",
            params={
                "length": length,
                "scalar": scalar,
                "offset": offset
            }
        )
    
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate RSI and add to DataFrame."""
        if not self.validate_data(data):
            raise ValueError(f"Data missing required columns: {self.get_required_columns()}")
        
        rsi = ta.rsi(
            data["close"], 
            length=self.params["length"],
            scalar=self.params["scalar"],
            offset=self.params["offset"]
        )
        data[self.column_name] = rsi
        return data
    
    def get_plot_config(self) -> Dict[str, Any]:
        """Return RSI plot configuration."""
        return {
            "plot_type": "line",
            "subplot_row": 1,  # Separate subplot
            "color": "purple",
            "additional_config": {
                "line": {"width": 2},
                "hovertemplate": f"{self.name}: %{{y:.2f}}<extra></extra>"
            }
        }
    
    def get_required_columns(self) -> List[str]:
        """RSI requires close prices."""
        return ["close"]
    
    def get_y_axis_range(self) -> Optional[Tuple[float, float]]:
        """RSI typically ranges from 0 to 100."""
        return (0, 100)
    
    def get_subplot_title(self) -> str:
        return f"RSI ({self.params['length']})"