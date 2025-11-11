import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd

from indicators import InverseFisherIndicator, StochasticRSIIndicator


def load_tsla_data(period: str = "1y") -> pd.DataFrame:
    """Fetch TSLA historical data and format columns."""
    data = yf.download("TSLA", period=period, progress=False)
    if data.empty:
        raise ValueError("No data returned for TSLA")

    data = data.rename(columns=str.lower)
    return data


def calculate_indicators(data: pd.DataFrame):
    """Add Stochastic RSI and Inverse Fisher columns to the DataFrame."""
    stoch_rsi = StochasticRSIIndicator()
    inverse_fisher = InverseFisherIndicator()

    stoch_rsi.calculate(data)
    inverse_fisher.calculate(data)

    return stoch_rsi, inverse_fisher


def plot_data(data: pd.DataFrame, stoch_rsi: StochasticRSIIndicator, inverse_fisher: InverseFisherIndicator):
    """Plot TSLA close price alongside Stochastic RSI and Inverse Fisher."""
    fig, ax_price = plt.subplots(figsize=(12, 6))

    ax_price.plot(data.index, data["close"], label="TSLA Close", color="black")
    ax_price.set_ylabel("Price (USD)")
    ax_price.set_title("TSLA with Stochastic RSI and Inverse Fisher Transform")

    ax_osc = ax_price.twinx()

    stoch_k = data[stoch_rsi.k_column]
    inv_fisher = data[inverse_fisher.column_name]
    inv_fisher_scaled = (inv_fisher + 1) * 50  # Scale to 0-100 for comparison

    ax_osc.plot(data.index, stoch_k, label="Stochastic RSI %K", color="blue", linewidth=1.8)
    ax_osc.plot(data.index, inv_fisher_scaled, label="Inverse Fisher (scaled)", color="green", linewidth=1.8)
    ax_osc.set_ylabel("Oscillator Value")
    ax_osc.set_ylim(0, 100)

    ax_osc.axhline(80, color="gray", linestyle="--", linewidth=0.8)
    ax_osc.axhline(20, color="gray", linestyle="--", linewidth=0.8)

    lines_price, labels_price = ax_price.get_legend_handles_labels()
    lines_osc, labels_osc = ax_osc.get_legend_handles_labels()
    ax_price.legend(lines_price + lines_osc, labels_price + labels_osc, loc="upper left")

    plt.tight_layout()
    plt.show()


def main():
    data = load_tsla_data()
    stoch_rsi, inverse_fisher = calculate_indicators(data)
    plot_data(data, stoch_rsi, inverse_fisher)


if __name__ == "__main__":
    main()
