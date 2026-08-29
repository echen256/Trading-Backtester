# Canonical dashboard architecture

## Ownership

`modules/analysis/dashboard/src/chart/ChartWorkbench.tsx` is the only component
that owns interactive market and study rendering. It is deliberately unaware of
Python generators and provider-specific formats. `modules/frontend` delegates
its scripts and root `App` export here so old entry points cannot fork the UI.

The Python package under `trading_analysis.dashboard` owns the other side of
the boundary:

1. `DatasetImporter` validates heterogeneous OHLCV files and writes normalized,
   content-addressed Parquet.
2. `DatasetCatalog` indexes dataset provenance, coverage, quality, and immutable
   study runs in SQLite.
3. `StudyArtifactWriter` validates and atomically publishes generator output.
4. The local HTTP server exposes catalog metadata, bounded/range-aggregated bars,
   native-bar TPO profiles, study manifests, contracts, and resources to the
   React application.

The browser never reads arbitrary source CSVs and generators never import React
code. The versioned JSON contracts are the integration point.

## Data and study flow

```text
CSV / CSV.gz / Parquet              Python study generator
          |                                  |
          v                                  v
  DatasetImporter  ----------------> StudyArtifactWriter
          |                                  |
          v                                  v
 normalized Parquet + metadata       manifest + resources
          |                                  |
          +------------ SQLite --------------+
                           |
                           v
                   local range API
                           |
                           v
                    React workbench
```

Normalized datasets and study runs live in `modules/analysis/artifacts/` and
are intentionally ignored by Git. Source reports remain wherever their
generators currently write them; a report study copies a stable snapshot into
its immutable run bundle.

## Contracts

- `trading-market-dataset/v1` describes identity, interval, storage,
  provenance, coverage, and quality.
- `trading-chart-study/v2` describes synchronized panes, series, toggle groups,
  markers, links, bounded spans, and levels.
- `trading-study-run/v1` describes a reproducible run, input fingerprints,
  chart views, metrics, tables, methodology, and downloadable resources.

The writer accepts the established `trading-chart-annotations/v1` shape and
upgrades it at publication. Unknown group references and non-conforming output
fail before a run becomes visible. Publication uses a temporary directory and
rename so the UI never sees half-written artifacts.

## Generator migration

Chart-native producers:

- MACD histogram shape exports
- gap-up afternoon re-entry audit
- options premium versus underlying (opt-in CLI flag)

Report producers publishing canonical run bundles:

- QQQ gap sweep sequence
- daily SMH/QQQ histogram events
- DVOL MACD/BTC
- weekly swing failures
- QQQ sector-relative divergence
- US 30Y/gold comparison
- SMH SEMI-VOL
- QQQ early green-to-red
- trade TPO grades
- trade hold review

The report adapter exposes scalar JSON values as metrics, the first 1,000 CSV
rows as a table, Markdown/text as methodology, and every source file as a
download. This is the migration bridge, not a second rendering system. A report
can later add chart views without changing how the dashboard discovers it.

Portable Plotly/TPO drill-down files, scanner run charts, and trade-review
charts remain export formats for workflows that need standalone files. They are
not alternate dashboard shells. New study-level interactivity belongs in the
chart contract and `ChartWorkbench`.

## Data-quality and operational snags

- Filenames are hints, not truth. At least one archive named `MU-15M.csv`
  contains sparse one-minute timestamps. The importer infers from timestamps
  unless an explicit interval is supplied.
- `I_VIX-1440M.csv` currently contains 20 internally invalid OHLC rows. It was
  rejected instead of silently widening highs/lows. Fix or explicitly curate
  the source before importing it.
- Continuous crypto can be gap-counted directly. Equities need an exchange
  calendar to distinguish missing bars from nights, weekends, and holidays;
  until calendar-aware validation is added, the catalog records that stock gap
  counting was skipped.
- Five years of five-minute bars are too large to ship to the browser at once.
  Parquet predicate filtering serves narrow ranges at native resolution; wider
  ranges are server-resampled using first/max/min/last/sum semantics.
- TPO profiles cannot be derived correctly from a multi-hour overview candle.
  The profile endpoint reads the underlying native Parquet session separately,
  uses NYSE 09:30–16:00 New York time for equities and UTC days for crypto, and
  stops at the slider timestamp so a developing profile cannot see future bars.
- The API is designed for a trusted workstation and binds to `127.0.0.1` by
  default. There is no authentication. Do not bind it to a public interface
  without adding access control.
- Dataset IDs include a content fingerprint. Re-running a generator against
  changed input produces a new immutable run rather than mutating historical
  provenance.
- Multiple events can share one candle. The event table retains all events;
  the current candle click target selects one marker at that timestamp. If this
  becomes common, the contract/UI should add a stacked-event picker.
- Artifacts and frontend build products are ignored. A new checkout must import
  data, publish or reindex studies, and build the frontend locally.

## Extension rule

Add provider aliases and normalization behavior in `DatasetImporter`, add study
semantics to the JSON schemas and Python adapter, and render them once in
`ChartWorkbench`. Do not add a provider-specific browser loader or a new
generator-specific dashboard.
