#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
BACKEND_DIR="$REPO_ROOT/backend"
mkdir -p "$BACKEND_DIR/logs"

cd "$BACKEND_DIR"
source venv/bin/activate

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

trading-data-sync \
  --pattern "TSLA-*.csv" \
  --dataset stock_data_bucket_dataset_256 \
  --table stock-data-table-daily "$@"
