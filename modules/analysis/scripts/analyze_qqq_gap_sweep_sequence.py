"""Analyze QQQ gap-up → open retest → initial-candle-low sweep sequences.

Uses the existing QQQ RTH one-minute cache. No network access is required.
Events are evaluated in strict minute order; same-minute target touches are
reported as ambiguous rather than assigned a fabricated intrabar order.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from trading_analysis.dashboard import StudyArtifactWriter


REPO_ROOT = Path(__file__).resolve().parents[3]
ORDER_DATA = REPO_ROOT / "modules" / "analysis" / "order-data"
BARS_PATH = ORDER_DATA / "qqq-candle-body-gap-rth-minute-bars.csv"
DAILY_PATH = ORDER_DATA / "qqq-candle-body-gap-checkpoints.csv"
ALL_DAILY_PATH = ORDER_DATA / "qqq-daily-gaps-2024-07-27-to-2026-07-27.csv"
EVENTS_OUTPUT = ORDER_DATA / "qqq-gap-up-open-retest-low-sweep-events.csv"
SUMMARY_OUTPUT = ORDER_DATA / "qqq-gap-up-open-retest-low-sweep-study.json"
REPORT_OUTPUT = REPO_ROOT / "reports" / "qqq_gap_up_open_retest_low_sweep_study.md"

PRIMARY_INITIAL_MINUTES = 5
PRIMARY_GAP_MIN_PCT = 0.10
FIRST_HOUR_LAST_MINUTE = 59
SESSION_LAST_MINUTE = 389


def wilson(successes: int, observations: int) -> list[float | None]:
    if observations == 0:
        return [None, None]
    z = 1.959963984540054
    p = successes / observations
    denominator = 1 + z * z / observations
    center = (p + z * z / (2 * observations)) / denominator
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * observations)) / observations) / denominator
    return [(center - half) * 100, (center + half) * 100]


def clock(minute: float | int | None) -> str:
    if minute is None or pd.isna(minute):
        return "—"
    hour, minute_part = divmod(9 * 60 + 30 + int(minute), 60)
    return f"{hour:02d}:{minute_part:02d} ET"


def classify_session(
    day: pd.DataFrame,
    daily: pd.Series,
    *,
    initial_minutes: int = PRIMARY_INITIAL_MINUTES,
    require_bullish_initial: bool = True,
) -> dict[str, Any] | None:
    """Classify one session using only strictly later bars for each sequence step."""

    day = day.sort_values("minute").drop_duplicates("minute", keep="last")
    initial = day[day.minute.between(0, initial_minutes - 1)]
    if len(initial) < initial_minutes:
        return None

    session_open = float(daily.open)
    prior_close = float(daily.prior_close)
    initial_high = float(initial.high.max())
    initial_low = float(initial.low.min())
    initial_close = float(initial.iloc[-1].close)
    bullish_initial = initial_close > session_open
    gap_pct = (session_open / prior_close - 1) * 100

    result: dict[str, Any] = {
        "date": str(daily.name),
        "gap_pct": gap_pct,
        "prior_close": prior_close,
        "session_open": session_open,
        "initial_minutes": initial_minutes,
        "initial_high": initial_high,
        "initial_low": initial_low,
        "initial_close": initial_close,
        "bullish_initial": bullish_initial,
        "eligible_initial": bullish_initial or not require_bullish_initial,
        "open_retest_first_hour": False,
        "open_retest_minute": None,
        "swept_initial_low": False,
        "sweep_minute": None,
        "sweep_in_first_hour": False,
        "prior_close_reached_by_sweep": False,
        "revisited_initial_high_after_sweep": False,
        "initial_high_revisit_minute": None,
        "retested_prior_close_after_sweep": False,
        "prior_close_retest_minute": None,
        "resolution": "no_setup",
    }
    if not result["eligible_initial"]:
        return result

    # The initial composite must finish before a return to its opening level can
    # count as a retracement. This avoids counting the 09:30 opening print itself.
    retraces = day[
        day.minute.between(initial_minutes, FIRST_HOUR_LAST_MINUTE)
        & day.low.le(session_open)
    ]
    if retraces.empty:
        return result
    retrace_minute = int(retraces.iloc[0].minute)
    result["open_retest_first_hour"] = True
    result["open_retest_minute"] = retrace_minute

    # The sweep must occur on a strictly later minute than the open retest.
    sweeps = day[day.minute.gt(retrace_minute) & day.low.lt(initial_low)]
    if sweeps.empty:
        return result
    sweep = sweeps.iloc[0]
    sweep_minute = int(sweep.minute)
    result["swept_initial_low"] = True
    result["sweep_minute"] = sweep_minute
    result["sweep_in_first_hour"] = sweep_minute <= FIRST_HOUR_LAST_MINUTE
    result["prior_close_reached_by_sweep"] = bool(day[day.minute.le(sweep_minute)].low.le(prior_close).any())

    # Resolve targets only on later one-minute bars. A target reached on the
    # sweep bar has unknown ordering and is captured separately above.
    after = day[day.minute.gt(sweep_minute)]
    high_touches = after[after.high.ge(initial_high)]
    prior_touches = after[after.low.le(prior_close)]
    high_minute = None if high_touches.empty else int(high_touches.iloc[0].minute)
    prior_minute = None if prior_touches.empty else int(prior_touches.iloc[0].minute)
    result["revisited_initial_high_after_sweep"] = high_minute is not None
    result["initial_high_revisit_minute"] = high_minute
    result["retested_prior_close_after_sweep"] = prior_minute is not None
    result["prior_close_retest_minute"] = prior_minute

    if high_minute is not None and prior_minute is not None and high_minute == prior_minute:
        result["resolution"] = "same_minute_ambiguous"
    elif high_minute is not None and (prior_minute is None or high_minute < prior_minute):
        result["resolution"] = "initial_high_first"
    elif prior_minute is not None:
        result["resolution"] = "prior_close_first"
    else:
        result["resolution"] = "neither"
    return result


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = pd.read_csv(BARS_PATH)
    daily = pd.read_csv(DAILY_PATH)
    daily = daily[daily.direction.eq("up")].copy()
    daily["simple_gap_pct"] = daily.open.div(daily.prior_close).sub(1).mul(100)
    return bars[bars.direction.eq("up")].copy(), daily


def build_events(
    bars: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    initial_minutes: int,
    gap_min_pct: float,
    require_bullish_initial: bool,
) -> pd.DataFrame:
    daily_by_date = daily.set_index("date")
    records: list[dict[str, Any]] = []
    for date, day in bars.groupby("date", sort=True):
        if date not in daily_by_date.index:
            continue
        daily_row = daily_by_date.loc[date]
        if float(daily_row.simple_gap_pct) < gap_min_pct:
            continue
        record = classify_session(
            day,
            daily_row,
            initial_minutes=initial_minutes,
            require_bullish_initial=require_bullish_initial,
        )
        if record is not None:
            records.append(record)
    return pd.DataFrame(records)


def metric(count: int, denominator: int) -> dict[str, Any]:
    return {
        "count": int(count),
        "n": int(denominator),
        "pct": count / denominator * 100 if denominator else None,
        "ci95_pct": wilson(int(count), int(denominator)),
    }


def summarize(events: pd.DataFrame) -> dict[str, Any]:
    eligible = events[events.eligible_initial]
    retraces = eligible[eligible.open_retest_first_hour]
    setups = retraces[retraces.swept_initial_low]
    not_filled = setups[~setups.prior_close_reached_by_sweep]
    resolutions = setups.resolution.value_counts().to_dict()
    clean_resolutions = not_filled.resolution.value_counts().to_dict()
    return {
        "gap_ups": len(events),
        "bullish_initial": metric(int(events.bullish_initial.sum()), len(events)),
        "open_retest": metric(len(retraces), len(events)),
        "open_retest_given_eligible_initial": metric(len(retraces), len(eligible)),
        "full_setup": metric(len(setups), len(events)),
        "setup_given_eligible_initial": metric(len(setups), len(eligible)),
        "sweep_given_open_retest": metric(len(setups), len(retraces)),
        "sweep_in_first_hour": metric(int(setups.sweep_in_first_hour.sum()), len(setups)),
        "prior_close_reached_by_sweep": metric(int(setups.prior_close_reached_by_sweep.sum()), len(setups)),
        "revisited_initial_high_after_sweep": metric(int(setups.revisited_initial_high_after_sweep.sum()), len(setups)),
        "retested_prior_close_after_sweep": metric(int(setups.retested_prior_close_after_sweep.sum()), len(setups)),
        "both_targets_after_sweep": metric(
            int((setups.revisited_initial_high_after_sweep & setups.retested_prior_close_after_sweep).sum()), len(setups)
        ),
        "resolution_counts": {str(key): int(value) for key, value in resolutions.items()},
        "clean_not_filled_by_sweep_n": len(not_filled),
        "clean_resolution_counts": {str(key): int(value) for key, value in clean_resolutions.items()},
        "median_open_retest_minute": retraces.open_retest_minute.median() if len(retraces) else None,
        "median_sweep_minute": setups.sweep_minute.median() if len(setups) else None,
    }


def render_report(summary: dict[str, Any]) -> str:
    primary = summary["primary"]
    inclusive = summary["inclusive_initial_direction"]
    setup = primary["full_setup"]
    clean_n = primary["clean_not_filled_by_sweep_n"]
    clean = primary["clean_resolution_counts"]

    gap_rows = []
    for threshold, stats in summary["gap_size_sensitivity"].items():
        resolution = stats["resolution_counts"]
        gap_rows.append(
            f"| ≥{threshold}% | {stats['gap_ups']} | {stats['bullish_initial']['count']} | "
            f"{stats['full_setup']['count']} ({stats['full_setup']['pct']:.1f}%) | "
            f"{resolution.get('initial_high_first', 0)} | {resolution.get('prior_close_first', 0)} | "
            f"{resolution.get('neither', 0)} |"
        )

    candle_rows = []
    for minutes, stats in summary["initial_candle_sensitivity"].items():
        resolution = stats["resolution_counts"]
        candle_rows.append(
            f"| {minutes}m | {stats['bullish_initial']['count']} | {stats['full_setup']['count']} "
            f"({stats['full_setup']['pct']:.1f}% of gaps) | "
            f"{stats['revisited_initial_high_after_sweep']['pct']:.1f}% | "
            f"{stats['retested_prior_close_after_sweep']['pct']:.1f}% | "
            f"{resolution.get('initial_high_first', 0)} | {resolution.get('prior_close_first', 0)} |"
        )

    return "\n".join(
        [
            "# QQQ gap-up → open retest → initial-low sweep study",
            "",
            f"Source: existing Polygon-adjusted QQQ RTH one-minute cache. Sample: **{summary['range'][0]} through {summary['range'][1]}**.",
            "",
            "## Primary answer",
            "",
            f"Across the broader daily sample, a simple RTH gap-up (open above previous close) occurred in **{summary['simple_gap_ups']}/{summary['all_sessions']} "
            f"({summary['simple_gap_ups'] / summary['all_sessions'] * 100:.1f}%)** sessions. The stricter body-clearing ≥0.10% gap used for the intraday sequence occurred in "
            f"**{primary['gap_ups']}/{summary['all_sessions']} ({primary['gap_ups'] / summary['all_sessions'] * 100:.1f}%)** sessions.",
            "",
            f"Of **{primary['gap_ups']}** QQQ body-clearing gap-ups, **{primary['bullish_initial']['count']}** opened with a bullish five-minute candle. "
            f"**{primary['open_retest_given_eligible_initial']['count']} of {primary['open_retest_given_eligible_initial']['n']} "
            f"({primary['open_retest_given_eligible_initial']['pct']:.1f}%)** then returned to the 09:30 open by 10:29. "
            f"**{setup['count']} of {setup['n']} ({setup['pct']:.1f}%, 95% CI {setup['ci95_pct'][0]:.1f}–{setup['ci95_pct'][1]:.1f}%)** "
            "completed the entire sequence by subsequently trading below the initial five-minute low.",
            "",
            f"Conditional on a bullish initial candle, the full-setup rate was **{primary['setup_given_eligible_initial']['pct']:.1f}%**. "
            f"Conditional on the open retest already occurring, the low-sweep rate was **{primary['sweep_given_open_retest']['pct']:.1f}%**. "
            f"The sweep itself happened by 10:29 in **{primary['sweep_in_first_hour']['count']}/{primary['sweep_in_first_hour']['n']} "
            f"({primary['sweep_in_first_hour']['pct']:.1f}%)** cases. Median open retest: **{clock(primary['median_open_retest_minute'])}**; "
            f"median low sweep: **{clock(primary['median_sweep_minute'])}**.",
            "",
            "### Literal version without requiring a bullish opening candle",
            "",
            f"If every gap-up is included regardless of how the initial five-minute candle closes, **{inclusive['full_setup']['count']}/{inclusive['gap_ups']} "
            f"({inclusive['full_setup']['pct']:.1f}%)** qualifies: {inclusive['open_retest']['count']} touch the open after 09:34 and "
            f"{inclusive['full_setup']['count']} subsequently sweep the initial low. After those sweeps, "
            f"{inclusive['revisited_initial_high_after_sweep']['count']} revisit the initial high and "
            f"{inclusive['retested_prior_close_after_sweep']['count']} retest the previous close.",
            "",
            "That literal rate is inflated as a ‘retracement’ estimate because a bearish initial candle may already be trading below its open. "
            "The primary version requires the initial five-minute candle to close above the open, establishing an actual move away before the return.",
            "",
            "## What happened after the sweep?",
            "",
            f"- Revisited the initial five-minute high later: **{primary['revisited_initial_high_after_sweep']['count']}/{setup['count']} "
            f"({primary['revisited_initial_high_after_sweep']['pct']:.1f}%)**.",
            f"- Retested the previous close on a later minute: **{primary['retested_prior_close_after_sweep']['count']}/{setup['count']} "
            f"({primary['retested_prior_close_after_sweep']['pct']:.1f}%)**.",
            f"- Reached both targets later: **{primary['both_targets_after_sweep']['count']}/{setup['count']} "
            f"({primary['both_targets_after_sweep']['pct']:.1f}%)**.",
            "",
            f"Because both targets can trade in one session, the cleaner competing-risk result is: previous close had already been reached by the sweep in "
            f"**{primary['prior_close_reached_by_sweep']['count']}** cases. Among the remaining **{clean_n}**, the initial high traded first in "
            f"**{clean.get('initial_high_first', 0)} ({clean.get('initial_high_first', 0) / clean_n * 100:.1f}%)**, the previous close traded first in "
            f"**{clean.get('prior_close_first', 0)} ({clean.get('prior_close_first', 0) / clean_n * 100:.1f}%)**, and neither traded in "
            f"**{clean.get('neither', 0)} ({clean.get('neither', 0) / clean_n * 100:.1f}%)**.",
            "",
            "## Operational sequence",
            "",
            "1. **Gap-up:** the 09:30 open is at least 0.10% above the larger of the prior session’s open and close. This is the existing cache’s stricter body-clearing gap definition.",
            "2. **Initial gap candle:** the 09:30–09:34 composite closes above the 09:30 open.",
            "3. **Gap-level retracement:** after 09:34 and by 10:29, a one-minute low touches or crosses the 09:30 open.",
            "4. **Low sweep:** on a strictly later minute, price trades below the 09:30–09:34 low.",
            "5. **Resolution:** only later one-minute bars are used to decide whether the initial high or previous close trades first. Same-minute ordering is never inferred.",
            "",
            "## Gap-size sensitivity",
            "",
            "| Simple open/previous-close gap | Gap days | Bullish 5m | Full setup | Initial high first | Previous close first | Neither |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *gap_rows,
            "",
            "Larger gaps were less likely to reach the previous close before revisiting the opening high. This is the clearest conditioning variable in the sample.",
            "",
            "## Initial-candle sensitivity",
            "",
            "| Initial candle | Bullish candles | Full setup | Any later high revisit | Any later previous-close retest | High first | Previous close first |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *candle_rows,
            "",
            "The initial-candle definition materially changes the result: a ten-minute opening candle favors previous-close resolution, while the one- and five-minute definitions favor or roughly balance a high revisit.",
            "",
            "## Limitations",
            "",
            "The cache contains body-clearing gaps, not every open one cent above the previous close, so the estimate does not apply to tiny inside-body gaps. "
            "The study uses one-minute OHLC bars and therefore cannot order two levels touched within the same minute. Exact equality is treated as a touch; the low sweep requires a strict break. "
            "Results are descriptive and overlap across time, so the nominal Wilson interval does not address regime dependence.",
            "",
        ]
    )


def main() -> None:
    bars, daily = load_inputs()
    all_daily = pd.read_csv(ALL_DAILY_PATH)
    primary_events = build_events(
        bars,
        daily,
        initial_minutes=PRIMARY_INITIAL_MINUTES,
        gap_min_pct=PRIMARY_GAP_MIN_PCT,
        require_bullish_initial=True,
    )
    primary = summarize(primary_events)
    gap_sensitivity = {
        f"{threshold:g}": summarize(
            build_events(
                bars,
                daily,
                initial_minutes=PRIMARY_INITIAL_MINUTES,
                gap_min_pct=threshold,
                require_bullish_initial=True,
            )
        )
        for threshold in (0.10, 0.25, 0.50, 1.00)
    }
    candle_sensitivity = {
        str(minutes): summarize(
            build_events(
                bars,
                daily,
                initial_minutes=minutes,
                gap_min_pct=PRIMARY_GAP_MIN_PCT,
                require_bullish_initial=True,
            )
        )
        for minutes in (1, 5, 10)
    }
    inclusive = summarize(
        build_events(
            bars,
            daily,
            initial_minutes=PRIMARY_INITIAL_MINUTES,
            gap_min_pct=PRIMARY_GAP_MIN_PCT,
            require_bullish_initial=False,
        )
    )
    summary = {
        "source": "Existing Polygon-adjusted QQQ RTH one-minute cache",
        "range": [str(daily.date.min()), str(daily.date.max())],
        "all_sessions": int(len(all_daily)),
        "simple_gap_ups": int(all_daily.direction.eq("up").sum()),
        "primary_definition": {
            "body_gap_min_pct": PRIMARY_GAP_MIN_PCT,
            "initial_candle_minutes": PRIMARY_INITIAL_MINUTES,
            "requires_bullish_initial_close": True,
            "gap_level": "09:30 RTH open",
            "open_retest_deadline": "10:29 ET",
            "low_sweep": "strictly below initial composite low on a later one-minute bar",
        },
        "primary": primary,
        "inclusive_initial_direction": inclusive,
        "gap_size_sensitivity": gap_sensitivity,
        "initial_candle_sensitivity": candle_sensitivity,
    }
    primary_events.to_csv(EVENTS_OUTPUT, index=False)
    SUMMARY_OUTPUT.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    REPORT_OUTPUT.write_text(render_report(summary), encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="qqq-gap-sweep-sequence",
        study_name="QQQ Gap-up Open Retest / Low Sweep",
        version="1.0",
        generator="modules/analysis/scripts/analyze_qqq_gap_sweep_sequence.py",
        description="Sequence study of bullish opening composites, open retests, and later low sweeps.",
        files={"summary": SUMMARY_OUTPUT, "events": EVENTS_OUTPUT, "report": REPORT_OUTPUT},
    )
    print(f"Wrote {EVENTS_OUTPUT}")
    print(f"Wrote {SUMMARY_OUTPUT}")
    print(f"Wrote {REPORT_OUTPUT}")
    print(f"Published dashboard study {dashboard_output}")


if __name__ == "__main__":
    main()
