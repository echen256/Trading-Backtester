#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)

DATA_PIPELINE_DIR="$REPO_ROOT/modules/data-pipeline"
LOG_DIR="$DATA_PIPELINE_DIR/logs"
ENV_FILE="$REPO_ROOT/.env"
LOG_FILE="$LOG_DIR/data_sync.txt"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

echo "LOG_FILE: $LOG_FILE"

log() {
  printf '%s [sync_data] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

exec >> "$LOG_FILE" 2>&1

log "Starting sync_data.sh"
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

log "Invoking trading-data-sync with args: $*"
trading-data-sync --replace "$@"
status=$?
log "trading-data-sync exited with status $status"
exit $status
