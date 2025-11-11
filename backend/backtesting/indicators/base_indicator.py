from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple


class BaseIndicator(ABC):
    """Abstract base class for all trading indicators."""
    
    def __init__(self, name: str, params: Dict[str, Any] = None):
        self.name = name
        self.params = params or {}
        self.column_name = name.lower()
    
    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate the indicator and add it to the DataFrame.
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            DataFrame with indicator column(s) added
        """
        pass
    
    @abstractmethod
    def get_plot_config(self) -> Dict[str, Any]:
        """
        Return plotting configuration for this indicator.
        
        Returns:
            Dict with plot configuration including:
            - plot_type: 'line', 'bar', 'scatter', etc.
            - subplot_row: which subplot row to plot on (0=main chart, 1+ = separate subplot)
            - color: plot color
            - additional_config: any plotly-specific configuration
        """
        pass
    
    def validate_data(self, data: pd.DataFrame) -> bool:
        """Validate that the data contains required columns for this indicator."""
        required_columns = self.get_required_columns()
        return all(col in data.columns for col in required_columns)
    
    @abstractmethod
    def get_required_columns(self) -> List[str]:
        """Return list of required column names for this indicator."""
        pass
    
    def get_subplot_title(self) -> str:
        """Return title for the subplot (if using separate subplot)."""
        return self.name.upper()
    
    def get_y_axis_range(self) -> Optional[Tuple[float, float]]:
        """Return optional y-axis range for this indicator's subplot."""
        return None