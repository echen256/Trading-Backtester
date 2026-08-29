"""Construct a realised-volatility SEMI-VOL index and test SMH price/vol regimes.

SEMI-VOL is a transparent synthetic index: the 20-session annualised standard
deviation of SMH log returns, expressed in volatility points.  It is not an
options-implied-volatility product, so its results should be interpreted as a
price-derived analogue to DVOL rather than a substitute for semiconductor
option implied volatility.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from trading_analysis.dashboard import StudyArtifactWriter


START = pd.Timestamp("2010-01-01")
END = pd.Timestamp("2026-08-16")
THRESHOLD = 0.5
HORIZONS = (1, 3, 5, 10, 20, 30)
REGIMES = {
    "All available history": ("2010-01-01", None),
    "2020–2021 semiconductor bull": ("2020-04-01", "2021-11-10"),
    "2022 bear": ("2022-01-01", "2022-12-31"),
    "2023 early bull": ("2023-01-01", "2023-06-30"),
    "October 2025–present": ("2025-10-01", None),
}


def fetch_adjusted_close(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    params = urlencode(
        {
            "period1": int(start.timestamp()),
            "period2": int((end + pd.Timedelta(days=2)).timestamp()),
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
    dates = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    closes = adjusted if adjusted is not None else result["indicators"]["quote"][0]["close"]
    series = pd.Series(closes, index=dates, name="smh_close", dtype=float)
    return series[~series.index.duplicated()].dropna()


def confirmed_exit(macd: pd.Series, start: int) -> int | None:
    values = macd.to_numpy(dtype=float)
    for index in range(start + 1, len(values) - 4):
        if values[index - 1] >= THRESHOLD and np.all(values[index : index + 5] < THRESHOLD):
            return index
    return None


def pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.2f}%"


def rate(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:.1f}%"


def build_frame(close: pd.Series) -> pd.DataFrame:
    log_returns = np.log(close).diff()
    semi_vol = log_returns.rolling(20).std() * np.sqrt(252) * 100
    # TradingView's conventional MACD line, applied to the synthetic index.
    macd = semi_vol.ewm(span=12, adjust=False).mean() - semi_vol.ewm(span=26, adjust=False).mean()
    prior_high20 = close.shift(1).rolling(20).max()
    quiet_cutoff = semi_vol.rolling(252, min_periods=126).quantile(0.35)
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    frame = pd.DataFrame(
        {
            "smh_close": close,
            "semi_vol": semi_vol,
            "macd": macd,
            "quiet_cutoff": quiet_cutoff,
            # Compression must precede, rather than coexist with, the
            # expansion. Five sessions is known at the entry close.
            "quiet": semi_vol.shift(5).le(quiet_cutoff.shift(5)),
            "price_breakout": close.gt(prior_high20),
            "trend_ok": close.gt(sma50) & sma50.gt(sma200),
        }
    )
    for horizon in HORIZONS:
        frame[f"return_{horizon}d"] = close.shift(-horizon).div(close).sub(1)
    return frame.dropna(subset=["semi_vol", "macd"])


def build_events(frame: pd.DataFrame) -> pd.DataFrame:
    events: list[dict[str, object]] = []
    position = 1
    while position < len(frame):
        if not (frame.macd.iloc[position - 1] <= THRESHOLD < frame.macd.iloc[position]):
            position += 1
            continue
        row = frame.iloc[position]
        exit_position = confirmed_exit(frame.macd, position)
        end_position = exit_position if exit_position is not None else len(frame) - 1
        episode = frame.iloc[position : end_position + 1]
        event: dict[str, object] = {
            "date": frame.index[position],
            "entry_macd": row.macd,
            "semi_vol": row.semi_vol,
            "quiet": row.quiet,
            "price_breakout": row.price_breakout,
            "trend_ok": row.trend_ok,
            "confirmed_exit": frame.index[exit_position] if exit_position is not None else pd.NaT,
            "max_macd": episode.macd.max(),
        }
        for horizon in HORIZONS:
            event[f"return_{horizon}d"] = row[f"return_{horizon}d"]
        events.append(event)
        position = exit_position + 5 if exit_position is not None else len(frame)
    output = pd.DataFrame(events).set_index("date")
    output["constructive"] = output.quiet & output.price_breakout & output.trend_ok
    return output


def window(frame: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    result = frame.loc[frame.index >= pd.Timestamp(start)]
    return result if end is None else result.loc[result.index <= pd.Timestamp(end)]


def result_table(events: pd.DataFrame, baseline: pd.DataFrame, label: str, start: str, end: str | None) -> list[str]:
    selected = window(events, start, end)
    base = window(baseline, start, end)
    constructive = selected[selected.constructive]
    lines = [
        f"### {label}",
        "",
        f"- All SEMI-VOL MACD >0.5 episodes: **{len(selected)}**",
        f"- Constructive episodes (quiet five sessions earlier + 20-day price breakout + price > 50d > 200d): **{len(constructive)}**",
        "",
        "| Horizon | All MACD crosses | Constructive cross | Same-window all days |",
        "|---:|---:|---:|---:|",
    ]
    for horizon in HORIZONS:
        all_returns = selected[f"return_{horizon}d"].dropna()
        good_returns = constructive[f"return_{horizon}d"].dropna()
        base_returns = base[f"return_{horizon}d"].dropna()
        lines.append(
            f"| {horizon} sessions | {pct(all_returns.mean())} / {rate(all_returns.gt(0).mean())} (N={len(all_returns)}) | "
            f"{pct(good_returns.mean())} / {rate(good_returns.gt(0).mean())} (N={len(good_returns)}) | "
            f"{pct(base_returns.mean())} / {rate(base_returns.gt(0).mean())} |"
        )
    return lines


def main() -> None:
    close = fetch_adjusted_close("SMH", START, END)
    frame = build_frame(close)
    events = build_events(frame)
    output = Path(__file__).resolve().parents[3] / "reports" / "smh_semivol_event_study.md"
    lines = [
        "# SMH SEMI-VOL: price-led volatility-expansion event study",
        "",
        "Source: Yahoo Finance adjusted daily SMH closes. Sample: "
        f"{frame.index.min():%Y-%m-%d} to {frame.index.max():%Y-%m-%d}.",
        "",
        "## Construction and signal",
        "",
        "**SEMI-VOL** = 20-session annualized standard deviation of SMH log returns, in volatility points. "
        "Its MACD line is the conventional 12/26 EMA difference. An episode begins when that MACD crosses from ≤0.5 to >0.5, "
        "and ends only on a down-cross that remains below 0.5 for five sessions.",
        "",
        "A **constructive** cross additionally requires: SEMI-VOL was in the lower 35% of its trailing 252-session distribution five sessions earlier, "
        "an SMH close above the prior 20-session high, and SMH > 50-day average > 200-day average. These are all known at the close; "
        "thresholds are descriptive and were not fitted to outcomes.",
        "",
        "The table shows mean return / fraction positive. Small-N subgroup results are descriptive, not proof of a standalone trading rule.",
        "",
    ]
    for label, (start, end) in REGIMES.items():
        lines.extend(result_table(events, frame, label, start, end))
        lines.append("")
    lines.extend(
        [
            "## Overall event detail",
            "",
            "| Date | SEMI-VOL | MACD at cross | Constructive | Peak MACD | SMH 5d | SMH 10d | SMH 20d |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for date, row in events.iterrows():
        lines.append(
            f"| {date:%Y-%m-%d} | {row.semi_vol:.1f} | {row.entry_macd:.2f} | {'Yes' if row.constructive else 'No'} | "
            f"{row.max_macd:.2f} | {pct(row.return_5d)} | {pct(row.return_10d)} | {pct(row.return_20d)} |"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="smh-semivol",
        study_name="SMH SEMI-VOL Event Study",
        version="1.0",
        generator="modules/analysis/scripts/analyze_smh_semivol.py",
        files={"report": output},
        metrics=[{"label": "Events", "value": len(events)}],
    )
    print("\n".join(lines[:70]))
    print(f"\nWrote {output}")
    print(f"Published dashboard study {dashboard_output}")


if __name__ == "__main__":
    main()
