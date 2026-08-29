"""Dynamic Market Profile/TPO payloads anchored to the chart timeline."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from trading_analysis.tpo.profile import adaptive_bracket_size

from .catalog import DatasetCatalog


NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
TPO_PERIOD_MINUTES = 30
MAX_TPO_INTERVAL_SECONDS = TPO_PERIOD_MINUTES * 60


def load_tpo_payload(
    catalog: DatasetCatalog,
    dataset_id: str,
    *,
    at: str | None = None,
) -> dict[str, Any]:
    """Build a no-lookahead session profile at the supplied chart timestamp."""

    metadata = catalog.get_dataset(dataset_id)
    if metadata is None:
        raise KeyError(f"Unknown dataset: {dataset_id}")
    interval = int(metadata["interval_seconds"])
    if interval > MAX_TPO_INTERVAL_SECONDS:
        return _unavailable(
            metadata,
            f"TPO requires intraday bars of {TPO_PERIOD_MINUTES} minutes or finer; "
            f"this dataset's native interval is {interval // 60} minutes.",
        )

    anchor = pd.to_datetime(at, utc=True, errors="coerce")
    if pd.isna(anchor):
        anchor = pd.to_datetime(metadata["quality"]["last_timestamp"], utc=True)
    first = pd.to_datetime(metadata["quality"]["first_timestamp"], utc=True)
    last = pd.to_datetime(metadata["quality"]["last_timestamp"], utc=True)
    anchor = min(max(anchor, first), last)

    if metadata["asset_class"] == "crypto" or metadata.get("calendar") == "24/7":
        start = anchor.floor("D")
        end = start + pd.Timedelta(days=1)
        frame = _read_session(metadata, start, min(anchor, end), end)
        label = "00:00–24:00 UTC"
        timezone = "UTC"
    else:
        start, end, anchor, frame = _equity_session(metadata, anchor)
        label = "09:30–16:00 America/New_York"
        timezone = "America/New_York"

    if frame.empty:
        return _unavailable(metadata, "No native bars were found in the standard session at this chart position.")

    profile = build_tpo_profile(frame, start=start, period_minutes=TPO_PERIOD_MINUTES)
    last_bar = pd.Timestamp(frame.timestamp.max())
    if last_bar.tzinfo is None:
        last_bar = last_bar.tz_localize("UTC")
    session_complete = last_bar + pd.Timedelta(seconds=interval) >= end
    return {
        "available": True,
        "dataset_id": dataset_id,
        "symbol": metadata["symbol"],
        "asset_class": metadata["asset_class"],
        "session_date": start.tz_convert(timezone).date().isoformat(),
        "session_label": label,
        "session_timezone": timezone,
        "session_start": _iso(start),
        "session_end": _iso(end),
        "profile_through": _iso(min(anchor, end)),
        "complete": session_complete,
        "period_minutes": TPO_PERIOD_MINUTES,
        "native_interval_seconds": interval,
        "bar_count": len(frame),
        **profile,
    }


def build_tpo_profile(
    frame: pd.DataFrame,
    *,
    start: pd.Timestamp,
    period_minutes: int = TPO_PERIOD_MINUTES,
) -> dict[str, Any]:
    """Build a classic 70% value-area profile from session OHLC bars."""

    period_seconds = period_minutes * 60
    ranges: dict[int, tuple[float, float]] = {}
    for row in frame.itertuples(index=False):
        timestamp = pd.Timestamp(row.timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        index = max(0, int((timestamp - start).total_seconds() // period_seconds))
        high = float(row.high)
        low = float(row.low)
        if index in ranges:
            old_high, old_low = ranges[index]
            ranges[index] = max(old_high, high), min(old_low, low)
        else:
            ranges[index] = high, low

    session_high = max(high for high, _ in ranges.values())
    session_low = min(low for _, low in ranges.values())
    bracket_size = adaptive_bracket_size(session_high, session_low)
    brackets: dict[float, list[str]] = defaultdict(list)
    for index, (high, low) in sorted(ranges.items()):
        letter = _tpo_letter(index)
        first_level = math.floor(low / bracket_size)
        last_level = math.floor(high / bracket_size)
        for bracket_index in range(first_level, last_level + 1):
            level = round((bracket_index + 0.5) * bracket_size, 6)
            if letter not in brackets[level]:
                brackets[level].append(letter)

    counts = {level: len(letters) for level, letters in brackets.items()}
    total = sum(counts.values())
    midpoint = (session_high + session_low) / 2
    poc = max(counts, key=lambda level: (counts[level], -abs(level - midpoint)))
    vah, val = _value_area(counts, poc, total)
    initial_balance = [ranges[index] for index in (0, 1) if index in ranges]
    ib_high = max((high for high, _ in initial_balance), default=session_high)
    ib_low = min((low for _, low in initial_balance), default=session_low)
    levels = [{
        "price": level,
        "count": counts[level],
        "letters": brackets[level],
        "in_value_area": val <= level <= vah,
        "is_poc": level == poc,
    } for level in sorted(counts, reverse=True)]
    return {
        "bracket_size": bracket_size,
        "total_tpos": total,
        "poc": poc,
        "vah": vah,
        "val": val,
        "ib_high": ib_high,
        "ib_low": ib_low,
        "session_high": session_high,
        "session_low": session_low,
        "levels": levels,
    }


def _equity_session(
    metadata: dict[str, Any],
    anchor: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.DataFrame]:
    local = anchor.tz_convert(NY_TZ)
    candidate = local.date()
    if local.time() < RTH_OPEN:
        candidate -= timedelta(days=1)

    # The archive itself is the final calendar authority. Walking backward also
    # handles weekends, exchange holidays, and dates outside the fixed calendar.
    for _ in range(12):
        if candidate.weekday() < 5:
            start = pd.Timestamp(datetime.combine(candidate, RTH_OPEN, tzinfo=NY_TZ)).tz_convert("UTC")
            end = pd.Timestamp(datetime.combine(candidate, RTH_CLOSE, tzinfo=NY_TZ)).tz_convert("UTC")
            through = min(anchor, end) if anchor >= start else end
            frame = _read_session(metadata, start, through, end)
            if not frame.empty:
                return start, end, through, frame
        candidate -= timedelta(days=1)
    start = pd.Timestamp(datetime.combine(candidate, RTH_OPEN, tzinfo=NY_TZ)).tz_convert("UTC")
    end = pd.Timestamp(datetime.combine(candidate, RTH_CLOSE, tzinfo=NY_TZ)).tz_convert("UTC")
    return start, end, end, pd.DataFrame()


def _read_session(
    metadata: dict[str, Any],
    start: pd.Timestamp,
    through: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    effective_end = min(max(through, start), end)
    filters = [
        ("timestamp", ">=", start.to_pydatetime()),
        ("timestamp", "<=", effective_end.to_pydatetime()),
    ]
    frame = pd.read_parquet(
        Path(metadata["storage"]["path"]),
        columns=["timestamp", "high", "low"],
        filters=filters,
    )
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame[(frame.timestamp >= start) & (frame.timestamp < end) & (frame.timestamp <= effective_end)]


def _value_area(counts: dict[float, int], poc: float, total: int) -> tuple[float, float]:
    target = total * 0.70
    included = {poc}
    running = counts[poc]
    below = sorted((level for level in counts if level < poc), reverse=True)
    above = sorted(level for level in counts if level > poc)
    while running < target and (below or above):
        lower = below[0] if below else None
        upper = above[0] if above else None
        lower_count = counts[lower] if lower is not None else -1
        upper_count = counts[upper] if upper is not None else -1
        if upper_count > lower_count:
            included.add(above.pop(0))
            running += upper_count
        elif lower_count > upper_count:
            included.add(below.pop(0))
            running += lower_count
        else:
            if lower is not None:
                included.add(below.pop(0))
                running += lower_count
            if upper is not None:
                included.add(above.pop(0))
                running += upper_count
    return max(included), min(included)


def _tpo_letter(index: int) -> str:
    output = ""
    current = max(0, index)
    while True:
        current, remainder = divmod(current, 26)
        output = chr(ord("A") + remainder) + output
        if current == 0:
            return output
        current -= 1


def _unavailable(metadata: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "dataset_id": metadata["id"],
        "symbol": metadata["symbol"],
        "asset_class": metadata["asset_class"],
        "reason": reason,
    }


def _iso(value: pd.Timestamp) -> str:
    return value.tz_convert("UTC").isoformat().replace("+00:00", "Z")
