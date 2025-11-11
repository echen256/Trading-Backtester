import numpy as np
import pandas as pd
import pandas_ta as ta
from typing import Dict, Any, List, Optional, Tuple
from .base_indicator import BaseIndicator


class InverseFisherIndicator(BaseIndicator):
    """Inverse Fisher Transform applied to RSI."""

    def __init__(self, rsi_length: int = 9, smoothing_length: int = 5, scalar: float = 0.1):
        super().__init__(
            name="Inverse Fisher",
            params={
                "rsi_length": rsi_length,
                "smoothing_length": smoothing_length,
                "scalar": scalar,
            },
        )
        self.column_name = (
            f"inverse_fisher_{rsi_length}_{smoothing_length}_{str(scalar).replace('.', '_')}"
        )

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate the Inverse Fisher Transform of RSI and add it to the DataFrame."""
        if not self.validate_data(data):
            raise ValueError(f"Data missing required columns: {self.get_required_columns()}")

        rsi_series = ta.rsi(data["close"], length=self.params["rsi_length"])
        scaled = (rsi_series - 50) * self.params["scalar"]
        smoothed = scaled.ewm(span=self.params["smoothing_length"], adjust=False).mean()

        exp_component = np.exp(2 * smoothed)
        inverse_fisher = (exp_component - 1) / (exp_component + 1)

        data[self.column_name] = inverse_fisher
        return data

    def get_plot_config(self) -> Dict[str, Any]:
        """Return plot configuration for the Inverse Fisher Transform."""
        return {
            "plot_type": "line",
            "subplot_row": 1,
            "color": "green",
            "additional_config": {
                "line": {"width": 2},
                "hovertemplate": f"{self.name}: %{{y:.4f}}<extra></extra>",
            },
        }

    def get_required_columns(self) -> List[str]:
        """Inverse Fisher Transform requires close prices."""
        return ["close"]

    def get_y_axis_range(self) -> Optional[Tuple[float, float]]:
        """Inverse Fisher Transform oscillates between -1 and 1."""
        return (-1, 1)

    def get_subplot_title(self) -> str:
        return (
            f"Inverse Fisher (RSI={self.params['rsi_length']}, Smooth={self.params['smoothing_length']})"
        )
