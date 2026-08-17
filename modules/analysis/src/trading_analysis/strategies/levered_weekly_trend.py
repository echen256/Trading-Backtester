"""Weekly adaptive-MACD position management for externally selected long entries.

This module intentionally does not choose securities or generate initial entry
alpha.  Callers supply the entry dates; the state machine then records every
exposure decision, reconstructs closed trades, and produces an analysis-ready
JSON/HTML artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots


@dataclass(frozen=True, slots=True)
class LeveredTrendConfig:
    """Coarse, deliberately non-optimized first-pass management parameters."""

    fisher_length: int = 50
    macd_fast: int = 10
    macd_slow: int = 20
    macd_signal: int = 9
    macd_r2_period: int = 20
    atr_period: int = 14
    rsi_period: int = 14
    core_exposure: float = 1.0
    max_exposure: float = 2.0
    pyramid_increment: float = 0.25
    pyramid_atr_multiple: float = 1.0
    emergency_stop_atr_multiple: float = 3.5
    extreme_releverage_cap: float = 1.25
    allow_pyramiding: bool = True
    allow_delevering: bool = True
    allow_relevering: bool = True
    enable_emergency_exit: bool = True
    enable_structure_exit: bool = True
    fixed_hold_bars: int | None = None
    fresh_deceleration_bars: int = 3
    developed_deceleration_bars: int = 2
    mature_deceleration_bars: int = 1
    extreme_deceleration_bars: int = 1


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    time: str
    index: int
    action: str
    target_exposure: float
    price: float
    regime: str
    momentum_extension: float | None
    reason: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    average_exposure: float
    bars_held: int
    pnl_pct: float
    exit_reason: str


@dataclass(slots=True)
class StrategyRun:
    schema_version: str
    strategy: str
    ticker: str
    timeframe_days: int
    config: dict[str, object]
    bars: list[dict[str, object]]
    decisions: list[StrategyDecision]
    closed_trades: list[ClosedTrade]
    statistics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy": self.strategy,
            "ticker": self.ticker,
            "timeframe_days": self.timeframe_days,
            "config": self.config,
            "bars": self.bars,
            "decisions": [asdict(item) for item in self.decisions],
            "closed_trades": [asdict(item) for item in self.closed_trades],
            "statistics": self.statistics,
        }


def _parse_time(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ValueError("OHLC row timestamps must be ISO strings or datetimes")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_ohlcv_csv(path: Path) -> list[dict[str, object]]:
    """Load normalized OHLCV CSV input produced by the existing data pipeline."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path} must contain timestamp, open, high, low, close columns")
        rows = [
            {
                "timestamp": _parse_time(row["timestamp"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if row.get("volume") else None,
            }
            for row in reader
            if row.get("timestamp")
        ]
    return sorted(rows, key=lambda item: item["timestamp"])


def aggregate_bars(rows: Iterable[dict[str, object]], *, timeframe_days: int = 7) -> list[dict[str, object]]:
    """Aggregate daily bars to 7D (Monday-anchored) or fixed 3-calendar-day bars."""
    if timeframe_days not in {3, 7}:
        raise ValueError("timeframe_days must be 3 or 7")
    buckets: dict[date, list[dict[str, object]]] = {}
    for raw in rows:
        timestamp = _parse_time(raw["timestamp"])
        day = timestamp.date()
        bucket = day.fromordinal(day.toordinal() - day.weekday()) if timeframe_days == 7 else day.fromordinal(
            (day.toordinal() // timeframe_days) * timeframe_days
        )
        buckets.setdefault(bucket, []).append({**raw, "timestamp": timestamp})
    output: list[dict[str, object]] = []
    for bucket in sorted(buckets):
        group = sorted(buckets[bucket], key=lambda item: item["timestamp"])
        output.append(
            {
                "period_start": bucket.isoformat(),
                "timestamp": group[-1]["timestamp"],
                "open": float(group[0]["open"]),
                "high": max(float(item["high"]) for item in group),
                "low": min(float(item["low"]) for item in group),
                "close": float(group[-1]["close"]),
                "volume": sum(float(item.get("volume") or 0.0) for item in group),
            }
        )
    return output


def _fisher(values: list[float], length: int) -> list[float]:
    previous_smooth = previous_fisher = 0.0
    result: list[float] = []
    for index, value in enumerate(values):
        window = values[max(0, index - length + 1) : index + 1]
        high, low = max(window), min(window)
        normalized = 0.0 if high == low else 2.0 * ((value - low) / (high - low) - 0.5)
        smooth = max(-0.999, min(0.999, 0.33 * normalized + 0.67 * previous_smooth))
        transformed = 0.5 * math.log((1 + smooth) / (1 - smooth)) + 0.5 * previous_fisher
        result.append(transformed)
        previous_smooth, previous_fisher = smooth, transformed
    return result


def _ema(values: list[float | None], period: int) -> list[float | None]:
    alpha = 2.0 / (period + 1.0)
    previous: float | None = None
    output: list[float | None] = []
    for value in values:
        if value is None:
            output.append(None)
            continue
        previous = value if previous is None else value * alpha + previous * (1 - alpha)
        output.append(previous)
    return output


def _adaptive_macd(values: list[float], config: LeveredTrendConfig) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_alpha, slow_alpha = 2.0 / (config.macd_fast + 1), 2.0 / (config.macd_slow + 1)
    macd: list[float | None] = []
    prior_one = prior_two = 0.0
    for index, value in enumerate(values):
        if index < config.macd_r2_period - 1:
            macd.append(None)
            prior_two, prior_one = prior_one, 0.0
            continue
        sample = values[index - config.macd_r2_period + 1 : index + 1]
        x_values = list(range(config.macd_r2_period))
        x_mean, y_mean = sum(x_values) / len(x_values), sum(sample) / len(sample)
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, sample))
        x_var = sum((x - x_mean) ** 2 for x in x_values)
        y_var = sum((y - y_mean) ** 2 for y in sample)
        correlation = 0.0 if x_var == 0 or y_var == 0 else numerator / math.sqrt(x_var * y_var)
        r2 = 0.5 * correlation**2 + 0.5
        k = r2 * ((1 - fast_alpha) * (1 - slow_alpha)) + (1 - r2) * ((1 - fast_alpha) / (1 - slow_alpha))
        previous_value = values[index - 1] if index else 0.0
        current = ((value - previous_value) * (fast_alpha - slow_alpha)) + ((-slow_alpha - fast_alpha + 2) * prior_one) - k * prior_two
        macd.append(current)
        prior_two, prior_one = prior_one, current
    signal = _ema(macd, config.macd_signal)
    histogram = [value - average if value is not None and average is not None else None for value, average in zip(macd, signal)]
    return macd, signal, histogram


def _wilder_rsi(closes: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return output
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    gain, loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    output[period] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    for index in range(period + 1, len(closes)):
        gain = (gain * (period - 1) + gains[index - 1]) / period
        loss = (loss * (period - 1) + losses[index - 1]) / period
        output[index] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return output


def _wilder_atr(rows: list[dict[str, object]], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(rows)
    if len(rows) <= period:
        return output
    ranges = [float(rows[0]["high"]) - float(rows[0]["low"])]
    for index in range(1, len(rows)):
        high, low, prior_close = float(rows[index]["high"]), float(rows[index]["low"]), float(rows[index - 1]["close"])
        ranges.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    atr = sum(ranges[1 : period + 1]) / period
    output[period] = atr
    for index in range(period + 1, len(rows)):
        atr = (atr * (period - 1) + ranges[index]) / period
        output[index] = atr
    return output


def _prior_major_peaks(macd: list[float | None], histogram: list[float | None]) -> list[float | None]:
    completed_peak: float | None = None
    current_peak: float | None = None
    output: list[float | None] = []
    previous_histogram: float | None = None
    for value, hist in zip(macd, histogram):
        output.append(completed_peak)
        if value is not None and value > 0:
            current_peak = max(current_peak or value, value)
        if previous_histogram is not None and hist is not None and previous_histogram >= 0 > hist and current_peak is not None:
            completed_peak, current_peak = current_peak, None
        previous_histogram = hist
    return output


def build_weekly_features(rows: list[dict[str, object]], config: LeveredTrendConfig | None = None) -> list[dict[str, object]]:
    """Expose the exact feature contract handed to strategy and reporting layers."""
    cfg = config or LeveredTrendConfig()
    closes = [float(item["close"]) for item in rows]
    macd, signal, histogram = _adaptive_macd(_fisher(closes, cfg.fisher_length), cfg)
    rsi, atr = _wilder_rsi(closes, cfg.rsi_period), _wilder_atr(rows, cfg.atr_period)
    peaks = _prior_major_peaks(macd, histogram)
    features: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        peak, value = peaks[index], macd[index]
        extension = (value / peak) if peak and peak > 0 and value is not None and value > 0 else None
        features.append(
            {
                "time": _parse_time(row["timestamp"]).date().isoformat(),
                "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]),
                "adaptive_macd": value, "signal": signal[index], "histogram": histogram[index], "rsi_14": rsi[index], "atr_14": atr[index],
                "prior_major_macd_peak": peak, "momentum_extension": extension,
            }
        )
    return features


def _regime(extension: float | None, extreme_seen: bool) -> str:
    if extreme_seen or (extension is not None and extension >= 1.0):
        return "extreme"
    if extension is None or extension < 0.5:
        return "fresh"
    if extension < 0.75:
        return "developed"
    return "mature"


def _regime_max_exposure(regime: str, config: LeveredTrendConfig, extreme_seen: bool) -> float:
    if regime == "extreme" or extreme_seen:
        return min(config.extreme_releverage_cap, config.max_exposure)
    if regime == "mature":
        return min(1.5, config.max_exposure)
    return config.max_exposure


def _deceleration_threshold(regime: str, config: LeveredTrendConfig) -> int:
    return {
        "fresh": config.fresh_deceleration_bars,
        "developed": config.developed_deceleration_bars,
        "mature": config.mature_deceleration_bars,
        "extreme": config.extreme_deceleration_bars,
    }[regime]


def _confirmed_lower_high_break(rows: list[dict[str, object]]) -> list[bool]:
    """Causal lower-high + intervening-low break; no future bars are consumed."""
    output = [False] * len(rows)
    major_high: tuple[int, float] | None = None
    lower_high_low: float | None = None
    for index in range(2, len(rows)):
        pivot = index - 1
        if float(rows[pivot]["high"]) > float(rows[pivot - 1]["high"]) and float(rows[pivot]["high"]) > float(rows[index]["high"]):
            if major_high is not None and float(rows[pivot]["high"]) < major_high[1]:
                intervening = [float(item["low"]) for item in rows[major_high[0] + 1 : pivot + 1]]
                lower_high_low = min(intervening) if intervening else None
            elif major_high is None or float(rows[pivot]["high"]) >= major_high[1]:
                major_high = (pivot, float(rows[pivot]["high"]))
                lower_high_low = None
        if lower_high_low is not None and float(rows[index]["close"]) < lower_high_low:
            output[index] = True
    return output


def run_levered_weekly_trend(
    ticker: str,
    daily_rows: list[dict[str, object]],
    entry_dates: Iterable[date | str],
    *,
    timeframe_days: int = 7,
    config: LeveredTrendConfig | None = None,
) -> StrategyRun:
    """Run the position manager against supplied entries; no selection logic is inferred."""
    cfg = config or LeveredTrendConfig()
    rows = aggregate_bars(daily_rows, timeframe_days=timeframe_days)
    features = build_weekly_features(rows, cfg)
    entry_set = {item if isinstance(item, date) else date.fromisoformat(item) for item in entry_dates}
    pending_entries = set(entry_set)
    structure_break = _confirmed_lower_high_break(rows)
    decisions: list[StrategyDecision] = []
    trades: list[ClosedTrade] = []
    exposures, equities = [], []
    exposure = 0.0
    entry_price = last_add_price = None
    entry_index = None
    trade_start_equity = None
    exposure_samples: list[float] = []
    extreme_seen = deceleration_bars = 0
    equity = peak_equity = 1.0

    def decide(index: int, action: str, target: float, reason: str, regime: str, feature: dict[str, object]) -> None:
        decisions.append(StrategyDecision(
            time=str(feature["time"]), index=index, action=action, target_exposure=round(target, 4), price=float(feature["close"]),
            regime=regime, momentum_extension=_float_or_none(feature["momentum_extension"]), reason=reason,
            metadata={"adaptive_macd": feature["adaptive_macd"], "histogram": feature["histogram"], "atr_14": feature["atr_14"]},
        ))

    for index, feature in enumerate(features):
        close = float(feature["close"])
        current_day = date.fromisoformat(str(feature["time"]))
        period_start = date.fromisoformat(str(rows[index]["period_start"]))
        prior = features[index - 1] if index else None
        if index:
            previous_close = float(prior["close"])
            equity *= 1.0 + exposure * ((close / previous_close) - 1.0)
        peak_equity = max(peak_equity, equity)

        # A broker entry can fall on a weekend or holiday.  Execute it at the
        # close of the first completed strategy bar available after that date.
        eligible_entries = sorted(item for item in pending_entries if item <= current_day)
        if exposure == 0.0 and eligible_entries:
            exposure = cfg.core_exposure
            entry_price = last_add_price = close
            entry_index, exposure_samples, extreme_seen, deceleration_bars = index, [], False, 0
            trade_start_equity = equity
            pending_entries.difference_update(eligible_entries)
            decide(
                index,
                "ENTER",
                exposure,
                "externally supplied selection/entry (executed at enclosing bar close)",
                "fresh",
                feature,
            )
        elif exposure > 0.0 and entry_price is not None:
            # One manager run represents one underlying position at a time.
            # Selection events received while it is already open are treated
            # as duplicates of that thesis, not queued stale re-entries.
            pending_entries.difference_update(eligible_entries)
            extension = _float_or_none(feature["momentum_extension"])
            if extension is not None and extension >= 1.0:
                extreme_seen = True
            regime = _regime(extension, extreme_seen)
            atr = _float_or_none(feature["atr_14"])
            histogram, macd, signal = (
                _float_or_none(feature["histogram"]),
                _float_or_none(feature["adaptive_macd"]),
                _float_or_none(feature["signal"]),
            )
            prior_histogram = _float_or_none(prior["histogram"]) if prior else None
            prior_macd = _float_or_none(prior["adaptive_macd"]) if prior else None
            fixed_hold = cfg.fixed_hold_bars is not None and index - entry_index >= cfg.fixed_hold_bars
            emergency = cfg.enable_emergency_exit and atr is not None and close <= entry_price - cfg.emergency_stop_atr_multiple * atr
            structure_exit = cfg.enable_structure_exit and structure_break[index]
            if fixed_hold or emergency or structure_exit:
                reason = (
                    f"fixed {cfg.fixed_hold_bars}-bar hold completed"
                    if fixed_hold
                    else "emergency ATR thesis invalidation"
                    if emergency
                    else "confirmed weekly lower-high structure break"
                )
                average = sum(exposure_samples) / len(exposure_samples) if exposure_samples else exposure
                trade_return = ((equity / trade_start_equity) - 1.0) * 100.0 if trade_start_equity else 0.0
                trades.append(ClosedTrade(str(features[entry_index]["time"]), str(feature["time"]), entry_price, close, round(average, 4), index - entry_index, round(trade_return, 4), reason))
                decide(index, "EXIT", 0.0, reason, "structural_failure", feature)
                exposure, entry_price, last_add_price, entry_index, trade_start_equity, exposure_samples = 0.0, None, None, None, None, []
            else:
                decelerating = histogram is not None and prior_histogram is not None and macd is not None and prior_macd is not None and histogram < prior_histogram and macd <= prior_macd
                reaccelerating = (
                    histogram is not None
                    and prior_histogram is not None
                    and macd is not None
                    and prior_macd is not None
                    and signal is not None
                    and macd > 0
                    and signal > 0
                    and histogram > prior_histogram
                    and macd > prior_macd
                    and close >= float(prior["close"])
                )
                deceleration_bars = deceleration_bars + 1 if decelerating else 0
                threshold = _deceleration_threshold(regime, cfg)
                # Preserve the original spot tranche. Ordinary momentum
                # deterioration can remove only the earned trend sleeve;
                # emergency invalidation or structural failure closes core.
                if cfg.allow_delevering and deceleration_bars >= threshold and exposure > cfg.core_exposure:
                    floor = cfg.core_exposure
                    decrement = 0.5 if regime == "extreme" else cfg.pyramid_increment
                    exposure = max(floor, exposure - decrement)
                    decide(index, "DELEVER", exposure, f"{deceleration_bars} bars of MACD/histogram deceleration", regime, feature)
                    deceleration_bars = 0
                elif cfg.allow_relevering and reaccelerating and exposure < _regime_max_exposure(regime, cfg, extreme_seen):
                    exposure = min(_regime_max_exposure(regime, cfg, extreme_seen), exposure + cfg.pyramid_increment)
                    last_add_price = close
                    decide(index, "RELEVER", exposure, "momentum reacceleration with structure intact", regime, feature)
                elif cfg.allow_pyramiding and atr is not None and last_add_price is not None and close >= last_add_price + cfg.pyramid_atr_multiple * atr and histogram is not None and histogram >= 0 and exposure < _regime_max_exposure(regime, cfg, extreme_seen):
                    exposure = min(_regime_max_exposure(regime, cfg, extreme_seen), exposure + cfg.pyramid_increment)
                    last_add_price = close
                    decide(index, "PYRAMID", exposure, "favorable ATR continuation with non-negative momentum", regime, feature)
            if exposure > 0:
                exposure_samples.append(exposure)
        exposures.append(round(exposure, 4))
        equities.append(round(equity, 8))

    for feature, exposure_value, equity_value in zip(features, exposures, equities):
        feature["target_exposure"] = exposure_value
        feature["equity"] = equity_value
    first_entry_index = next((item.index for item in decisions if item.action == "ENTER"), 0)
    statistics = _statistics(equities, exposures, trades, decisions, measurement_start_index=first_entry_index)
    return StrategyRun("levered-trend-following/v1", "levered_weekly_trend", ticker.upper(), timeframe_days, asdict(cfg), features, decisions, trades, statistics)


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None


def _statistics(
    equities: list[float],
    exposures: list[float],
    trades: list[ClosedTrade],
    decisions: list[StrategyDecision],
    *,
    measurement_start_index: int = 0,
) -> dict[str, object]:
    """Summarize the study from its first externally supplied entry onward."""
    scoped_equities = equities[measurement_start_index:]
    scoped_exposures = exposures[measurement_start_index:]
    peak, max_drawdown = 1.0, 0.0
    for value in scoped_equities:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, (value / peak - 1.0) * 100.0)
    trade_returns = sorted((item.pnl_pct for item in trades), reverse=True)
    total_trade_pnl = sum(trade_returns)
    top = lambda fraction: sum(trade_returns[: max(1, math.ceil(len(trade_returns) * fraction))]) / total_trade_pnl * 100 if total_trade_pnl else None
    turnover = sum(abs(decisions[i].target_exposure - decisions[i - 1].target_exposure) for i in range(1, len(decisions))) if decisions else 0.0
    average_exposure = sum(scoped_exposures) / len(scoped_exposures) if scoped_exposures else 0.0
    return {
        "measurement_start_index": measurement_start_index,
        "total_return_pct": round((scoped_equities[-1] - 1.0) * 100.0, 4) if scoped_equities else 0.0,
        "max_drawdown_pct": round(max_drawdown, 4),
        "exposure_adjusted_return_pct": round(((scoped_equities[-1] - 1.0) * 100.0) / average_exposure, 4) if average_exposure else None,
        "average_exposure": round(average_exposure, 4),
        "time_in_market_pct": round(sum(value > 0 for value in scoped_exposures) / len(scoped_exposures) * 100, 2) if scoped_exposures else 0.0,
        "turnover_exposure_units": round(turnover, 4),
        "closed_trades": len(trades),
        "average_winner_pct": round(sum(item.pnl_pct for item in trades if item.pnl_pct > 0) / max(1, sum(item.pnl_pct > 0 for item in trades)), 4),
        "average_loser_pct": round(sum(item.pnl_pct for item in trades if item.pnl_pct < 0) / max(1, sum(item.pnl_pct < 0 for item in trades)), 4),
        "top_5pct_trade_pnl_share": None if top(0.05) is None else round(top(0.05), 4),
        "top_10pct_trade_pnl_share": None if top(0.10) is None else round(top(0.10), 4),
        "decision_counts": {action: sum(item.action == action for item in decisions) for action in sorted({item.action for item in decisions})},
    }


def write_strategy_report(run: StrategyRun | dict[str, object], path: Path) -> Path:
    """Render the normalized output contract for rapid strategy inspection."""
    payload = run.to_dict() if isinstance(run, StrategyRun) else run
    bars = list(payload["bars"])
    decisions = list(payload["decisions"])
    figure = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        specs=[[{}], [{}], [{"secondary_y": True}], [{}]],
        subplot_titles=("Price / decisions", "Adaptive MACD", "RSI(14) / ATR(14)", "Exposure / equity"),
    )
    times = [bar["time"] for bar in bars]
    figure.add_trace(go.Candlestick(x=times, open=[bar["open"] for bar in bars], high=[bar["high"] for bar in bars], low=[bar["low"] for bar in bars], close=[bar["close"] for bar in bars], name="Price"), row=1, col=1)
    colors = {"ENTER": "#2ecc71", "PYRAMID": "#27ae60", "RELEVER": "#3498db", "DELEVER": "#f39c12", "EXIT": "#e74c3c"}
    for action in colors:
        points = [item for item in decisions if item["action"] == action]
        if points:
            figure.add_trace(go.Scatter(x=[item["time"] for item in points], y=[item["price"] for item in points], mode="markers", name=action, marker={"size": 10, "color": colors[action]}), row=1, col=1)
    figure.add_trace(go.Bar(x=times, y=[bar["histogram"] for bar in bars], name="Histogram", marker_color="#86d6e8"), row=2, col=1)
    figure.add_trace(go.Scatter(x=times, y=[bar["adaptive_macd"] for bar in bars], name="Adaptive MACD", line={"color": "#8ecae6"}), row=2, col=1)
    figure.add_trace(go.Scatter(x=times, y=[bar["signal"] for bar in bars], name="Signal", line={"color": "#ffd166"}), row=2, col=1)
    figure.add_trace(go.Scatter(x=times, y=[bar["rsi_14"] for bar in bars], name="RSI(14)", line={"color": "#cdb4db"}), row=3, col=1)
    figure.add_hline(y=50, line_dash="dot", line_color="#8d99ae", row=3, col=1)
    figure.add_trace(go.Scatter(x=times, y=[bar["atr_14"] for bar in bars], name="ATR(14)", line={"color": "#ff9f1c"}), row=3, col=1, secondary_y=True)
    figure.add_trace(go.Scatter(x=times, y=[bar["target_exposure"] for bar in bars], name="Exposure", line={"color": "#f39c12", "shape": "hv"}), row=4, col=1)
    figure.add_trace(go.Scatter(x=times, y=[bar["equity"] for bar in bars], name="Equity", line={"color": "#2ecc71"}), row=4, col=1)
    figure.update_layout(template="plotly_dark", height=1250, title=f"{payload['ticker']} — levered {payload['timeframe_days']}D trend manager", hovermode="x unified", xaxis_rangeslider_visible=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(path, include_plotlyjs="cdn", auto_open=False)
    return path


def _parse_entry_dates(values: Sequence[str]) -> list[date]:
    return [date.fromisoformat(value) for value in values]


def _load_config(path: Path | None) -> LeveredTrendConfig:
    if path is None:
        return LeveredTrendConfig()
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("strategy config must be a JSON object")
    return LeveredTrendConfig(**values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run supplied entry dates through the position manager")
    run.add_argument("ticker")
    run.add_argument("--ohlcv", type=Path, required=True)
    run.add_argument("--entry-date", action="append", required=True, help="YYYY-MM-DD; may be repeated")
    run.add_argument("--timeframe-days", type=int, choices=(3, 7), default=7)
    run.add_argument("--config", type=Path, help="JSON overrides matching LeveredTrendConfig")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--report", type=Path)
    analyze = commands.add_parser("analyze", help="Render a previously saved strategy-output JSON artifact")
    analyze.add_argument("input", type=Path)
    analyze.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        write_strategy_report(json.loads(args.input.read_text(encoding="utf-8")), args.report)
        print(f"Wrote {args.report}")
        return
    run = run_levered_weekly_trend(
        args.ticker,
        load_ohlcv_csv(args.ohlcv),
        _parse_entry_dates(args.entry_date),
        timeframe_days=args.timeframe_days,
        config=_load_config(args.config),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
    if args.report:
        write_strategy_report(run, args.report)
    print(f"Wrote {args.output} ({len(run.decisions)} decisions, {len(run.closed_trades)} closed trades)")


if __name__ == "__main__":  # pragma: no cover
    main()
