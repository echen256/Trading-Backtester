# Trading Analysis Dashboard

This is the repository's canonical market-data and study UI. It loads local
stock, crypto, index, option, or forex OHLCV archives through the analysis
catalog and renders versioned study artifacts without importing generator code.

See [ARCHITECTURE.md](ARCHITECTURE.md) for ownership boundaries, the generator
migration inventory, operational tradeoffs, and known data-quality snags.

## Run

From the repository root:

```bash
npm --prefix modules/analysis/dashboard install
npm --prefix modules/analysis/dashboard run build
trading-analysis-dashboard serve --open
```

For frontend development, one command starts the API, waits for it to become
healthy, and then starts Vite:

```bash
npm --prefix modules/analysis/dashboard run dev
```

Vite proxies `/api` to `http://127.0.0.1:8765`. If an API process is already
healthy on that port, the launcher reuses it. `npm run dev:web` remains
available when intentionally managing the API in a separate terminal.

## Import market data

The importer accepts CSV, compressed CSV, and Parquet. It recognizes canonical
OHLCV names, Polygon short names, and Binance `open_time_utc` timestamps.

```bash
trading-analysis-dashboard import /path/to/AAPL.csv --symbol AAPL --asset-class stock
trading-analysis-dashboard import /path/to/BTCUSDT_5m.csv.gz \
  --asset-class crypto --venue binance --base-asset BTC --quote-asset USDT \
  --interval-seconds 300
```

Inputs are validated and normalized into content-addressed, Zstandard-compressed
Parquet files under `modules/analysis/artifacts/datasets/`. Original files are
not modified. The SQLite catalog records provenance, interval, coverage,
duplicates, and crypto gap ranges.

By default, file imports are restricted to the Trading workspace. Add other
roots with `TRADING_DASHBOARD_DATA_ROOTS`, separated by the operating system
path separator.

## Publish a study

Generators should use `StudyArtifactWriter`; they should not render custom
interactive HTML.

```python
from trading_analysis.dashboard import StudyArtifactWriter

writer = StudyArtifactWriter()
manifest = writer.build_manifest(
    study_id="my-study",
    study_name="My Study",
    version="1.0",
    generator="my_generator.py",
    views=[{
        "id": "overview",
        "label": "Overview",
        "dataset_id": dataset_id,
        "chart": annotation_document,
    }],
    metrics=[{"label": "Signals", "value": 14}],
)
writer.publish(manifest)
```

Existing `trading-chart-annotations/v1` documents are accepted and upgraded to
`trading-chart-study/v2`. Published runs are atomic and appear after catalog
refresh.

Report-oriented generators can publish their existing JSON, CSV, Markdown,
image, or HTML outputs while they are being migrated to chart-native views:

```python
writer.publish_report_study(
    study_id="my-report",
    study_name="My Report",
    version="1.0",
    generator=__file__,
    files={"summary": summary_json, "events": events_csv, "method": report_md},
)
```

The options-premium CLI can publish its interactive underlying/premium view
directly with `trading-options-premium fetch ... --publish-dashboard` or
`trading-options-premium chart ... --publish-dashboard`.

## Contracts

The language-neutral source contracts are in `dashboard/contracts/`:

- `market-dataset-v1.schema.json`
- `chart-study-v2.schema.json`
- `study-run-v1.schema.json`

The dashboard supports price/volume data, synchronized indicator panes,
toggleable groups, markers, linked outcomes, bounded spans, horizontal levels,
metrics, result tables, methodology, a backward/forward timeline scrubber, and
URL-restorable workspace state.

The TPO panel below the timeline follows the slider's right edge and requests
native intraday bars independently of main-chart aggregation. Equity profiles
use the repository standard of 09:30–16:00 America/New_York with 30-minute
periods; 24/7 crypto profiles use 00:00–24:00 UTC. Developing sessions are
strictly cut off at the slider timestamp to avoid future-session leakage.

Long ranges are server-aggregated with correct OHLCV semantics. Narrowing the
date range returns native-resolution bars.
