"""Test strict weekly swing-failure patterns (SFPs) in BTC-USD and QQQ.

The definition is deliberately mechanical and uses only information available
at the weekly close.  It is a research implementation of the user's "weekly
SPF" idea, not a claim that every wick is a tradable reversal.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle


START = pd.Timestamp("2005-01-01")
END = pd.Timestamp("2026-08-16")
HORIZONS = (4, 8, 13, 26)
PIVOT_LEFT_RIGHT = 5
MAX_SWING_AGE = 52
CONFIRMATION_WINDOW = 26


def fetch_daily(symbol: str) -> pd.DataFrame:
    params = urlencode(
        {
            "period1": int(START.timestamp()),
            "period2": int((END + pd.Timedelta(days=2)).timestamp()),
            "interval": "1d",
            "events": "history",
        }
    )
    request = Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS endpoint
        result = json.load(response)["chart"]["result"][0]
    index = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    quote = pd.DataFrame(result["indicators"]["quote"][0], index=index)[["open", "high", "low", "close"]].astype(float)
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    # Adjust all OHLC fields for ETF splits/dividends so old QQQ candles are
    # comparable to current ones. BTC has no adjusted-close series.
    if adjusted is not None:
        factor = pd.Series(adjusted, index=index, dtype=float).div(quote["close"])
        quote = quote.mul(factor, axis=0)
    return quote.dropna()


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    weekly = daily.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    true_range = pd.concat(
        [
            weekly.high - weekly.low,
            (weekly.high - weekly.close.shift()).abs(),
            (weekly.low - weekly.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    weekly["atr14"] = true_range.rolling(14).mean()
    weekly["range"] = weekly.high - weekly.low
    weekly["upper_wick"] = weekly.high - weekly[["open", "close"]].max(axis=1)
    weekly["lower_wick"] = weekly[["open", "close"]].min(axis=1) - weekly.low
    return weekly


def pivot_flags(values: pd.Series, kind: str) -> pd.Series:
    """Strict confirmed pivot: greater/lower than every one of five weeks each side."""

    flags = pd.Series(False, index=values.index)
    for position in range(PIVOT_LEFT_RIGHT, len(values) - PIVOT_LEFT_RIGHT):
        current = values.iloc[position]
        left = values.iloc[position - PIVOT_LEFT_RIGHT : position]
        right = values.iloc[position + 1 : position + PIVOT_LEFT_RIGHT + 1]
        if kind == "high":
            flags.iloc[position] = current > left.max() and current > right.max()
        else:
            flags.iloc[position] = current < left.min() and current < right.min()
    return flags


def structure_confirmation(
    weekly: pd.DataFrame,
    high_indices: np.ndarray,
    low_indices: np.ndarray,
    *,
    failure_position: int,
    prior_high_position: int,
    prior_low_position: int,
    direction: str,
) -> int | None:
    """Return when an opposite HH/HL or LL/LH pair becomes confirmed.

    The pair is searched after the failed breakout/breakdown.  A pivot itself
    is only actionable five weeks later, when its right-side confirmation is
    available, so the returned index is the tradeable confirmation week.
    """

    latest_pivot = min(len(weekly) - PIVOT_LEFT_RIGHT - 1, failure_position + CONFIRMATION_WINDOW)
    if direction == "bearish inflection":
        lower_lows = [
            position
            for position in low_indices
            if failure_position < position <= latest_pivot and weekly.low.iloc[position] < weekly.low.iloc[prior_low_position]
        ]
        lower_highs = [
            position
            for position in high_indices
            if failure_position < position <= latest_pivot and weekly.high.iloc[position] < weekly.high.iloc[prior_high_position]
        ]
        if lower_lows and lower_highs:
            return max(lower_lows[0], lower_highs[0]) + PIVOT_LEFT_RIGHT
    else:
        higher_highs = [
            position
            for position in high_indices
            if failure_position < position <= latest_pivot and weekly.high.iloc[position] > weekly.high.iloc[prior_high_position]
        ]
        higher_lows = [
            position
            for position in low_indices
            if failure_position < position <= latest_pivot and weekly.low.iloc[position] > weekly.low.iloc[prior_low_position]
        ]
        if higher_highs and higher_lows:
            return max(higher_highs[0], higher_lows[0]) + PIVOT_LEFT_RIGHT
    return None


def make_events(weekly: pd.DataFrame) -> pd.DataFrame:
    pivot_high = pivot_flags(weekly.high, "high")
    pivot_low = pivot_flags(weekly.low, "low")
    high_indices = np.flatnonzero(pivot_high.to_numpy())
    low_indices = np.flatnonzero(pivot_low.to_numpy())
    events: list[dict[str, object]] = []
    for position in range(PIVOT_LEFT_RIGHT + 1, len(weekly) - 1):
        # A pivot is only known after its five following weeks complete.
        # An actionable weekly swing is recent structure, not a level from an
        # unrelated cycle years earlier.
        earliest = position - MAX_SWING_AGE
        previous_highs = high_indices[(high_indices <= position - PIVOT_LEFT_RIGHT) & (high_indices >= earliest)]
        previous_lows = low_indices[(low_indices <= position - PIVOT_LEFT_RIGHT) & (low_indices >= earliest)]
        if len(previous_highs) < 2 or len(previous_lows) < 2:
            continue
        row = weekly.iloc[position]
        # "Previous swing" means the last confirmed pivot of that type. The
        # breakout attempt begins only when the week's high/low newly breaches
        # that level; a close back through it may occur that week or next week.
        prior_high_position = previous_highs[-1]
        prior_low_position = previous_lows[-1]
        older_high_position = previous_highs[-2]
        older_low_position = previous_lows[-2]
        prior_high = weekly.high.iloc[prior_high_position]
        prior_low = weekly.low.iloc[prior_low_position]
        prior = weekly.iloc[position - 1]
        next_row = weekly.iloc[position + 1]
        candidates = (
            (
                "bearish inflection",
                weekly.high.iloc[prior_high_position] > weekly.high.iloc[older_high_position]
                and weekly.low.iloc[prior_low_position] > weekly.low.iloc[older_low_position]
                and row.high > prior_high
                and prior.high <= prior_high,
                row.close < prior_high,
                next_row.close < prior_high,
                prior_high,
                prior_high_position,
            ),
            (
                "bullish inflection",
                weekly.high.iloc[prior_high_position] < weekly.high.iloc[older_high_position]
                and weekly.low.iloc[prior_low_position] < weekly.low.iloc[older_low_position]
                and row.low < prior_low
                and prior.low >= prior_low,
                row.close > prior_low,
                next_row.close > prior_low,
                prior_low,
                prior_low_position,
            ),
        )
        for direction, broke_out, immediate_failure, next_week_failure, level, pivot_position in candidates:
            if not broke_out or not (immediate_failure or next_week_failure):
                continue
            failure_position = position if immediate_failure else position + 1
            confirmation_position = structure_confirmation(
                weekly,
                high_indices,
                low_indices,
                failure_position=failure_position,
                prior_high_position=prior_high_position,
                prior_low_position=prior_low_position,
                direction=direction,
            )
            confirmed = confirmation_position is not None
            event: dict[str, object] = {
                "date": weekly.index[failure_position],
                "direction": direction,
                "level": level,
                "pivot_date": weekly.index[pivot_position],
                "breakout_date": weekly.index[position],
                "failure_date": weekly.index[failure_position],
                "failure_candles": 1 if immediate_failure else 2,
                "confirmed": confirmed,
                "confirmation_date": weekly.index[confirmation_position] if confirmed else pd.NaT,
            }
            for horizon in HORIZONS:
                event[f"return_{horizon}w"] = (
                    weekly.close.iloc[confirmation_position + horizon] / weekly.close.iloc[confirmation_position] - 1
                    if confirmed and confirmation_position + horizon < len(weekly)
                    else np.nan
                )
            events.append(event)
    if not events:
        columns = [
            "direction", "level", "pivot_date", "breakout_date", "failure_date", "failure_candles", "confirmed", "confirmation_date",
            *[f"return_{horizon}w" for horizon in HORIZONS],
        ]
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], name="date"))
    return pd.DataFrame(events).set_index("date").sort_index()


def percent(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.2f}%"


def probability(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:.1f}%"


def summary(asset: str, weekly: pd.DataFrame, events: pd.DataFrame) -> list[str]:
    baseline = pd.DataFrame(index=weekly.index)
    for horizon in HORIZONS:
        baseline[f"return_{horizon}w"] = weekly.close.shift(-horizon).div(weekly.close).sub(1)
    lines = [f"## {asset}", ""]
    for direction, expected_sign in (("bearish inflection", -1), ("bullish inflection", 1)):
        candidates = events[events.direction.eq(direction)]
        subset = candidates[candidates.confirmed]
        lines.extend(
            [
                f"### {direction.title()}",
                "",
                f"Candidate 1–2 candle SFPs: **{len(candidates)}**. Confirmed structure shifts: **{len(subset)}**. "
                f"Expected outcome after confirmation: {'lower' if expected_sign < 0 else 'higher'} future price.",
                "",
                "| Horizon | Mean return | Median | Opposite-direction hit rate | All-week baseline |",
                "|---:|---:|---:|---:|---:|",
            ]
        )
        for horizon in HORIZONS:
            returns = subset[f"return_{horizon}w"].dropna()
            # Baseline is the asset's unconditional return across every
            # eligible weekly starting point, not the event dates themselves.
            base = baseline[f"return_{horizon}w"].dropna()
            hit = (returns * expected_sign > 0).mean()
            lines.append(
                f"| {horizon} weeks | {percent(returns.mean())} | {percent(returns.median())} | "
                f"{probability(hit)} | {percent(base.mean())} |"
            )
        lines.append("")
    return lines


def event_table(asset: str, events: pd.DataFrame) -> list[str]:
    lines = [f"## {asset} event detail", "", "| SFP failure date | Pattern | Structure confirmation | Prior swing date | Breakout week | Failure candles | 4w | 8w | 13w | 26w |", "|---|---|---|---|---|---:|---:|---:|---:|---:|"]
    for date, row in events.iterrows():
        confirmation = f"{row.confirmation_date:%Y-%m-%d}" if row.confirmed else "Not confirmed"
        lines.append(
            f"| {date:%Y-%m-%d} | {row.direction} | {confirmation} | {row.pivot_date:%Y-%m-%d} | {row.breakout_date:%Y-%m-%d} | {row.failure_candles} | "
            f"{percent(row.return_4w)} | {percent(row.return_8w)} | {percent(row.return_13w)} | {percent(row.return_26w)} |"
        )
    return lines


def plot_candles(axis: plt.Axes, weekly: pd.DataFrame) -> None:
    """Draw compact weekly OHLC candles that remain legible when zoomed."""

    dates = mdates.date2num(weekly.index.to_pydatetime())
    width = 4.1  # Friday-ending weekly candle, in matplotlib date units.
    for x, (_, row) in zip(dates, weekly.iterrows(), strict=True):
        color = "#15803d" if row.close >= row.open else "#dc2626"
        axis.vlines(x, row.low, row.high, color=color, linewidth=0.55, alpha=0.74, zorder=1)
        bottom = min(row.open, row.close)
        height = max(abs(row.close - row.open), row.close * 0.00035)
        axis.add_patch(Rectangle((x - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.25, alpha=0.76, zorder=2))


def write_chart(data: dict[str, pd.DataFrame], events: dict[str, pd.DataFrame], output: Path) -> None:
    """Render price history with each strict weekly SFP and swept level shown."""

    fig, axes = plt.subplots(2, 1, figsize=(16, 10), layout="constrained")
    for axis, asset in zip(axes, ("BTCUSD", "QQQ"), strict=True):
        weekly = data[asset]
        pattern_events = events[asset]
        plot_candles(axis, weekly)
        axis.set_yscale("log")
        pivot_highs = weekly[pivot_flags(weekly.high, "high")]
        pivot_lows = weekly[pivot_flags(weekly.low, "low")]
        axis.scatter(pivot_highs.index, pivot_highs.high, marker="o", s=10, color="#64748b", alpha=0.48, zorder=3, label="All confirmed 5×5 swing highs")
        axis.scatter(pivot_lows.index, pivot_lows.low, marker="o", s=10, color="#94a3b8", alpha=0.48, zorder=3, label="All confirmed 5×5 swing lows")
        for direction, color, marker, label in (
            ("bearish inflection", "#dc2626", "v", "Bearish SFP failure"),
            ("bullish inflection", "#16a34a", "^", "Bullish SFP failure"),
        ):
            subset = pattern_events[pattern_events.direction.eq(direction)]
            if subset.empty:
                continue
            failure_prices = weekly.loc[pd.DatetimeIndex(subset.failure_date), "close"]
            axis.scatter(subset.failure_date, failure_prices, marker=marker, s=60, color=color, edgecolor="white", linewidth=0.7, zorder=5, label=label)
            confirmed_subset = subset[subset.confirmed]
            if not confirmed_subset.empty:
                confirmation_prices = weekly.loc[pd.DatetimeIndex(confirmed_subset.confirmation_date), "close"]
                axis.scatter(confirmed_subset.confirmation_date, confirmation_prices, marker="D", s=48, color=color, edgecolor="white", linewidth=0.7, zorder=6, label=f"Confirmed {'bearish' if direction == 'bearish inflection' else 'bullish'} shift")
            for count, (date, row) in enumerate(subset.iterrows()):
                signal = weekly.loc[row.failure_date]
                axis.vlines(row.failure_date, signal.low, signal.high, color=color, linewidth=1.4, alpha=0.85, zorder=3)
                axis.hlines(row.level, row.pivot_date, row.failure_date, color=color, linewidth=1.0, linestyle="--", alpha=0.75, zorder=2)
                breakout_price = weekly.loc[row.breakout_date, "high" if direction == "bearish inflection" else "low"]
                axis.scatter(
                    row.breakout_date,
                    breakout_price,
                    marker="x",
                    s=38,
                    color=color,
                    linewidth=1.35,
                    zorder=5,
                    label="Breakout attempt" if count == 0 else None,
                )
                axis.scatter(
                    row.pivot_date,
                    row.level,
                    marker="o",
                    s=44,
                    facecolor="white",
                    edgecolor=color,
                    linewidth=1.35,
                    zorder=4,
                    label=f"Swept {PIVOT_LEFT_RIGHT}×{PIVOT_LEFT_RIGHT} {'high' if direction == 'bearish inflection' else 'low'} pivot" if count == 0 else None,
                )
        axis.set_title(f"{asset}: weekly failed breakouts / breakdowns", loc="left", fontweight="bold")
        axis.set_ylabel("Price (log scale)")
        axis.grid(axis="y", alpha=0.22)
        axis.text(
            0.012,
            0.025,
            f"Swing reference: confirmed {PIVOT_LEFT_RIGHT}-left / {PIVOT_LEFT_RIGHT}-right weekly pivot, ≤{MAX_SWING_AGE} weeks old\n"
            f"SFP: first breach then close back through in 1–2 candles; diamond = LL+LH / HH+HL confirmation within {CONFIRMATION_WINDOW} weeks",
            transform=axis.transAxes,
            va="bottom",
            fontsize=8.3,
            color="#334155",
            bbox={"boxstyle": "round,pad=0.38", "facecolor": "white", "edgecolor": "#cbd5e1", "alpha": 0.92},
        )
        axis.legend(loc="upper left", ncol=3, frameon=False, fontsize=8)
    axes[-1].set_xlabel("Week ending Friday")
    fig.suptitle("Weekly SFPs: x = breakout attempt; triangle = failure close; diamond = confirmed market-structure shift", fontsize=14, fontweight="bold")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    assets = {"BTC-USD": "BTCUSD", "QQQ": "QQQ"}
    all_data = {name: to_weekly(fetch_daily(symbol)) for symbol, name in assets.items()}
    all_events = {name: make_events(frame) for name, frame in all_data.items()}
    report = Path(__file__).resolve().parents[3] / "reports" / "weekly_swing_failure_study.md"
    chart = Path(__file__).resolve().parents[3] / "reports" / "weekly_swing_failure_chart.png"
    lines = [
        "# Weekly swing-point failure study: BTCUSD and QQQ",
        "",
        "Source: Yahoo Finance daily OHLC, resampled to Friday-ending weeks. QQQ OHLC is adjustment-factor normalized.",
        "",
        "## Weekly failed-breakout / failed-breakdown plus market-structure definition",
        "",
        f"- A prior swing is a confirmed {PIVOT_LEFT_RIGHT}-week-left / {PIVOT_LEFT_RIGHT}-week-right pivot from the preceding {MAX_SWING_AGE} weeks.",
        "- **Potential bearish SFP:** price is in higher-high / higher-low structure, then the first weekly high to break the prior swing high closes back below it in one or two candles.",
        "- **Bearish inflection confirmation:** after that failure, both a lower low and lower high must form within 26 weeks, in either order. Each pivot is only recognized after its five-week right-side confirmation.",
        "- **Potential bullish SFP:** price is in lower-high / lower-low structure, then the first weekly low to break the prior swing low closes back above it in one or two candles.",
        "- **Bullish inflection confirmation:** after that failure, both a higher high and higher low must form within 26 weeks, in either order; pivots again require five weeks of confirmation.",
        "- Outcomes begin at the structure-confirmation close, which is the earliest point at which the full inflection is objectively known. The baseline is the unconditional return across all eligible weekly starting points.",
        "",
    ]
    for asset in ("BTCUSD", "QQQ"):
        lines.extend(summary(asset, all_data[asset], all_events[asset]))
    for asset in ("BTCUSD", "QQQ"):
        lines.extend(event_table(asset, all_events[asset]))
        lines.append("")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_chart(all_data, all_events, chart)
    print("\n".join(lines[:100]))
    print(f"\nWrote {report}\nWrote {chart}")


if __name__ == "__main__":
    main()
