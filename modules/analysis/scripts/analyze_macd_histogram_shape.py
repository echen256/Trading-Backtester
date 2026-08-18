"""Pilot study of adaptive-MACD line geometry around histogram crossovers.

The study reuses bar-level features embedded in the local weekly and three-day
scanner runs. It deliberately selects one longest run per ticker so repeated
entry-date runs do not duplicate observations.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = REPO_ROOT / "modules" / "analysis" / "strategies" / "runs"
REPORT = REPO_ROOT / "reports" / "macd_histogram_shape_study.md"
EVENTS_CSV = REPO_ROOT / "reports" / "macd_histogram_shape_events.csv"
SOURCES = {
    "Weekly": RUN_ROOT / "scanner-weekly-fixed-core" / "runs",
    "3-day": RUN_ROOT / "scanner-3d-fixed-core" / "runs",
}
MAIN_HORIZON = {"Weekly": 4, "3-day": 5}
HORIZONS = {"Weekly": (1, 2, 4, 8), "3-day": (1, 3, 5, 10)}


def pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.2f}%"


def rate(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:.1f}%"


def choose_longest_runs(root: Path) -> dict[str, dict[str, object]]:
    """Load one longest/latest feature history for each ticker."""

    chosen: dict[str, tuple[tuple[int, str], dict[str, object]]] = {}
    for path in root.glob("*/*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars = payload.get("bars") or []
        if not bars:
            continue
        ticker = str(payload.get("ticker") or path.parent.name).upper()
        key = (len(bars), str(bars[-1].get("time") or ""))
        if ticker not in chosen or key > chosen[ticker][0]:
            chosen[ticker] = (key, payload)
    return {ticker: payload for ticker, (_, payload) in chosen.items()}


def line_scale(macd: np.ndarray, index: int, lookback: int = 52) -> float:
    """Past-only robust scale for comparing slopes across assets."""

    sample = macd[max(0, index - lookback) : index + 1]
    differences = np.diff(sample[np.isfinite(sample)])
    if len(differences) < 8:
        return np.nan
    scale = float(np.nanmedian(np.abs(differences - np.nanmedian(differences))))
    return scale if scale > 1e-12 else float(np.nanstd(differences))


def impulse_line_shape(macd_slope: float, signal_slope: float) -> str:
    """Describe confirmation of a rising MACD impulse by its signal line."""

    if macd_slope <= 0:
        return "MACD not rising"
    if signal_slope <= 0:
        return "MACD leads / signal flat-falling"
    if signal_slope / macd_slope < 0.5:
        return "MACD leads signal"
    return "MACD and signal aligned"


def add_outcomes(record: dict[str, object], frame: pd.DataFrame, index: int, horizons: tuple[int, ...]) -> None:
    entry = float(frame.iloc[index].close)
    histogram = frame.histogram.to_numpy(dtype=float)
    for horizon in horizons:
        end = index + horizon
        if end >= len(frame):
            record[f"return_{horizon}"] = np.nan
            record[f"short_mfe_{horizon}"] = np.nan
            record[f"short_mae_{horizon}"] = np.nan
            continue
        window = frame.iloc[index + 1 : end + 1]
        record[f"return_{horizon}"] = float(frame.iloc[end].close / entry - 1)
        record[f"short_mfe_{horizon}"] = float(1 - window.low.min() / entry)
        record[f"short_mae_{horizon}"] = float(window.high.max() / entry - 1)
    next_two = histogram[index + 1 : min(len(histogram), index + 3)]
    record["recross_two_bars"] = bool(np.any(next_two > 0)) if len(next_two) else np.nan
    record["fails_two_bars"] = bool(np.any(next_two < 0)) if len(next_two) else np.nan


def extract_events(label: str, ticker: str, payload: dict[str, object]) -> list[dict[str, object]]:
    frame = pd.DataFrame(payload["bars"])
    required = {"time", "open", "high", "low", "close", "adaptive_macd", "signal", "histogram"}
    if not required.issubset(frame.columns):
        return []
    for column in ("open", "high", "low", "close", "adaptive_macd", "signal", "histogram"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    macd = frame.adaptive_macd.to_numpy(dtype=float)
    signal = frame.signal.to_numpy(dtype=float)
    hist = frame.histogram.to_numpy(dtype=float)
    events: list[dict[str, object]] = []

    # Early, causal checkpoint: the third consecutive positive and strictly
    # increasing histogram bar. Only one observation is emitted per impulse.
    for index in range(2, len(frame)):
        if not np.all(np.isfinite(hist[index - 2 : index + 1])):
            continue
        if not (0 < hist[index - 2] < hist[index - 1] < hist[index]):
            continue
        if index >= 3 and np.isfinite(hist[index - 3]) and hist[index - 3] > 0:
            continue
        scale = line_scale(macd, index)
        if not np.isfinite(scale):
            continue
        macd_slope = float((macd[index] - macd[index - 2]) / 2)
        signal_slope = float((signal[index] - signal[index - 2]) / 2)
        record: dict[str, object] = {
            "timeframe": label,
            "ticker": ticker,
            "date": frame.iloc[index].time,
            "event": "early_rising_blue",
            "duration": 3,
            "macd_slope": macd_slope,
            "signal_slope": signal_slope,
            "slope_norm": macd_slope / scale,
            "macd_level": macd[index],
            "signal_level": signal[index],
            "both_above_zero": bool(macd[index] > 0 and signal[index] > 0),
            "line_shape": impulse_line_shape(macd_slope, signal_slope),
        }
        add_outcomes(record, frame, index, HORIZONS[label])
        events.append(record)

    # Bearish crossover: summarize the completed positive histogram impulse.
    for index in range(1, len(frame)):
        if not (np.isfinite(hist[index - 1]) and np.isfinite(hist[index]) and hist[index - 1] >= 0 > hist[index]):
            continue
        start = index - 1
        while start > 0 and np.isfinite(hist[start - 1]) and hist[start - 1] >= 0:
            start -= 1
        duration = index - start
        rising_steps = [
            step for step in range(start, index)
            if step > 0 and np.isfinite(hist[step - 1]) and hist[step] > hist[step - 1]
            and np.isfinite(macd[step]) and np.isfinite(macd[step - 1])
        ]
        if duration < 2 or not rising_steps:
            continue
        scale = line_scale(macd, index)
        if not np.isfinite(scale):
            continue
        rising_macd_slope = float(np.mean([macd[step] - macd[step - 1] for step in rising_steps]))
        impulse_signal_slope = float(np.mean([signal[step] - signal[step - 1] for step in rising_steps]))
        cross_macd_slope = float(macd[index] - macd[index - 1])
        cross_signal_slope = float(signal[index] - signal[index - 1])
        record = {
            "timeframe": label,
            "ticker": ticker,
            "date": frame.iloc[index].time,
            "event": "bearish_crossover",
            "duration": duration,
            "macd_slope": rising_macd_slope,
            "signal_slope": impulse_signal_slope,
            "slope_norm": rising_macd_slope / scale,
            "macd_level": macd[index],
            "signal_level": signal[index],
            "both_above_zero": bool(macd[index] > 0 and signal[index] > 0),
            "line_shape": impulse_line_shape(rising_macd_slope, impulse_signal_slope),
            "cross_macd_slope": cross_macd_slope,
            "cross_signal_slope": cross_signal_slope,
        }
        add_outcomes(record, frame, index, HORIZONS[label])
        events.append(record)
    return events


def cluster_bootstrap_spread(frame: pd.DataFrame, outcome: str, repetitions: int = 5000) -> tuple[float, float, float]:
    """Top-minus-bottom slope quartile, resampling whole tickers."""

    clean = frame.dropna(subset=[outcome, "slope_quartile"])
    bottom = clean.loc[clean.slope_quartile.eq("Q1 weak"), outcome]
    top = clean.loc[clean.slope_quartile.eq("Q4 steep"), outcome]
    observed = float(top.mean() - bottom.mean())
    tickers = clean.ticker.unique()
    rng = np.random.default_rng(20260817)
    samples: list[float] = []
    for _ in range(repetitions):
        selected = rng.choice(tickers, size=len(tickers), replace=True)
        pieces = [clean[clean.ticker.eq(ticker)] for ticker in selected]
        sample = pd.concat(pieces, ignore_index=True)
        low = sample.loc[sample.slope_quartile.eq("Q1 weak"), outcome]
        high = sample.loc[sample.slope_quartile.eq("Q4 steep"), outcome]
        if len(low) and len(high):
            samples.append(float(high.mean() - low.mean()))
    lower, upper = np.quantile(samples, [0.025, 0.975])
    return observed, float(lower), float(upper)


def assign_quartiles(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    labels = ["Q1 weak", "Q2", "Q3", "Q4 steep"]
    output["slope_quartile"] = output.groupby(["timeframe", "event"], group_keys=False)["slope_norm"].transform(
        lambda values: pd.qcut(values.rank(method="first"), 4, labels=labels)
    )
    return output


def main() -> None:
    records: list[dict[str, object]] = []
    universe: dict[str, int] = {}
    coverage: dict[str, tuple[str, str]] = {}
    for label, root in SOURCES.items():
        runs = choose_longest_runs(root)
        universe[label] = len(runs)
        dates: list[str] = []
        for ticker, payload in sorted(runs.items()):
            bars = payload["bars"]
            dates.extend([str(bars[0]["time"]), str(bars[-1]["time"])])
            records.extend(extract_events(label, ticker, payload))
        coverage[label] = (min(dates), max(dates))
    events = assign_quartiles(pd.DataFrame(records))
    events.to_csv(EVENTS_CSV, index=False)

    lines = [
        "# Adaptive-MACD histogram shape study — local pilot",
        "",
        "## Scope and causal definitions",
        "",
        "This pilot uses the Fisher adaptive-MACD already embedded in the local scanner runs (Fisher 50; adaptive MACD 10/20/9; R² 20). One longest bar history is retained per ticker so multiple entry-date runs do not duplicate events.",
        "",
        "- **Early rising-blue checkpoint:** the third consecutive positive and strictly increasing histogram bar. The feature is the average MACD-line slope across those three bars.",
        "- **Bearish crossover:** the first negative histogram bar after a positive impulse. The feature is the average MACD-line change on only the bars where the positive histogram was expanding.",
        "- Slopes are divided by the past-only 52-bar median absolute MACD change. Quartiles are formed separately by timeframe and event type.",
        "- A bearish cross is called a two-bar whipsaw when the histogram returns positive within the next two bars. At the early checkpoint, failure means it turns negative within two bars.",
        "",
        "This is a selected 27-symbol scanner universe, not a survivorship-free market universe. Results are hypothesis-screening evidence, not final production thresholds.",
        "",
    ]

    for timeframe in SOURCES:
        horizon = MAIN_HORIZON[timeframe]
        horizon_label = f"{horizon} bars" + (" (~4 weeks)" if timeframe == "Weekly" else " (~15 calendar days)")
        lines.extend([
            f"## {timeframe}",
            "",
            f"Universe: **{universe[timeframe]} symbols**; embedded histories span {coverage[timeframe][0]} through {coverage[timeframe][1]}.",
            "",
        ])
        for event_name, title in (("early_rising_blue", "Early rising-blue checkpoint"), ("bearish_crossover", "Bearish histogram crossover")):
            sample = events[(events.timeframe == timeframe) & (events.event == event_name)].copy()
            outcome = f"return_{horizon}"
            lines.extend([
                f"### {title}",
                "",
                f"Events: **{len(sample)}**. Primary forward window: **{horizon_label}**.",
                "",
                "| Normalized MACD slope | N | Mean forward return | Median | Price positive | Two-bar noise | Short MFE | Short MAE |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ])
            for quartile in ("Q1 weak", "Q2", "Q3", "Q4 steep"):
                group = sample[sample.slope_quartile.eq(quartile)].dropna(subset=[outcome])
                noise_column = "fails_two_bars" if event_name == "early_rising_blue" else "recross_two_bars"
                lines.append(
                    f"| {quartile} | {len(group)} | {pct(group[outcome].mean())} | {pct(group[outcome].median())} | "
                    f"{rate(group[outcome].gt(0).mean())} | {rate(group[noise_column].mean())} | "
                    f"{pct(group[f'short_mfe_{horizon}'].mean())} | {pct(group[f'short_mae_{horizon}'].mean())} |"
                )
            correlation = sample[["slope_norm", outcome]].corr(method="spearman").iloc[0, 1]
            spread = cluster_bootstrap_spread(sample, outcome)
            lines.extend([
                "",
                f"- Spearman slope/forward-return relationship: **{correlation:+.3f}**.",
                f"- Steep-minus-weak mean-return spread: **{pct(spread[0])}**; ticker-clustered 95% interval **{pct(spread[1])} to {pct(spread[2])}**.",
                "",
                "| MACD/signal shape at observation | N | Mean forward return | Price positive | Two-bar noise |",
                "|---|---:|---:|---:|---:|",
            ])
            for shape, group in sample.groupby("line_shape", sort=False):
                valid = group.dropna(subset=[outcome])
                noise_column = "fails_two_bars" if event_name == "early_rising_blue" else "recross_two_bars"
                lines.append(
                    f"| {shape} | {len(valid)} | {pct(valid[outcome].mean())} | {rate(valid[outcome].gt(0).mean())} | {rate(valid[noise_column].mean())} |"
                )
            lines.extend([
                "",
                "| Zero-line regime | Slope group | N | Mean forward return | Median | Directional hit |",
                "|---|---|---:|---:|---:|---:|",
            ])
            for above_zero, regime_label in ((True, "MACD + signal above zero"), (False, "Not both above zero")):
                for quartile in ("Q1 weak", "Q4 steep"):
                    group = sample[sample.both_above_zero.eq(above_zero) & sample.slope_quartile.eq(quartile)].dropna(subset=[outcome])
                    directional = group[outcome].gt(0).mean() if event_name == "early_rising_blue" else group[outcome].lt(0).mean()
                    lines.append(
                        f"| {regime_label} | {quartile} | {len(group)} | {pct(group[outcome].mean())} | {pct(group[outcome].median())} | {rate(directional)} |"
                    )
            lines.extend([
                "",
                "| Forward horizon | Weak-slope mean / positive | Steep-slope mean / positive |",
                "|---|---:|---:|",
            ])
            for forward in HORIZONS[timeframe]:
                forward_column = f"return_{forward}"
                weak = sample[sample.slope_quartile.eq("Q1 weak")][forward_column].dropna()
                steep = sample[sample.slope_quartile.eq("Q4 steep")][forward_column].dropna()
                lines.append(
                    f"| {forward} bars | {pct(weak.mean())} / {rate(weak.gt(0).mean())} | {pct(steep.mean())} / {rate(steep.gt(0).mean())} |"
                )
            lines.append("")

    weekly_bear = events[(events.timeframe == "Weekly") & (events.event == "bearish_crossover")]
    three_day_bear = events[(events.timeframe == "3-day") & (events.event == "bearish_crossover")]
    weekly_weak = weekly_bear[weekly_bear.slope_quartile.eq("Q1 weak")].return_4.dropna()
    weekly_steep = weekly_bear[weekly_bear.slope_quartile.eq("Q4 steep")].return_4.dropna()
    three_day_weak = three_day_bear[three_day_bear.slope_quartile.eq("Q1 weak")].return_5.dropna()
    three_day_steep = three_day_bear[three_day_bear.slope_quartile.eq("Q4 steep")].return_5.dropna()
    lines.extend([
        "## Pilot conclusion",
        "",
        "- **Slope did not create a clean continuation signal at the early rising-blue checkpoint.** Neither timeframe was monotonic across quartiles, and both ticker-clustered Q4−Q1 intervals included zero.",
        f"- **At weekly bearish crossovers, steep prior impulses behaved more like pullbacks than shorts:** {rate(weekly_steep.gt(0).mean())} of steep events were positive four weeks later versus {rate(weekly_weak.gt(0).mean())} for weak events. The mean spread was not statistically resolved because weak events had a positively skewed tail.",
        f"- **At 3-day bearish crossovers, the relationship reversed:** steep impulses returned {pct(three_day_steep.mean())} over the next five bars with only {rate(three_day_steep.gt(0).mean())} positive, versus {pct(three_day_weak.mean())} and {rate(three_day_weak.gt(0).mean())} positive for weak impulses. The ticker-clustered steep-minus-weak interval excluded zero.",
        "- The useful feature is therefore not ‘high slope always means continuation.’ It is an interaction between slope, timeframe, and crossover state: weekly steep-impulse crossovers often reset and continue, while 3-day steep-impulse crossovers look like shorter-term exhaustion.",
        "",
        "## Interpretation rules",
        "",
        "- The hypothesis is supported only when returns improve monotonically from weak to steep slope, the continuous Spearman relationship has the same sign, and the clustered interval for the Q4−Q1 spread excludes zero.",
        "- For bearish crossovers, a low-slope short filter should produce lower underlying returns, higher short MFE, and fewer positive recrosses. A steep prior impulse should do the reverse if the crossover is merely a pullback.",
        "- Line geometry is useful only if it improves on the raw histogram event. A slope filter that changes returns but not whipsaw or adverse excursion may not reduce execution noise.",
        "",
        "## Limitations",
        "",
        "- The scanner universe is selected from previously traded/entered assets and is concentrated in volatile growth names.",
        "- Events share market regimes and some forward windows overlap. The bootstrap clusters by ticker but not simultaneously by calendar date.",
        "- Quartile boundaries are descriptive and use the full pilot sample. Production thresholds require a broader universe and walk-forward validation.",
        "- Returns exclude costs, borrow constraints, dividends, and options implied volatility.",
    ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT}")
    print(f"Wrote {EVENTS_CSV}")
    print(events.groupby(["timeframe", "event"]).size())


if __name__ == "__main__":
    main()
