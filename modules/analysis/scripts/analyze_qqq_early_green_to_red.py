"""Study QQQ's early-green then delayed green-to-red intraday failure.

Uses full Polygon regular-hours five-minute QQQ bars. The primary event is
deliberately time-bounded: QQQ first turns green versus the prior session close
during 09:35–10:30 ET, then closes red during 10:35–12:30 ET. A literal
alternative allows the red cross at any point in the 120 minutes after the
first green close.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from trading_analysis.dashboard import StudyArtifactWriter


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "modules" / "data-pipeline" / "src"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from trading_data_pipeline.downloader import PolygonDownloader  # noqa: E402


REPORT = REPO_ROOT / "reports" / "qqq_early_green_to_red_study.md"
START = datetime(2024, 7, 29)
END = datetime(2026, 8, 14)
EARLY_START, EARLY_END = 0, 55   # 5-minute bars beginning 09:30 through 10:25
FAIL_START, FAIL_END = 60, 175   # 5-minute bars beginning 10:30 through 12:25
FORWARD_DAYS = (1, 2, 5)


def pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.2f}%"


def rate(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:.1f}%"


def stats_line(series: pd.Series) -> tuple[int, float, float, float]:
    clean = series.dropna()
    return len(clean), clean.mean(), clean.median(), clean.gt(0).mean()


def block_bootstrap_difference(
    values: pd.Series, signal_dates: pd.Index, repetitions: int = 5000, block_length: int = 5
) -> tuple[float, float, float]:
    """Signal-minus-nonsignal mean difference with a five-session block CI."""

    sample = pd.DataFrame({"value": values}).dropna()
    sample["signal"] = sample.index.isin(signal_dates)
    observed = sample.loc[sample.signal, "value"].mean() - sample.loc[~sample.signal, "value"].mean()
    sample_values = sample.value.to_numpy(dtype=float)
    flags = sample.signal.to_numpy()
    count = len(sample)
    rng = np.random.default_rng(20260817)
    differences: list[float] = []
    for _ in range(repetitions):
        starts = rng.integers(0, count - block_length + 1, size=int(np.ceil(count / block_length)))
        positions = np.concatenate([np.arange(start, start + block_length) for start in starts])[:count]
        sampled_values = sample_values[positions]
        sampled_flags = flags[positions]
        if sampled_flags.any() and (~sampled_flags).any():
            differences.append(sampled_values[sampled_flags].mean() - sampled_values[~sampled_flags].mean())
    lower, upper = np.quantile(differences, [0.025, 0.975])
    return observed, lower, upper


def format_minute(minute: float) -> str:
    # Polygon timestamps aggregates at their start; display the bar's close.
    hours, minutes = divmod(9 * 60 + 30 + int(minute) + 5, 60)
    return f"{hours:02d}:{minutes:02d}"


def fetch_rth_bars() -> pd.DataFrame:
    """Fetch the full study range in small Polygon windows, then keep RTH."""

    downloader = PolygonDownloader()
    frames: list[pd.DataFrame] = []
    current = START
    while current < END:
        window_end = min(current + timedelta(days=28), END)
        frame = downloader.fetch_bars("QQQ", current, window_end, 5)
        if not frame.empty:
            frames.append(frame[["open", "high", "low", "close"]])
        current = window_end
        time.sleep(0.08)
    bars = pd.concat(frames).sort_index()
    bars = bars[~bars.index.duplicated(keep="last")]
    local = bars.copy()
    local.index = local.index.tz_convert("America/New_York")
    local["date"] = local.index.tz_localize(None).normalize()
    local["minute"] = (local.index.hour * 60 + local.index.minute) - (9 * 60 + 30)
    return local[local.minute.between(0, 385)].copy()


def main() -> None:
    bars = fetch_rth_bars().reset_index(drop=True).sort_values(["date", "minute"])
    daily = bars.groupby("date").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), session_close=("close", "last"))
    first_hour = bars[bars.minute.between(EARLY_START, EARLY_END)].groupby("date").agg(first_hour_high=("high", "max"), first_hour_low=("low", "min"))
    daily = daily.join(first_hour)
    daily["prior_close"] = daily.session_close.shift()
    daily["range_pct"] = daily.high.sub(daily.low).div(daily.open)
    daily["true_range_pct"] = pd.concat(
        [
            daily.high.sub(daily.low),
            daily.high.sub(daily.prior_close).abs(),
            daily.low.sub(daily.prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1).div(daily.prior_close)
    daily["first_hour_range_pct"] = daily.first_hour_high.sub(daily.first_hour_low).div(daily.open)
    daily["open_to_close_pct"] = daily.session_close.div(daily.open).sub(1)
    daily["abs_open_close"] = daily.session_close.sub(daily.open).abs().div(daily.open)
    daily["up_excursion"] = daily.high.div(daily.open).sub(1)
    daily["down_excursion"] = daily.open.sub(daily.low).div(daily.open)
    daily["max_open_excursion"] = pd.concat(
        [daily.up_excursion, daily.down_excursion], axis=1
    ).max(axis=1)
    daily["either_075"] = daily.max_open_excursion.ge(0.0075)
    daily["both_050"] = daily.up_excursion.ge(0.005) & daily.down_excursion.ge(0.005)
    daily["directional_efficiency"] = daily.session_close.sub(daily.open).abs().div(daily.high.sub(daily.low))
    daily["range_vs_prior20"] = daily.range_pct.div(daily.range_pct.shift().rolling(20).median())
    for horizon in FORWARD_DAYS:
        daily[f"next_{horizon}d"] = daily.session_close.shift(-horizon).div(daily.session_close).sub(1)

    events: list[dict[str, object]] = []
    dynamic_events: list[dict[str, object]] = []

    def event_record(date: pd.Timestamp, early: pd.DataFrame, green: pd.Series, red: pd.Series, prior_close: float) -> dict[str, object]:
        event: dict[str, object] = {
            "date": date,
            "green_minute": int(green.minute),
            "red_minute": int(red.minute),
            "prior_close": prior_close,
            "red_cross_close": float(red.close),
            "session_close": float(daily.at[date, "session_close"]),
            "rest_session": float(daily.at[date, "session_close"] / red.close - 1),
            "session_red": daily.at[date, "session_close"] < prior_close,
            "clean_transition": float(early.iloc[-1].close) > prior_close,
            "early_max_pct": float(early.close.max() / prior_close - 1),
            "red_depth_pct": float(red.close / prior_close - 1),
        }
        for horizon in FORWARD_DAYS:
            event[f"next_{horizon}d"] = daily.at[date, f"next_{horizon}d"]
            if not pd.isna(event[f"next_{horizon}d"]):
                event[f"cross_to_{horizon}d"] = daily.session_close.shift(-horizon).loc[date] / red.close - 1
            else:
                event[f"cross_to_{horizon}d"] = np.nan
        return event

    for date, day in bars.groupby("date", sort=True):
        if date not in daily.index or pd.isna(daily.at[date, "prior_close"]):
            continue
        prior_close = float(daily.at[date, "prior_close"])
        early = day[day.minute.between(EARLY_START, EARLY_END)]
        first_green = early[early.close.gt(prior_close)]
        if first_green.empty:
            continue
        green = first_green.iloc[0]
        dynamic_failure = day[
            day.minute.gt(green.minute)
            & day.minute.le(green.minute + 120)
            & day.close.lt(prior_close)
        ]
        if not dynamic_failure.empty:
            dynamic_events.append(event_record(date, early, green, dynamic_failure.iloc[0], prior_close))
        failure = day[day.minute.between(FAIL_START, FAIL_END) & day.close.lt(prior_close)]
        if failure.empty:
            continue
        red = failure.iloc[0]
        events.append(event_record(date, early, green, red, prior_close))
    event_frame = pd.DataFrame(events).set_index("date")
    dynamic_frame = pd.DataFrame(dynamic_events).set_index("date")
    next_day_metrics = daily[
        [
            "range_pct", "true_range_pct", "first_hour_range_pct", "open_to_close_pct", "abs_open_close",
            "up_excursion", "down_excursion", "max_open_excursion", "either_075", "both_050",
            "directional_efficiency", "range_vs_prior20",
        ]
    ].shift(-1).add_prefix("next_")
    event_frame = event_frame.join(next_day_metrics)
    dynamic_frame = dynamic_frame.join(next_day_metrics)
    clean_frame = event_frame[event_frame.clean_transition]
    material_frame = clean_frame[clean_frame.early_max_pct.ge(0.001) & clean_frame.red_depth_pct.le(-0.001)]

    lines = [
        "# QQQ early green → delayed green-to-red study",
        "",
        "Source: Polygon five-minute QQQ aggregates, filtered to regular trading hours.",
        f"Sample: {daily.index.min():%Y-%m-%d} through {daily.index.max():%Y-%m-%d} ({len(daily)} sessions).",
        "",
        "## Signal definition",
        "",
        "- QQQ records at least one five-minute bar close above the prior session close between **09:35 and 10:30 ET**.",
        "- It then records a five-minute bar close below the prior session close between **10:35 and 12:30 ET**.",
        "- The entry/reference is the first delayed red five-minute close. ‘Rest of session’ is that close to 16:00; following-day returns are measured from the 16:00 close.",
        "",
        "## Methodology audit",
        "",
        "The literal rule looks for red within 120 minutes of the first green close and therefore includes opening whipsaws. "
        "The broad fixed-window rule only requires that QQQ was green at some point in the first hour and later red from 10:35–12:30. "
        "The cleaner state-transition rule additionally requires the 10:30 bar to remain green before the later red close. "
        "A fixed materiality sensitivity requires at least +0.10% early strength and a red close at least −0.10% below the prior close; these thresholds are not optimized.",
        "",
        "| Variant | Events | Rest-session mean / positive | Next-1d mean / positive | Next-5d mean / positive | Next-day RTH range |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, frame in (
        ("Literal: red within 120m of first green", dynamic_frame),
        ("Broad: green sometime in first hour", event_frame),
        ("Clean: still green at 10:30", clean_frame),
        ("Clean + ±0.10% material move", material_frame),
    ):
        rest = stats_line(frame.rest_session)
        next_one = stats_line(frame.next_1d)
        next_five = stats_line(frame.next_5d)
        next_range = frame.next_range_pct.dropna()
        lines.append(
            f"| {label} | {len(frame)} | {pct(rest[1])} / {rate(rest[3])} | {pct(next_one[1])} / {rate(next_one[3])} | "
            f"{pct(next_five[1])} / {rate(next_five[3])} | {pct(next_range.mean())} |"
        )
    lines.extend(
        [
        "",
        "## Results",
        "",
        f"- Events: **{len(event_frame)}**",
        f"- Median first green close: **{format_minute(event_frame.green_minute.median())} ET**",
        f"- Median delayed red close: **{format_minute(event_frame.red_minute.median())} ET**",
        f"- Close remains red versus prior session: **{rate(event_frame.session_red.mean())}**",
        "",
        "| Holding period | N | Mean return | Median | Positive rate | All-session baseline |",
        "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for label, column, baseline in (
        ("Red cross → 16:00", "rest_session", None),
        ("Next 1 trading day (from 16:00)", "next_1d", daily.next_1d),
        ("Next 2 trading days (from 16:00)", "next_2d", daily.next_2d),
        ("Next 5 trading days (from 16:00)", "next_5d", daily.next_5d),
        ("Red cross → next 1d close", "cross_to_1d", None),
        ("Red cross → next 2d close", "cross_to_2d", None),
        ("Red cross → next 5d close", "cross_to_5d", None),
    ):
        count, mean, median, positive = stats_line(event_frame[column])
        base_text = "—" if baseline is None else pct(baseline.mean())
        lines.append(f"| {label} | {count} | {pct(mean)} | {pct(median)} | {rate(positive)} | {base_text} |")

    lines.extend(
        [
            "",
            "## Following-session volatility and tradability",
            "",
            "RTH range is high minus low divided by the open. True range also includes the overnight gap. Directional efficiency is |close − open| / high-low; a high range with low efficiency is choppier and harder to monetize directionally.",
            "",
            "| Sample | Next-day N | Mean RTH range | Median RTH range | Range >1% | Range >1.5% | Above prior 20d median | Directional efficiency |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    volatility_samples = [
        ("All sessions baseline", daily.rename(columns={column: f"next_{column}" for column in ["range_pct", "directional_efficiency", "range_vs_prior20"]})),
        ("Literal 120-minute rule", dynamic_frame),
        ("Broad signal", event_frame),
        ("Clean transition", clean_frame),
        ("Clean + material move", material_frame),
    ]
    for label, frame in volatility_samples:
        ranges = frame.next_range_pct.dropna()
        efficiency = frame.loc[ranges.index, "next_directional_efficiency"].dropna()
        expansion = frame.loc[ranges.index, "next_range_vs_prior20"].dropna()
        lines.append(
            f"| {label} | {len(ranges)} | {pct(ranges.mean())} | {pct(ranges.median())} | {rate(ranges.gt(0.01).mean())} | "
            f"{rate(ranges.gt(0.015).mean())} | {rate(expansion.gt(1).mean())} | {rate(efficiency.mean())} |"
        )
    lines.extend(
        [
            "",
            "### Is the range expansion distinct from ordinary sampling noise?",
            "",
            "The interval below resamples five-session blocks to preserve short-run volatility clustering. The comparison is signal dates versus nonsignal dates, using the following session's RTH range.",
            "",
            "| Signal | Mean range diff. (95% CI) | Range >1.5% diff. (95% CI) | Either-side 0.75% diff. (95% CI) | Event-day mean range |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    next_ranges = daily.range_pct.shift(-1)
    next_large_range = next_ranges.ge(0.015).where(next_ranges.notna()).astype(float)
    next_either_move = daily.either_075.shift(-1).astype(float)
    for label, frame in (
        ("Literal 120-minute", dynamic_frame),
        ("Broad fixed-window", event_frame),
        ("Clean transition", clean_frame),
        ("Clean + material", material_frame),
    ):
        range_difference = block_bootstrap_difference(next_ranges, frame.index)
        large_range_difference = block_bootstrap_difference(next_large_range, frame.index)
        either_move_difference = block_bootstrap_difference(next_either_move, frame.index)
        lines.append(
            f"| {label} | {pct(range_difference[0])} ({pct(range_difference[1])} to {pct(range_difference[2])}) | "
            f"{pct(large_range_difference[0])} ({pct(large_range_difference[1])} to {pct(large_range_difference[2])}) | "
            f"{pct(either_move_difference[0])} ({pct(either_move_difference[1])} to {pct(either_move_difference[2])}) | "
            f"{pct(daily.loc[frame.index, 'range_pct'].mean())} |"
        )
    lines.extend(
        [
            "",
            "### Next-open opportunity shape",
            "",
            "Excursions are measured from the following session's open, so they are available to a trader acting only after the signal day has completed. ‘Either side ≥0.75%’ measures raw opportunity; ‘both sides ≥0.50%’ flags two-sided sessions where a naive directional breakout is vulnerable to whipsaw.",
            "",
            "| Next-day component | Literal 120m | Broad fixed | Clean transition | All-session baseline |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for label, column in (
        ("True range", "true_range_pct"),
        ("First-hour range", "first_hour_range_pct"),
        ("Open-to-close return", "open_to_close_pct"),
        ("Absolute open-to-close move", "abs_open_close"),
        ("Upside excursion from open", "up_excursion"),
        ("Downside excursion from open", "down_excursion"),
        ("Maximum one-sided excursion from open", "max_open_excursion"),
    ):
        lines.append(
            f"| {label} | {pct(dynamic_frame[f'next_{column}'].mean())} | {pct(event_frame[f'next_{column}'].mean())} | "
            f"{pct(clean_frame[f'next_{column}'].mean())} | {pct(daily[column].mean())} |"
        )
    for label, column in (
        ("Positive open-to-close", "open_to_close_pct"),
        ("Either side reaches 0.75%", "either_075"),
        ("Both sides reach 0.50%", "both_050"),
    ):
        baseline = daily[column].gt(0).mean() if column == "open_to_close_pct" else daily[column].mean()
        values = []
        for frame in (dynamic_frame, event_frame, clean_frame):
            series = frame[f"next_{column}"].dropna()
            values.append(series.gt(0).mean() if column == "open_to_close_pct" else series.mean())
        lines.append(f"| {label} | {rate(values[0])} | {rate(values[1])} | {rate(values[2])} | {rate(baseline)} |")
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- The sample is approximately two years and contains overlapping 1–5 day forward windows, so observations are not fully independent.",
            "- Results are descriptive and do not include transaction costs, slippage, or an executable high/low-capture rule.",
            "- A larger realized range is opportunity, not profit. Options profitability additionally depends on implied volatility; breakout profitability depends on entry, stop, and whipsaw handling.",
            "- The block-bootstrap interval preserves five-session clusters but does not remove all regime confounding. Signal dates are compared with nonsignal dates, not randomized experiments.",
            "- The materiality threshold is a sensitivity check, not a fitted trading parameter.",
            "",
            "## Event detail",
            "",
            "| Date | First green | Delayed red | Rest session | Next 1d | Next 2d | Next 5d |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for date, row in event_frame.iterrows():
        lines.append(
            f"| {date:%Y-%m-%d} | {format_minute(row.green_minute)} | {format_minute(row.red_minute)} | {pct(row.rest_session)} | "
            f"{pct(row.next_1d)} | {pct(row.next_2d)} | {pct(row.next_5d)} |"
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="qqq-early-green-to-red",
        study_name="QQQ Early Green-to-red",
        version="1.0",
        generator="modules/analysis/scripts/analyze_qqq_early_green_to_red.py",
        files={"report": REPORT},
        metrics=[{"label": "Events", "value": len(event_frame)}],
    )
    print("\n".join(lines[:36]))
    print(f"\nWrote {REPORT}")
    print(f"Published dashboard study {dashboard_output}")


if __name__ == "__main__":
    main()
