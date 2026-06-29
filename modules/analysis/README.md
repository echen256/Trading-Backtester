# Trading Analysis Module

This package contains the order-parsing utilities and Schwab CSV converters that
were previously nested directly under `backend/analysis`.  Converting them into a
self-contained module makes it easier to run ad-hoc analysis or reuse the
helpers in notebooks without pulling in the entire backend.

## Installation

```bash
pip install -e modules/analysis
```

## CLI entry points

After installation these commands are available:

- `trading-parse-orders` – analyze a Webull OpenAPI orders CSV such as
  `modules/analysis/order-data/webull_orders_2026.csv`, including realized
  PnL for options and equities. Run with `--help` to see the available filters.
- `trading-schwab-convert` – convert Schwab exports into the normalized
  `orders.csv` schema before analysis.
- `trading-webull-bridge sync-analysis` – fetch Webull OpenAPI orders into
  `modules/analysis/order-data/orders.csv` using the analysis-ready option
  contract schema.

Sample CSV files remain under `examples/` for quick experiments.
