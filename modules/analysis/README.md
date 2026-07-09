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
  Pass `--tpo-grades path.json` (or rely on auto-discovery) to show TPO grade
  badges and enable interactive `[G] Grade trade`.
- `trading-tpo-grade` – build underlying Market Profile (TPO) features for
  realized trades from Polygon minute bars, write
  `order-data/trade-tpo-grades-*.json`, optionally call an LLM grader with
  `--grade-llm`. Use `--rescan-errors` to slowly retry Polygon 403 trades.
- `trading-trade-hold-review` – hold-longer counterfactual on long options
  using the same `analyze_orders` pipeline and shared option daily cache.
- `trading-rescan-market-data` – throttled rescan of TPO and/or option-cache
  errors (`--target tpo|hold|both`).

### Shared market-data cache

TPO and trade-hold share `order-data/market-data-cache/`:

| Path | Contents |
| --- | --- |
| `underlying/1m/{TICKER}/{YYYY-MM-DD}.json` | RTH minute bars (TPO) |
| `options/1d/{OCC_SYMBOL}.json` | Option daily bars (hold) |

Existing `order-data/tpo-cache/` files are still read as a fallback for
underlying minutes so prior TPO runs are not re-fetched.

### TPO LLM grader (DeepSeek / OpenAI)

`--grade-llm` calls an OpenAI-compatible chat completions API. With only
`DEEPSEEK_API_KEY` in `.env`, it auto-selects DeepSeek:

| Env var | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek key (auto provider when no OpenAI key) |
| `OPENAI_API_KEY` / `TPO_GRADE_API_KEY` | OpenAI or override key |
| `TPO_GRADE_PROVIDER` | Force `deepseek` or `openai` |
| `TPO_GRADE_BASE_URL` | Override API base (default DeepSeek or OpenAI) |
| `TPO_GRADE_MODEL` | Override model (`deepseek-v4-flash` / `gpt-4.1-mini`) |

```bash
# DeepSeek (uses DEEPSEEK_API_KEY from Trading-Backtester/.env)
trading-tpo-grade --csv order-data/webull_orders_2026.csv \
  --start-date 2026-01-01 --end-date 2026-06-30 --grade-llm
```
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
