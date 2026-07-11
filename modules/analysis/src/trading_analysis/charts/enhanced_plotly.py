"""Reusable Plotly chart with horizontal scroll and vertical zoom/pan."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

FISHER_OVERBOUGHT = 2.0
FISHER_OVERSOLD = -2.0
# Keep arrows near the Fisher line (fraction of indicator pane range).
ARROW_OFFSET_FRACTION = 0.06
# Cluster markers whose timestamps fall on the same calendar day.
STACK_WINDOW = timedelta(days=1)


@dataclass(slots=True)
class AnnotatedTradeMarker:
    """A single entry or exit annotation plotted on the indicator pane."""

    timestamp: datetime
    y_value: float
    kind: str  # "entry" | "exit"
    instrument: str
    trade_id: str = ""
    pair_timestamp: datetime | None = None
    realized_pnl: float | None = None
    missed_pnl: float | None = None
    missed_pnl_label: str | None = None
    trade_quality: str | None = None
    quality_score: float | None = None
    quantity: float | None = None
    open_price: float | None = None
    close_price: float | None = None
    ideal_exit_date: str | None = None
    ideal_exit_price: float | None = None
    ideal_exit_label: str | None = None
    underlying: str | None = None
    entry_datetime: str | None = None
    exit_datetime: str | None = None
    strike: float | None = None
    expiration: str | None = None
    option_type: str | None = None
    extra_lines: list[str] = field(default_factory=list)

    def hover_text(self) -> str:
        lines = [
            f"<b>{self.kind.title()}</b>",
            f"Instrument: {self.instrument}",
            f"Time: {self.timestamp.strftime('%Y-%m-%d %H:%M')}",
        ]
        if self.strike is not None:
            strike_text = (
                f"{self.strike:.0f}" if float(self.strike).is_integer() else f"{self.strike:g}"
            )
            lines.append(f"Strike: {strike_text}")
        if self.expiration:
            lines.append(f"Expiration: {self.expiration}")
        if self.option_type:
            lines.append(f"Type: {self.option_type.title()}")
        if self.y_value is not None:
            lines.append(f"Fisher: {self.y_value:.3f}")
        if self.quantity is not None:
            lines.append(f"Qty: {self.quantity:g}")
        if self.open_price is not None and self.kind == "entry":
            lines.append(f"Open: {self.open_price:.4g}")
        if self.close_price is not None and self.kind == "exit":
            lines.append(f"Close: {self.close_price:.4g}")
        if self.realized_pnl is not None:
            lines.append(f"Realized PnL: {_fmt_money(self.realized_pnl)}")
        if self.missed_pnl is not None:
            label = self.missed_pnl_label or "Missed PnL"
            lines.append(f"{label}: {_fmt_money(self.missed_pnl)}")
        if self.trade_quality:
            score = f" ({self.quality_score:.0f})" if self.quality_score is not None else ""
            lines.append(f"Trade quality: {self.trade_quality}{score}")
        if self.ideal_exit_date:
            lines.append(f"{self.ideal_exit_label or 'Ideal exit'}: {self.ideal_exit_date}")
        lines.append("Press <b>D</b> to open 15m drill-down")
        lines.extend(self.extra_lines)
        return "<br>".join(lines)

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "kind": self.kind,
            "instrument": self.instrument,
            "timestamp": self.timestamp.isoformat(),
            "pair_timestamp": self.pair_timestamp.isoformat() if self.pair_timestamp else None,
            "fisher": self.y_value,
            "realized_pnl": self.realized_pnl,
            "missed_pnl": self.missed_pnl,
            "missed_pnl_label": self.missed_pnl_label,
            "trade_quality": self.trade_quality,
            "quality_score": self.quality_score,
            "quantity": self.quantity,
            "open_price": self.open_price,
            "close_price": self.close_price,
            "ideal_exit_date": self.ideal_exit_date,
            "ideal_exit_price": self.ideal_exit_price,
            "ideal_exit_label": self.ideal_exit_label,
            "underlying": self.underlying,
            "entry_datetime": self.entry_datetime,
            "exit_datetime": self.exit_datetime,
            "strike": self.strike,
            "expiration": self.expiration,
            "option_type": self.option_type,
            "label": self._picker_label(),
        }

    def _picker_label(self) -> str:
        pnl = _fmt_money(self.realized_pnl) if self.realized_pnl is not None else "n/a"
        quality = self.trade_quality or "ungraded"
        bits = [self.instrument]
        if self.strike is not None:
            strike_text = (
                f"{self.strike:.0f}" if float(self.strike).is_integer() else f"{self.strike:g}"
            )
            bits.append(f"K{strike_text}")
        if self.expiration:
            bits.append(self.expiration)
        bits.extend([pnl, quality])
        return " · ".join(bits)


@dataclass(slots=True)
class EnhancedChartSeries:
    """OHLC + indicator series for the enhanced scrollable chart."""

    timestamps: Sequence[datetime]
    opens: Sequence[float]
    highs: Sequence[float]
    lows: Sequence[float]
    closes: Sequence[float]
    indicator_values: Sequence[float | None]
    indicator_name: str = "Fisher"
    ticker: str = ""
    title: str | None = None


def build_enhanced_scrollable_figure(
    series: EnhancedChartSeries,
    markers: Sequence[AnnotatedTradeMarker],
    *,
    initial_visible_bars: int = 120,
    height: int = 820,
    overbought: float = FISHER_OVERBOUGHT,
    oversold: float = FISHER_OVERSOLD,
) -> go.Figure:
    """Build a dual-pane Plotly figure with rangeslider + free vertical zoom.

    Top pane: price candlesticks.
    Bottom pane: indicator with trade markers near the Fisher line.
    Same-day stacks show a count badge; click opens a trade picker when needed.
    Selecting a trade highlights the holding window on the price pane.
    """
    if not series.timestamps:
        raise ValueError("series.timestamps must not be empty")

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.55, 0.45],
        subplot_titles=(
            f"{series.ticker} Price" if series.ticker else "Price",
            series.indicator_name,
        ),
    )

    figure.add_trace(
        go.Candlestick(
            x=list(series.timestamps),
            open=list(series.opens),
            high=list(series.highs),
            low=list(series.lows),
            close=list(series.closes),
            name=series.ticker or "Price",
            increasing_line_color="#2ca02c",
            decreasing_line_color="#d62728",
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=list(series.timestamps),
            y=list(series.indicator_values),
            mode="lines",
            name=series.indicator_name,
            line={"color": "#1f77b4", "width": 1.6},
            hovertemplate=(
                f"{series.indicator_name}: %{{y:.3f}}<br>"
                "%{x|%Y-%m-%d}<extra></extra>"
            ),
        ),
        row=2,
        col=1,
    )

    y_min, y_max = _indicator_y_bounds(series.indicator_values, overbought, oversold)
    arrow_offset = max(0.15, (y_max - y_min) * ARROW_OFFSET_FRACTION)

    # Zone fills behind the Fisher line (above +2 green, below -2 red).
    figure.add_hrect(
        y0=overbought,
        y1=y_max,
        fillcolor="rgba(44, 160, 44, 0.18)",
        line_width=0,
        row=2,
        col=1,
        layer="below",
    )
    figure.add_hrect(
        y0=y_min,
        y1=oversold,
        fillcolor="rgba(214, 39, 40, 0.18)",
        line_width=0,
        row=2,
        col=1,
        layer="below",
    )
    figure.add_hline(y=overbought, line_dash="dot", line_color="#2ca02c", line_width=1, row=2, col=1)
    figure.add_hline(y=oversold, line_dash="dot", line_color="#d62728", line_width=1, row=2, col=1)
    figure.add_hline(y=0, line_color="#999999", line_width=1, row=2, col=1)

    entry_clusters = _cluster_markers([m for m in markers if m.kind == "entry"])
    exit_clusters = _cluster_markers([m for m in markers if m.kind == "exit"])

    if entry_clusters:
        figure.add_trace(
            _cluster_marker_trace(
                entry_clusters,
                name="Entries",
                color="#2ca02c",
                symbol="triangle-up",
                y_offset=-arrow_offset,
            ),
            row=2,
            col=1,
        )
        figure.add_trace(
            _stack_count_trace(entry_clusters, y_offset=-arrow_offset, color="#1b6e1b"),
            row=2,
            col=1,
        )
    if exit_clusters:
        figure.add_trace(
            _cluster_marker_trace(
                exit_clusters,
                name="Exits",
                color="#d62728",
                symbol="triangle-down",
                y_offset=arrow_offset,
            ),
            row=2,
            col=1,
        )
        figure.add_trace(
            _stack_count_trace(exit_clusters, y_offset=arrow_offset, color="#9b1c1c"),
            row=2,
            col=1,
        )

    # Selected-trade overlays (filled by click handler).
    figure.add_trace(
        go.Scatter(
            x=[],
            y=[],
            mode="lines+markers",
            name="Selected trade",
            line={"color": "#f0ad4e", "width": 2, "dash": "dot"},
            marker={
                "size": 16,
                "color": "#f0ad4e",
                "symbol": "circle-open",
                "line": {"width": 3, "color": "#f0ad4e"},
            },
            hoverinfo="skip",
            showlegend=True,
        ),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=[],
            y=[],
            mode="markers",
            name="Selected price marks",
            marker={
                "size": 14,
                "color": ["#2ca02c", "#d62728"],
                "symbol": ["triangle-up", "triangle-down"],
                "line": {"width": 2, "color": "#f0ad4e"},
            },
            hoverinfo="skip",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    title = series.title or (
        f"{series.ticker} — {series.indicator_name} with trade overlays"
        if series.ticker
        else f"{series.indicator_name} with trade overlays"
    )

    x_range = _initial_x_range(series.timestamps, initial_visible_bars)
    price_lookup = {
        _date_key(ts): float(close)
        for ts, close in zip(series.timestamps, series.closes)
    }
    trade_catalog = {
        marker.trade_id: {
            **marker.catalog_entry(),
            # Prefer entry-side catalog fields when both exist; JS merges pairs.
        }
        for marker in markers
        if marker.kind == "entry"
    }
    # Ensure exits also contribute pair info for trades missing an entry marker.
    for marker in markers:
        if marker.kind != "exit":
            continue
        existing = trade_catalog.get(marker.trade_id)
        if existing is None:
            trade_catalog[marker.trade_id] = marker.catalog_entry()
            continue
        existing["pair_timestamp"] = marker.timestamp.isoformat()
        existing["exit_fisher"] = marker.y_value

    for trade_id, entry in trade_catalog.items():
        # Prefer explicit normalized datetimes from the trade markers.
        entry_ts = entry.get("entry_datetime") or entry.get("timestamp")
        exit_ts = entry.get("exit_datetime") or entry.get("pair_timestamp")
        if entry_ts and exit_ts and entry_ts > exit_ts:
            entry_ts, exit_ts = exit_ts, entry_ts
        entry["entry_timestamp"] = entry_ts
        entry["exit_timestamp"] = exit_ts
        entry["entry_price"] = price_lookup.get(_date_key_from_iso(entry_ts)) if entry_ts else None
        entry["exit_price"] = price_lookup.get(_date_key_from_iso(exit_ts)) if exit_ts else None

    figure.update_layout(
        title=title,
        height=height,
        template="plotly_white",
        hovermode="closest",
        dragmode="pan",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        margin={"l": 60, "r": 30, "t": 80, "b": 40},
        xaxis2={
            "rangeslider": {"visible": True, "thickness": 0.08},
            "type": "date",
            "range": x_range,
            "rangeslider_range": x_range,
        },
        yaxis={"fixedrange": False, "title": "Price"},
        yaxis2={
            "fixedrange": False,
            "title": series.indicator_name,
            "zeroline": False,
            "range": [y_min, y_max],
        },
        xaxis={"fixedrange": False},
        meta={
            "arrow_offset": arrow_offset,
            "trade_catalog": trade_catalog,
            "base_shape_count": len(figure.layout.shapes or ()),
        },
    )
    figure.update_xaxes(rangeslider_visible=False, row=1, col=1)
    figure.update_xaxes(rangeslider_visible=True, row=2, col=1)
    return figure


def write_enhanced_chart_html(
    figure: go.Figure,
    output_path: Path | None = None,
    *,
    auto_open: bool = False,
    drilldown_index: dict[str, str] | None = None,
) -> Path:
    """Write an enhanced chart to HTML with CDN Plotly.js and interactive overlays."""
    if output_path is None:
        output_dir = Path(tempfile.gettempdir()) / "trading-analysis"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "enhanced-chart.html"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "scrollZoom": True,
        "displayModeBar": True,
        "modeBarButtonsToAdd": ["drawline", "eraseshape"],
        "responsive": True,
    }
    catalog = {}
    meta = figure.layout.meta
    if isinstance(meta, dict):
        catalog = meta.get("trade_catalog") or {}
    catalog_json = json.dumps(catalog)
    base_shape_count = 0
    if isinstance(meta, dict):
        base_shape_count = int(meta.get("base_shape_count") or 0)
    drilldown_json = json.dumps(drilldown_index or {})

    # Leave room for the hotkey footer.
    figure.update_layout(margin={"l": 60, "r": 30, "t": 80, "b": 70})

    post_script = (
        _INTERACTIVE_SCRIPT.replace("__TRADE_CATALOG__", catalog_json)
        .replace("__BASE_SHAPE_COUNT__", str(base_shape_count))
        .replace("__DRILLDOWN_INDEX__", drilldown_json)
    )

    figure.write_html(
        str(output_path),
        auto_open=auto_open,
        include_plotlyjs="cdn",
        config=config,
        post_script=post_script,
    )
    return output_path


@dataclass(slots=True)
class _MarkerCluster:
    timestamp: datetime
    plot_fisher: float
    markers: list[AnnotatedTradeMarker]


def _cluster_markers(markers: Sequence[AnnotatedTradeMarker]) -> list[_MarkerCluster]:
    """Group markers that fall within one day of a cluster anchor."""
    if not markers:
        return []
    ordered = sorted(markers, key=lambda marker: marker.timestamp)
    clusters: list[list[AnnotatedTradeMarker]] = []
    current: list[AnnotatedTradeMarker] = [ordered[0]]
    for marker in ordered[1:]:
        # Stack if within 1 day of the cluster's first (anchor) timestamp.
        if marker.timestamp - current[0].timestamp <= STACK_WINDOW:
            current.append(marker)
        else:
            clusters.append(current)
            current = [marker]
    clusters.append(current)

    result: list[_MarkerCluster] = []
    for group in clusters:
        avg_fisher = sum(marker.y_value for marker in group) / len(group)
        result.append(
            _MarkerCluster(
                timestamp=group[0].timestamp,
                plot_fisher=avg_fisher,
                markers=group,
            )
        )
    return result


def _cluster_marker_trace(
    clusters: Sequence[_MarkerCluster],
    *,
    name: str,
    color: str,
    symbol: str,
    y_offset: float,
) -> go.Scatter:
    xs: list[datetime] = []
    ys: list[float] = []
    texts: list[str] = []
    customdata: list[list[Any]] = []
    for cluster in clusters:
        plot_y = cluster.plot_fisher + y_offset
        xs.append(cluster.timestamp)
        ys.append(plot_y)
        count = len(cluster.markers)
        if count == 1:
            texts.append(cluster.markers[0].hover_text())
        else:
            texts.append(
                f"<b>{count} {name.lower()}</b><br>"
                f"{cluster.timestamp.strftime('%Y-%m-%d')}<br>"
                "Click to choose a trade"
            )
        customdata.append(
            [
                [marker.trade_id for marker in cluster.markers],
                cluster.markers[0].kind,
                plot_y,
                count,
                [marker.catalog_entry() for marker in cluster.markers],
            ]
        )
    return go.Scatter(
        x=xs,
        y=ys,
        mode="markers",
        name=name,
        marker={
            "size": 13,
            "color": color,
            "symbol": symbol,
            "line": {"width": 1, "color": "#111111"},
            "opacity": 0.95,
        },
        text=texts,
        customdata=customdata,
        hovertemplate="%{text}<extra></extra>",
    )


def _stack_count_trace(
    clusters: Sequence[_MarkerCluster],
    *,
    y_offset: float,
    color: str,
) -> go.Scatter:
    xs: list[datetime] = []
    ys: list[float] = []
    texts: list[str] = []
    for cluster in clusters:
        count = len(cluster.markers)
        if count <= 1:
            continue
        # Slightly later / lower-right of the arrow.
        xs.append(cluster.timestamp + timedelta(hours=8))
        ys.append(cluster.plot_fisher + y_offset - abs(y_offset) * 0.35)
        texts.append(str(count))
    return go.Scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        name="Stack counts",
        text=texts,
        textposition="middle center",
        textfont={"size": 10, "color": "#ffffff", "family": "Arial Black"},
        marker={
            "size": 16,
            "color": color,
            "symbol": "circle",
            "line": {"width": 1, "color": "#ffffff"},
        },
        hoverinfo="skip",
        showlegend=False,
    )


def _indicator_y_bounds(
    values: Sequence[float | None],
    overbought: float,
    oversold: float,
) -> tuple[float, float]:
    finite = [float(value) for value in values if value is not None]
    if not finite:
        return oversold - 1.0, overbought + 1.0
    data_min = min(finite)
    data_max = max(finite)
    y_min = min(data_min, oversold) - 0.35
    y_max = max(data_max, overbought) + 0.35
    if y_max <= y_min:
        y_max = y_min + 1.0
    return y_min, y_max


def _initial_x_range(timestamps: Sequence[datetime], visible_bars: int) -> list[datetime]:
    if len(timestamps) <= visible_bars:
        return [timestamps[0], timestamps[-1]]
    return [timestamps[-visible_bars], timestamps[-1]]


def _fmt_money(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f}"


def _date_key(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date().isoformat()


def _date_key_from_iso(value: str | None) -> str | None:
    if not value:
        return None
    return _date_key(datetime.fromisoformat(value.replace("Z", "+00:00")))


_INTERACTIVE_SCRIPT = r"""
(function() {
  const gd = document.querySelectorAll('.plotly-graph-div')[0];
  if (!gd) return;

  const TRADE_CATALOG = __TRADE_CATALOG__;
  const BASE_SHAPE_COUNT = __BASE_SHAPE_COUNT__;
  const DRILLDOWN_INDEX = __DRILLDOWN_INDEX__;

  // Hotkey footer
  const footer = document.createElement('div');
  footer.id = 'chart-hotkey-footer';
  footer.style.cssText = [
    'position:fixed',
    'left:0',
    'right:0',
    'bottom:0',
    'z-index:9998',
    'padding:8px 14px',
    'background:rgba(17,24,39,0.94)',
    'color:#e5e7eb',
    'font:12px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',
    'border-top:1px solid #374151',
  ].join(';');
  footer.innerHTML = [
    '<b>Hotkeys</b>: ',
    '<kbd style="background:#374151;padding:1px 6px;border-radius:4px;">D</kbd> ',
    'open 15m drill-down for the selected trade (entry → ideal exit) · ',
    'click arrow to select · click stacked arrow to pick a trade · ',
    'double-click chart to clear',
  ].join('');
  document.body.appendChild(footer);
  document.body.style.paddingBottom = '40px';

  // Picker widget
  const picker = document.createElement('div');
  picker.id = 'trade-picker';
  picker.style.cssText = [
    'display:none',
    'position:fixed',
    'z-index:9999',
    'min-width:280px',
    'max-width:360px',
    'max-height:320px',
    'overflow:auto',
    'background:#111827',
    'color:#f9fafb',
    'border:1px solid #374151',
    'border-radius:10px',
    'box-shadow:0 12px 30px rgba(0,0,0,0.35)',
    'font:13px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',
  ].join(';');
  picker.innerHTML = [
    '<div style="padding:10px 12px;border-bottom:1px solid #374151;display:flex;justify-content:space-between;align-items:center;">',
    '  <strong id="trade-picker-title">Select trade</strong>',
    '  <button id="trade-picker-close" style="background:transparent;border:0;color:#9ca3af;font-size:18px;cursor:pointer;line-height:1;">×</button>',
    '</div>',
    '<div id="trade-picker-list" style="padding:6px;"></div>',
  ].join('');
  document.body.appendChild(picker);
  picker.querySelector('#trade-picker-close').addEventListener('click', hidePicker);

  // Toast for hotkey feedback
  const toast = document.createElement('div');
  toast.style.cssText = [
    'display:none',
    'position:fixed',
    'left:50%',
    'bottom:56px',
    'transform:translateX(-50%)',
    'z-index:10000',
    'background:#111827',
    'color:#f9fafb',
    'border:1px solid #4b5563',
    'border-radius:8px',
    'padding:8px 12px',
    'font:12px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',
    'box-shadow:0 8px 20px rgba(0,0,0,0.3)',
  ].join(';');
  document.body.appendChild(toast);
  let toastTimer = null;
  function showToast(message) {
    toast.textContent = message;
    toast.style.display = 'block';
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.style.display = 'none'; }, 2200);
  }

  let selectedTradeId = null;

  function findTraceIndexes() {
    const indexes = {
      entries: -1,
      exits: -1,
      selected: -1,
      selectedPrice: -1,
    };
    (gd.data || []).forEach((trace, i) => {
      if (trace.name === 'Entries') indexes.entries = i;
      if (trace.name === 'Exits') indexes.exits = i;
      if (trace.name === 'Selected trade') indexes.selected = i;
      if (trace.name === 'Selected price marks') indexes.selectedPrice = i;
    });
    return indexes;
  }

  function clusterTradeIds(custom) {
    if (!custom) return [];
    if (Array.isArray(custom)) {
      const ids = custom[0];
      return Array.isArray(ids) ? ids : [];
    }
    return custom.trade_ids || [];
  }

  function clusterTrades(custom) {
    if (!custom) return [];
    if (Array.isArray(custom)) return custom[4] || [];
    return custom.trades || [];
  }

  function hidePicker() {
    picker.style.display = 'none';
  }

  function showPicker(trades, clientX, clientY, kind) {
    const list = picker.querySelector('#trade-picker-list');
    const title = picker.querySelector('#trade-picker-title');
    title.textContent = kind === 'entry' ? 'Select entry trade' : 'Select exit trade';
    list.innerHTML = '';
    trades.forEach((trade) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.cssText = [
        'display:block',
        'width:100%',
        'text-align:left',
        'margin:4px 0',
        'padding:8px 10px',
        'border-radius:8px',
        'border:1px solid #4b5563',
        'background:#1f2937',
        'color:#f9fafb',
        'cursor:pointer',
      ].join(';');
      const pnl = trade.realized_pnl == null ? 'n/a' : formatMoney(trade.realized_pnl);
      const strike = trade.strike == null ? '' : `<div style="font-size:12px;color:#c4b5fd;">Strike: ${Number.isInteger(trade.strike) ? trade.strike : trade.strike}</div>`;
      const expiration = trade.expiration ? `<div style="font-size:12px;color:#93c5fd;">Exp: ${trade.expiration}</div>` : '';
      const missed = trade.missed_pnl == null ? '' : `<div style="color:#fbbf24;font-size:12px;">Missed: ${formatMoney(trade.missed_pnl)}</div>`;
      const quality = trade.trade_quality ? `<div style="color:#93c5fd;font-size:12px;">Quality: ${trade.trade_quality}${trade.quality_score != null ? ' (' + Math.round(trade.quality_score) + ')' : ''}</div>` : '';
      btn.innerHTML = [
        `<div style="font-weight:600;">${trade.instrument || trade.trade_id}</div>`,
        `<div style="font-size:12px;color:#d1d5db;">${trade.timestamp ? trade.timestamp.slice(0,10) : ''} · PnL ${pnl}</div>`,
        strike,
        expiration,
        missed,
        quality,
      ].join('');
      btn.addEventListener('click', function(ev) {
        ev.stopPropagation();
        hidePicker();
        selectTrade(trade.trade_id);
      });
      list.appendChild(btn);
    });

    const pad = 12;
    let left = clientX + pad;
    let top = clientY + pad;
    picker.style.display = 'block';
    const rect = picker.getBoundingClientRect();
    if (left + rect.width > window.innerWidth - pad) left = clientX - rect.width - pad;
    if (top + rect.height > window.innerHeight - pad) top = clientY - rect.height - pad;
    picker.style.left = Math.max(pad, left) + 'px';
    picker.style.top = Math.max(pad, top) + 'px';
  }

  function formatMoney(value) {
    const sign = value < 0 ? '-' : '+';
    return sign + '$' + Math.abs(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function clearHighlight() {
    const indexes = findTraceIndexes();
    if (indexes.selected >= 0) Plotly.restyle(gd, { x: [[]], y: [[]] }, [indexes.selected]);
    if (indexes.selectedPrice >= 0) {
      Plotly.restyle(gd, {
        x: [[]],
        y: [[]],
        'marker.color': [[[]]],
        'marker.symbol': [[[]]],
      }, [indexes.selectedPrice]);
    }
    for (const key of ['entries', 'exits']) {
      const ti = indexes[key];
      if (ti < 0) continue;
      const n = (gd.data[ti].x || []).length;
      Plotly.restyle(gd, {
        'marker.size': [Array(n).fill(13)],
        'marker.opacity': [Array(n).fill(0.95)],
        'marker.line.width': [Array(n).fill(1)],
        'marker.line.color': [Array(n).fill('#111111')],
      }, [ti]);
    }
    const shapes = (gd.layout.shapes || []).slice(0, BASE_SHAPE_COUNT);
    Plotly.relayout(gd, { shapes: shapes });
  }

  function tradeWindow(tradeId) {
    const trade = TRADE_CATALOG[tradeId] || {};
    let entryTs = trade.entry_timestamp || trade.timestamp;
    let actualExitTs = trade.exit_timestamp || trade.pair_timestamp;
    if (trade.kind === 'exit' && trade.pair_timestamp) {
      entryTs = trade.pair_timestamp;
      actualExitTs = trade.timestamp;
    }
    let highlightEndTs = actualExitTs;
    if (trade.ideal_exit_date) {
      const idealTs = trade.ideal_exit_date + 'T20:00:00+00:00';
      if (!highlightEndTs || idealTs > highlightEndTs) highlightEndTs = idealTs;
    }
    return { entryTs, actualExitTs, highlightEndTs, trade };
  }

  function fisherPointsForTrade(tradeId) {
    const indexes = findTraceIndexes();
    const points = [];
    for (const key of ['entries', 'exits']) {
      const ti = indexes[key];
      if (ti < 0) continue;
      const trace = gd.data[ti];
      const custom = trace.customdata || [];
      for (let i = 0; i < custom.length; i++) {
        const ids = clusterTradeIds(custom[i]);
        if (!ids.includes(tradeId)) continue;
        points.push({ x: trace.x[i], y: trace.y[i], side: key });
      }
    }
    return points;
  }

  function emphasizeTrade(tradeId) {
    const indexes = findTraceIndexes();
    const { entryTs, actualExitTs, highlightEndTs, trade } = tradeWindow(tradeId);
    const fisherPoints = fisherPointsForTrade(tradeId);
    if (indexes.selected >= 0 && fisherPoints.length) {
      const ordered = fisherPoints.slice().sort((a, b) => String(a.x).localeCompare(String(b.x)));
      Plotly.restyle(gd, {
        x: [ordered.map(p => p.x)],
        y: [ordered.map(p => p.y)],
      }, [indexes.selected]);
    }

    if (indexes.selectedPrice >= 0 && entryTs && actualExitTs) {
      const entryPrice = trade.entry_price;
      const exitPrice = trade.exit_price;
      Plotly.restyle(gd, {
        x: [[entryTs, actualExitTs]],
        y: [[entryPrice, exitPrice]],
        'marker.color': [['#2ca02c', '#d62728']],
        'marker.symbol': [['triangle-up', 'triangle-down']],
      }, [indexes.selectedPrice]);
    }

    function styleTrace(traceIndex) {
      if (traceIndex < 0) return;
      const custom = gd.data[traceIndex].customdata || [];
      const sizes = custom.map(item => (clusterTradeIds(item).includes(tradeId) ? 18 : 10));
      const opacities = custom.map(item => (clusterTradeIds(item).includes(tradeId) ? 1.0 : 0.25));
      const widths = custom.map(item => (clusterTradeIds(item).includes(tradeId) ? 3 : 1));
      const colors = custom.map(item => (clusterTradeIds(item).includes(tradeId) ? '#f0ad4e' : '#111111'));
      Plotly.restyle(gd, {
        'marker.size': [sizes],
        'marker.opacity': [opacities],
        'marker.line.width': [widths],
        'marker.line.color': [colors],
      }, [traceIndex]);
    }
    styleTrace(indexes.entries);
    styleTrace(indexes.exits);

    const baseShapes = (gd.layout.shapes || []).slice(0, BASE_SHAPE_COUNT);
    const exitTs = highlightEndTs || actualExitTs;
    if (entryTs && exitTs) {
      const x0 = entryTs <= exitTs ? entryTs : exitTs;
      const x1 = entryTs <= exitTs ? exitTs : entryTs;
      baseShapes.push({
        type: 'rect',
        xref: 'x',
        yref: 'y domain',
        x0: x0,
        x1: x1,
        y0: 0,
        y1: 1,
        fillcolor: 'rgba(240, 173, 78, 0.18)',
        line: { width: 1, color: 'rgba(240, 173, 78, 0.7)' },
        layer: 'below',
      });
      baseShapes.push({
        type: 'rect',
        xref: 'x2',
        yref: 'y2 domain',
        x0: x0,
        x1: x1,
        y0: 0,
        y1: 1,
        fillcolor: 'rgba(240, 173, 78, 0.12)',
        line: { width: 1, color: 'rgba(240, 173, 78, 0.55)' },
        layer: 'below',
      });
    }
    Plotly.relayout(gd, { shapes: baseShapes });
  }

  function selectTrade(tradeId) {
    if (selectedTradeId === tradeId) {
      selectedTradeId = null;
      clearHighlight();
      return;
    }
    selectedTradeId = tradeId;
    emphasizeTrade(tradeId);
  }

  function openDrilldown() {
    if (!selectedTradeId) {
      showToast('Select a trade first, then press D for 15m drill-down');
      return;
    }
    const rel = DRILLDOWN_INDEX[selectedTradeId];
    if (!rel) {
      showToast('No 15m drill-down available for this trade');
      return;
    }
    const url = new URL(rel, window.location.href).toString();
    window.open(url, '_blank');
  }

  gd.on('plotly_click', function(event) {
    if (!event || !event.points || !event.points.length) return;
    const point = event.points[0];
    const traceName = point.data && point.data.name;
    if (traceName !== 'Entries' && traceName !== 'Exits') {
      hidePicker();
      return;
    }
    const ids = clusterTradeIds(point.customdata);
    const trades = clusterTrades(point.customdata);
    if (!ids.length) return;

    const evt = event.event || {};
    const clientX = evt.clientX || 0;
    const clientY = evt.clientY || 0;

    if (ids.length === 1) {
      hidePicker();
      selectTrade(ids[0]);
      return;
    }
    showPicker(trades, clientX, clientY, traceName === 'Entries' ? 'entry' : 'exit');
  });

  gd.on('plotly_doubleclick', function() {
    selectedTradeId = null;
    hidePicker();
    clearHighlight();
  });

  document.addEventListener('keydown', function(ev) {
    if (ev.defaultPrevented) return;
    const tag = (ev.target && ev.target.tagName) ? ev.target.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (ev.target && ev.target.isContentEditable)) return;
    if (ev.key === 'd' || ev.key === 'D') {
      ev.preventDefault();
      openDrilldown();
    }
  });

  document.addEventListener('click', function(ev) {
    if (picker.style.display === 'none') return;
    if (picker.contains(ev.target)) return;
    if (ev.target && ev.target.closest && ev.target.closest('.plotly-graph-div')) return;
    hidePicker();
  });
})();
"""
