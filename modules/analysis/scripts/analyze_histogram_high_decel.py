"""Does buying a high, decelerating histogram have negative EV over a few bars?

Event (causal): first dark-blue bar — histogram still > 0, just rolled over from
a local peak. 'At the highs' is the mature/extreme MACD-extension regime used
by the levered manager (>=75% of the last completed MACD peak), plus a
trailing-52-bar histogram-high filter as a robustness check.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_macd_histogram_shape import choose_longest_runs


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = REPO_ROOT / "modules" / "analysis" / "strategies" / "runs"
DAILY_EVENTS = REPO_ROOT / "reports" / "daily_smh_qqq_histogram_events.csv"
OUT_JSON = REPO_ROOT / "reports" / "histogram_high_decel_summary.json"
SOURCES = {
    "Weekly": (RUN_ROOT / "scanner-weekly-fixed-core" / "runs", (1, 2, 4), 4),
    "3-day": (RUN_ROOT / "scanner-3d-fixed-core" / "runs", (1, 2, 3, 5), 5),
}


def regime(extension: float | None) -> str:
    if extension is None or not np.isfinite(extension):
        return "fresh"
    if extension >= 1.0:
        return "extreme"
    if extension < 0.5:
        return "fresh"
    if extension < 0.75:
        return "developed"
    return "mature"


def summarize(series: pd.Series) -> dict[str, float | int]:
    clean = series.dropna().astype(float)
    if clean.empty:
        return {"n": 0, "mean": float("nan"), "median": float("nan"), "hit": float("nan")}
    return {
        "n": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "hit": float(clean.gt(0).mean()),
    }


def clustered_mean_ci(
    frame: pd.DataFrame, column: str, repetitions: int = 1500, seed: int = 20260828
) -> tuple[float, float, float]:
    clean = frame.dropna(subset=[column]).copy()
    if clean.empty:
        return float("nan"), float("nan"), float("nan")
    observed = float(clean[column].mean())
    tickers = clean.ticker.unique()
    if len(tickers) < 2:
        return observed, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(repetitions):
        selected = rng.choice(tickers, size=len(tickers), replace=True)
        pieces = [clean[clean.ticker.eq(ticker)] for ticker in selected]
        sample = pd.concat(pieces, ignore_index=True)
        samples.append(float(sample[column].mean()))
    lower, upper = np.quantile(samples, [0.025, 0.975])
    return observed, float(lower), float(upper)


def extract(label: str, ticker: str, payload: dict, horizons: tuple[int, ...]) -> tuple[list[dict], dict]:
    frame = pd.DataFrame(payload["bars"])
    needed = {"time", "open", "high", "low", "close", "histogram", "adaptive_macd", "signal"}
    if not needed.issubset(frame.columns):
        return [], {}
    for column in ("open", "high", "low", "close", "histogram", "adaptive_macd", "signal", "momentum_extension"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    hist = frame.histogram.to_numpy(dtype=float)
    macd = frame.adaptive_macd.to_numpy(dtype=float)
    close = frame.close.to_numpy(dtype=float)
    extension = (
        frame.momentum_extension.to_numpy(dtype=float)
        if "momentum_extension" in frame.columns
        else np.full(len(frame), np.nan)
    )
    valid = np.isfinite(hist) & np.isfinite(close)
    records: list[dict] = []
    for index in range(2, len(frame) - 1):
        if not (valid[index] and valid[index - 1] and valid[index - 2]):
            continue
        if not (hist[index] > 0 and hist[index - 1] > 0):
            continue
        if not (hist[index] < hist[index - 1] and hist[index - 1] >= hist[index - 2]):
            continue
        lookback = hist[max(0, index - 52) : index]
        lookback = lookback[np.isfinite(lookback)]
        hist_pct = float(np.mean(lookback <= hist[index - 1])) if len(lookback) >= 20 else float("nan")
        window20 = hist[max(0, index - 20) : index]
        window20 = window20[np.isfinite(window20)]
        at_20bar_high = bool(len(window20) >= 10 and hist[index - 1] >= np.nanmax(window20) - 1e-12)
        ext = float(extension[index]) if np.isfinite(extension[index]) else float("nan")
        record: dict = {
            "timeframe": label,
            "ticker": ticker,
            "date": str(frame.iloc[index].time),
            "histogram": float(hist[index]),
            "hist_peak": float(hist[index - 1]),
            "hist_pct": hist_pct,
            "at_20bar_high": at_20bar_high,
            "extension": ext,
            "regime": regime(None if not np.isfinite(ext) else ext),
            "macd": float(macd[index]) if np.isfinite(macd[index]) else float("nan"),
            "high_hist": bool(np.isfinite(hist_pct) and hist_pct >= 0.75),
        }
        entry = float(close[index])
        for horizon in horizons:
            end = index + horizon
            if end >= len(frame) or not np.isfinite(close[end]):
                record[f"return_{horizon}"] = np.nan
                continue
            record[f"return_{horizon}"] = float(close[end] / entry - 1.0)
        records.append(record)

    baselines: dict[str, dict[str, float | int]] = {}
    for horizon in horizons:
        rets = []
        for index in range(len(frame) - horizon):
            if not (np.isfinite(close[index]) and np.isfinite(close[index + horizon]) and valid[index]):
                continue
            rets.append(close[index + horizon] / close[index] - 1.0)
        baselines[str(horizon)] = summarize(pd.Series(rets))
    return records, baselines


def pack_ci(frame: pd.DataFrame, column: str) -> dict:
    mean, lo, hi = clustered_mean_ci(frame, column)
    return {"mean": mean, "lo": lo, "hi": hi, "excludes_zero": bool(np.isfinite(lo) and np.isfinite(hi) and (hi < 0 or lo > 0))}


def slice_stats(frame: pd.DataFrame, horizons: tuple[int, ...], ci_horizon: int | None = None) -> dict:
    out: dict = {"n": int(len(frame))}
    for horizon in horizons:
        col = f"return_{horizon}"
        stats = summarize(frame[col]) if col in frame.columns else {"n": 0, "mean": float("nan"), "median": float("nan"), "hit": float("nan")}
        out[str(horizon)] = stats
        if ci_horizon is not None and horizon == ci_horizon:
            out[str(horizon)]["ci"] = pack_ci(frame, col)
            excess_col = f"excess_{horizon}"
            if excess_col in frame.columns:
                out[str(horizon)]["excess"] = {**summarize(frame[excess_col]), "ci": pack_ci(frame, excess_col)}
    return out


def main() -> None:
    payload: dict = {"sources": {}, "daily": {}}
    for label, (root, horizons, primary) in SOURCES.items():
        runs = choose_longest_runs(root)
        records: list[dict] = []
        ticker_baselines: list[dict] = []
        for ticker, run in sorted(runs.items()):
            events, baselines = extract(label, ticker, run, horizons)
            records.extend(events)
            ticker_baselines.append({"ticker": ticker, **{f"h{h}": baselines[str(h)]["mean"] for h in horizons}})
        events = pd.DataFrame(records)
        baseline_means = {str(h): float(np.nanmean([row[f"h{h}"] for row in ticker_baselines])) for h in horizons}
        base_by_ticker = {row["ticker"]: row for row in ticker_baselines}

        def add_excess(frame: pd.DataFrame) -> pd.DataFrame:
            out = frame.copy()
            for horizon in horizons:
                out[f"excess_{horizon}"] = [
                    (ret - base_by_ticker[ticker][f"h{horizon}"])
                    if pd.notna(ret) and ticker in base_by_ticker
                    else np.nan
                    for ret, ticker in zip(out[f"return_{horizon}"], out.ticker)
                ]
            return out

        events = add_excess(events)
        print(f"loaded {label}: {len(runs)} names, {len(events)} first-fade events", flush=True)
        mature = events[events.regime.isin(["mature", "extreme"])]
        hist_high = events[events.high_hist]
        peak20 = events[events.at_20bar_high]
        both = events[events.regime.isin(["mature", "extreme"]) & events.high_hist]

        source = {
            "universe": len(runs),
            "primary": primary,
            "horizons": list(horizons),
            "baseline": {h: baseline_means[str(h)] for h in horizons},
            "all_first_fade": slice_stats(events, horizons, primary),
            "mature_extreme": slice_stats(mature, horizons, primary),
            "hist_pct75": slice_stats(hist_high, horizons, primary),
            "hist_20bar_high": slice_stats(peak20, horizons, primary),
            "mature_and_hist_high": slice_stats(both, horizons, primary),
            "by_regime": {
                key: slice_stats(events[events.regime.eq(key)], horizons)
                for key in ("fresh", "developed", "mature", "extreme")
            },
        }
        payload["sources"][label] = source
        print(f"done {label}: {len(events)} first-fade events", flush=True)

    daily = pd.read_csv(DAILY_EVENTS)
    fades = daily[daily.event.eq("first_dark_blue")].copy()
    fades["hist_q"] = pd.qcut(fades.histogram.rank(method="first"), 4, labels=["Q1 low", "Q2", "Q3", "Q4 high"])
    daily_out: dict = {"baseline_5": {"SMH": 0.0072, "QQQ": 0.0032}, "all": {}, "by_quartile": {}}
    for horizon in (1, 2, 3, 5, 10):
        col = f"return_{horizon}"
        daily_out["all"][str(horizon)] = summarize(fades[col])
    for quartile in ("Q1 low", "Q2", "Q3", "Q4 high"):
        group = fades[fades.hist_q.eq(quartile)]
        daily_out["by_quartile"][quartile] = {
            "n": int(len(group)),
            **{str(h): summarize(group[f"return_{h}"]) for h in (1, 2, 3, 5, 10)},
        }
        daily_out["by_quartile"][quartile]["by_ticker"] = {
            ticker: {str(h): summarize(group.loc[group.ticker.eq(ticker), f"return_{h}"]) for h in (1, 5)}
            for ticker in ("SMH", "QQQ")
        }
    payload["daily"] = daily_out
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
