"""MACD histogram state: fresh / developed / mature / extreme, plus top/bottom."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class MacdHistogramState:
    last: float
    prev: float
    sign: str
    slope: str
    extension: str
    at_top: bool
    at_bottom: bool
    percentile: float | None
    bars: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ema(values: Sequence[float], period: int) -> list[float]:
    if period < 1:
        raise ValueError("period must be >= 1")
    alpha = 2.0 / (period + 1)
    out: list[float] = []
    seed = sum(values[:period]) / period if len(values) >= period else values[0]
    prev = seed
    for index, value in enumerate(values):
        if index < period - 1:
            out.append(float("nan"))
            continue
        if index == period - 1:
            prev = seed
            out.append(prev)
            continue
        prev = alpha * value + (1 - alpha) * prev
        out.append(prev)
    return out


def macd_histogram(
    closes: Sequence[float],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[float]:
    if len(closes) < slow + signal:
        return []
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = [
        f - s if f == f and s == s else float("nan")
        for f, s in zip(fast_ema, slow_ema)
    ]
    valid = [value for value in macd_line if value == value]
    if len(valid) < signal:
        return []
    # Signal EMA over the MACD line, skipping leading NaNs.
    lead = next(i for i, value in enumerate(macd_line) if value == value)
    signal_line_tail = ema(valid, signal)
    histogram: list[float] = []
    signal_index = 0
    for index, macd_value in enumerate(macd_line):
        if index < lead or macd_value != macd_value:
            histogram.append(float("nan"))
            continue
        sig = signal_line_tail[signal_index] if signal_index < len(signal_line_tail) else float("nan")
        signal_index += 1
        histogram.append(macd_value - sig if sig == sig else float("nan"))
    return histogram


def classify_histogram(histogram: Sequence[float], *, lookback: int = 63) -> MacdHistogramState:
    clean = [value for value in histogram if value == value]
    if len(clean) < 5:
        raise ValueError("need at least 5 histogram values")
    last = clean[-1]
    prev = clean[-2]
    window = clean[-lookback:] if len(clean) >= lookback else clean
    same_sign = [abs(value) for value in window if (value >= 0) == (last >= 0)]
    percentile = None
    if same_sign:
        ranked = sorted(same_sign)
        # fraction of same-sign bars with |h| <= |last|
        count = sum(1 for value in ranked if value <= abs(last))
        percentile = count / len(ranked)

    tail = clean[-5:]
    prev_is_peak = prev == max(tail) and prev >= last
    prev_is_trough = prev == min(tail) and prev <= last
    slope = "expanding" if abs(last) > abs(prev) + 1e-12 else "contracting"
    sign = "positive" if last >= 0 else "negative"
    at_top = last > 0 and prev_is_peak
    at_bottom = last < 0 and prev_is_trough

    extreme = percentile is not None and percentile >= 0.85
    just_flipped = (last >= 0) != (prev >= 0)
    if extreme and (at_top or at_bottom or slope == "expanding"):
        extension = "extreme"
    elif just_flipped or (percentile is not None and percentile <= 0.25 and slope == "expanding"):
        extension = "fresh"
    elif slope == "contracting" and percentile is not None and percentile >= 0.5:
        extension = "mature"
    else:
        extension = "developed"

    return MacdHistogramState(
        last=round(last, 6),
        prev=round(prev, 6),
        sign=sign,
        slope=slope,
        extension=extension,
        at_top=at_top,
        at_bottom=at_bottom,
        percentile=None if percentile is None else round(percentile, 3),
        bars=len(clean),
    )


def classify_closes(closes: Sequence[float]) -> MacdHistogramState:
    hist = macd_histogram(closes)
    return classify_histogram(hist)
