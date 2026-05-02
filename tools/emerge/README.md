# Emerge Setup

This repository includes an Emerge template at [trading-backtester.template.yaml](/Users/ericchen/Documents/Dev/Trading/Trading-Backtester/tools/emerge/trading-backtester.template.yaml).

Use the wrapper script from the repo root:

```bash
./scripts/run_emerge.sh
```

The script prefers a local `emerge` install and falls back to Docker if available. Generated reports are written to `reports/emerge/` and include one analysis each for:

- `backend`
- `modules/data-pipeline`
- `modules/analysis`
- `modules/frontend/src`

Useful commands:

```bash
./scripts/run_emerge.sh auto
./scripts/run_emerge.sh local
./scripts/run_emerge.sh docker
./scripts/serve_emerge.sh backend
```

If you want a local install instead of Docker:

```bash
pip install 'setuptools<81' emerge-viz
```

If opening `emerge.html` directly shows a blank or empty-looking UI, serve it over localhost instead:

```bash
./scripts/serve_emerge.sh backend
```

Then open `http://127.0.0.1:8765/emerge.html`.
