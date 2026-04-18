# Modules

Reusable pieces of the project live under this directory:

- `analysis/` – CLI utilities for parsing broker order exports
- `data-pipeline/` – Polygon.io downloader plus BigQuery sync/pull scripts
- `frontend/` – React dashboard (moved from the former `trading-frontend/` path)

Installable packages expose console scripts once you run `pip install -e` on the
module.
