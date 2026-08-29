# Trading Data Pipeline

This module encapsulates the Polygon.io download worker, the watchlist
configuration, and the BigQuery upload script that used to live under
`backend/app/data_download` and `backend/scripts`.

## Installation

```bash
pip install -e modules/data-pipeline
```

## Commands

- `trading-data-download`: Download a single ticker or the entire watchlist and
  save the CSV files under `modules/data-pipeline/data/<interval>`. Supports
  `--market stocks` and `--market indices`.
- `trading-data-sync`: Upload the generated CSV files to a BigQuery table.
- `trading-data-pull`: Pull one ticker from BigQuery into a local CSV archive.
- `trading-data-download-cmc`: Download crypto OHLCV from CoinMarketCap into
  `modules/data-pipeline/data/cmc/<timeframe>/`.
- `trading-data-visualize`: Export the legacy standalone local chart for an archived CSV,
  or load a workspace with in-app symbol, timeframe, and study selectors. It
  supports strategy overlays plus versioned, user-supplied annotations, linked
  entry/exit paths, time spans, hover metadata, and custom indicator panes.

Interactive development has moved to `modules/analysis/dashboard`. The legacy
visualizer remains for portable HTML exports while generators migrate to
`trading-study-run/v1`; do not add new application UI here.

Run each command with `--help` to discover the available options.  Configuration
defaults live under `modules/data-pipeline/config/`.

## Quick View

```bash
trading-data-visualize AAPL D
trading-data-visualize MU 1440 --no-open
trading-data-visualize MU 1440 --annotations my-study.json --output mu-study.html --no-open
trading-data-visualize --workspace research-workspace.json --output research-workspace.html --no-open
trading-data-download I:SPX --market indices --interval 1440
```

For `--market indices`, the downloader uses Massive's indices aggregates
endpoint and skips stock market-cap filtering.

## Reuse From Python

Other modules can now generate the same HTML viewer directly:

```python
from trading_data_pipeline.visualize import make_chart_payload, render_chart_html

payload = make_chart_payload(
    ticker="AAPL",
    timeframe_minutes=1440,
    rows=[
        {
            "timestamp": "2026-01-02T05:00:00Z",
            "open": 100,
            "high": 105,
            "low": 99,
            "close": 103,
        }
    ],
    overlays={
        "red_markers": [{"time": "2026-01-02T05:00:00Z", "price": 106}],
        "green_markers": [{"time": "2026-01-02T05:00:00Z", "price": 98}],
    },
)
html = render_chart_html(payload)
```

See [UNIVERSAL_VISUALIZER.md](UNIVERSAL_VISUALIZER.md) for the annotation and
workspace JSON contracts, supported marker/panel types, and complete examples.
