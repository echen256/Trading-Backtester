"""Event study for the embedded Deribit DVOL MACD line and BTC-USD returns.

The input file is expected to be a TradingView CSV export with a ``time``
column and the indicator's own ``MACD`` column.  It deliberately does not
recompute MACD: the study measures the line visible in that export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


THRESHOLD = 0.5
HORIZONS = (1, 3, 5, 10, 20, 30)
REGIMES = {
    "2022 bear-market window": ("2022-01-01", "2022-12-31"),
    "October 2025–present window": ("2025-10-01", None),
}
PRICE_VOL_REGIMES = {
    "2020–early-2021 bull window": ("2020-04-01", "2021-04-11"),
    "2023 early-bull window": ("2023-01-01", "2023-06-30"),
}


def fetch_btc(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Fetch UTC daily BTC-USD closes from Yahoo Finance's chart endpoint."""

    params = urlencode(
        {
            "period1": int((start - pd.Timedelta(days=2)).timestamp()),
            "period2": int((end + pd.Timedelta(days=2)).timestamp()),
            "interval": "1d",
            "events": "history",
        }
    )
    request = Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS endpoint
        result = json.load(response)["chart"]["result"][0]
    dates = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    close = pd.Series(result["indicators"]["quote"][0]["close"], index=dates, name="btc_close")
    return close[~close.index.duplicated()].dropna()


def confirmed_exit(macd: pd.Series, start: int) -> int | None:
    """First down-cross that is followed by five consecutive days below 0.5."""

    values = macd.to_numpy(dtype=float)
    for index in range(start + 1, len(values) - 4):
        if values[index - 1] >= THRESHOLD and np.all(values[index : index + 5] < THRESHOLD):
            return index
    return None


def percentage(value: float) -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.2f}%"


def summarize_returns(frame: pd.DataFrame, label: str) -> list[str]:
    lines = [f"### {label}", "", "| Horizon | N | Mean BTC return | Median | Win rate |", "|---:|---:|---:|---:|---:|"]
    for horizon in HORIZONS:
        returns = frame[f"return_{horizon}d"].dropna()
        lines.append(
            f"| {horizon} calendar days | {len(returns)} | {percentage(returns.mean())} | "
            f"{percentage(returns.median())} | {(returns.gt(0).mean() * 100):.1f}% |"
        )
    return lines


def regime_slice(frame: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    """Select observations by their signal/start date, inclusive."""

    result = frame.loc[frame.index >= pd.Timestamp(start)]
    return result if end is None else result.loc[result.index <= pd.Timestamp(end)]


def summarize_regime(events: pd.DataFrame, baseline: pd.DataFrame, label: str, start: str, end: str | None) -> list[str]:
    selected_events = regime_slice(events, start, end)
    selected_baseline = regime_slice(baseline, start, end)
    lines = [
        f"### {label}",
        "",
        f"- Independent 0.5-cross episodes: **{len(selected_events)}**",
        f"- Reached MACD ≥1.0: **{selected_events.reached_1.sum()} ({selected_events.reached_1.mean() * 100:.1f}%)**",
        f"- Reached MACD ≥2.0: **{selected_events.reached_2.sum()} ({selected_events.reached_2.mean() * 100:.1f}%)**",
        "",
        "| Horizon | Cross return | Win rate | Same-window all-day return | All-day win rate |",
        "|---:|---:|---:|---:|---:|",
    ]
    for horizon in HORIZONS:
        event_returns = selected_events[f"return_{horizon}d"].dropna()
        base_returns = selected_baseline[f"return_{horizon}d"].dropna()
        lines.append(
            f"| {horizon} calendar days | {percentage(event_returns.mean())} (N={len(event_returns)}) | "
            f"{event_returns.gt(0).mean() * 100:.1f}% | {percentage(base_returns.mean())} | "
            f"{base_returns.gt(0).mean() * 100:.1f}% |"
        )
    return lines


def make_price_vol_signal(btc: pd.Series) -> pd.DataFrame:
    """A no-look-ahead compression-to-expansion BTC breakout proxy.

    It is used before DVOL exists.  "Quiet" is a 20-day realised-volatility
    reading in the lower 35% of its trailing 252-day distribution.  Expansion
    is 5-day realised volatility at least 1.25x the 20-day reading, while the
    closing price makes a 20-day breakout.  The thresholds are deliberately
    simple descriptive cutoffs, not fitted to the forward returns.
    """

    returns = btc.pct_change()
    rv5 = returns.rolling(5).std() * np.sqrt(365)
    rv20 = returns.rolling(20).std() * np.sqrt(365)
    quiet_cutoff = rv20.rolling(252, min_periods=126).quantile(0.35)
    prior_high20 = btc.shift(1).rolling(20).max()
    signal = (rv20.le(quiet_cutoff) & rv5.ge(rv20 * 1.25) & btc.gt(prior_high20)).rename("signal")
    output = pd.DataFrame({"btc_close": btc, "rv5": rv5, "rv20": rv20, "quiet_cutoff": quiet_cutoff, "signal": signal})
    for horizon in HORIZONS:
        output[f"return_{horizon}d"] = btc.shift(-horizon).div(btc).sub(1)
    return output.dropna(subset=["btc_close"])


def summarize_price_vol_proxy(frame: pd.DataFrame) -> list[str]:
    lines = [
        "## Pre-DVOL check: price-confirmed realized-volatility expansion",
        "",
        "Deribit returns no DVOL observations before 2021-03-24. For the 2020 portion, this uses a BTC-only proxy: "
        "20-day realised volatility must be in the bottom 35% of its trailing 252-day distribution; 5-day realised volatility "
        "must then be at least 1.25× the 20-day reading; and the BTC close must break its prior 20-day high. "
        "Every input is known at that day's close.",
        "",
    ]
    for label, (start, end) in PRICE_VOL_REGIMES.items():
        window = regime_slice(frame, start, end)
        signals = window[window.signal]
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Price-confirmed compression-to-expansion signals: **{len(signals)}**",
                "",
                "| Horizon | Signal return | Signal win rate | Same-window all-day return | All-day win rate |",
                "|---:|---:|---:|---:|---:|",
            ]
        )
        for horizon in HORIZONS:
            signal_returns = signals[f"return_{horizon}d"].dropna()
            all_returns = window[f"return_{horizon}d"].dropna()
            lines.append(
                f"| {horizon} calendar days | {percentage(signal_returns.mean())} (N={len(signal_returns)}) | "
                f"{signal_returns.gt(0).mean() * 100:.1f}% | {percentage(all_returns.mean())} | "
                f"{all_returns.gt(0).mean() * 100:.1f}% |"
            )
        lines.append("")
    return lines


def principle_section() -> list[str]:
    return [
        "## General principle: price-led volatility expansion",
        "",
        "Volatility expansion is direction-neutral; it is an amplifier of the market's active price-discovery regime. "
        "It is constructive when a prolonged compression is resolved by accepted upside price discovery, and destructive when "
        "price is breaking down or repeatedly failing to hold a breakout.",
        "",
        "Treat a rising DVOL / positive DVOL-MACD as a continuation tailwind only when all three conditions are present:",
        "",
        "1. **Compression:** realised and/or implied volatility has been subdued relative to its own recent history.",
        "2. **Price leadership:** spot closes through a multi-week range high and holds it, rather than merely wicking above it.",
        "3. **Trend acceptance:** the higher-timeframe price trend remains constructive (for example, rising medium-term trend and higher highs).",
        "",
        "The volatility expansion then represents new participation and a repricing of upside risk. Without price leadership and trend "
        "acceptance, the same vol signal more often represents deleveraging, hedging demand, or a bear-market rally that can fail. "
        "Use the price breakout/hold as the entry trigger; use the volatility signal as a sizing and regime filter, not as a directional trigger by itself.",
        "",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dvol_csv", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "reports" / "dvol_macd_btc_event_study.md",
    )
    args = parser.parse_args()

    raw = pd.read_csv(args.dvol_csv)
    dvol = raw[["time", "MACD"]].copy()
    # TradingView exports this field as Unix *seconds* (e.g. 1616544000), not
    # ISO text or pandas' default nanoseconds.
    dvol["date"] = pd.to_datetime(dvol.pop("time"), unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    dvol["macd"] = pd.to_numeric(dvol.pop("MACD"), errors="coerce")
    dvol = dvol.dropna().drop_duplicates("date", keep="last").set_index("date").sort_index()

    # DVOL itself starts in March 2021, but the price/realised-vol proxy below
    # lets us examine the preceding 2020–21 BTC bull leg with the same source.
    btc_history = fetch_btc(pd.Timestamp("2018-01-01"), dvol.index.max())
    btc = btc_history.loc[btc_history.index >= dvol.index.min()]
    frame = dvol.join(btc, how="left").dropna(subset=["btc_close"])
    events: list[dict[str, object]] = []
    # Treat a brief move below 0.5 followed by an immediate re-cross as the
    # same breakout episode.  Only a five-session confirmed exit resets the
    # state and permits the next event.  This is the definition used in the
    # original threshold-persistence calculation.
    position = 1
    while position < len(frame):
        if not (frame.macd.iloc[position - 1] <= THRESHOLD < frame.macd.iloc[position]):
            position += 1
            continue
        date = frame.index[position]
        row = frame.iloc[position]
        exit_position = confirmed_exit(frame["macd"], position)
        end_position = exit_position if exit_position is not None else len(frame) - 1
        episode = frame.iloc[position : end_position + 1]
        event: dict[str, object] = {
            "date": date,
            "entry_macd": row.macd,
            "confirmed_exit": frame.index[exit_position] if exit_position is not None else pd.NaT,
            "max_macd_before_exit": episode.macd.max(),
            "reached_1": episode.macd.ge(1.0).any(),
            "reached_2": episode.macd.ge(2.0).any(),
        }
        for horizon in HORIZONS:
            if position + horizon < len(frame):
                event[f"return_{horizon}d"] = frame.btc_close.iloc[position + horizon] / row.btc_close - 1
            else:
                event[f"return_{horizon}d"] = np.nan
        events.append(event)
        # An event remains open until its confirmed exit; do not count an
        # intervening re-cross as a new independent signal.
        position = (exit_position + 5) if exit_position is not None else len(frame)
    event_frame = pd.DataFrame(events).set_index("date")

    # Same-date baseline, provided as context rather than as an independent test.
    baseline = pd.DataFrame(index=frame.index)
    for horizon in HORIZONS:
        baseline[f"return_{horizon}d"] = frame.btc_close.shift(-horizon).div(frame.btc_close).sub(1)

    completed = event_frame.confirmed_exit.notna()
    lines = [
        "# DVOL embedded-MACD 0.5 cross: BTCUSD event study",
        "",
        f"Source: `{args.dvol_csv}` (TradingView-exported `MACD` line) and Yahoo Finance daily `BTC-USD` closes.",
        f"Sample: {frame.index.min():%Y-%m-%d} to {frame.index.max():%Y-%m-%d}.",
        "",
        "## Signal definition",
        "",
        "An event is the first daily close where the exported MACD line moves from ≤0.5 to >0.5. "
        "An episode ends only at a down-cross whose current day and next four sessions all remain below 0.5. "
        "BTC returns are close-to-close from the event-day BTC close; they are calendar-day horizons because BTC trades every day.",
        "",
        "## Threshold persistence",
        "",
        f"- 0.5 upside-cross events: **{len(event_frame)}**",
        f"- Confirmed exits below 0.5 for five sessions: **{completed.sum()}**",
        f"- Reached MACD ≥1.0 before confirmed exit: **{event_frame.reached_1.sum()} ({event_frame.reached_1.mean() * 100:.1f}%)**",
        f"- Reached MACD ≥2.0 before confirmed exit: **{event_frame.reached_2.sum()} ({event_frame.reached_2.mean() * 100:.1f}%)**",
        "",
        *summarize_returns(event_frame, "BTCUSD returns after a 0.5 upside cross"),
        "",
        *summarize_returns(baseline, "BTCUSD all-day baseline (context only)"),
        "",
        "## Regime split",
        "",
        "Regimes are assigned by the 0.5-cross date. The all-day reference uses every BTC starting day in the same window; it is context, not an independent statistical test.",
        "",
        *summarize_regime(event_frame, baseline, "2022 bear-market window", *REGIMES["2022 bear-market window"]),
        "",
        *summarize_regime(event_frame, baseline, "October 2025–present window", *REGIMES["October 2025–present window"]),
        "",
        *principle_section(),
        *summarize_price_vol_proxy(make_price_vol_signal(btc_history)),
        "## Event-level detail",
        "",
        "| Cross date | Entry MACD | Confirmed exit | Peak MACD before exit | Hit ≥1 | Hit ≥2 | BTC 5d | BTC 10d | BTC 20d |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for date, row in event_frame.iterrows():
        exit_date = "Open" if pd.isna(row.confirmed_exit) else f"{row.confirmed_exit:%Y-%m-%d}"
        lines.append(
            f"| {date:%Y-%m-%d} | {row.entry_macd:.3f} | {exit_date} | {row.max_macd_before_exit:.3f} | "
            f"{'Yes' if row.reached_1 else 'No'} | {'Yes' if row.reached_2 else 'No'} | "
            f"{percentage(row.return_5d)} | {percentage(row.return_10d)} | {percentage(row.return_20d)} |"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
