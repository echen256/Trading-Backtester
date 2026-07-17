"""Fetch underlying + option premium daily series."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Sequence

from trading_analysis.market_data import (
    PolygonHttpError,
    fetch_option_daily_bars,
    fetch_underlying_daily_bars,
)

from .contracts import ContractMeta


def _bar_date(ts_ms: object) -> str:
    return datetime.fromtimestamp(int(ts_ms) / 1000, timezone.utc).date().isoformat()


def _normalize_bar(bar: dict[str, object]) -> dict[str, Any] | None:
    if "t" not in bar:
        return None
    try:
        return {
            "date": _bar_date(bar["t"]),
            "o": float(bar["o"]),  # type: ignore[arg-type]
            "h": float(bar["h"]),  # type: ignore[arg-type]
            "l": float(bar["l"]),  # type: ignore[arg-type]
            "c": float(bar["c"]),  # type: ignore[arg-type]
            "v": int(bar["v"]) if bar.get("v") is not None else 0,
            "t": int(bar["t"]),  # type: ignore[arg-type]
        }
    except (TypeError, ValueError, KeyError):
        return None


def fetch_underlying_series(
    ticker: str,
    *,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    bars = fetch_underlying_daily_bars(
        ticker,
        start_date=start_date,
        end_date=end_date,
        api_key=api_key,
        force_refresh=force_refresh,
    )
    out: list[dict[str, Any]] = []
    for bar in bars:
        if isinstance(bar, dict):
            norm = _normalize_bar(bar)
            if norm is not None:
                out.append(norm)
    return out


def fetch_option_premium_series(
    contracts: Sequence[ContractMeta | str],
    *,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
    throttle_seconds: float = 0.05,
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Return ``{occ_symbol: [normalized daily bars]}`` for each contract."""
    from trading_analysis.market_data.cache import load_option_daily_bars

    series: dict[str, list[dict[str, Any]]] = {}
    for item in contracts:
        symbol = item.symbol if isinstance(item, ContractMeta) else str(item).upper()
        cache_hit = (
            not force_refresh
            and load_option_daily_bars(
                symbol, start_date=start_date, end_date=end_date
            )
            is not None
        )
        try:
            bars = fetch_option_daily_bars(
                symbol,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
                throttle_seconds=0.0,
                force_refresh=force_refresh,
            )
        except PolygonHttpError:
            series[symbol] = []
            if throttle_seconds > 0 and not cache_hit:
                time.sleep(throttle_seconds)
            continue
        normed: list[dict[str, Any]] = []
        for bar in bars:
            if isinstance(bar, dict):
                norm = _normalize_bar(bar)
                if norm is not None:
                    normed.append(norm)
        series[symbol] = normed
        if throttle_seconds > 0 and not cache_hit:
            time.sleep(throttle_seconds)
    return series
