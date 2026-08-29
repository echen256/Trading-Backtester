# Modules

Reusable pieces of the project live under this directory:

- `analysis/` – analysis utilities plus the canonical React market/study dashboard
- `data-pipeline/` – Polygon.io downloader plus BigQuery sync/pull scripts
- `frontend/` – compatibility launcher that delegates to `analysis/dashboard/`

Installable packages expose console scripts once you run `pip install -e` on the
module.
