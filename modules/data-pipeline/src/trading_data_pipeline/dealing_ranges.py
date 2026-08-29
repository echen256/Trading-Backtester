"""Lookahead-safe dealing-range detection for OHLC charts.

A range is initialized from the latest confirmed swing high and swing low.  A
wick through either boundary that closes back inside is a sweep and does not
invalidate the range.  A close beyond a boundary expands the range, using the
latest confirmed opposite swing as the new anchor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


SwingKind = Literal["high", "low"]
EventKind = Literal[
    "sweep_high",
    "sweep_low",
    "double_sweep",
    "expansion_up",
    "expansion_down",
]


@dataclass(frozen=True, slots=True)
class Swing:
    id: str
    kind: SwingKind
    pivot_index: int
    confirmed_index: int
    time: str
    confirmed_time: str
    price: float


@dataclass(slots=True)
class DealingRange:
    id: str
    start_index: int
    start_time: str
    end_index: int | None
    end_time: str | None
    lower: float
    midpoint: float
    upper: float
    status: str
    direction: str
    expansion_target: str | None
    high_swing_id: str | None
    low_swing_id: str | None


@dataclass(frozen=True, slots=True)
class RangeEvent:
    id: str
    range_id: str
    kind: EventKind
    index: int
    time: str
    price: float
    boundary: float | None
    target: str | None = None


def _swing_at(
    rows: list[dict[str, object]],
    pivot_index: int,
    confirmed_index: int,
    *,
    lookback: int,
    lookahead: int,
    kind: SwingKind,
) -> Swing | None:
    start = pivot_index - lookback
    stop = pivot_index + lookahead + 1
    if start < 0 or stop > len(rows):
        return None

    field = "high" if kind == "high" else "low"
    value = float(rows[pivot_index][field])
    neighbors = [float(rows[index][field]) for index in range(start, stop) if index != pivot_index]
    is_pivot = value > max(neighbors) if kind == "high" else value < min(neighbors)
    if not is_pivot:
        return None

    return Swing(
        id=f"swing-{kind}-{pivot_index}",
        kind=kind,
        pivot_index=pivot_index,
        confirmed_index=confirmed_index,
        time=str(rows[pivot_index]["time"]),
        confirmed_time=str(rows[confirmed_index]["time"]),
        price=value,
    )


def _historical_target(
    ranges: list[DealingRange],
    *,
    close: float,
) -> str:
    """Classify an expansion as price discovery or a revisit of an older range."""

    completed = ranges[:-1]
    for old_range in reversed(completed):
        if old_range.lower <= close <= old_range.upper:
            return "old_range"
    return "new_prices"


def compute_dealing_ranges(
    rows: list[dict[str, object]],
    *,
    lookback: int = 5,
    lookahead: int = 1,
) -> dict[str, object]:
    """Compute swing-confirmed dealing ranges and their lifecycle events.

    ``rows`` must be chronological normalized OHLC rows containing ``time``,
    ``high``, ``low``, and ``close``.  Pivot timestamps identify where the
    swing occurred, while ``confirmed_time`` makes the lookahead delay explicit.
    """

    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    if lookahead < 1:
        raise ValueError("lookahead must be at least 1")

    swings: list[Swing] = []
    ranges: list[DealingRange] = []
    events: list[RangeEvent] = []
    latest_high: Swing | None = None
    latest_low: Swing | None = None
    active: DealingRange | None = None

    def start_range(
        index: int,
        *,
        lower: float,
        upper: float,
        direction: str,
        target: str | None,
        high_swing: Swing | None,
        low_swing: Swing | None,
    ) -> DealingRange | None:
        if upper <= lower:
            return None
        item = DealingRange(
            id=f"range-{len(ranges) + 1}",
            start_index=index,
            start_time=str(rows[index]["time"]),
            end_index=None,
            end_time=None,
            lower=lower,
            midpoint=(lower + upper) / 2,
            upper=upper,
            status="active",
            direction=direction,
            expansion_target=target,
            high_swing_id=high_swing.id if high_swing else None,
            low_swing_id=low_swing.id if low_swing else None,
        )
        ranges.append(item)
        return item

    for index, row in enumerate(rows):
        pivot_index = index - lookahead
        if pivot_index >= lookback:
            high_swing = _swing_at(
                rows,
                pivot_index,
                index,
                lookback=lookback,
                lookahead=lookahead,
                kind="high",
            )
            low_swing = _swing_at(
                rows,
                pivot_index,
                index,
                lookback=lookback,
                lookahead=lookahead,
                kind="low",
            )
            if high_swing:
                swings.append(high_swing)
                latest_high = high_swing
            if low_swing:
                swings.append(low_swing)
                latest_low = low_swing

        if active is None and latest_high and latest_low:
            active = start_range(
                index,
                lower=latest_low.price,
                upper=latest_high.price,
                direction="initial",
                target=None,
                high_swing=latest_high,
                low_swing=latest_low,
            )

        if active is None:
            continue

        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        above = high > active.upper
        below = low < active.lower

        if close > active.upper:
            kind: EventKind = "expansion_up"
            direction: Literal["up", "down"] = "up"
            event_price = high
            boundary = active.upper
        elif close < active.lower:
            kind = "expansion_down"
            direction = "down"
            event_price = low
            boundary = active.lower
        else:
            if above and below:
                kind = "double_sweep"
                event_price = close
                boundary = None
            elif above:
                kind = "sweep_high"
                event_price = high
                boundary = active.upper
            elif below:
                kind = "sweep_low"
                event_price = low
                boundary = active.lower
            else:
                continue
            events.append(
                RangeEvent(
                    id=f"event-{len(events) + 1}",
                    range_id=active.id,
                    kind=kind,
                    index=index,
                    time=str(row["time"]),
                    price=event_price,
                    boundary=boundary,
                )
            )
            continue

        target = _historical_target(ranges, close=close)
        events.append(
            RangeEvent(
                id=f"event-{len(events) + 1}",
                range_id=active.id,
                kind=kind,
                index=index,
                time=str(row["time"]),
                price=event_price,
                boundary=boundary,
                target=target,
            )
        )
        active.end_index = index
        active.end_time = str(row["time"])
        active.status = kind

        if direction == "up":
            anchor_low = latest_low.price if latest_low else active.lower
            active = start_range(
                index,
                lower=min(anchor_low, high),
                upper=high,
                direction="up",
                target=target,
                high_swing=None,
                low_swing=latest_low,
            )
        else:
            anchor_high = latest_high.price if latest_high else active.upper
            active = start_range(
                index,
                lower=low,
                upper=max(anchor_high, low),
                direction="down",
                target=target,
                high_swing=latest_high,
                low_swing=None,
            )

    current = ranges[-1] if ranges and ranges[-1].status == "active" else None
    return {
        "config": {"lookback": lookback, "lookahead": lookahead},
        "swings": [asdict(swing) for swing in swings],
        "ranges": [asdict(item) for item in ranges],
        "events": [asdict(event) for event in events],
        "current_range_id": current.id if current else None,
    }


__all__ = ["compute_dealing_ranges"]
