"""Streamlit UI — thin wrapper over options_premium agent API."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Ensure `streamlit run .../app.py` can import the package when not installed editable.
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st

from trading_analysis.options_premium.api import (
    PLOT_SERIES_CAP,
    build_premium_payload,
    default_lookback_window,
)
from trading_analysis.options_premium.chart import build_premium_figure
from trading_analysis.options_premium.contracts import (
    DEFAULT_DTE_MAX,
    DEFAULT_DTE_MIN,
    DEFAULT_MIN_OI,
    DEFAULT_MIN_VOLUME,
    DEFAULT_MONEYNESS_BAND,
    list_liquid_contracts,
)
from trading_analysis.options_premium.watchlist import (
    DEFAULT_WATCHLIST_PATH,
    load_watchlist,
)


def _run() -> None:
    st.set_page_config(page_title="Options Premium vs Underlying", layout="wide")
    st.title("Options Premium vs Underlying")
    st.caption(
        "Thin UI over `build_premium_payload` / Polygon daily cache. "
        f"Watchlist: `{DEFAULT_WATCHLIST_PATH}`"
    )

    watchlist = load_watchlist()
    with st.sidebar:
        st.header("Filters")
        source = st.radio("Ticker source", ["Watchlist", "Custom"], horizontal=True)
        if source == "Watchlist":
            if not watchlist:
                st.warning(f"Empty watchlist — add tickers to {DEFAULT_WATCHLIST_PATH}")
                ticker = st.text_input("Symbol", value="MU").strip().upper()
            else:
                ticker = st.selectbox("Symbol", watchlist)
        else:
            ticker = (
                st.text_input("Symbol", value=watchlist[0] if watchlist else "MU")
                .strip()
                .upper()
            )

        today = date.today()
        default_start, default_end = default_lookback_window(end=today, days=60)
        start_date = st.date_input("Start", value=default_start)
        end_date = st.date_input("End", value=default_end)
        asof = st.date_input("DTE as-of", value=end_date)

        dte_min = st.number_input("DTE min", min_value=0, max_value=365, value=DEFAULT_DTE_MIN)
        dte_max = st.number_input("DTE max", min_value=0, max_value=730, value=DEFAULT_DTE_MAX)
        min_volume = st.number_input("Min volume", min_value=0, value=DEFAULT_MIN_VOLUME)
        min_oi = st.number_input("Min open interest", min_value=0, value=DEFAULT_MIN_OI)
        opt_type = st.selectbox("Type", ["both", "call", "put"], index=0)
        option_type = None if opt_type == "both" else opt_type

        show_close = st.checkbox("Plot premium close", value=True)
        show_high = st.checkbox("Plot premium high", value=True)
        force_refresh = st.checkbox("Force refresh Polygon", value=False)
        series_cap = st.number_input("Series cap", min_value=1, max_value=200, value=PLOT_SERIES_CAP)
        moneyness_band = st.number_input(
            "Moneyness band (±spot)",
            min_value=0.0,
            max_value=2.0,
            value=float(DEFAULT_MONEYNESS_BAND),
            step=0.05,
            help="0 = scan all strikes (slow). Default limits volume scan near spot.",
        )

        load_contracts = st.button("List liquid contracts", type="secondary")
        run_chart = st.button("Build chart", type="primary")

    if not ticker:
        st.stop()

    if "contracts" not in st.session_state:
        st.session_state.contracts = []
    if "contracts_ticker" not in st.session_state:
        st.session_state.contracts_ticker = ""

    if load_contracts or (run_chart and st.session_state.contracts_ticker != ticker):
        with st.spinner(
            f"Listing liquid {int(dte_min)}-{int(dte_max)} DTE contracts for {ticker}…"
        ):
            try:
                contracts = list_liquid_contracts(
                    ticker,
                    asof=asof,
                    dte_min=int(dte_min),
                    dte_max=int(dte_max),
                    min_volume=int(min_volume),
                    min_oi=int(min_oi),
                    option_type=option_type,
                    force_refresh=force_refresh,
                    moneyness_band=None if moneyness_band == 0 else float(moneyness_band),
                )
            except Exception as exc:  # noqa: BLE001 — surface to UI
                st.error(str(exc))
                st.stop()
        st.session_state.contracts = contracts
        st.session_state.contracts_ticker = ticker

    contracts = st.session_state.contracts
    pick_expiries = None
    strike_lo = strike_hi = None
    selected = None

    if contracts and st.session_state.contracts_ticker == ticker:
        expiries = sorted({c.expiration for c in contracts if c.expiration})
        strikes = sorted({c.strike for c in contracts if c.strike == c.strike})
        labels = [
            f"{c.symbol}  {c.option_type} {c.strike:g} exp {c.expiration}  "
            f"vol={c.last_volume} oi={c.open_interest}"
            for c in contracts
        ]
        label_to_symbol = {labels[i]: contracts[i].symbol for i in range(len(contracts))}

        col_a, col_b = st.columns(2)
        with col_a:
            pick_expiries = st.multiselect("Expiries", expiries, default=expiries)
        with col_b:
            if strikes:
                strike_lo, strike_hi = st.select_slider(
                    "Strike range",
                    options=strikes,
                    value=(strikes[0], strikes[-1]),
                )

        default_labels = labels[: min(len(labels), int(series_cap))]
        picked_labels = st.multiselect(
            "Contracts to plot",
            labels,
            default=default_labels,
        )
        selected = [label_to_symbol[lab] for lab in picked_labels]

        if len(selected) > int(series_cap):
            st.warning(
                f"{len(selected)} series selected — cap is {int(series_cap)}. "
                "Trim selection or raise series cap."
            )
            confirm = st.checkbox("Plot anyway (may be slow / crowded)", value=False)
            if not confirm:
                selected = selected[: int(series_cap)]

        st.write(f"**{len(contracts)}** liquid contracts · plotting **{len(selected)}**")
    else:
        st.info("Click **List liquid contracts** (or Build chart) to load the option chain.")

    if run_chart:
        if start_date > end_date:
            st.error("Start date must be on or before end date.")
            st.stop()
        with st.spinner("Fetching underlying + premiums…"):
            try:
                payload = build_premium_payload(
                    ticker,
                    start_date=start_date,
                    end_date=end_date,
                    asof=asof,
                    dte_min=int(dte_min),
                    dte_max=int(dte_max),
                    min_volume=int(min_volume),
                    min_oi=int(min_oi),
                    option_type=option_type,
                    strike_min=float(strike_lo) if strike_lo is not None else None,
                    strike_max=float(strike_hi) if strike_hi is not None else None,
                    expirations=pick_expiries,
                    selected_symbols=selected,
                    include_high=show_high,
                    force_refresh=force_refresh,
                    series_cap=max(int(series_cap), len(selected or [])),
                    moneyness_band=None if moneyness_band == 0 else float(moneyness_band),
                )
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
                st.stop()

        liq = payload.get("liquidity") or {}
        st.success(
            f"Loaded {liq.get('contract_count', 0)} liquid · "
            f"plotted {liq.get('plotted_count', 0)}"
            + (" (truncated)" if liq.get("truncated_to_cap") else "")
        )
        fig = build_premium_figure(
            payload,
            selected_symbols=selected,
            show_close=show_close,
            show_high=show_high,
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("Payload meta / contracts"):
            st.json(
                {
                    "filters": payload.get("filters"),
                    "liquidity": payload.get("liquidity"),
                    "contracts": payload.get("contracts"),
                }
            )


_run()
