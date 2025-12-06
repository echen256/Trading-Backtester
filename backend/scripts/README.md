# Scripts

## upload_to_bigquery.py

Uploads the CSV outputs under `app/data_download/data/` into a BigQuery table.

```
cd backend
source venv/bin/activate
python scripts/upload_to_bigquery.py \
  --dataset my_dataset \
  --table equities_1440 \
  --timeframe 1440 \
  --replace
```

Notes:
- Authenticate with Google Cloud first (e.g., set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account JSON with BigQuery write access, or run `gcloud auth application-default login`).
- `--replace` truncates the table before the first load; omit it to append.
- Use `--limit-files` for dry runs and `--pattern "TSLA-*.csv"` to target specific tickers.
