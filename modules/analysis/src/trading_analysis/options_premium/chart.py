"""Plotly chart: underlying candlesticks + option premium overlays."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_premium_figure(
    payload: dict[str, Any],
    *,
    selected_symbols: Sequence[str] | None = None,
    show_close: bool = True,
    show_high: bool = True,
    title: str | None = None,
) -> go.Figure:
    underlying = payload.get("underlying") or []
    premiums = payload.get("premiums") or {}
    ticker = str(payload.get("ticker") or "")

    if selected_symbols:
        want = {s.upper() for s in selected_symbols}
        symbols = [s for s in premiums if s in want]
    else:
        symbols = sorted(premiums.keys())

    dates = [b["date"] for b in underlying]
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.55, 0.45],
        subplot_titles=(
            f"{ticker} underlying (daily)",
            "Option premium ($)",
        ),
    )

    if underlying:
        fig.add_trace(
            go.Candlestick(
                x=dates,
                open=[b["o"] for b in underlying],
                high=[b["h"] for b in underlying],
                low=[b["l"] for b in underlying],
                close=[b["c"] for b in underlying],
                name=f"{ticker} OHLC",
                increasing_line_color="#2ca02c",
                decreasing_line_color="#d62728",
            ),
            row=1,
            col=1,
        )

    for symbol in symbols:
        series = premiums.get(symbol) or {}
        if show_close:
            closes = series.get("close") or []
            if closes:
                fig.add_trace(
                    go.Scatter(
                        x=[p["date"] for p in closes],
                        y=[p["value"] for p in closes],
                        mode="lines",
                        name=f"{symbol} close",
                        line={"width": 1.5},
                    ),
                    row=2,
                    col=1,
                )
        if show_high:
            highs = series.get("high") or []
            if highs:
                fig.add_trace(
                    go.Scatter(
                        x=[p["date"] for p in highs],
                        y=[p["value"] for p in highs],
                        mode="lines",
                        name=f"{symbol} high",
                        line={"width": 1, "dash": "dot"},
                        opacity=0.7,
                    ),
                    row=2,
                    col=1,
                )

    filters = payload.get("filters") or {}
    dte_min = filters.get("dte_min")
    dte_max = filters.get("dte_max")
    chart_title = title or (
        f"{ticker} premiums vs underlying"
        + (f" · DTE {dte_min}-{dte_max}" if dte_min is not None else "")
    )
    fig.update_layout(
        title=chart_title,
        template="plotly_white",
        height=720,
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        margin={"l": 60, "r": 20, "t": 80, "b": 40},
    )
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="Premium ($)", row=2, col=1)
    fig.update_xaxes(title_text="Date", row=2, col=1)
    return fig


def write_premium_chart_html(
    payload: dict[str, Any],
    output_path: Path,
    *,
    selected_symbols: Sequence[str] | None = None,
    show_close: bool = True,
    show_high: bool = True,
    auto_open: bool = False,
) -> Path:
    figure = build_premium_figure(
        payload,
        selected_symbols=selected_symbols,
        show_close=show_close,
        show_high=show_high,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(output_path), auto_open=auto_open, include_plotlyjs="cdn")
    return output_path
