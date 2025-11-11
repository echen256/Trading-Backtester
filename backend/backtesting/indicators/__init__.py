from .base_indicator import BaseIndicator
from .rsi_indicator import RSIIndicator
from .atr_indicator import ATRIndicator
from .macd_indicator import MACDIndicator
from .stochastic_rsi_indicator import StochasticRSIIndicator
from .inverse_fisher import InverseFisherIndicator

# Registry for easy indicator lookup
INDICATOR_REGISTRY = {
    "rsi": RSIIndicator,
    "atr": ATRIndicator,
    "macd": MACDIndicator,
    "stochastic_rsi": StochasticRSIIndicator,
    "inverse_fisher": InverseFisherIndicator,
}


def get_indicator(name: str, **kwargs) -> BaseIndicator:
    """Factory function to create indicators by name."""
    if name.lower() not in INDICATOR_REGISTRY:
        raise ValueError(
            f"Unknown indicator: {name}. Available: {list(INDICATOR_REGISTRY.keys())}"
        )

    return INDICATOR_REGISTRY[name.lower()](**kwargs)


__all__ = [
    "BaseIndicator",
    "RSIIndicator",
    "ATRIndicator",
    "MACDIndicator",
    "StochasticRSIIndicator",
    "InverseFisherIndicator",
    "INDICATOR_REGISTRY",
    "get_indicator",
]
