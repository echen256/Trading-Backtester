#!/bin/bash
cd ./backend
mkdir -p logs
source venv/bin/activate

set -a  # Automatically export all variables
source ./.env
set +a

cd scripts

python3 upload_to_bigquery.py --pattern "TSLA-*.csv" --dataset stock_data_bucket_dataset_256 --table stock-data-table-daily