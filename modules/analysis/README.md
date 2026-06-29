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

For YTD analysis, fetch a warmup window inside Webull's roughly two-year order
history limit, then report only the desired close-date window:

```bash
trading-webull-bridge orders --start-date 2025-01-01 --end-date 2026-06-29
trading-parse-orders modules/analysis/order-data/webull_orders_2025-01-01_to_2026-06-29.csv --start-date 2026-01-01 --end-date 2026-06-29
```

The parser keeps earlier orders for cost basis and open lots, but filters
realized PnL by close date.

Sample CSV files remain under `examples/` for quick experiments.
