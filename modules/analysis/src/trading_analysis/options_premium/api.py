"""Agent-facing API: build stable JSON payloads for options premium vs underlying."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Sequence

from trading_analysis.market_data import get_polygon_api_key

from .contracts import (
    DEFAULT_DTE_MAX,
    DEFAULT_DTE_MIN,
    DEFAULT_MIN_OI,
    DEFAULT_MIN_VOLUME,
    DEFAULT_MONEYNESS_BAND,
    ContractMeta,
    OptionType,
    list_liquid_contracts,
)
from .series import fetch_option_premium_series, fetch_underlying_series

PLOT_SERIES_CAP = 40


def build_premium_payload(
    ticker: str,
    *,
    start_date: date,
    end_date: date,
    asof: date | None = None,
    dte_min: int = DEFAULT_DTE_MIN,
    dte_max: int = DEFAULT_DTE_MAX,
    min_volume: int = DEFAULT_MIN_VOLUME,
    min_oi: int = DEFAULT_MIN_OI,
    option_type: OptionType | None = None,
    strike_min: float | None = None,
    strike_max: float | None = None,
    expirations: Sequence[str] | None = None,
    symbols: Sequence[str] | None = None,
    selected_symbols: Sequence[str] | None = None,
    include_high: bool = True,
    attach_volume: bool = True,
    throttle_seconds: float = 0.05,
    force_refresh: bool = False,
    api_key: str | None = None,
    series_cap: int = PLOT_SERIES_CAP,
    moneyness_band: float | None = DEFAULT_MONEYNESS_BAND,
) -> dict[str, Any]:
    """
    Build a JSON-serializable payload of underlying OHLC + option premium series.

    ``selected_symbols`` limits which contracts get full history fetched/plotted
    and skips a full-chain liquidity scan. If omitted, liquid contracts in the
    moneyness band are fetched up to ``series_cap``.
    """
    key = api_key or get_polygon_api_key()
    if not key:
        raise RuntimeError("POLYGON_API_KEY is not set.")
    if end_date < start_date:
        raise ValueError("end_date must be >= start_date")

    asof_date = asof or end_date
    exp_set = set(expirations) if expirations else None
    sym_set = {s.upper() for s in symbols} if symbols else None
    selected = {s.upper() for s in selected_symbols} if selected_symbols else None

    if selected:
        # Agent/UI already chose OCC symbols — skip chain-wide volume scans.
        plot_contracts = [
            ContractMeta(
                symbol=sym,
                underlying=ticker.upper(),
                expiration="",
                strike=float("nan"),
                option_type="",
                dte=-1,
            )
            for sym in sorted(selected)
        ]
        contracts = plot_contracts
    else:
        contracts = list_liquid_contracts(
            ticker,
            asof=asof_date,
            dte_min=dte_min,
            dte_max=dte_max,
            min_volume=min_volume,
            min_oi=min_oi,
            option_type=option_type,
            strike_min=strike_min,
            strike_max=strike_max,
            expirations=exp_set,
            symbols=sym_set,
            api_key=key,
            attach_volume=attach_volume,
            throttle_seconds=throttle_seconds,
            force_refresh=force_refresh,
            moneyness_band=moneyness_band,
        )
        plot_contracts = list(contracts)

    truncated = False
    if len(plot_contracts) > series_cap:
        plot_contracts = plot_contracts[:series_cap]
        truncated = True

    underlying = fetch_underlying_series(
        ticker,
        start_date=start_date,
        end_date=end_date,
        api_key=key,
        force_refresh=force_refresh,
    )
    premium_series = fetch_option_premium_series(
        plot_contracts,
        start_date=start_date,
        end_date=end_date,
        api_key=key,
        throttle_seconds=throttle_seconds,
        force_refresh=force_refresh,
    )

    contracts_out = []
    for c in contracts:
        row = c.to_dict()
        series = premium_series.get(c.symbol) or []
        if series:
            row["series_points"] = len(series)
            row["last_close"] = series[-1]["c"]
            row["last_high"] = series[-1]["h"]
        contracts_out.append(row)

    return {
        "ticker": ticker.upper(),
        "asof": asof_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "filters": {
            "dte_min": dte_min,
            "dte_max": dte_max,
            "min_volume": min_volume,
            "min_oi": min_oi,
            "option_type": option_type,
            "strike_min": strike_min,
            "strike_max": strike_max,
            "expirations": sorted(exp_set) if exp_set else None,
            "symbols": sorted(sym_set) if sym_set else None,
            "include_high": include_high,
            "moneyness_band": moneyness_band,
        },
        "liquidity": {
            "contract_count": len(contracts),
            "plotted_count": len(plot_contracts),
            "truncated_to_cap": truncated,
            "series_cap": series_cap,
        },
        "contracts": contracts_out,
        "underlying": underlying,
        "premiums": {
            sym: {
                "close": [{"date": b["date"], "value": b["c"]} for b in bars],
                "high": [{"date": b["date"], "value": b["h"]} for b in bars]
                if include_high
                else [],
                "bars": bars,
            }
            for sym, bars in premium_series.items()
        },
        "bar_source": "polygon_daily",
    }


def default_lookback_window(*, end: date | None = None, days: int = 60) -> tuple[date, date]:
    end_date = end or date.today()
    return end_date - timedelta(days=days), end_date
