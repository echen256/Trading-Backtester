"""Fisher Transform + Adaptive MACD strategy translation for archived OHLCV data."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..strategy_metrics import build_trade, compute_strategy_statistics, serialize_trades
from ..visualize import (
    DEFAULT_DATA_DIR,
    _find_data_file,
    _load_rows,
    _parse_timeframe,
    normalize_rows,
)


@dataclass(slots=True)
class StrategyConfig:
    ft_len: int = 50
    ob_level: float = 2.5
    os_level: float = -2.5
    r2_period: int = 20
    macd_fast: int = 10
    macd_slow: int = 20
    macd_signal: int = 9
    enable_longs: bool = True
    enable_shorts: bool = True
    stop_loss_pct: float = 2.0
    confirm_window: int = 1
    htf_tf: str = "D"
    block_shorts_on_htf_ob: bool = True
    short_emergency_stop_pct: float = 8.0
    short_max_bars_in_trade: int = 40


@dataclass(slots=True)
class StrategyResult:
    ticker: str
    timeframe_minutes: int
    rows: list[dict[str, object]]
    series: dict[str, list[float | None]]
    detections: dict[str, list[bool]]
    events: dict[str, list[dict[str, object]]]
    trades: list[dict[str, object]]
    statistics: dict[str, object]
    summary: dict[str, object]
    config: StrategyConfig


def _rolling_extrema(values: list[float], length: int, index: int) -> tuple[float, float]:
    start = max(0, index - length + 1)
    window = values[start : index + 1]
    return max(window), min(window)


def _fisher_transform(values: list[float], length: int) -> list[float]:
    result: list[float] = []
    prev_smoothed = 0.0
    prev_fisher = 0.0
    for index, value in enumerate(values):
        highest, lowest = _rolling_extrema(values, length, index)
        price_range = highest - lowest
        normalized = 2.0 * ((value - lowest) / price_range - 0.5) if price_range != 0 else 0.0
        clamped = max(-0.999, min(0.999, normalized))
        smoothed = 0.33 * clamped + 0.67 * prev_smoothed
        fisher = 0.5 * math.log((1.0 + smoothed) / (1.0 - smoothed)) + 0.5 * prev_fisher
        result.append(fisher)
        prev_smoothed = smoothed
        prev_fisher = fisher
    return result


def _ema_optional(values: list[float | None], period: int) -> list[float | None]:
    alpha = 2.0 / (period + 1)
    ema_value: float | None = None
    result: list[float | None] = []
    for value in values:
        if value is None:
            result.append(None)
            continue
        ema_value = value if ema_value is None else (value * alpha) + (ema_value * (1.0 - alpha))
        result.append(ema_value)
    return result


def _rolling_correlation_to_index(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        start = index - period + 1
        if start < 0:
            result.append(None)
            continue
        y_values = values[start : index + 1]
        x_values = list(range(start, index + 1))
        x_mean = sum(x_values) / period
        y_mean = sum(y_values) / period
        covariance = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        x_var = sum((x - x_mean) ** 2 for x in x_values)
        y_var = sum((y - y_mean) ** 2 for y in y_values)
        if x_var <= 0 or y_var <= 0:
            result.append(0.0)
            continue
        result.append(covariance / math.sqrt(x_var * y_var))
    return result


def _adaptive_macd(
    fisher: list[float],
    *,
    fast_period: int,
    slow_period: int,
    signal_period: int,
    r2_period: int,
) -> tuple[list[float | None], list[float | None], list[float | None], list[float | None]]:
    a1 = 2.0 / (fast_period + 1)
    a2 = 2.0 / (slow_period + 1)
    correlations = _rolling_correlation_to_index(fisher, r2_period)
    r2_values: list[float | None] = []
    macd_values: list[float | None] = []
    previous_macd_1 = 0.0
    previous_macd_2 = 0.0

    for index, fisher_value in enumerate(fisher):
        correlation = correlations[index]
        if correlation is None:
            r2_values.append(None)
            macd_values.append(None)
            previous_macd_2 = previous_macd_1
            previous_macd_1 = 0.0
            continue

        r2 = 0.5 * (correlation**2) + 0.5
        k_value = r2 * ((1 - a1) * (1 - a2)) + (1 - r2) * ((1 - a1) / (1 - a2))
        fisher_prev = fisher[index - 1] if index > 0 else 0.0
        macd_value = ((fisher_value - fisher_prev) * (a1 - a2)) + ((-a2 - a1 + 2) * previous_macd_1) - (
            k_value * previous_macd_2
        )
        r2_values.append(r2)
        macd_values.append(macd_value)
        previous_macd_2 = previous_macd_1
        previous_macd_1 = macd_value

    signal_values = _ema_optional(macd_values, signal_period)
    histogram_values = [
        (macd - signal) if macd is not None and signal is not None else None
        for macd, signal in zip(macd_values, signal_values)
    ]
    return r2_values, macd_values, signal_values, histogram_values


def _is_local_pivot(
    values: list[float | None],
    pivot_index: int,
    *,
    valley: bool,
    min_value: float | None = None,
    max_value: float | None = None,
) -> bool:
    if pivot_index <= 0 or pivot_index >= len(values) - 1:
        return False
    current = values[pivot_index]
    prev_value = values[pivot_index - 1]
    next_value = values[pivot_index + 1]
    if current is None or prev_value is None or next_value is None:
        return False
    if min_value is not None and current < min_value:
        return False
    if max_value is not None and current > max_value:
        return False
    if valley:
        return prev_value > current and next_value > current
    return prev_value < current and next_value < current


def _pivot_detection_flags(
    values: list[float | None],
    *,
    lookback: int,
    valley: bool,
    require_negative: bool = False,
    require_positive: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
) -> tuple[list[bool], list[dict[str, object]]]:
    flags = [False] * len(values)
    pivot_markers: list[dict[str, object]] = []
    for index in range(lookback + 1, len(values)):
        pivot_index = index - lookback
        if not _is_local_pivot(values, pivot_index, valley=valley, min_value=min_value, max_value=max_value):
            continue
        pivot_value = values[pivot_index]
        if pivot_value is None:
            continue
        if require_negative and pivot_value >= 0:
            continue
        if require_positive and pivot_value <= 0:
            continue
        flags[index] = True
        pivot_markers.append({"pivot_index": pivot_index, "value": pivot_value})
    return flags, pivot_markers


def _barssince(flags: list[bool]) -> list[int | None]:
    result: list[int | None] = []
    last_true_index: int | None = None
    for index, flag in enumerate(flags):
        if flag:
            last_true_index = index
            result.append(0)
        elif last_true_index is None:
            result.append(None)
        else:
            result.append(index - last_true_index)
    return result


def _aggregate_rows(rows: list[dict[str, object]], htf_minutes: int) -> list[dict[str, object]]:
    if not rows:
        return []
    base_time = rows[0]["timestamp"]
    if not hasattr(base_time, "timestamp"):
        raise ValueError("Rows must include normalized datetime timestamps before HTF aggregation.")

    grouped: list[list[dict[str, object]]] = []
    current_bucket: list[dict[str, object]] = []
    current_bucket_key: int | None = None

    for row in rows:
        timestamp = row["timestamp"]
        bucket_key = int(timestamp.timestamp() // (htf_minutes * 60))
        if current_bucket_key is None or bucket_key == current_bucket_key:
            current_bucket.append(row)
            current_bucket_key = bucket_key
            continue
        grouped.append(current_bucket)
        current_bucket = [row]
        current_bucket_key = bucket_key

    if current_bucket:
        grouped.append(current_bucket)

    aggregated: list[dict[str, object]] = []
    for bucket in grouped:
        first = bucket[0]
        last = bucket[-1]
        aggregated.append(
            {
                "timestamp": last["timestamp"],
                "time": last["time"],
                "open": first["open"],
                "high": max(float(entry["high"]) for entry in bucket),
                "low": min(float(entry["low"]) for entry in bucket),
                "close": last["close"],
                "volume": sum(float(entry["volume"]) for entry in bucket if entry.get("volume") is not None) or None,
            }
        )
    return aggregated


def _parse_htf_minutes(value: str, base_timeframe_minutes: int) -> int:
    normalized = value.strip().lower()
    if normalized in {"d", "1d", "day", "daily"}:
        return 1440
    if normalized in {"w", "1w", "week", "weekly"}:
        return 10080
    return _parse_timeframe(value if normalized.endswith("m") else normalized) if normalized not in {"d", "w"} else base_timeframe_minutes


def _align_htf_series(
    rows: list[dict[str, object]],
    htf_rows: list[dict[str, object]],
    htf_values: list[float],
    htf_minutes: int,
) -> list[float | None]:
    if not htf_rows:
        return [None] * len(rows)
    htf_by_bucket: dict[int, float] = {}
    for row, value in zip(htf_rows, htf_values):
        bucket = int(row["timestamp"].timestamp() // (htf_minutes * 60))
        htf_by_bucket[bucket] = value

    aligned: list[float | None] = []
    previous_value: float | None = None
    for row in rows:
        bucket = int(row["timestamp"].timestamp() // (htf_minutes * 60))
        current_bucket_value = htf_by_bucket.get(bucket)
        aligned.append(previous_value if current_bucket_value is None else previous_value)
        if current_bucket_value is not None:
            previous_value = current_bucket_value
    return aligned


def _series_to_chart_points(
    rows: list[dict[str, object]],
    values: list[float | None],
    *,
    round_digits: int = 6,
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for row, value in zip(rows, values):
        if value is None:
            continue
        points.append({"time": row["time"], "value": round(float(value), round_digits)})
    return points


def _event_series(
    rows: list[dict[str, object]],
    events: list[dict[str, object]],
    *,
    value_key: str = "value",
    round_digits: int = 6,
) -> list[dict[str, object]]:
    return [
        {"time": rows[int(event["index"])]["time"], "value": round(float(event[value_key]), round_digits)}
        for event in events
    ]


def _build_chart_indicators(result: StrategyResult) -> list[dict[str, object]]:
    scale_id = "fisher-macd"
    histogram_positive = [value if value is not None and value >= 0 else None for value in result.series["histogram"]]
    histogram_negative = [value if value is not None and value < 0 else None for value in result.series["histogram"]]
    zero_line = [0.0] * len(result.rows)
    ob_line = [result.config.ob_level] * len(result.rows)
    os_line = [result.config.os_level] * len(result.rows)

    return [
        {
            "name": "Fisher",
            "data": _series_to_chart_points(result.rows, result.series["fisher"]),
            "options": {"color": "#ffd166", "lineWidth": 2, "priceScaleId": scale_id},
        },
        {
            "name": "HTF Fisher",
            "data": _series_to_chart_points(result.rows, result.series["fisher_htf"]),
            "options": {"color": "#f4a261", "lineWidth": 2, "priceScaleId": scale_id},
        },
        {
            "name": "Adaptive MACD",
            "data": _series_to_chart_points(result.rows, result.series["adaptive_macd"]),
            "options": {"color": "#8ecae6", "lineWidth": 2, "priceScaleId": scale_id},
        },
        {
            "name": "Signal Line",
            "data": _series_to_chart_points(result.rows, result.series["signal_line"]),
            "options": {"color": "#ff5d00", "lineWidth": 2, "priceScaleId": scale_id},
        },
        {
            "name": "Histogram Positive",
            "data": _series_to_chart_points(result.rows, histogram_positive),
            "options": {"color": "#2a9d8f", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Histogram Negative",
            "data": _series_to_chart_points(result.rows, histogram_negative),
            "options": {"color": "#e63946", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Fisher Overbought",
            "data": _series_to_chart_points(result.rows, ob_line),
            "options": {"color": "#4caf50", "lineWidth": 1, "priceScaleId": scale_id},
        },
        {
            "name": "Fisher Oversold",
            "data": _series_to_chart_points(result.rows, os_line),
            "options": {"color": "#ef5350", "lineWidth": 1, "priceScaleId": scale_id},
        },
        {
            "name": "Fisher Zero",
            "data": _series_to_chart_points(result.rows, zero_line),
            "options": {"color": "#9aa0a6", "lineWidth": 1, "priceScaleId": scale_id},
        },
        {
            "name": "MACD Valleys",
            "data": _event_series(result.rows, result.events["macd_valleys"]),
            "options": {"color": "#00c853", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "MACD Peaks",
            "data": _event_series(result.rows, result.events["macd_peaks"]),
            "options": {"color": "#d50000", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Fisher Valleys",
            "data": _event_series(result.rows, result.events["fisher_valleys"]),
            "options": {"color": "#76ff03", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Fisher Peaks",
            "data": _event_series(result.rows, result.events["fisher_peaks"]),
            "options": {"color": "#880e4f", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Fuzzy Fisher Peaks",
            "data": _event_series(result.rows, result.events["fuzzy_fisher_peaks"]),
            "options": {"color": "#fb8c00", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Short Entries",
            "data": _event_series(result.rows, result.events["short_entries"]),
            "options": {"color": "#ef5350", "lineType": "histogram", "priceScaleId": scale_id},
        },
        {
            "name": "Short Exits",
            "data": _event_series(result.rows, result.events["short_exits"]),
            "options": {"color": "#42a5f5", "lineType": "histogram", "priceScaleId": scale_id},
        },
    ]


def compute_fisher_adaptive_macd_strategy(
    rows: list[dict[str, object]],
    *,
    ticker: str = "UNKNOWN",
    timeframe_minutes: int = 1440,
    config: StrategyConfig | None = None,
) -> StrategyResult:
    cfg = config or StrategyConfig()
    normalized_rows = normalize_rows(rows)
    open_values = [float(row["open"]) for row in normalized_rows]
    high_values = [float(row["high"]) for row in normalized_rows]
    low_values = [float(row["low"]) for row in normalized_rows]
    close_values = [float(row["close"]) for row in normalized_rows]

    fisher_open = _fisher_transform(open_values, cfg.ft_len)
    fisher_high = _fisher_transform(high_values, cfg.ft_len)
    fisher_low = _fisher_transform(low_values, cfg.ft_len)
    fisher_close = _fisher_transform(close_values, cfg.ft_len)
    fisher_candle_high = [
        max(f_open, f_high, f_low, fisher)
        for f_open, f_high, f_low, fisher in zip(fisher_open, fisher_high, fisher_low, fisher_close)
    ]
    fisher_candle_low = [
        min(f_open, f_high, f_low, fisher)
        for f_open, f_high, f_low, fisher in zip(fisher_open, fisher_high, fisher_low, fisher_close)
    ]

    htf_minutes = _parse_htf_minutes(cfg.htf_tf, timeframe_minutes)
    if htf_minutes <= timeframe_minutes:
        fisher_htf = list(fisher_close)
    else:
        htf_rows = _aggregate_rows(normalized_rows, htf_minutes)
        fisher_htf_raw = _fisher_transform([float(row["close"]) for row in htf_rows], cfg.ft_len)
        fisher_htf = _align_htf_series(normalized_rows, htf_rows, fisher_htf_raw, htf_minutes)

    r2_values, adaptive_macd, signal_line, histogram = _adaptive_macd(
        fisher_close,
        fast_period=cfg.macd_fast,
        slow_period=cfg.macd_slow,
        signal_period=cfg.macd_signal,
        r2_period=cfg.r2_period,
    )

    macd_valley_flags, macd_valley_markers = _pivot_detection_flags(
        histogram, lookback=1, valley=True, require_negative=True
    )
    macd_peak_flags, macd_peak_markers = _pivot_detection_flags(
        histogram, lookback=1, valley=False, require_positive=True
    )
    fisher_valley_flags, fisher_valley_markers = _pivot_detection_flags(
        fisher_close, lookback=1, valley=True, require_negative=True
    )
    fisher_peak_flags, fisher_peak_markers = _pivot_detection_flags(
        fisher_close, lookback=1, valley=False, require_positive=True
    )
    fuzzy_peak_flags, fuzzy_peak_markers = _pivot_detection_flags(
        fisher_close, lookback=1, valley=False, min_value=-0.25, max_value=0.25
    )

    recent_macd_valley = _barssince(macd_valley_flags)
    recent_fisher_valley = _barssince(fisher_valley_flags)
    recent_macd_peak = _barssince(macd_peak_flags)
    recent_fisher_peak = _barssince(fisher_peak_flags)

    allow_shorts_htf: list[bool] = []
    is_overbought: list[bool] = []
    is_oversold: list[bool] = []
    short_signal_raw: list[bool] = []
    short_signal: list[bool] = []
    short_entries: list[dict[str, object]] = []
    short_exits: list[dict[str, object]] = []
    short_position: list[int] = []
    completed_trades = []

    position = 0
    short_entry_bar: int | None = None
    entry_price: float | None = None
    current_short_entry: dict[str, object] | None = None

    for index, row in enumerate(normalized_rows):
        fisher_value = fisher_close[index]
        histogram_value = histogram[index]
        fisher_htf_value = fisher_htf[index]
        htf_is_overbought = fisher_htf_value is not None and fisher_htf_value >= cfg.ob_level
        allow_short = (not cfg.block_shorts_on_htf_ob) or (not htf_is_overbought)
        overbought = fisher_value >= cfg.ob_level
        oversold = fisher_value <= cfg.os_level
        is_overbought.append(overbought)
        is_oversold.append(oversold)
        allow_shorts_htf.append(allow_short)

        prev_fisher = fisher_close[index - 1] if index > 0 else None
        short_signal_strict = prev_fisher is not None and prev_fisher >= 0 and fisher_value < 0
        short_signal_fuzzy = fuzzy_peak_flags[index]
        raw_signal = (short_signal_strict or short_signal_fuzzy) and histogram_value is not None and histogram_value < 0
        signal = raw_signal and allow_short
        short_signal_raw.append(raw_signal)
        short_signal.append(signal)

        if cfg.enable_shorts and position == 0 and signal:
            position = -1
            short_entry_bar = index
            entry_price = float(row["close"])
            current_short_entry = {
                "index": index,
                "time": row["time"],
                "price": entry_price,
                "value": fisher_value,
                "reason": "strict_crossunder" if short_signal_strict else "fuzzy_peak",
                "side": "short",
            }
            short_entries.append(current_short_entry)
            short_position.append(position)
            continue

        if position < 0:
            emergency_stop = entry_price * (1.0 + cfg.short_emergency_stop_pct / 100.0) if entry_price is not None else None
            short_emergency_exit = emergency_stop is not None and float(row["close"]) >= emergency_stop
            short_invalidation = fisher_value > 0
            short_time_exit = short_entry_bar is not None and (index - short_entry_bar >= cfg.short_max_bars_in_trade)
            short_exit_opposite = fisher_valley_flags[index] and fisher_value < cfg.os_level
            if short_exit_opposite or short_invalidation or short_time_exit or short_emergency_exit:
                reason = "opposite_valley"
                if short_invalidation:
                    reason = "fisher_invalidation"
                elif short_time_exit:
                    reason = "time_exit"
                elif short_emergency_exit:
                    reason = "emergency_stop"
                short_exits.append(
                    {
                        "index": index,
                        "time": row["time"],
                        "price": float(row["close"]),
                        "value": fisher_value,
                        "reason": reason,
                    }
                )
                if current_short_entry is not None and entry_price is not None and short_entry_bar is not None:
                    completed_trades.append(
                        build_trade(
                            side="short",
                            entry_time=str(current_short_entry["time"]),
                            entry_price=entry_price,
                            exit_time=row["time"],
                            exit_price=float(row["close"]),
                            bars_held=index - short_entry_bar,
                            exit_reason=reason,
                        )
                    )
                position = 0
                short_entry_bar = None
                entry_price = None
                current_short_entry = None
        short_position.append(position)

    events = {
        "macd_valleys": [
            {
                "index": marker["pivot_index"],
                "time": normalized_rows[int(marker["pivot_index"])]["time"],
                "value": float(marker["value"]) - 0.4,
            }
            for marker in macd_valley_markers
        ],
        "macd_peaks": [
            {
                "index": marker["pivot_index"],
                "time": normalized_rows[int(marker["pivot_index"])]["time"],
                "value": float(marker["value"]) + 0.4,
            }
            for marker in macd_peak_markers
        ],
        "fisher_valleys": [
            {
                "index": marker["pivot_index"],
                "time": normalized_rows[int(marker["pivot_index"])]["time"],
                "value": float(marker["value"]) - 0.4,
            }
            for marker in fisher_valley_markers
        ],
        "fisher_peaks": [
            {
                "index": marker["pivot_index"],
                "time": normalized_rows[int(marker["pivot_index"])]["time"],
                "value": float(marker["value"]) + 0.4,
            }
            for marker in fisher_peak_markers
        ],
        "fuzzy_fisher_peaks": [
            {
                "index": marker["pivot_index"],
                "time": normalized_rows[int(marker["pivot_index"])]["time"],
                "value": float(marker["value"]) + 0.25,
            }
            for marker in fuzzy_peak_markers
        ],
        "short_entries": short_entries,
        "short_exits": short_exits,
    }

    latest_close = close_values[-1] if close_values else None
    open_trade = None
    if position < 0 and current_short_entry is not None and entry_price is not None:
        open_trade = {
            "side": "short",
            "entry_time": current_short_entry["time"],
            "entry_price": entry_price,
            "bars_open": (len(normalized_rows) - 1) - int(current_short_entry["index"]),
            "reason": current_short_entry["reason"],
        }

    statistics = compute_strategy_statistics(
        completed_trades,
        open_trade=open_trade,
        latest_close=latest_close,
    )

    summary = {
        "bars": len(normalized_rows),
        "short_entries": len(short_entries),
        "short_exits": len(short_exits),
        "open_short": position < 0,
        "latest_close": latest_close,
        "latest_fisher": fisher_close[-1] if fisher_close else None,
        "recent_macd_valley": recent_macd_valley[-1] if recent_macd_valley else None,
        "recent_fisher_valley": recent_fisher_valley[-1] if recent_fisher_valley else None,
        "recent_macd_peak": recent_macd_peak[-1] if recent_macd_peak else None,
        "recent_fisher_peak": recent_fisher_peak[-1] if recent_fisher_peak else None,
    }

    return StrategyResult(
        ticker=ticker,
        timeframe_minutes=timeframe_minutes,
        rows=normalized_rows,
        series={
            "fisher_open": fisher_open,
            "fisher_high": fisher_high,
            "fisher_low": fisher_low,
            "fisher": fisher_close,
            "fisher_candle_high": fisher_candle_high,
            "fisher_candle_low": fisher_candle_low,
            "fisher_htf": fisher_htf,
            "r2": r2_values,
            "adaptive_macd": adaptive_macd,
            "signal_line": signal_line,
            "histogram": histogram,
            "short_position": [float(value) for value in short_position],
        },
        detections={
            "macd_valley": macd_valley_flags,
            "macd_peak": macd_peak_flags,
            "fisher_valley": fisher_valley_flags,
            "fisher_peak": fisher_peak_flags,
            "fuzzy_fisher_peak": fuzzy_peak_flags,
            "allow_shorts_htf": allow_shorts_htf,
            "is_overbought": is_overbought,
            "is_oversold": is_oversold,
            "short_signal_raw": short_signal_raw,
            "short_signal": short_signal,
        },
        events=events,
        trades=serialize_trades(completed_trades),
        statistics=statistics,
        summary=summary,
        config=cfg,
    )


def build_chart_payload(result: StrategyResult) -> dict[str, object]:
    return {
        "ticker": result.ticker,
        "timeframe_minutes": result.timeframe_minutes,
        "summary": result.summary,
        "statistics": result.statistics,
        "trades": result.trades,
        "customIndicators": _build_chart_indicators(result),
        "events": result.events,
    }


def compute_archived_indicator_payload(
    ticker: str,
    timeframe: str | int,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    config: StrategyConfig | None = None,
) -> dict[str, object]:
    timeframe_minutes = _parse_timeframe(str(timeframe))
    csv_path = _find_data_file(data_dir, ticker, timeframe_minutes)
    rows = _load_rows(csv_path)
    result = compute_fisher_adaptive_macd_strategy(
        rows,
        ticker=ticker.upper(),
        timeframe_minutes=timeframe_minutes,
        config=config,
    )
    payload = build_chart_payload(result)
    payload["source_csv"] = str(csv_path)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate the Fisher Transform + Adaptive MACD Pine logic onto archived CSV data."
    )
    parser.add_argument("ticker", help="Ticker symbol to load from the local archive.")
    parser.add_argument("timeframe", help="Chart timeframe such as 15m, 60, or D.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Archive root containing timeframe folders (default: %(default)s).",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    parser.add_argument("--htf", default="D", help="Higher timeframe filter, e.g. D or W.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    payload = compute_archived_indicator_payload(
        args.ticker,
        args.timeframe,
        data_dir=args.data_dir,
        config=StrategyConfig(htf_tf=args.htf),
    )
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        return
    print(rendered)


__all__ = [
    "StrategyConfig",
    "StrategyResult",
    "build_chart_payload",
    "compute_archived_indicator_payload",
    "compute_fisher_adaptive_macd_strategy",
    "main",
]
