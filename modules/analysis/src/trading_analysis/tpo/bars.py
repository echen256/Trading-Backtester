"""Polygon minute-bar fetch with per-day on-disk cache."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from .sessions import RTH_CLOSE, RTH_OPEN, is_rth_session_day, to_ny

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
POLYGON_API_BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
DEFAULT_CACHE_DIR = REPO_ROOT / "modules" / "analysis" / "order-data" / "tpo-cache"


def parse_bar_timestamp(raw_timestamp: object) -> datetime:
    if isinstance(raw_timestamp, (int, float)):
        return datetime.fromtimestamp(raw_timestamp / 1000, tz=timezone.utc)
    raise ValueError(f"Unsupported bar timestamp: {raw_timestamp!r}")


def _get_polygon_api_key() -> str | None:
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key:
        return api_key
    return _load_env_value(DEFAULT_ENV_PATH, "POLYGON_API_KEY")


def _load_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            os.environ[key] = cleaned
            return cleaned
    return None


def cache_path_for(underlying: str, session: date, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / underlying.upper() / f"{session.isoformat()}.json"


def load_cached_day_bars(
    underlying: str,
    session: date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[dict[str, object]] | None:
    path = cache_path_for(underlying, session, cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    return results


def save_day_bars(
    underlying: str,
    session: date,
    bars: Sequence[dict[str, object]],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    path = cache_path_for(underlying, session, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "underlying": underlying.upper(),
        "session": session.isoformat(),
        "results": list(bars),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def fetch_minute_bars_polygon(
    ticker: str,
    start_date: date,
    end_date: date,
    *,
    api_key: str | None = None,
) -> list[dict[str, object]]:
    key = api_key or _get_polygon_api_key()
    if not key:
        raise RuntimeError(
            f"POLYGON_API_KEY is not set. Expected it in the environment or {DEFAULT_ENV_PATH}."
        )

    all_results: list[dict[str, object]] = []
    query = urllib.parse.urlencode(
        {
            "apiKey": key,
            "limit": 50000,
            "adjusted": "true",
            "sort": "asc",
        }
    )
    url: str | None = (
        f"{POLYGON_API_BASE_URL}/{ticker}/range/1/minute/"
        f"{start_date.isoformat()}/{end_date.isoformat()}?{query}"
    )
    while url:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Polygon minute request failed ({exc.code}): {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Polygon for minute bars: {url}") from exc

        results = payload.get("results")
        if isinstance(results, list):
            all_results.extend(results)

        next_url = payload.get("next_url")
        if isinstance(next_url, str) and next_url:
            sep = "&" if "?" in next_url else "?"
            url = f"{next_url}{sep}apiKey={urllib.parse.quote(key)}"
        else:
            url = None

    return all_results


def fetch_session_minute_bars(
    underlying: str,
    session: date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    api_key: str | None = None,
    throttle_seconds: float = 0.0,
    force_refresh: bool = False,
) -> list[dict[str, object]]:
    if not is_rth_session_day(session):
        return []

    if not force_refresh:
        cached = load_cached_day_bars(underlying, session, cache_dir=cache_dir)
        if cached is not None:
            return filter_rth_bars(cached, session)

    raw = fetch_minute_bars_polygon(underlying.upper(), session, session, api_key=api_key)
    rth = filter_rth_bars(raw, session)
    save_day_bars(underlying, session, rth, cache_dir=cache_dir)
    if throttle_seconds > 0:
        time.sleep(throttle_seconds)
    return rth


def fetch_sessions_minute_bars(
    underlying: str,
    sessions: Sequence[date],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    api_key: str | None = None,
    throttle_seconds: float = 0.12,
    force_refresh: bool = False,
) -> dict[date, list[dict[str, object]]]:
    by_day: dict[date, list[dict[str, object]]] = {}
    missing: list[date] = []
    for session in sessions:
        if not force_refresh:
            cached = load_cached_day_bars(underlying, session, cache_dir=cache_dir)
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

    key = api_key or _get_polygon_api_key()
    for start, end in ranges:
        raw = fetch_minute_bars_polygon(underlying.upper(), start, end, api_key=key)
        buckets: dict[date, list[dict[str, object]]] = {}
        for bar in raw:
            try:
                ts = parse_bar_timestamp(bar.get("t"))
            except (TypeError, ValueError):
                continue
            local = to_ny(ts)
            buckets.setdefault(local.date(), []).append(dict(bar))
        for session in missing_sorted:
            if start <= session <= end:
                rth = filter_rth_bars(buckets.get(session, []), session)
                save_day_bars(underlying, session, rth, cache_dir=cache_dir)
                by_day[session] = rth
        if throttle_seconds > 0:
            time.sleep(throttle_seconds)

    return by_day


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
