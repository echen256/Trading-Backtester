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
  save the CSV files under `modules/data-pipeline/data/<interval>`.
- `trading-data-sync`: Upload the generated CSV files to a BigQuery table.
- `trading-data-pull`: Pull one ticker from BigQuery into a local CSV archive.
- `trading-data-download-cmc`: Download crypto OHLCV from CoinMarketCap into
  `modules/data-pipeline/data/cmc/<timeframe>/`.
- `trading-data-visualize`: Open a browser view for one archived CSV by ticker
  and timeframe, rendering the local series and embedding a TradingView market
  widget alongside it when available.
- `trading-data-fisher-adaptive`: Translate the archived OHLCV into the Fisher
  Transform + Adaptive MACD indicator bundle and emit a chart-ready JSON payload.

Run each command with `--help` to discover the available options.  Configuration
defaults live under `modules/data-pipeline/config/`.

## Quick View

```bash
trading-data-visualize AAPL D
trading-data-visualize MU 1440 --no-open
trading-data-fisher-adaptive MU D --output /tmp/mu-fisher.json
```

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

The Pine translation is also reusable from Python and returns `customIndicators`
in the same `{name, data, options}` shape consumed by the frontend chart:

```python
from trading_data_pipeline.strategies.fisher_adaptive_macd import compute_archived_indicator_payload

payload = compute_archived_indicator_payload("MU", "D")
print(payload["customIndicators"][0]["name"])
print(payload["summary"])
```
