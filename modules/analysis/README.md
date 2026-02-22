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

After installation two commands are available:

- `trading-parse-orders` – run the `parse_orders.py` workflow against a broker
  `orders.csv` export.  Run with `--help` to see the available filters.
- `trading-schwab-convert` – convert Schwab exports into the normalized
  `orders.csv` schema before analysis.

Sample CSV files remain under `examples/` for quick experiments.
