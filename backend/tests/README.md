# Tests

## TSLA download integration test

This suite currently contains a single integration test that exercises the Polygon download path:

```
cd backend
source venv/bin/activate
pytest tests/test_download_tsla.py
```

Make sure the repo-level `.env` (or `backend/.env` as a fallback) contains `POLYGON_API_KEY` before running. The test will be skipped automatically if the key is missing.
