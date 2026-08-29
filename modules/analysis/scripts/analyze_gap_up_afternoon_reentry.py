"""Study afternoon re-entry opportunities after large-gap first-hour runners.

The candidate cohort comes from the existing adjusted Polygon daily/one-minute
gap study. Missing event-day RTH minute bars are fetched from Polygon and cached
locally. All intraday decisions use only information available by that minute.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "modules" / "data-pipeline" / "src"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from trading_data_pipeline.downloader import PolygonDownloader  # noqa: E402
from trading_data_pipeline.chart_workspace import WorkspaceView, render_chart_workspace_html  # noqa: E402
from trading_data_pipeline.visualize import make_chart_payload, render_chart_html  # noqa: E402
from trading_analysis.dashboard import DatasetImporter, ImportOptions, StudyArtifactWriter  # noqa: E402


ORDER_DATA = REPO_ROOT / "modules" / "analysis" / "order-data"
SOURCE = ORDER_DATA / "stock-double-digit-gap-up-first-hour-fade-study.json"
CACHE = ORDER_DATA / "stock-double-digit-gap-up-rth-minute-bars.csv"
EVENTS_OUTPUT = ORDER_DATA / "stock-gap-up-afternoon-reentry-events.csv"
SUMMARY_OUTPUT = ORDER_DATA / "stock-gap-up-afternoon-reentry-study.json"
REPORT = REPO_ROOT / "reports" / "stock_gap_up_afternoon_reentry_study.md"
WORKSPACE = REPO_ROOT / "reports" / "stock_gap_up_afternoon_reentry_workspace.html"

FIRST_HOUR_END = 59       # 09:30 through 10:29 bar starts
AFTERNOON_START = 210     # 13:00
ENTRY_CUTOFF = 360        # 15:30
SESSION_END = 389         # 15:59
NEW_HIGH_BUFFER = 0.001   # Require 10 bps above the relevant prior high.
PULLBACK_MIN = 0.01
PULLBACK_SENSITIVITY = (0.005, 0.01, 0.015, 0.02, 0.03)

RUNNER_VARIANTS = {
    "loose": {
        "label": "Loose",
        "return_min": 0.02,
        "close_location_min": 0.65,
        "max_close_drawdown_max": 0.05,
        "efficiency_min": 0.0,
    },
    "primary": {
        "label": "Primary",
        "return_min": 0.03,
        "close_location_min": 0.75,
        "max_close_drawdown_max": 0.03,
        "efficiency_min": 0.0,
    },
    "strict": {
        "label": "Strict",
        "return_min": 0.05,
        "close_location_min": 0.85,
        "max_close_drawdown_max": 0.02,
        "efficiency_min": 0.0,
    },
}


def wilson_interval(successes: int, observations: int) -> tuple[float, float]:
    if observations == 0:
        return math.nan, math.nan
    z = 1.959963984540054
    p = successes / observations
    denominator = 1 + z * z / observations
    center = (p + z * z / (2 * observations)) / denominator
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * observations)) / observations) / denominator
    return center - half, center + half


def event_key(ticker: str, date: str) -> str:
    return f"{ticker.upper()}|{date}"


def load_candidates(path: Path = SOURCE) -> tuple[dict[str, Any], pd.DataFrame]:
    document = json.loads(path.read_text(encoding="utf-8"))
    events = pd.DataFrame(event for event in document["events"] if event.get("minute_ok"))
    events["ticker"] = events.ticker.str.upper()
    events["date"] = events.date.astype(str)
    events["event_key"] = [event_key(ticker, date) for ticker, date in zip(events.ticker, events.date)]
    return document, events


def _normalize_polygon_day(frame: pd.DataFrame, ticker: str, date: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    bars = frame.copy().reset_index()
    timestamp_column = "timestamp" if "timestamp" in bars.columns else bars.columns[0]
    bars["timestamp"] = pd.to_datetime(bars[timestamp_column], utc=True)
    local = bars.timestamp.dt.tz_convert("America/New_York")
    bars["date"] = local.dt.strftime("%Y-%m-%d")
    bars["minute"] = local.dt.hour.mul(60).add(local.dt.minute).sub(9 * 60 + 30)
    bars = bars[(bars.date == date) & bars.minute.between(0, SESSION_END)].copy()
    bars["ticker"] = ticker
    columns = ["ticker", "date", "timestamp", "minute", "open", "high", "low", "close", "volume"]
    if "vwap" in bars.columns:
        columns.append("vwap")
    return bars[columns].sort_values("minute")


def load_or_fetch_bars(
    candidates: pd.DataFrame,
    *,
    cache_path: Path = CACHE,
    fetch_missing: bool = True,
    refresh: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    if cache_path.exists() and not refresh:
        cached = pd.read_csv(cache_path, parse_dates=["timestamp"])
    else:
        cached = pd.DataFrame()
    if not cached.empty:
        cached["event_key"] = [event_key(ticker, date) for ticker, date in zip(cached.ticker, cached.date)]
    present = set(cached.event_key.unique()) if not cached.empty else set()
    missing = candidates[~candidates.event_key.isin(present)]
    errors: list[str] = []
    if missing.empty or not fetch_missing:
        return cached.drop(columns=["event_key"], errors="ignore"), errors

    downloader = PolygonDownloader()
    additions: list[pd.DataFrame] = []
    total = len(missing)
    for position, event in enumerate(missing.itertuples(index=False), start=1):
        print(f"[{position}/{total}] {event.ticker} {event.date}", flush=True)
        day = datetime.fromisoformat(event.date)
        try:
            frame = downloader.fetch_bars(event.ticker, day, day, 1)
            normalized = _normalize_polygon_day(frame, event.ticker, event.date)
            if normalized.empty:
                errors.append(f"{event.event_key}: no RTH bars")
            else:
                additions.append(normalized)
        except Exception as exc:  # Preserve other event results if one symbol fails.
            errors.append(f"{event.event_key}: {type(exc).__name__}: {exc}")
        if position % 10 == 0 and additions:
            combined = pd.concat([cached.drop(columns=["event_key"], errors="ignore"), *additions], ignore_index=True)
            combined.drop_duplicates(["ticker", "date", "timestamp"], keep="last").to_csv(cache_path, index=False)
        time.sleep(0.05)

    combined = pd.concat([cached.drop(columns=["event_key"], errors="ignore"), *additions], ignore_index=True)
    combined = combined.drop_duplicates(["ticker", "date", "timestamp"], keep="last")
    combined = combined.sort_values(["ticker", "date", "minute"])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(cache_path, index=False)
    return combined, errors


def _first_time_of_high(frame: pd.DataFrame, threshold: float) -> int | None:
    matches = frame[frame.high.gt(threshold)]
    return None if matches.empty else int(matches.iloc[0].minute)


def analyze_event(day: pd.DataFrame, candidate: pd.Series) -> dict[str, Any] | None:
    day = day.sort_values("minute").drop_duplicates("minute", keep="last")
    first = day[day.minute.between(0, FIRST_HOUR_END)]
    afternoon = day[day.minute.between(AFTERNOON_START, SESSION_END)]
    if len(first) < 50 or len(afternoon) < 90:
        return None

    session_open = float(first.iloc[0].open)
    session_close = float(day.iloc[-1].close)
    first_high = float(first.high.max())
    first_low = float(first.low.min())
    first_close = float(first.iloc[-1].close)
    first_return = first_close / session_open - 1
    first_location = (first_close - first_low) / (first_high - first_low) if first_high > first_low else 0.5
    close_path = np.r_[session_open, first.close.to_numpy(dtype=float)]
    running_peak = np.maximum.accumulate(close_path)
    max_close_drawdown = float(np.max(1 - close_path / running_peak))
    path_length = float(np.abs(np.diff(close_path)).sum())
    efficiency = max(first_close - session_open, 0) / path_length if path_length else 0.0

    pre_afternoon = day[day.minute.lt(AFTERNOON_START)]
    pre_afternoon_high = float(pre_afternoon.high.max())
    pre_afternoon_high_minute = int(pre_afternoon.loc[pre_afternoon.high.idxmax(), "minute"])
    first_hour_new_high_threshold = first_high * (1 + NEW_HIGH_BUFFER)
    afternoon_new_high_threshold = pre_afternoon_high * (1 + NEW_HIGH_BUFFER)
    afternoon_new_high_minute = _first_time_of_high(afternoon, afternoon_new_high_threshold)
    afternoon_new_high = afternoon_new_high_minute is not None
    after_first = day[day.minute.gt(FIRST_HOUR_END)]
    post_first_new_high_minute = _first_time_of_high(after_first, first_hour_new_high_threshold)

    pullback_before_hod = False
    constructive_pullback_before_hod = False
    pre_hod_pullback_depth = math.nan
    if afternoon_new_high_minute is not None:
        pre_hod = day[day.minute.between(pre_afternoon_high_minute + 1, afternoon_new_high_minute - 1)]
        if not pre_hod.empty:
            trough = float(pre_hod.low.min())
            pre_hod_pullback_depth = 1 - trough / pre_afternoon_high
            pullback_before_hod = pre_hod_pullback_depth >= PULLBACK_MIN
            constructive_pullback_before_hod = pullback_before_hod and trough >= session_open

    # Real-time-safe diagnostic signal: after 13:00, enter at the first close
    # above the halfway recovery from the running low to the high-of-day known
    # at 13:00, once the observed pullback reaches the configured minimum.
    post = day[day.minute.gt(pre_afternoon_high_minute)].copy()
    post["running_low"] = post.low.cummin()
    post["pullback_depth"] = 1 - post.running_low / pre_afternoon_high
    post["reclaim_level"] = post.running_low + 0.5 * (pre_afternoon_high - post.running_low)
    eligible = post[
        post.minute.between(AFTERNOON_START, ENTRY_CUTOFF)
        & post.pullback_depth.ge(PULLBACK_MIN)
        & post.close.ge(post.reclaim_level)
    ]
    signal = None if eligible.empty else eligible.iloc[0]
    signal_minute: int | None = None
    signal_price = math.nan
    signal_success = False
    signal_close_return = math.nan
    signal_mfe = math.nan
    signal_mae = math.nan
    if signal is not None:
        signal_minute = int(signal.minute)
        signal_price = float(signal.close)
        subsequent = day[day.minute.gt(signal_minute)]
        if not subsequent.empty:
            signal_success = float(subsequent.high.max()) > afternoon_new_high_threshold
            signal_close_return = session_close / signal_price - 1
            signal_mfe = float(subsequent.high.max()) / signal_price - 1
            signal_mae = float(subsequent.low.min()) / signal_price - 1

    result: dict[str, Any] = {
        "ticker": str(candidate.ticker),
        "date": str(candidate.date),
        "gap_pct": float(candidate.gap_pct) / 100,
        "bars": int(len(day)),
        "session_open": session_open,
        "session_close": session_close,
        "first_hour_high": first_high,
        "first_hour_low": first_low,
        "first_hour_close": first_close,
        "first_hour_return": first_return,
        "first_hour_close_location": first_location,
        "first_hour_max_close_drawdown": max_close_drawdown,
        "first_hour_directional_efficiency": efficiency,
        "pre_afternoon_high": pre_afternoon_high,
        "pre_afternoon_high_minute": pre_afternoon_high_minute,
        "post_first_new_high": post_first_new_high_minute is not None,
        "post_first_new_high_minute": post_first_new_high_minute,
        "afternoon_new_high": afternoon_new_high,
        "afternoon_new_high_minute": afternoon_new_high_minute,
        "close_above_first_hour_high": session_close > first_high,
        "close_above_pre_afternoon_high": session_close > pre_afternoon_high,
        "close_within_2pct_of_hod": session_close >= float(day.high.max()) * 0.98,
        "pullback_before_afternoon_hod": pullback_before_hod,
        "constructive_pullback_before_afternoon_hod": constructive_pullback_before_hod,
        "pre_hod_pullback_depth": pre_hod_pullback_depth,
        "reclaim_signal": signal is not None,
        "reclaim_signal_minute": signal_minute,
        "reclaim_signal_price": signal_price,
        "reclaim_new_hod_after": signal_success,
        "reclaim_to_close_return": signal_close_return,
        "reclaim_mfe": signal_mfe,
        "reclaim_mae": signal_mae,
    }
    for slug, definition in RUNNER_VARIANTS.items():
        result[f"runner_{slug}"] = bool(
            first_return >= definition["return_min"]
            and first_location >= definition["close_location_min"]
            and max_close_drawdown <= definition["max_close_drawdown_max"]
            and efficiency >= definition["efficiency_min"]
        )
    return result


def summarize_group(frame: pd.DataFrame) -> dict[str, Any]:
    count = len(frame)

    def proportion(column: str, denominator: pd.DataFrame = frame) -> dict[str, Any]:
        n = len(denominator)
        successes = int(denominator[column].sum()) if n else 0
        lower, upper = wilson_interval(successes, n)
        return {
            "count": successes,
            "n": n,
            "pct": successes / n * 100 if n else None,
            "ci95_pct": [lower * 100, upper * 100] if n else [None, None],
        }

    signals = frame[frame.reclaim_signal] if count else frame
    hod_winners = frame[frame.afternoon_new_high] if count else frame
    pullback_sensitivity: dict[str, Any] = {}
    for threshold in PULLBACK_SENSITIVITY:
        all_count = int(frame.pre_hod_pullback_depth.ge(threshold).sum()) if count else 0
        winner_count = int(hod_winners.pre_hod_pullback_depth.ge(threshold).sum()) if len(hod_winners) else 0
        pullback_sensitivity[f"{threshold * 100:g}%"] = {
            "all_primary_count": all_count,
            "all_primary_n": count,
            "hod_winner_count": winner_count,
            "hod_winner_n": len(hod_winners),
        }
    hod_hours = {
        "13:00-13:59": int(hod_winners.afternoon_new_high_minute.between(210, 269).sum()),
        "14:00-14:59": int(hod_winners.afternoon_new_high_minute.between(270, 329).sum()),
        "15:00-15:59": int(hod_winners.afternoon_new_high_minute.between(330, 389).sum()),
    }
    return {
        "n": count,
        "afternoon_new_high": proportion("afternoon_new_high"),
        "pullback_then_afternoon_new_high": proportion("pullback_before_afternoon_hod"),
        "constructive_pullback_then_new_high": proportion("constructive_pullback_before_afternoon_hod"),
        "close_above_first_hour_high": proportion("close_above_first_hour_high"),
        "close_above_pre_afternoon_high": proportion("close_above_pre_afternoon_high"),
        "close_within_2pct_of_hod": proportion("close_within_2pct_of_hod"),
        "reclaim_signal_offered": proportion("reclaim_signal"),
        "new_high_after_reclaim": proportion("reclaim_new_hod_after", signals),
        "pullback_depth_sensitivity": pullback_sensitivity,
        "first_afternoon_hod_hour_counts": hod_hours,
        "median_first_hour_return_pct": frame.first_hour_return.median() * 100 if count else None,
        "median_afternoon_hod_minute": frame.loc[frame.afternoon_new_high, "afternoon_new_high_minute"].median() if count else None,
        "median_reclaim_minute": signals.reclaim_signal_minute.median() if len(signals) else None,
        "median_reclaim_to_close_pct": signals.reclaim_to_close_return.median() * 100 if len(signals) else None,
        "mean_reclaim_to_close_pct": signals.reclaim_to_close_return.mean() * 100 if len(signals) else None,
        "reclaim_close_win_pct": signals.reclaim_to_close_return.gt(0).mean() * 100 if len(signals) else None,
        "median_reclaim_mfe_pct": signals.reclaim_mfe.median() * 100 if len(signals) else None,
        "median_reclaim_mae_pct": signals.reclaim_mae.median() * 100 if len(signals) else None,
    }


def clock_time(minute: float | int | None) -> str:
    if minute is None or pd.isna(minute):
        return "—"
    hour, minute_part = divmod(9 * 60 + 30 + int(minute), 60)
    return f"{hour:02d}:{minute_part:02d} ET"


def percent(value: float | None, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:{'+' if signed else ''}.1f}%"


def render_report(summary: dict[str, Any], events: pd.DataFrame) -> str:
    primary = summary["variants"]["primary"]
    sensitivity_rows = []
    for slug, definition in RUNNER_VARIANTS.items():
        stats = summary["variants"][slug]
        hod = stats["afternoon_new_high"]
        pullback = stats["pullback_then_afternoon_new_high"]
        offered = stats["reclaim_signal_offered"]
        success = stats["new_high_after_reclaim"]
        sensitivity_rows.append(
            f"| {definition['label']} | {stats['n']} | {percent(hod['pct'])} ({hod['count']}/{hod['n']}) | "
            f"{percent(pullback['pct'])} | {percent(offered['pct'])} | {percent(success['pct'])} | "
            f"{percent(stats['median_reclaim_to_close_pct'], signed=True)} |"
        )

    pullback_rows = []
    for label, stats in primary["pullback_depth_sensitivity"].items():
        pullback_rows.append(
            f"| ≥{label} | {stats['all_primary_count']}/{stats['all_primary_n']} "
            f"({stats['all_primary_count'] / stats['all_primary_n'] * 100:.1f}%) | "
            f"{stats['hod_winner_count']}/{stats['hod_winner_n']} "
            f"({stats['hod_winner_count'] / stats['hod_winner_n'] * 100:.1f}%) |"
        )

    primary_events = events[events.runner_primary]
    signals = primary_events[primary_events.reclaim_signal]
    successes = signals[signals.reclaim_new_hod_after].sort_values("reclaim_to_close_return", ascending=False).head(8)
    failures = signals[~signals.reclaim_new_hod_after].sort_values("reclaim_to_close_return").head(8)

    def examples(frame: pd.DataFrame) -> list[str]:
        if frame.empty:
            return ["| — | — | — | — | — |"]
        return [
            f"| {row.ticker} | {row.date} | {row.gap_pct * 100:.1f}% | {clock_time(row.reclaim_signal_minute)} | "
            f"{row.reclaim_to_close_return * 100:+.1f}% |"
            for row in frame.itertuples()
        ]

    hod = primary["afternoon_new_high"]
    reclaim = primary["new_high_after_reclaim"]
    baseline = summary["baseline_non_primary"]["afternoon_new_high"]
    return "\n".join(
        [
            "# Huge gap-up → first-hour runner → afternoon re-entry study",
            "",
            f"Source: Polygon adjusted one-minute aggregates, RTH only. Cohort: **{summary['cohort_n']}** ≥10% gap-ups "
            f"from **{summary['date_range'][0]} through {summary['date_range'][1]}** across {summary['universe_n']} selected liquid/high-beta stocks.",
            "",
            "## Answer",
            "",
            f"Under the primary straight-up definition, **{hod['count']} of {hod['n']} ({hod['pct']:.1f}%, "
            f"95% Wilson CI {hod['ci95_pct'][0]:.1f}–{hod['ci95_pct'][1]:.1f}%)** made a fresh high of day after 13:00.",
            f"A ≥1% pullback occurred before that afternoon high in **{primary['pullback_then_afternoon_new_high']['count']} of {primary['n']} "
            f"({primary['pullback_then_afternoon_new_high']['pct']:.1f}%)** primary runners.",
            f"The mechanical afternoon 50%-recovery reclaim appeared in **{primary['reclaim_signal_offered']['count']} of {primary['n']} "
            f"({primary['reclaim_signal_offered']['pct']:.1f}%)**. Conditional on a signal, **{reclaim['count']} of {reclaim['n']} "
            f"({reclaim['pct']:.1f}%, CI {reclaim['ci95_pct'][0]:.1f}–{reclaim['ci95_pct'][1]:.1f}%)** subsequently cleared the pre-afternoon HOD by at least 10 bps.",
            "",
            "## Operational definitions",
            "",
            "- **Huge gap:** open ≥10% above the adjusted prior close, prior close ≥$5, session volume ≥1M.",
            "- **First hour:** 09:30–10:29 ET. Primary ‘straight up’ requires return ≥3%, close in the top 25% of the first-hour range, and maximum close-to-running-peak drawdown ≤3%. Minute-path directional efficiency is retained in the event file for further filtering but is not used in the primary rule.",
            "- **Afternoon new HOD:** a 13:00–15:59 bar trades at least 10 bps above the full high-of-day already known at 13:00—not merely above the first-hour high.",
            "- **Pullback chance:** after that pre-afternoon HOD and before the new HOD, price trades at least 1% below the known high. Deeper thresholds are shown separately.",
            "- **Reclaim entry proxy:** from 13:00 through 15:30, after an observed ≥1% pullback, the first close at or above the halfway recovery from the running low to the HOD known at 13:00. The signal uses no future bars; success requires a later bar to clear that HOD by 10 bps.",
            "",
            "## Sensitivity",
            "",
            "| Runner filter | N | Afternoon new HOD | Pullback then HOD | Reclaim offered | HOD after reclaim | Median entry→close |",
            "|---|---:|---:|---:|---:|---:|---:|",
            *sensitivity_rows,
            "",
            "### Pullback depth before the afternoon HOD (primary runners)",
            "",
            "| Minimum pullback | Share of all primary runners | Share of afternoon-HOD winners |",
            "|---|---:|---:|",
            *pullback_rows,
            "",
            f"For comparison, non-primary gap-ups made an afternoon new HOD **{baseline['pct']:.1f}%** of the time "
            f"({baseline['count']}/{baseline['n']}). The primary cohort’s median afternoon HOD time was "
            f"**{clock_time(primary['median_afternoon_hod_minute'])}**; its median reclaim time was **{clock_time(primary['median_reclaim_minute'])}**.",
            f"Of the {hod['count']} primary afternoon-HOD events, **{primary['first_afternoon_hod_hour_counts']['13:00-13:59']}** first broke out from 13:00–13:59, "
            f"**{primary['first_afternoon_hod_hour_counts']['14:00-14:59']}** from 14:00–14:59, and **{primary['first_afternoon_hod_hour_counts']['15:00-15:59']}** after 15:00.",
            "",
            "## Entry-path characteristics",
            "",
            f"Among primary reclaim signals, entry-to-close return averaged **{percent(primary['mean_reclaim_to_close_pct'], signed=True)}** "
            f"and had a **{percent(primary['reclaim_close_win_pct'])}** positive-close rate. Median post-entry MFE was "
            f"**{percent(primary['median_reclaim_mfe_pct'], signed=True)}** and median MAE was **{percent(primary['median_reclaim_mae_pct'], signed=True)}**.",
            f"The session closed above the pre-afternoon HOD in **{primary['close_above_pre_afternoon_high']['pct']:.1f}%** of primary cases and within 2% of HOD in **{primary['close_within_2pct_of_hod']['pct']:.1f}%**.",
            "",
            "## Strongest successful reclaim examples",
            "",
            "| Ticker | Date | Gap | Signal | Entry→close |",
            "|---|---|---:|---:|---:|",
            *examples(successes),
            "",
            "## Weakest / failed reclaim examples",
            "",
            "| Ticker | Date | Gap | Signal | Entry→close |",
            "|---|---|---:|---:|---:|",
            *examples(failures),
            "",
            "## Interpretation and limitations",
            "",
            "This is an opportunity-frequency study, not a fill-level backtest. The reclaim close omits spread, slippage, halts, and liquidity constraints. "
            f"The 31-stock universe is selected, and the {primary['n']} primary observations represent only {summary['primary_unique_tickers']} tickers and "
            f"{summary['primary_unique_dates']} dates; ticker/date clustering makes the nominal Wilson intervals too optimistic. "
            "The operational thresholds were selected after an initial feasibility pass showed that a literal straight-line rule left only two events. "
            "The results are therefore descriptive rather than confirmatory; the loose/primary/strict tiers expose sensitivity, but an out-of-sample universe is still required.",
            "",
            "The practical distinction is important: ‘made a new afternoon HOD’ is not itself an entry rule. The separate reclaim statistic asks whether a known-at-the-time pullback/recovery setup appeared before the later high.",
            "",
        ]
    )


def render_audit_workspace(events: pd.DataFrame, cache_path: Path = CACHE) -> str:
    """Build annotated one-minute charts for every primary-runner event."""

    bars = pd.read_csv(cache_path, parse_dates=["timestamp"])
    primary = events[events.runner_primary].sort_values(["date", "ticker"])
    views: list[WorkspaceView] = []
    dashboard_views: list[dict[str, Any]] = []
    importer = DatasetImporter()

    for event in primary.itertuples():
        day = bars[(bars.ticker == event.ticker) & (bars.date.astype(str) == event.date)].sort_values("minute")
        if day.empty:
            continue

        def point_time(minute: int) -> str:
            exact = day.loc[day.minute.eq(minute)]
            row = exact.iloc[0] if not exact.empty else day.iloc[(day.minute - minute).abs().argmin()]
            return pd.Timestamp(row.timestamp).isoformat()

        first_time = point_time(0)
        afternoon_time = point_time(AFTERNOON_START)
        close_time = point_time(int(day.minute.max()))
        reference_time = point_time(int(event.pre_afternoon_high_minute))
        groups = [
            {"id": "windows", "label": "Study windows", "color": "#64748b", "visible": True},
            {"id": "hod", "label": "HOD levels", "color": "#f6c85f", "visible": True},
            {"id": "reentry", "label": "Re-entry", "color": "#56b6c2", "visible": True},
        ]
        points: list[dict[str, Any]] = [
            {
                "id": "pre-afternoon-hod",
                "group": "hod",
                "time": reference_time,
                "pane": "price",
                "value": float(event.pre_afternoon_high),
                "label": "HOD known at 13:00",
                "role": "reference_hod",
                "marker": "triangle-down",
            }
        ]
        links: list[dict[str, Any]] = [
            {
                "id": "pre-afternoon-hod-level",
                "group": "hod",
                "pane": "price",
                "start_time": afternoon_time,
                "end_time": close_time,
                "start_value": float(event.pre_afternoon_high),
                "end_value": float(event.pre_afternoon_high),
                "label": "13:00 HOD reference",
                "dash": "dash",
            }
        ]
        if not pd.isna(event.reclaim_signal_minute):
            signal_minute = int(event.reclaim_signal_minute)
            signal_time = point_time(signal_minute)
            points.append(
                {
                    "id": "reclaim-signal",
                    "group": "reentry",
                    "time": signal_time,
                    "pane": "price",
                    "value": float(event.reclaim_signal_price),
                    "label": "50% recovery reclaim",
                    "role": "entry",
                    "marker": "triangle-up",
                    "metadata": {"new_hod_after": bool(event.reclaim_new_hod_after)},
                }
            )
        if not pd.isna(event.afternoon_new_high_minute):
            hod_minute = int(event.afternoon_new_high_minute)
            hod_row = day.loc[day.minute.eq(hod_minute)].iloc[0]
            hod_time = point_time(hod_minute)
            points.append(
                {
                    "id": "afternoon-new-hod",
                    "group": "hod",
                    "time": hod_time,
                    "pane": "price",
                    "value": float(hod_row.high),
                    "label": "Fresh afternoon HOD",
                    "role": "target",
                    "marker": "star",
                }
            )
            if not pd.isna(event.reclaim_signal_minute) and bool(event.reclaim_new_hod_after):
                links.append(
                    {
                        "id": "entry-to-new-hod",
                        "group": "reentry",
                        "pane": "price",
                        "start_time": point_time(int(event.reclaim_signal_minute)),
                        "end_time": hod_time,
                        "start_value": float(event.reclaim_signal_price),
                        "end_value": float(hod_row.high),
                        "label": "Reclaim to new HOD",
                        "dash": "dot",
                    }
                )

        annotations = {
            "schema_version": "trading-chart-annotations/v1",
            "groups": groups,
            "panels": [],
            "points": points,
            "links": links,
            "spans": [
                {
                    "id": "first-hour-window",
                    "group": "windows",
                    "pane": "price",
                    "start_time": first_time,
                    "end_time": point_time(FIRST_HOUR_END),
                    "label": "First hour",
                    "color": "#56b6c2",
                    "opacity": 0.04,
                },
                {
                    "id": "afternoon-window",
                    "group": "windows",
                    "pane": "price",
                    "start_time": afternoon_time,
                    "end_time": close_time,
                    "label": "Afternoon",
                    "color": "#f6c85f",
                    "opacity": 0.035,
                },
            ],
        }
        rows = day[["timestamp", "open", "high", "low", "close", "volume"]].to_dict("records")
        payload = make_chart_payload(
            ticker=event.ticker,
            timeframe_minutes=1,
            rows=rows,
            source_label=f"{cache_path.name} · {event.date}",
            annotations=annotations,
        )
        outcome = "new HOD" if event.afternoon_new_high else "no new HOD"
        views.append(
            WorkspaceView(
                id=f"{event.ticker.lower()}-{event.date}",
                ticker=event.ticker,
                timeframe="1m",
                study_id=event.date,
                study_label=f"{event.date} · {outcome}",
                label=f"{event.ticker} · {event.date} · {outcome}",
                html=render_chart_html(payload),
            )
        )
        dataset = importer.import_rows(
            rows,
            source_label=f"{cache_path.resolve()}#{event.ticker}/{event.date}",
            options=ImportOptions(
                symbol=event.ticker,
                asset_class="stock",
                venue="polygon",
                provider="polygon-cache",
                interval_seconds=60,
                calendar="XNYS",
                adjustment="adjusted",
            ),
        )
        dashboard_views.append({
            "id": f"{event.ticker.lower()}-{event.date}",
            "label": f"{event.ticker} · {event.date} · {outcome}",
            "dataset_id": dataset["id"],
            "default_start": first_time,
            "default_end": close_time,
            "chart": annotations,
        })
    if dashboard_views:
        table_columns = [
            column for column in (
                "ticker", "date", "gap_pct", "reclaim_signal_minute", "reclaim_to_close_pct",
                "reclaim_mfe_pct", "reclaim_mae_pct", "afternoon_new_high",
            ) if column in primary.columns
        ]
        table_rows = json.loads(primary[table_columns].to_json(orient="records", date_format="iso"))
        writer = StudyArtifactWriter(importer.catalog)
        manifest = writer.build_manifest(
            study_id="gap-up-afternoon-reentry",
            study_name="Gap-up Afternoon Re-entry",
            version="2.0",
            description="One-minute audit views for primary large-gap first-hour runners.",
            generator="modules/analysis/scripts/analyze_gap_up_afternoon_reentry.py",
            parameters={
                "first_hour_end_minute": FIRST_HOUR_END,
                "afternoon_start_minute": AFTERNOON_START,
                "entry_cutoff_minute": ENTRY_CUTOFF,
                "new_high_buffer": NEW_HIGH_BUFFER,
                "pullback_min": PULLBACK_MIN,
            },
            views=dashboard_views,
            metrics=[
                {"label": "Primary events", "value": len(dashboard_views)},
                {"label": "Unique tickers", "value": int(primary.ticker.nunique())},
                {"label": "Fresh afternoon HOD", "value": int(primary.afternoon_new_high.sum())},
            ],
            tables=[{
                "id": "primary-events",
                "label": "Primary runner events",
                "columns": table_columns,
                "rows": table_rows,
            }],
            methodology=(
                "The candidate cohort and all signal decisions are computed by the generator using only "
                "information available by each minute. Full-session spans are preserved in the chart contract."
            ),
        )
        dashboard_output = writer.publish(manifest)
        print(f"Published dashboard study {dashboard_output}")
    return render_chart_workspace_html(views, title="Gap-up afternoon re-entry audit")


def run_study(
    *,
    source_path: Path = SOURCE,
    cache_path: Path = CACHE,
    fetch_missing: bool = True,
    refresh: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, list[str]]:
    source, candidates = load_candidates(source_path)
    bars, errors = load_or_fetch_bars(candidates, cache_path=cache_path, fetch_missing=fetch_missing, refresh=refresh)
    bars["date"] = bars.date.astype(str)
    bars["event_key"] = [event_key(ticker, date) for ticker, date in zip(bars.ticker, bars.date)]
    grouped = {key: day for key, day in bars.groupby("event_key")}
    records = []
    for _, candidate in candidates.iterrows():
        day = grouped.get(candidate.event_key)
        if day is None:
            errors.append(f"{candidate.event_key}: missing cached event bars")
            continue
        result = analyze_event(day, candidate)
        if result is None:
            errors.append(f"{candidate.event_key}: incomplete RTH session")
        else:
            records.append(result)
    events = pd.DataFrame(records).sort_values(["date", "ticker"])
    variants = {
        slug: summarize_group(events[events[f"runner_{slug}"]])
        for slug in RUNNER_VARIANTS
    }
    primary_events = events[events.runner_primary]
    summary = {
        "source": "Polygon adjusted daily cohort + cached RTH one-minute aggregates",
        "date_range": source["range"],
        "universe": source["universe"],
        "universe_n": len(source["universe"]),
        "cohort_n": len(events),
        "candidate_n": len(candidates),
        "errors": errors,
        "gap_filters": source["filters"],
        "new_high_buffer_pct": NEW_HIGH_BUFFER * 100,
        "pullback_min_pct": PULLBACK_MIN * 100,
        "runner_definitions": RUNNER_VARIANTS,
        "primary_unique_tickers": int(primary_events.ticker.nunique()),
        "primary_unique_dates": int(primary_events.date.nunique()),
        "variants": variants,
        "baseline_all_gap_ups": summarize_group(events),
        "baseline_non_primary": summarize_group(events[~events.runner_primary]),
    }
    return summary, events, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--refresh", action="store_true", help="Ignore cached minute bars and fetch all event days again")
    parser.add_argument("--no-fetch", action="store_true", help="Use only cached minute bars")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    summary, events, errors = run_study(
        source_path=args.source,
        cache_path=args.cache,
        fetch_missing=not args.no_fetch,
        refresh=args.refresh,
    )
    EVENTS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(EVENTS_OUTPUT, index=False)
    SUMMARY_OUTPUT.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(summary, events), encoding="utf-8")
    WORKSPACE.write_text(render_audit_workspace(events, args.cache), encoding="utf-8")
    print(f"Wrote {EVENTS_OUTPUT}")
    print(f"Wrote {SUMMARY_OUTPUT}")
    print(f"Wrote {REPORT}")
    print(f"Wrote {WORKSPACE}")
    if errors:
        print(f"Completed with {len(errors)} missing/incomplete events")


if __name__ == "__main__":
    main()
