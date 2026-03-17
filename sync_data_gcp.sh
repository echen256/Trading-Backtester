#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
BACKEND_DIR="$REPO_ROOT/backend"
mkdir -p "$BACKEND_DIR/logs"

source "$REPO_ROOT/venv/bin/activate"

trading-data-sync \
  --pattern "*.csv" \
  --dataset stock_data_bucket_dataset_256 \
  --table stock-data-table-daily "$@"
