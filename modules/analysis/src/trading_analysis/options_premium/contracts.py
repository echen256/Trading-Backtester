"""Polygon option contract discovery with DTE + liquidity filters."""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from trading_analysis.market_data.cache import (
    DEFAULT_OPTION_CONTRACTS_CACHE_DIR,
    load_json,
    option_contracts_cache_path,
    write_json,
)
from trading_analysis.market_data.env import get_polygon_api_key
from trading_analysis.market_data.option_dailies import fetch_option_daily_bars
from trading_analysis.market_data.polygon import PolygonHttpError, _request_json

OptionType = Literal["call", "put"]

POLYGON_CONTRACTS_URL = "https://api.polygon.io/v3/reference/options/contracts"

DEFAULT_DTE_MIN = 15
DEFAULT_DTE_MAX = 60
DEFAULT_MIN_VOLUME = 1
DEFAULT_MIN_OI = 0
# Only attach volume for strikes within ± this fraction of spot (keeps scans tractable).
DEFAULT_MONEYNESS_BAND = 0.5


@dataclass(slots=True)
class ContractMeta:
    symbol: str
    underlying: str
    expiration: str
    strike: float
    option_type: str
    dte: int
    open_interest: int | None = None
    last_volume: int | None = None
    shares_per_contract: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bar_date(ts_ms: object) -> date:
    return datetime.fromtimestamp(int(ts_ms) / 1000, timezone.utc).date()


def _normalize_occ_symbol(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if symbol.startswith("O:"):
        symbol = symbol[2:]
    return symbol


def _fetch_contracts_page(
    *,
    underlying: str,
    expiration_gte: date,
    expiration_lte: date,
    option_type: OptionType | None,
    api_key: str,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    params: dict[str, str | int] = {
        "underlying_ticker": underlying.upper(),
        "expiration_date.gte": expiration_gte.isoformat(),
        "expiration_date.lte": expiration_lte.isoformat(),
        "limit": 1000,
        "sort": "expiration_date",
        "order": "asc",
        "apiKey": api_key,
    }
    if option_type in ("call", "put"):
        params["contract_type"] = option_type

    url: str | None = f"{POLYGON_CONTRACTS_URL}?{urllib.parse.urlencode(params)}"
    results: list[dict[str, Any]] = []
    while url:
        payload = _request_json(url, key=api_key, timeout=timeout, max_retries=3)
        page = payload.get("results")
        if isinstance(page, list):
            results.extend(r for r in page if isinstance(r, dict))
        next_url = payload.get("next_url")
        if isinstance(next_url, str) and next_url:
            sep = "&" if "?" in next_url else "?"
            url = f"{next_url}{sep}apiKey={urllib.parse.quote(api_key)}"
        else:
            url = None
    return results


def _load_cached_contracts(
    underlying: str,
    *,
    asof: date,
    dte_min: int,
    dte_max: int,
    option_type: OptionType | None,
    cache_dir: Path,
) -> list[dict[str, Any]] | None:
    path = option_contracts_cache_path(
        underlying,
        asof=asof,
        dte_min=dte_min,
        dte_max=dte_max,
        option_type=option_type,
        cache_dir=cache_dir,
    )
    payload = load_json(path)
    if not payload or payload.get("error"):
        return None
    results = payload.get("results")
    return results if isinstance(results, list) else None


def _save_cached_contracts(
    underlying: str,
    *,
    asof: date,
    dte_min: int,
    dte_max: int,
    option_type: OptionType | None,
    results: list[dict[str, Any]],
    cache_dir: Path,
    error: str | None = None,
) -> Path:
    path = option_contracts_cache_path(
        underlying,
        asof=asof,
        dte_min=dte_min,
        dte_max=dte_max,
        option_type=option_type,
        cache_dir=cache_dir,
    )
    payload: dict[str, Any] = {
        "underlying": underlying.upper(),
        "asof": asof.isoformat(),
        "dte_min": dte_min,
        "dte_max": dte_max,
        "option_type": option_type or "all",
        "results": results,
    }
    if error:
        payload["error"] = error
    return write_json(path, payload)


def list_contracts(
    ticker: str,
    *,
    asof: date | None = None,
    dte_min: int = DEFAULT_DTE_MIN,
    dte_max: int = DEFAULT_DTE_MAX,
    option_type: OptionType | None = None,
    api_key: str | None = None,
    cache_dir: Path = DEFAULT_OPTION_CONTRACTS_CACHE_DIR,
    force_refresh: bool = False,
) -> list[ContractMeta]:
    """List option contracts for ``ticker`` in the DTE window as of ``asof``."""
    if dte_min < 0 or dte_max < dte_min:
        raise ValueError(f"Invalid DTE window: {dte_min}-{dte_max}")
    asof_date = asof or date.today()
    key = api_key or get_polygon_api_key()
    if not key:
        raise RuntimeError("POLYGON_API_KEY is not set.")

    underlying = ticker.upper()
    if not force_refresh:
        cached = _load_cached_contracts(
            underlying,
            asof=asof_date,
            dte_min=dte_min,
            dte_max=dte_max,
            option_type=option_type,
            cache_dir=cache_dir,
        )
        if cached is not None:
            return [_contract_from_raw(r, asof_date) for r in cached if isinstance(r, dict)]

    expiration_gte = asof_date + timedelta(days=dte_min)
    expiration_lte = asof_date + timedelta(days=dte_max)
    try:
        raw = _fetch_contracts_page(
            underlying=underlying,
            expiration_gte=expiration_gte,
            expiration_lte=expiration_lte,
            option_type=option_type,
            api_key=key,
        )
    except PolygonHttpError as exc:
        _save_cached_contracts(
            underlying,
            asof=asof_date,
            dte_min=dte_min,
            dte_max=dte_max,
            option_type=option_type,
            results=[],
            cache_dir=cache_dir,
            error=str(exc),
        )
        raise

    _save_cached_contracts(
        underlying,
        asof=asof_date,
        dte_min=dte_min,
        dte_max=dte_max,
        option_type=option_type,
        results=raw,
        cache_dir=cache_dir,
    )
    return [_contract_from_raw(r, asof_date) for r in raw]


def _contract_from_raw(raw: dict[str, Any], asof: date) -> ContractMeta:
    ticker = str(raw.get("ticker") or "")
    symbol = _normalize_occ_symbol(ticker)
    exp_raw = str(raw.get("expiration_date") or "")
    try:
        exp = date.fromisoformat(exp_raw)
        dte = (exp - asof).days
    except ValueError:
        exp_raw = exp_raw or ""
        dte = -1
    oi = raw.get("open_interest")
    try:
        open_interest = int(oi) if oi is not None else None
    except (TypeError, ValueError):
        open_interest = None
    spc = raw.get("shares_per_contract")
    try:
        shares = int(spc) if spc is not None else None
    except (TypeError, ValueError):
        shares = None
    strike_raw = raw.get("strike_price")
    try:
        strike = float(strike_raw)
    except (TypeError, ValueError):
        strike = float("nan")
    ctype = str(raw.get("contract_type") or "").lower()
    underlying = str(raw.get("underlying_ticker") or "").upper()
    return ContractMeta(
        symbol=symbol,
        underlying=underlying,
        expiration=exp_raw,
        strike=strike,
        option_type=ctype,
        dte=dte,
        open_interest=open_interest,
        shares_per_contract=shares,
    )


def attach_liquidity(
    contracts: list[ContractMeta],
    *,
    asof: date,
    lookback_days: int = 10,
    api_key: str | None = None,
    throttle_seconds: float = 0.05,
    force_refresh: bool = False,
) -> list[ContractMeta]:
    """Populate ``last_volume`` from the most recent option daily bar."""
    from trading_analysis.market_data.cache import load_option_daily_bars

    start = asof - timedelta(days=max(lookback_days, 1))
    enriched: list[ContractMeta] = []
    for contract in contracts:
        last_volume: int | None = None
        cache_hit = (
            not force_refresh
            and load_option_daily_bars(
                contract.symbol, start_date=start, end_date=asof
            )
            is not None
        )
        try:
            bars = fetch_option_daily_bars(
                contract.symbol,
                start_date=start,
                end_date=asof,
                api_key=api_key,
                throttle_seconds=0.0,
                force_refresh=force_refresh,
            )
            if bars:
                # Prefer the latest bar on/before asof.
                dated = sorted(
                    (
                        (_bar_date(b["t"]), b)
                        for b in bars
                        if isinstance(b, dict) and "t" in b
                    ),
                    key=lambda pair: pair[0],
                )
                if dated:
                    vol = dated[-1][1].get("v")
                    try:
                        last_volume = int(vol) if vol is not None else 0
                    except (TypeError, ValueError):
                        last_volume = 0
        except PolygonHttpError:
            last_volume = None
        enriched.append(
            ContractMeta(
                symbol=contract.symbol,
                underlying=contract.underlying,
                expiration=contract.expiration,
                strike=contract.strike,
                option_type=contract.option_type,
                dte=contract.dte,
                open_interest=contract.open_interest,
                last_volume=last_volume,
                shares_per_contract=contract.shares_per_contract,
            )
        )
        if throttle_seconds > 0 and not cache_hit:
            time.sleep(throttle_seconds)
    return enriched


def filter_liquid_contracts(
    contracts: list[ContractMeta],
    *,
    min_volume: int = DEFAULT_MIN_VOLUME,
    min_oi: int = DEFAULT_MIN_OI,
    strike_min: float | None = None,
    strike_max: float | None = None,
    expirations: set[str] | None = None,
    symbols: set[str] | None = None,
    option_type: OptionType | None = None,
) -> list[ContractMeta]:
    out: list[ContractMeta] = []
    for c in contracts:
        if option_type and c.option_type != option_type:
            continue
        if symbols is not None and c.symbol.upper() not in symbols:
            continue
        if expirations is not None and c.expiration not in expirations:
            continue
        if strike_min is not None and not (c.strike >= strike_min):
            continue
        if strike_max is not None and not (c.strike <= strike_max):
            continue
        if min_oi > 0:
            oi = c.open_interest if c.open_interest is not None else 0
            if oi < min_oi:
                continue
        if min_volume > 0:
            # Unknown volume (fetch failed) is excluded when a threshold is set.
            vol = c.last_volume if c.last_volume is not None else -1
            if vol < min_volume:
                continue
        out.append(c)
    return sorted(out, key=lambda c: (c.expiration, c.option_type, c.strike, c.symbol))


def _resolve_spot(ticker: str, asof: date, api_key: str | None) -> float | None:
    """Best-effort underlying close on/before asof for moneyness banding."""
    try:
        from trading_analysis.market_data import fetch_underlying_daily_bars

        bars = fetch_underlying_daily_bars(
            ticker,
            start_date=asof - timedelta(days=10),
            end_date=asof,
            api_key=api_key,
        )
    except PolygonHttpError:
        return None
    dated: list[tuple[date, float]] = []
    for bar in bars:
        if not isinstance(bar, dict) or "t" not in bar or "c" not in bar:
            continue
        try:
            dated.append((_bar_date(bar["t"]), float(bar["c"])))
        except (TypeError, ValueError):
            continue
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0])
    return dated[-1][1]


def list_liquid_contracts(
    ticker: str,
    *,
    asof: date | None = None,
    dte_min: int = DEFAULT_DTE_MIN,
    dte_max: int = DEFAULT_DTE_MAX,
    min_volume: int = DEFAULT_MIN_VOLUME,
    min_oi: int = DEFAULT_MIN_OI,
    option_type: OptionType | None = None,
    strike_min: float | None = None,
    strike_max: float | None = None,
    expirations: set[str] | None = None,
    symbols: set[str] | None = None,
    api_key: str | None = None,
    attach_volume: bool = True,
    throttle_seconds: float = 0.05,
    force_refresh: bool = False,
    moneyness_band: float | None = DEFAULT_MONEYNESS_BAND,
) -> list[ContractMeta]:
    """Discover contracts in DTE band and keep those meeting liquidity filters.

    When ``moneyness_band`` is set (default 0.5) and strike min/max are not,
    volume attachment is limited to strikes within ±band of spot so deep
    worthless chains do not trigger thousands of Polygon calls.
    """
    asof_date = asof or date.today()
    contracts = list_contracts(
        ticker,
        asof=asof_date,
        dte_min=dte_min,
        dte_max=dte_max,
        option_type=option_type,
        api_key=api_key,
        force_refresh=force_refresh,
    )

    eff_strike_min = strike_min
    eff_strike_max = strike_max
    if (
        moneyness_band is not None
        and moneyness_band > 0
        and strike_min is None
        and strike_max is None
        and not symbols
    ):
        spot = _resolve_spot(ticker, asof_date, api_key)
        if spot and spot > 0:
            eff_strike_min = spot * (1.0 - moneyness_band)
            eff_strike_max = spot * (1.0 + moneyness_band)

    # Pre-filter by static fields before volume fetches.
    pre = filter_liquid_contracts(
        contracts,
        min_volume=0,
        min_oi=min_oi,
        strike_min=eff_strike_min,
        strike_max=eff_strike_max,
        expirations=expirations,
        symbols=symbols,
        option_type=option_type,
    )
    if attach_volume and min_volume > 0:
        pre = attach_liquidity(
            pre,
            asof=asof_date,
            api_key=api_key,
            throttle_seconds=throttle_seconds,
            force_refresh=force_refresh,
        )
    return filter_liquid_contracts(
        pre,
        min_volume=min_volume,
        min_oi=0 if min_oi <= 0 else min_oi,
        strike_min=eff_strike_min,
        strike_max=eff_strike_max,
        expirations=expirations,
        symbols=symbols,
        option_type=option_type,
    )
