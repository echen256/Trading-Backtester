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

Run each command with `--help` to discover the available options.  Configuration
defaults live under `modules/data-pipeline/config/`.

## Quick View

```bash
trading-data-visualize AAPL D
trading-data-visualize MU 1440 --no-open
```
