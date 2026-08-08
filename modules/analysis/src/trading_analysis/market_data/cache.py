"""On-disk cache layout shared by TPO (underlying 1m) and trade-hold (option 1d)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from .env import REPO_ROOT

ORDER_DATA_DIR = REPO_ROOT / "modules" / "analysis" / "order-data"
DEFAULT_CACHE_ROOT = ORDER_DATA_DIR / "market-data-cache"
DEFAULT_UNDERLYING_MINUTE_CACHE_DIR = DEFAULT_CACHE_ROOT / "underlying" / "1m"
DEFAULT_UNDERLYING_DAILY_CACHE_DIR = DEFAULT_CACHE_ROOT / "underlying" / "1d"
DEFAULT_OPTION_DAILY_CACHE_DIR = DEFAULT_CACHE_ROOT / "options" / "1d"
DEFAULT_OPTION_CONTRACTS_CACHE_DIR = DEFAULT_CACHE_ROOT / "options" / "contracts"
# Pre-unification TPO cache — still read as a fallback so existing files are reused.
LEGACY_TPO_CACHE_DIR = ORDER_DATA_DIR / "tpo-cache"


def underlying_minute_cache_path(
    underlying: str,
    session: date,
    cache_dir: Path = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
) -> Path:
    return cache_dir / underlying.upper() / f"{session.isoformat()}.json"


def legacy_underlying_minute_cache_path(underlying: str, session: date) -> Path:
    return LEGACY_TPO_CACHE_DIR / underlying.upper() / f"{session.isoformat()}.json"


def option_daily_cache_path(
    option_symbol: str,
    cache_dir: Path = DEFAULT_OPTION_DAILY_CACHE_DIR,
) -> Path:
    return cache_dir / f"{option_symbol.upper()}.json"


def underlying_daily_cache_path(
    underlying: str,
    cache_dir: Path = DEFAULT_UNDERLYING_DAILY_CACHE_DIR,
) -> Path:
    return cache_dir / f"{underlying.upper()}.json"


def option_contracts_cache_path(
    underlying: str,
    *,
    asof: date,
    dte_min: int,
    dte_max: int,
    option_type: str | None,
    cache_dir: Path = DEFAULT_OPTION_CONTRACTS_CACHE_DIR,
) -> Path:
    type_key = (option_type or "all").lower()
    name = f"{underlying.upper()}_{asof.isoformat()}_dte{dte_min}-{dte_max}_{type_key}.json"
    return cache_dir / name


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def load_underlying_day_bars(
    underlying: str,
    session: date,
    *,
    cache_dir: Path = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
) -> list[dict[str, object]] | None:
    for path in (
        underlying_minute_cache_path(underlying, session, cache_dir),
        legacy_underlying_minute_cache_path(underlying, session),
    ):
        payload = load_json(path)
        if payload is None:
            continue
        results = payload.get("results")
        if isinstance(results, list):
            return results
    return None


def save_underlying_day_bars(
    underlying: str,
    session: date,
    bars: Sequence[dict[str, object]],
    *,
    cache_dir: Path = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
) -> Path:
    payload = {
        "underlying": underlying.upper(),
        "session": session.isoformat(),
        "timespan": "minute",
        "results": list(bars),
    }
    return write_json(underlying_minute_cache_path(underlying, session, cache_dir), payload)


def load_option_daily_bars(
    option_symbol: str,
    *,
    start_date: date,
    end_date: date,
    cache_dir: Path = DEFAULT_OPTION_DAILY_CACHE_DIR,
) -> list[dict[str, object]] | None:
    payload = load_json(option_daily_cache_path(option_symbol, cache_dir))
    if payload is None:
        return None
    if payload.get("error"):
        # Prior fetch failed — treat as miss so callers can retry or rescan.
        return None
    cached_start = payload.get("start_date")
    cached_end = payload.get("end_date")
    results = payload.get("results")
    if not isinstance(results, list) or not cached_start or not cached_end:
        return None
    try:
        cached_start_d = date.fromisoformat(str(cached_start))
        cached_end_d = date.fromisoformat(str(cached_end))
    except ValueError:
        return None
    if cached_start_d <= start_date and cached_end_d >= end_date:
        return results
    return None


def save_option_daily_bars(
    option_symbol: str,
    *,
    start_date: date,
    end_date: date,
    bars: Sequence[dict[str, object]],
    cache_dir: Path = DEFAULT_OPTION_DAILY_CACHE_DIR,
    error: str | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "symbol": option_symbol.upper(),
        "ticker": f"O:{option_symbol.upper()}",
        "timespan": "day",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "results": list(bars),
    }
    if error:
        payload["error"] = error
    return write_json(option_daily_cache_path(option_symbol, cache_dir), payload)


def load_underlying_daily_bars(
    underlying: str,
    *,
    start_date: date,
    end_date: date,
    cache_dir: Path = DEFAULT_UNDERLYING_DAILY_CACHE_DIR,
) -> list[dict[str, object]] | None:
    payload = load_json(underlying_daily_cache_path(underlying, cache_dir))
    if payload is None:
        return None
    if payload.get("error"):
        return None
    cached_start = payload.get("start_date")
    cached_end = payload.get("end_date")
    results = payload.get("results")
    if not isinstance(results, list) or not cached_start or not cached_end:
        return None
    try:
        cached_start_d = date.fromisoformat(str(cached_start))
        cached_end_d = date.fromisoformat(str(cached_end))
    except ValueError:
        return None
    if cached_start_d <= start_date and cached_end_d >= end_date:
        return results
    return None


def save_underlying_daily_bars(
    underlying: str,
    *,
    start_date: date,
    end_date: date,
    bars: Sequence[dict[str, object]],
    cache_dir: Path = DEFAULT_UNDERLYING_DAILY_CACHE_DIR,
    error: str | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "underlying": underlying.upper(),
        "ticker": underlying.upper(),
        "timespan": "day",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "results": list(bars),
    }
    if error:
        payload["error"] = error
    return write_json(underlying_daily_cache_path(underlying, cache_dir), payload)
