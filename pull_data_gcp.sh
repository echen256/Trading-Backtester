#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
DATA_PIPELINE_DIR="$REPO_ROOT/modules/data-pipeline"
LOG_DIR="$DATA_PIPELINE_DIR/logs"
ENV_FILE="$REPO_ROOT/.env"
LOG_FILE="$LOG_DIR/data_pull_gcp.txt"
DEFAULT_TABLE_ID="e-observer-454820-b3:stock_data_bucket_dataset_256.stock-data-table-daily"
DEFAULT_LOCATION="northamerica-northeast1"
DEFAULT_TIMEFRAME="1440"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

echo "LOG_FILE: $LOG_FILE"

log() {
  printf '%s [pull_data_gcp] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

exec >> "$LOG_FILE" 2>&1

log "Starting pull_data_gcp.sh"
log "Repo root: $REPO_ROOT"

log "Activating virtualenv at $REPO_ROOT/venv"
source "$REPO_ROOT/venv/bin/activate"

if [ -f "$ENV_FILE" ]; then
  log "Loading environment from $ENV_FILE"
  set -a
  source "$ENV_FILE"
  set +a
else
  log "No .env file found; continuing with current environment"
fi

has_table_id=false
has_location=false
has_timeframe=false

for arg in "$@"; do
  case "$arg" in
    --table-id|--table-id=*)
      has_table_id=true
      ;;
    --location|--location=*)
      has_location=true
      ;;
    --timeframe|--timeframe=*)
      has_timeframe=true
      ;;
  esac
done

pull_args=("$@")
if [ "$has_table_id" = false ]; then
  pull_args+=(--table-id "$DEFAULT_TABLE_ID")
fi
if [ "$has_location" = false ]; then
  pull_args+=(--location "$DEFAULT_LOCATION")
fi
if [ "$has_timeframe" = false ]; then
  pull_args+=(--timeframe "$DEFAULT_TIMEFRAME")
fi

log "Invoking trading-data-pull with args: ${pull_args[*]}"
trading-data-pull "${pull_args[@]}"
status=$?
log "trading-data-pull exited with status $status"
exit $status
