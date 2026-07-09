"""Underlying RTH minute bars with shared on-disk cache (TPO)."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from ..tpo.sessions import RTH_CLOSE, RTH_OPEN, is_rth_session_day, to_ny
from .cache import (
    DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    load_underlying_day_bars,
    save_underlying_day_bars,
)
from .polygon import PolygonHttpError, fetch_aggs


def parse_bar_timestamp(raw_timestamp: object) -> datetime:
    if isinstance(raw_timestamp, (int, float)):
        return datetime.fromtimestamp(raw_timestamp / 1000, tz=timezone.utc)
    raise ValueError(f"Unsupported bar timestamp: {raw_timestamp!r}")


def filter_rth_bars(bars: Sequence[dict[str, object]], session: date) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for bar in bars:
        try:
            ts = parse_bar_timestamp(bar.get("t"))
        except (TypeError, ValueError):
            continue
        local = to_ny(ts)
        if local.date() != session:
            continue
        clock = local.time()
        if RTH_OPEN <= clock <= RTH_CLOSE:
            filtered.append(dict(bar))
    return filtered


def fetch_session_minute_bars(
    underlying: str,
    session: date,
    *,
    cache_dir: Path = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    api_key: str | None = None,
    throttle_seconds: float = 0.0,
    force_refresh: bool = False,
) -> list[dict[str, object]]:
    if not is_rth_session_day(session):
        return []

    if not force_refresh:
        cached = load_underlying_day_bars(underlying, session, cache_dir=cache_dir)
        if cached is not None:
            return filter_rth_bars(cached, session)

    try:
        raw = fetch_aggs(
            underlying.upper(),
            multiplier=1,
            timespan="minute",
            start_date=session,
            end_date=session,
            api_key=api_key,
        )
    except PolygonHttpError as exc:
        if exc.is_unauthorized:
            save_underlying_day_bars(underlying, session, [], cache_dir=cache_dir)
            if throttle_seconds > 0:
                time.sleep(throttle_seconds)
            return []
        raise
    rth = filter_rth_bars(raw, session)
    save_underlying_day_bars(underlying, session, rth, cache_dir=cache_dir)
    if throttle_seconds > 0:
        time.sleep(throttle_seconds)
    return rth


def fetch_sessions_minute_bars(
    underlying: str,
    sessions: Sequence[date],
    *,
    cache_dir: Path = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    api_key: str | None = None,
    throttle_seconds: float = 0.12,
    force_refresh: bool = False,
) -> dict[date, list[dict[str, object]]]:
    by_day: dict[date, list[dict[str, object]]] = {}
    missing: list[date] = []
    for session in sessions:
        if not force_refresh:
            cached = load_underlying_day_bars(underlying, session, cache_dir=cache_dir)
            if cached is not None:
                by_day[session] = filter_rth_bars(cached, session)
                continue
        missing.append(session)

    if not missing:
        return by_day

    missing_sorted = sorted(missing)
    range_start = missing_sorted[0]
    range_end = missing_sorted[0]
    ranges: list[tuple[date, date]] = []
    for day in missing_sorted[1:]:
        if (day - range_end).days <= 3:
            range_end = day
        else:
            ranges.append((range_start, range_end))
            range_start = day
            range_end = day
    ranges.append((range_start, range_end))

    for start, end in ranges:
        try:
            raw = fetch_aggs(
                underlying.upper(),
                multiplier=1,
                timespan="minute",
                start_date=start,
                end_date=end,
                api_key=api_key,
            )
            _bucket_and_save(
                underlying,
                raw,
                sessions=missing_sorted,
                range_start=start,
                range_end=end,
                by_day=by_day,
                cache_dir=cache_dir,
            )
        except PolygonHttpError as exc:
            # Limited Polygon plans often 403 multi-day minute ranges; retry day-by-day.
            if not exc.is_unauthorized or start == end:
                raise
            for session in missing_sorted:
                if not (start <= session <= end):
                    continue
                if session in by_day:
                    continue
                try:
                    day_raw = fetch_aggs(
                        underlying.upper(),
                        multiplier=1,
                        timespan="minute",
                        start_date=session,
                        end_date=session,
                        api_key=api_key,
                    )
                    rth = filter_rth_bars(day_raw, session)
                    save_underlying_day_bars(underlying, session, rth, cache_dir=cache_dir)
                    by_day[session] = rth
                except PolygonHttpError as day_exc:
                    # Persist empty day so we don't keep re-hitting unauthorized dates.
                    if day_exc.is_unauthorized:
                        save_underlying_day_bars(underlying, session, [], cache_dir=cache_dir)
                    by_day.setdefault(session, [])
                if throttle_seconds > 0:
                    time.sleep(throttle_seconds)
            continue
        if throttle_seconds > 0:
            time.sleep(throttle_seconds)

    return by_day


def _bucket_and_save(
    underlying: str,
    raw: Sequence[dict[str, object]],
    *,
    sessions: Sequence[date],
    range_start: date,
    range_end: date,
    by_day: dict[date, list[dict[str, object]]],
    cache_dir: Path,
) -> None:
    buckets: dict[date, list[dict[str, object]]] = {}
    for bar in raw:
        try:
            ts = parse_bar_timestamp(bar.get("t"))
        except (TypeError, ValueError):
            continue
        local = to_ny(ts)
        buckets.setdefault(local.date(), []).append(dict(bar))
    for session in sessions:
        if range_start <= session <= range_end:
            rth = filter_rth_bars(buckets.get(session, []), session)
            save_underlying_day_bars(underlying, session, rth, cache_dir=cache_dir)
            by_day[session] = rth


def underlying_price_at(
    bars: Sequence[dict[str, object]],
    when: datetime,
) -> tuple[float | None, str]:
    """Return (price, source) nearest to `when` among RTH minute bars."""
    if not bars:
        return None, "missing"

    target = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    best: tuple[float, dict[str, object]] | None = None
    for bar in bars:
        try:
            ts = parse_bar_timestamp(bar.get("t"))
        except (TypeError, ValueError):
            continue
        delta = abs((ts - target).total_seconds())
        if best is None or delta < best[0]:
            best = (delta, bar)

    if best is None:
        return None, "missing"

    delta_sec, bar = best
    close = float(bar["c"])
    if delta_sec <= 60:
        return close, "exact_minute"
    if delta_sec <= 5 * 60:
        return close, "nearest_minute"
    return close, "nearest_minute_far"
