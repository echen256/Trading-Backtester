# Universal Visualizer

> **Migration status:** this is the legacy portable-HTML exporter. The
> canonical interactive app and artifact contracts live in
> `modules/analysis/dashboard`.

`trading-data-visualize` is the legacy local chart export for price data,
trades, research events, indicator states, and forward-evaluation windows. It
renders a self-contained HTML payload; Plotly itself is loaded from its CDN.

## Dealing ranges

Every chart includes a **Dealing Range 5/1** overlay. A swing high or low is
confirmed only after five prior bars and one subsequent bar, so the visualizer
does not leak the lookahead into the pivot timestamp. Once both sides exist,
the chart shades the lower half (discount) teal and the upper half (premium)
red, with a dotted equilibrium line at 50%.

The active range remains in force until a candle closes outside it:

- A wick outside followed by a close back inside is marked with a yellow
  diamond as a sweep / failed breakout. It does not change the range.
- A close outside is marked with a directional triangle and starts an expanded
  range from the latest confirmed opposite swing to the breakout extreme.
- Expansion markers distinguish price discovery (`new prices`) from movement
  back into a previously completed dealing range (`old range`) in their hover
  details.

The status panel reports the live low / 50% / high levels and whether the last
close is in premium or discount. The toolbar button hides or restores all
dealing-range zones and events without affecting custom annotations.

## Command line

```bash
trading-data-visualize MU 1440 \
  --annotations reports/mu-study-annotations.json \
  --output reports/mu-study.html \
  --no-open
```

The price CSV is resolved from `modules/data-pipeline/data/<minutes>/`. The
annotation document is optional and must use
`trading-chart-annotations/v1`.

## Multi-view workspace

A workspace bundles multiple symbols, timeframes, and study configurations into
one portable HTML file. The toolbar selectors swap views immediately; no chart
regeneration or page navigation is required.

```bash
trading-data-visualize \
  --workspace research-workspace.json \
  --output reports/research-workspace.html \
  --no-open
```

Workspace paths are resolved relative to the manifest:

```json
{
  "schema_version": "trading-chart-workspace/v1",
  "title": "Semiconductor research",
  "views": [
    {
      "id": "mu-daily-macd",
      "label": "MU daily adaptive MACD",
      "ticker": "MU",
      "timeframe": "D",
      "study_id": "adaptive_macd",
      "study_label": "Adaptive MACD",
      "data": "data/MU-1440M.csv",
      "annotations": "studies/mu-daily-macd.json"
    },
    {
      "id": "mu-weekly-sfp",
      "ticker": "MU",
      "timeframe": "W",
      "study_id": "weekly_sfp",
      "study_label": "Weekly SFP",
      "data": "data/MU-10080M.csv",
      "annotations": "studies/mu-weekly-sfp.json"
    }
  ]
}
```

Every unique `ticker`, `timeframe`, and `study_id` becomes an option in the
corresponding selector. Only combinations declared in `views` are offered.
Each view retains all universal viewer controls, including annotation-group and
indicator-pane toggles.

## Annotation document

```json
{
  "schema_version": "trading-chart-annotations/v1",
  "groups": [
    {
      "id": "trades",
      "label": "Executed trades",
      "color": "#22c55e",
      "visible": true
    }
  ],
  "panels": [
    {
      "id": "custom_signal",
      "label": "Custom signal",
      "height": 260,
      "visible": true,
      "zero_line": true,
      "series": [
        {
          "id": "signal",
          "name": "Signal",
          "type": "line",
          "color": "#56b6c2",
          "points": [
            {"time": "2026-01-02", "value": 0.25},
            {"time": "2026-01-05", "value": 0.41}
          ]
        }
      ]
    }
  ],
  "points": [
    {
      "id": "trade-1-entry",
      "group": "trades",
      "time": "2026-01-02",
      "pane": "price",
      "value": 101.25,
      "label": "Entry",
      "role": "entry",
      "marker": "triangle-up",
      "metadata": {"setup": "breakout", "risk_pct": 0.5}
    },
    {
      "id": "trade-1-exit",
      "group": "trades",
      "time": "2026-01-09",
      "pane": "price",
      "value": 108.0,
      "label": "Exit",
      "role": "exit",
      "marker": "triangle-down"
    }
  ],
  "links": [
    {
      "id": "trade-1-path",
      "group": "trades",
      "pane": "price",
      "start_time": "2026-01-02",
      "end_time": "2026-01-09",
      "start_value": 101.25,
      "end_value": 108.0,
      "label": "Trade 1",
      "dash": "dot",
      "metadata": {"return_pct": 6.67}
    }
  ],
  "spans": [
    {
      "id": "trade-1-holding-window",
      "group": "trades",
      "pane": "price",
      "start_time": "2026-01-02",
      "end_time": "2026-01-09",
      "label": "Holding window",
      "opacity": 0.08
    }
  ]
}
```

## Contract

- Built-in pane IDs are `price`, `fisher`, and `macd`.
- Custom pane IDs are declared under `panels` and may contain `line`,
  `histogram`, or `area` series.
- Annotation groups create interactive visibility controls. Every point, link,
  and span must reference a declared group.
- Points support `circle`, `square`, `diamond`, `triangle-up`,
  `triangle-down`, `cross`, `x`, and `star` markers.
- Metadata is arbitrary JSON and is rendered in the hover card.
- A span without `lower` and `upper` covers the full pane vertically. With both
  values it becomes a bounded price/indicator zone.
- All timestamps are normalized to UTC. Date-only values are accepted as UTC
  midnight.

## Python API

```python
from trading_data_pipeline.chart_annotations import load_annotation_document
from trading_data_pipeline.visualize import make_chart_payload, render_chart_html

annotations = load_annotation_document(annotation_path)
payload = make_chart_payload(
    ticker="MU",
    timeframe_minutes=1440,
    rows=rows,
    annotations=annotations,
)
html = render_chart_html(payload)
```

## MACD-shape adapter

The current histogram-shape study demonstrates the contract without adding
study-specific behavior to the viewer:

```bash
python modules/analysis/scripts/export_macd_shape_universal_chart.py \
  --ticker MU --timeframe 3-day
```

It emits the portable annotation JSON, a single rendered chart, and
`reports/mu_macd_shape_workspace.html`. The workspace includes 3-day and weekly
timeframes plus overview, early-momentum, and bear-crossover-slope study presets.
