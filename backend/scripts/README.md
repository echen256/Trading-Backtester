# Scripts

The standalone data-ingestion utilities now live in `modules/data-pipeline` and
expose CLI entry points once the module is installed.

## Upload CSVs to BigQuery

```
cd backend
source venv/bin/activate
trading-data-sync \
  --dataset my_dataset \
  --table equities_1440 \
  --timeframe 1440 \
  --replace
```

Notes:
- Authenticate with Google Cloud first (e.g., set `GOOGLE_APPLICATION_CREDENTIALS`
  to a service-account JSON with BigQuery write access, or run
  `gcloud auth application-default login`).
- `--replace` truncates the table before the first load; omit it to append.
- Use `--limit-files` for dry runs and `--pattern "TSLA-*.csv"` to target specific tickers.
