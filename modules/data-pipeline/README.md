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

Run each command with `--help` to discover the available options.  Configuration
defaults live under `modules/data-pipeline/config/`.
