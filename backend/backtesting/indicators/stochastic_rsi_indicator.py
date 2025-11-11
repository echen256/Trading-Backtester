import numpy as np
import pandas as pd
import pandas_ta as ta
from typing import Dict, Any, List, Optional, Tuple
from .base_indicator import BaseIndicator


class StochasticRSIIndicator(BaseIndicator):
    """Stochastic RSI oscillator."""

    def __init__(
        self,
        length: int = 14,
        rsi_length: int = 14,
        k: int = 3,
        d: int = 3,
        mamode: str = "sma",
    ):
        super().__init__(
            name="Stochastic RSI",
            params={
                "length": length,
                "rsi_length": rsi_length,
                "k": k,
                "d": d,
                "mamode": mamode,
            },
        )
        suffix = f"{length}_{rsi_length}_{k}_{d}"
        self.k_column = f"stochrsi_k_{suffix}"
        self.d_column = f"stochrsi_d_{suffix}"

    def _compute_rsi(self, close: pd.Series, length: int) -> pd.Series:
        """Compute RSI with Wilder smoothing and minimal length guards."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        alpha = 1 / length
        avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=length).mean()
        avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=length).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi.name = f"RSI_{length}"
        return rsi

    def _smooth(self, series: pd.Series, length: int) -> pd.Series:
        """Apply smoothing according to the configured MA mode."""
        if length <= 1:
            return series

        mamode = (self.params["mamode"] or "sma").lower()
        if mamode == "sma":
            return series.rolling(length, min_periods=1).mean()
        if mamode == "ema":
            alpha = 2 / (length + 1)
            return series.ewm(alpha=alpha, adjust=False).mean()

        smoothed = ta.ma(mamode, series, length=length)
        if smoothed is None:
            # Fallback to SMA if pandas_ta fails for the selected mode
            return series.rolling(length, min_periods=1).mean()
        return smoothed

    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Stochastic RSI %K and %D lines and add them to the DataFrame."""
        if not self.validate_data(data):
            raise ValueError(f"Data missing required columns: {self.get_required_columns()}")

        close = data["close"].astype(float)
        rsi_series = self._compute_rsi(close, self.params["rsi_length"])

        window = max(1, self.params["length"])
        lowest_rsi = rsi_series.rolling(window, min_periods=1).min()
        highest_rsi = rsi_series.rolling(window, min_periods=1).max()

        range_rsi = highest_rsi - lowest_rsi
        range_rsi = range_rsi.replace(0, np.nan)

        stoch = 100 * (rsi_series - lowest_rsi) / range_rsi
        stoch = stoch.clip(lower=0, upper=100)

        stochrsi_k = self._smooth(stoch, max(1, self.params["k"]))
        stochrsi_d = self._smooth(stochrsi_k, max(1, self.params["d"]))

        data[self.k_column] = stochrsi_k
        data[self.d_column] = stochrsi_d
        return data

    def get_plot_config(self) -> Dict[str, Any]:
        """Return plot configuration for Stochastic RSI."""
        return {
            "plot_type": "multi",
            "subplot_row": 1,
            "traces": [
                {
                    "column": self.k_column,
                    "name": "%K",
                    "type": "line",
                    "color": "blue",
                    "line": {"width": 2},
                },
                {
                    "column": self.d_column,
                    "name": "%D",
                    "type": "line",
                    "color": "red",
                    "line": {"width": 2},
                },
            ],
        }

    def get_required_columns(self) -> List[str]:
        """Stochastic RSI requires close prices."""
        return ["close"]

    def get_y_axis_range(self) -> Optional[Tuple[float, float]]:
        """Stochastic RSI oscillates between 0 and 100."""
        return (0, 100)

    def get_subplot_title(self) -> str:
        return (
            f"Stoch RSI (len={self.params['length']}, RSI={self.params['rsi_length']})"
        )
