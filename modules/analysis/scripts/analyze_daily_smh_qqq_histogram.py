"""Daily Fisher adaptive-MACD histogram events on SMH and QQQ.

Compares the dark→light color-shift (still on the same side of zero) with the
histogram zero-line flip, including a one-session timeout on failed color-shifts.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from trading_analysis.dashboard import StudyArtifactWriter

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "modules" / "data-pipeline" / "src"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from trading_analysis.market_data import fetch_aggs
from trading_data_pipeline.strategies.fisher_adaptive_macd import (
    StrategyConfig,
    compute_fisher_adaptive_macd_strategy,
)

TICKERS = ("SMH", "QQQ")
START = date(2010, 1, 1)
END = date(2026, 8, 18)
HORIZONS = (1, 2, 3, 5, 10)
MAIN_HORIZON = 5
REPORT = REPO_ROOT / "reports" / "daily_smh_qqq_histogram_study.md"
EVENTS_CSV = REPO_ROOT / "reports" / "daily_smh_qqq_histogram_events.csv"

EVENT_TITLES = {
    "first_dark_blue": "Light→dark in blue (first fade, still above zero)",
    "reaccel_in_blue": "Dark→light in blue (re-acceleration long)",
    "bullish_flip": "Histogram flip red→blue",
    "early_rising_blue": "Early rising-blue (3rd increasing bar)",
    "first_dark_red": "Light→dark-red in red (first fade toward zero)",
    "reaccel_in_red": "Dark→light-red in red (re-acceleration short)",
    "bearish_flip": "Histogram flip blue→red",
}


def pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.2f}%"


def rate(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:.1f}%"


def stats(series: pd.Series) -> tuple[int, float, float, float]:
    clean = series.dropna()
    if clean.empty:
        return 0, float("nan"), float("nan"), float("nan")
    return len(clean), float(clean.mean()), float(clean.median()), float(clean.gt(0).mean())


def fetch_daily(ticker: str) -> pd.DataFrame:
    bars = fetch_aggs(
        ticker,
        multiplier=1,
        timespan="day",
        start_date=START,
        end_date=END,
        adjusted=True,
    )
    rows = []
    for bar in bars:
        stamp = datetime.fromtimestamp(int(bar["t"]) / 1000, timezone.utc)
        rows.append(
            {
                "date": stamp.date(),
                "time": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timestamp": stamp,
                "open": float(bar["o"]),
                "high": float(bar["h"]),
                "low": float(bar["l"]),
                "close": float(bar["c"]),
                "volume": float(bar.get("v") or 0),
            }
        )
    frame = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return frame


def attach_macd(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    result = compute_fisher_adaptive_macd_strategy(
        frame.to_dict("records"),
        ticker=ticker,
        timeframe_minutes=1440,
        config=StrategyConfig(ft_len=50, r2_period=20, macd_fast=10, macd_slow=20, macd_signal=9, htf_tf="D"),
    )
    output = frame.copy()
    output["adaptive_macd"] = result.series["adaptive_macd"]
    output["signal"] = result.series["signal_line"]
    output["histogram"] = result.series["histogram"]
    return output


def add_outcomes(record: dict[str, object], frame: pd.DataFrame, index: int, side: str) -> None:
    entry = float(frame.iloc[index].close)
    hist = frame.histogram.to_numpy(dtype=float)
    sign = 1.0 if side == "long" else -1.0
    for horizon in HORIZONS:
        end = index + horizon
        if end >= len(frame):
            record[f"return_{horizon}"] = np.nan
            record[f"mfe_{horizon}"] = np.nan
            record[f"mae_{horizon}"] = np.nan
            continue
        window = frame.iloc[index + 1 : end + 1]
        raw = float(frame.iloc[end].close / entry - 1)
        record[f"return_{horizon}"] = sign * raw
        if side == "long":
            record[f"mfe_{horizon}"] = float(window.high.max() / entry - 1)
            record[f"mae_{horizon}"] = float(1 - window.low.min() / entry)
        else:
            record[f"mfe_{horizon}"] = float(1 - window.low.min() / entry)
            record[f"mae_{horizon}"] = float(window.high.max() / entry - 1)
    next_two = hist[index + 1 : min(len(hist), index + 3)]
    if side == "long":
        record["fails_two_bars"] = bool(np.any(next_two < 0)) if len(next_two) else np.nan
        record["recross_two_bars"] = bool(np.any(next_two < 0)) if len(next_two) else np.nan
    else:
        record["fails_two_bars"] = bool(np.any(next_two > 0)) if len(next_two) else np.nan
        record["recross_two_bars"] = bool(np.any(next_two > 0)) if len(next_two) else np.nan


def extract_events(ticker: str, frame: pd.DataFrame) -> list[dict[str, object]]:
    hist = frame.histogram.to_numpy(dtype=float)
    events: list[dict[str, object]] = []

    def base(index: int, event: str, side: str) -> dict[str, object]:
        row = frame.iloc[index]
        record = {
            "ticker": ticker,
            "date": str(row.date),
            "event": event,
            "side": side,
            "index": index,
            "close": float(row.close),
            "histogram": float(hist[index]),
            "macd": float(row.adaptive_macd) if pd.notna(row.adaptive_macd) else np.nan,
            "signal": float(row.signal) if pd.notna(row.signal) else np.nan,
            "both_above_zero": bool(row.adaptive_macd > 0 and row.signal > 0)
            if pd.notna(row.adaptive_macd) and pd.notna(row.signal)
            else False,
        }
        add_outcomes(record, frame, index, side)
        return record

    for index in range(2, len(frame)):
        h0, h1, h2 = hist[index - 2], hist[index - 1], hist[index]
        if not np.all(np.isfinite([h0, h1, h2])):
            continue
        if h0 > 0 and h1 > h0 and 0 < h2 < h1:
            events.append(base(index, "first_dark_blue", "long"))
        if h0 > 0 and 0 < h1 <= h0 and h2 > h1:
            events.append(base(index, "reaccel_in_blue", "long"))
        if h0 < 0 and h1 < h0 and h2 < 0 and h2 > h1:
            events.append(base(index, "first_dark_red", "short"))
        if h0 < 0 and h1 < 0 and h1 >= h0 and h2 < h1:
            events.append(base(index, "reaccel_in_red", "short"))
        if 0 < h0 < h1 < h2 and not (index >= 3 and np.isfinite(hist[index - 3]) and hist[index - 3] > 0):
            events.append(base(index, "early_rising_blue", "long"))

    for index in range(1, len(frame)):
        prev, curr = hist[index - 1], hist[index]
        if not (np.isfinite(prev) and np.isfinite(curr)):
            continue
        if prev <= 0 < curr:
            events.append(base(index, "bullish_flip", "long"))
        if prev >= 0 > curr:
            events.append(base(index, "bearish_flip", "short"))
    return events


def attach_next_flip(events: pd.DataFrame) -> pd.DataFrame:
    """For failed color-shifts, locate the next zero-line flip in that direction."""

    output = events.copy()
    output["days_to_next_flip"] = np.nan
    output["flip_date"] = pd.NA
    output["held_until_flip"] = np.nan
    output["new_flip_return_5"] = np.nan
    for ticker in TICKERS:
        color = output[
            (output.ticker == ticker)
            & (output.event.isin(("reaccel_in_blue", "reaccel_in_red", "first_dark_blue", "first_dark_red")))
        ]
        flips = output[(output.ticker == ticker) & (output.event.isin(("bullish_flip", "bearish_flip")))]
        for loc, row in color.iterrows():
            wanted = "bullish_flip" if row.side == "long" else "bearish_flip"
            later = flips[(flips.event == wanted) & (flips["index"] > row["index"])]
            if later.empty:
                continue
            nxt = later.iloc[0]
            output.at[loc, "days_to_next_flip"] = int(nxt["index"] - row["index"])
            output.at[loc, "flip_date"] = nxt.date
            # Close-to-close from the color-shift bar to the later flip bar.
            output.at[loc, "held_until_flip"] = (
                (nxt.close / row.close - 1) if row.side == "long" else (1 - nxt.close / row.close)
            )
            output.at[loc, "new_flip_return_5"] = nxt.return_5
    return output


def summarize_event(sample: pd.DataFrame, horizon: int = MAIN_HORIZON) -> str:
    column = f"return_{horizon}"
    n, mean, median, hit = stats(sample[column])
    fail = sample["fails_two_bars"].mean() if "fails_two_bars" in sample else float("nan")
    mfe = sample[f"mfe_{horizon}"].mean()
    mae = sample[f"mae_{horizon}"].mean()
    return f"{n} | {pct(mean)} | {pct(median)} | {rate(hit)} | {rate(fail)} | {pct(mfe)} | {pct(mae)}"


def baseline_table(frames: dict[str, pd.DataFrame]) -> list[str]:
    lines = [
        "| Ticker | Horizon | All-session mean | Median | Positive |",
        "|---|---:|---:|---:|---:|",
    ]
    for ticker, frame in frames.items():
        close = frame.close.astype(float)
        for horizon in HORIZONS:
            ret = close.shift(-horizon) / close - 1
            n, mean, median, hit = stats(ret)
            lines.append(f"| {ticker} | {horizon} | {pct(mean)} | {pct(median)} | {rate(hit)} |")
    return lines


def main() -> None:
    frames: dict[str, pd.DataFrame] = {}
    records: list[dict[str, object]] = []
    coverage: dict[str, tuple[str, str, int]] = {}
    for ticker in TICKERS:
        raw = fetch_daily(ticker)
        frame = attach_macd(raw, ticker)
        frames[ticker] = frame
        valid = frame.dropna(subset=["histogram"])
        coverage[ticker] = (str(valid.date.min()), str(valid.date.max()), len(valid))
        records.extend(extract_events(ticker, frame))

    events = attach_next_flip(pd.DataFrame(records))
    events.to_csv(EVENTS_CSV, index=False)

    lines = [
        "# Daily SMH / QQQ adaptive-MACD histogram study",
        "",
        "## Scope and causal definitions",
        "",
        "Fisher adaptive-MACD on daily bars (Fisher 50; adaptive MACD 10/20/9; R² 20), the same configuration as the weekly/3-day histogram-shape pilot. Prices are Polygon adjusted daily OHLC. Entry is the event-day close; forward returns are close-to-close. Short events are signed so that a profitable short is positive.",
        "",
        "Histogram colors match the local charts: **light blue** = positive and rising; **dark blue** = positive and falling; **light red** = negative and becoming more negative; **dark red** = negative and rising toward zero.",
        "",
        "- **Light→dark in blue:** first falling positive bar after a rising positive bar. This is the color-transition itself: histogram still above zero, momentum just rolled over. A long here is an early bet that the blue run continues.",
        "- **Dark→light in blue:** already in a positive histogram for at least two bars, the last bar decelerated, then the current bar re-accelerates. This is buying the color-shift back to light blue, not a zero-line flip.",
        "- **Histogram flip red→blue:** first positive histogram bar after a non-positive bar.",
        "- **Early rising-blue:** third consecutive strictly increasing positive bar; one observation per impulse. This is the weekly/3-day checkpoint, included for comparison.",
        "- **Dark→light-red / flip blue→red:** the short-side analogues.",
        "- A color-shift **fails the 1-day clock** when the next session’s signed return is ≤ 0. Holding on means keeping that ticket; waiting for the crossover means scratching and taking the next zero-line flip as a new trade.",
        "",
        f"Sample after MACD warmup: SMH {coverage['SMH'][0]}–{coverage['SMH'][1]} ({coverage['SMH'][2]} sessions); QQQ {coverage['QQQ'][0]}–{coverage['QQQ'][1]} ({coverage['QQQ'][2]} sessions).",
        "",
        "## All-session baseline",
        "",
        *baseline_table(frames),
        "",
    ]

    for event_name, title in EVENT_TITLES.items():
        sample = events[events.event == event_name]
        lines.extend(
            [
                f"## {title}",
                "",
                f"Events: **{len(sample)}** (SMH {int((sample.ticker=='SMH').sum())}, QQQ {int((sample.ticker=='QQQ').sum())}). Primary window: **{MAIN_HORIZON} sessions**.",
                "",
                "| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for label, group in (
            ("Pooled", sample),
            ("SMH", sample[sample.ticker == "SMH"]),
            ("QQQ", sample[sample.ticker == "QQQ"]),
        ):
            lines.append(f"| {label} {MAIN_HORIZON}d | {summarize_event(group)} |")
        lines.extend(
            [
                "",
                "| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |",
                "|---|---:|---:|---:|",
            ]
        )
        for horizon in HORIZONS:
            col = f"return_{horizon}"
            pooled = sample[col]
            smh = sample.loc[sample.ticker == "SMH", col]
            qqq = sample.loc[sample.ticker == "QQQ", col]
            lines.append(
                f"| {horizon}d | {pct(pooled.mean())} / {rate(pooled.gt(0).mean())} | "
                f"{pct(smh.mean())} / {rate(smh.gt(0).mean())} | "
                f"{pct(qqq.mean())} / {rate(qqq.gt(0).mean())} |"
            )
        lines.append("")

    # 1-day clock
    lines.extend(["## One-session clock on color-shifts", ""])
    for event_name, title in (
        ("first_dark_blue", "Light→dark blue (longs at first fade)"),
        ("reaccel_in_blue", "Dark→light blue (longs)"),
        ("reaccel_in_red", "Dark→light-red (shorts)"),
    ):
        sample = events[events.event == event_name].dropna(subset=["return_1", "return_5"])
        losers = sample[sample.return_1 <= 0]
        winners = sample[sample.return_1 > 0]
        managed = sample.copy()
        managed["managed_5"] = np.where(managed.return_1 > 0, managed.return_5, managed.return_1)
        hold = sample.return_5
        lines.extend(
            [
                f"### {title}",
                "",
                f"- Events with 1d and 5d outcomes: **{len(sample)}**. 1d losers: **{len(losers)}** ({rate(len(losers)/len(sample) if len(sample) else float('nan'))}).",
                f"- 1d winners held 5d: mean {pct(winners.return_5.mean())}, hit {rate(winners.return_5.gt(0).mean())} (N={len(winners)}).",
                f"- 1d losers held 5d: mean {pct(losers.return_5.mean())}, hit {rate(losers.return_5.gt(0).mean())} (N={len(losers)}).",
                f"- 1d losers held 2d: mean {pct(losers.return_2.mean())}, still red {rate(losers.return_2.le(0).mean())}.",
                f"- Hold every color-shift 5d: mean {pct(hold.mean())}, hit {rate(hold.gt(0).mean())}.",
                f"- Scratch losers at day 1, hold winners 5d: mean {pct(managed['managed_5'].mean())}, hit {rate(managed['managed_5'].gt(0).mean())}.",
                "",
            ]
        )
        failed = losers.dropna(subset=["days_to_next_flip"])
        if len(failed):
            lines.extend(
                [
                    f"- After a 1d-failed color-shift, median sessions to the next zero-line flip: **{failed.days_to_next_flip.median():.0f}** (mean {failed.days_to_next_flip.mean():.1f}, N={len(failed)}).",
                    f"- If you **hold the dead color-shift until that flip**: mean {pct(failed.held_until_flip.mean())}, hit {rate(failed.held_until_flip.gt(0).mean())}.",
                    f"- If you **scratch and take the new flip for 5d**: mean {pct(failed.new_flip_return_5.mean())}, hit {rate(failed.new_flip_return_5.gt(0).mean())}.",
                    "",
                ]
            )

    # Direct comparison table
    lines.extend(
        [
            "## Head-to-head: color-shift vs flip vs early-blue",
            "",
            "Signed 1-day and 5-day close-to-close. Long events want price up; short events want price down.",
            "",
            "| Event | Side | N | 1d mean / hit | 5d mean / hit | 5d vs SMH/QQQ baseline | 1d losers → 5d if held |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for event_name, title in EVENT_TITLES.items():
        sample = events[events.event == event_name]
        losers = sample[sample.return_1 <= 0]
        side = "long" if event_name in {
            "first_dark_blue",
            "reaccel_in_blue",
            "bullish_flip",
            "early_rising_blue",
        } else "short"
        smh_base = frames["SMH"].close.astype(float).shift(-MAIN_HORIZON).div(frames["SMH"].close).sub(1).mean()
        qqq_base = frames["QQQ"].close.astype(float).shift(-MAIN_HORIZON).div(frames["QQQ"].close).sub(1).mean()
        smh_r = sample.loc[sample.ticker == "SMH", "return_5"].mean()
        qqq_r = sample.loc[sample.ticker == "QQQ", "return_5"].mean()
        excess = (
            f"SMH {pct(smh_r - smh_base) if pd.notna(smh_r) else '—'}; "
            f"QQQ {pct(qqq_r - qqq_base) if pd.notna(qqq_r) else '—'}"
        )
        lines.append(
            f"| {title} | {side} | {len(sample.dropna(subset=['return_1']))} | "
            f"{pct(sample.return_1.mean())} / {rate(sample.return_1.gt(0).mean())} | "
            f"{pct(sample.return_5.mean())} / {rate(sample.return_5.gt(0).mean())} | "
            f"{excess} | "
            f"{pct(losers.return_5.mean())} / {rate(losers.return_5.gt(0).mean())} |"
        )

    color_long = events[events.event == "reaccel_in_blue"].dropna(subset=["return_1", "return_5"])
    fade_long = events[events.event == "first_dark_blue"].dropna(subset=["return_1", "return_5"])
    flip_long = events[events.event == "bullish_flip"].dropna(subset=["return_1", "return_5"])
    early_long = events[events.event == "early_rising_blue"].dropna(subset=["return_1", "return_5"])
    color_short = events[events.event == "reaccel_in_red"].dropna(subset=["return_1", "return_5"])
    flip_short = events[events.event == "bearish_flip"].dropna(subset=["return_1", "return_5"])
    smh_flip = flip_long[flip_long.ticker == "SMH"]
    qqq_flip = flip_long[flip_long.ticker == "QQQ"]
    fade_losers = fade_long[fade_long.return_1 <= 0]
    color_losers = color_long[color_long.return_1 <= 0]

    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            f"- The best daily **long** on this sample is the **third rising light-blue bar**, not the color-shift: 5d {pct(early_long.return_5.mean())} / {rate(early_long.return_5.gt(0).mean())} hit (N={len(early_long)}).",
            f"- **Red→blue flips** are +EV on SMH ({pct(smh_flip.return_5.mean())} 5d, {rate(smh_flip.return_5.gt(0).mean())} hit) and flat-to-negative on QQQ ({pct(qqq_flip.return_5.mean())} 5d). Pooled 1d is {pct(flip_long.return_1.mean())} / {rate(flip_long.return_1.gt(0).mean())} hit.",
            f"- **Light→dark** (first fade, still above zero) 1d {pct(fade_long.return_1.mean())} / {rate(fade_long.return_1.gt(0).mean())} hit. **Dark→light re-acceleration** 1d {pct(color_long.return_1.mean())} / {rate(color_long.return_1.gt(0).mean())} hit. Both underperform a coin flip on day one.",
            f"- If a color-shift long is red after one session, holding does not salvage it: light→dark losers 5d {pct(fade_losers.return_5.mean())}; dark→light losers 5d {pct(color_losers.return_5.mean())}.",
            f"- **Do not short the daily blue→red flip** on these two names: signed 5d {pct(flip_short.return_5.mean())} (price usually keeps rising). Color-shift shorts are worse ({pct(color_short.return_5.mean())} 5d).",
            "- Size: color-transition = probe and 1-session clock, or skip. SMH red→blue or 3rd light-blue bar = full daily swing. QQQ daily flip is not a full-size long on this sample.",
            "",
            "## Limitations",
            "",
            "- Polygon plan only returns ~5 years of daily bars, so the sample is 2021-08-19 through 2026-08-18, not 2010.",
            "- Two liquid ETFs, not a market-wide universe. Events overlap across names on the same dates.",
            "- Close-to-close, no gap-at-open slippage, no option premium path. A 30–45 DTE option will not match these underlying percentages one-for-one.",
            "- Color-shift and early-rising-blue can fire on nearby bars of the same impulse; they are not mutually exclusive samples.",
            "- Quartile slope filters from the weekly/3-day pilot are omitted here because the hypothesis under test is event type plus a 1-day timeout, not slope.",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="daily-smh-qqq-histogram",
        study_name="Daily SMH / QQQ Histogram Events",
        version="1.0",
        generator="modules/analysis/scripts/analyze_daily_smh_qqq_histogram.py",
        files={"events": EVENTS_CSV, "report": REPORT},
        metrics=[{"label": "Events", "value": len(events)}],
    )
    print(f"Wrote {REPORT}")
    print(f"Wrote {EVENTS_CSV}")
    print(events.groupby(["ticker", "event"]).size())
    print(f"Published dashboard study {dashboard_output}")


if __name__ == "__main__":
    main()
