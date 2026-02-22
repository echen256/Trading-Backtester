#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)

DATA_PIPELINE_DIR="$REPO_ROOT/modules/data-pipeline"
LOG_DIR="$DATA_PIPELINE_DIR/logs"
ENV_FILE="$REPO_ROOT/.env"
DEFAULT_WATCHLIST="$DATA_PIPELINE_DIR/config/watchlists/NASDAQ.csv"
LOG_FILE="$LOG_DIR/data_download.txt"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

log() {
  printf '%s [download_data] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

exec >> "$LOG_FILE" 2>&1

log "Starting download_data.sh"
log "Repo root: $REPO_ROOT"
log "Environment file: ${ENV_FILE:-<none>}"
log "Default watchlist: $DEFAULT_WATCHLIST"
 
log "Activating virtualenv at $REPO_ROOT/venv"
source venv/bin/activate

if [ -f "$ENV_FILE" ]; then
  log "Loading environment from $ENV_FILE"
  set -a
  source "$ENV_FILE"
  set +a
elif [ -f ./.env ]; then
  log "Loading environment from ./ .env"
  set -a
  source ./.env
  set +a
else
  log "No .env file found; continuing with current environment"
fi

ARGS=()
if [ "$#" -gt 0 ]; then
  ARGS=("$@")
fi
add_watchlist=true
if [ ${#ARGS[@]} -gt 0 ]; then
  for arg in "${ARGS[@]}"; do
    if [[ $arg == --watchlist* ]]; then
      add_watchlist=false
      break
    fi
  done
fi

if [[ $add_watchlist == true ]]; then
  if [[ -f "$DEFAULT_WATCHLIST" ]]; then
    ARGS=("--watchlist" "$DEFAULT_WATCHLIST" "${ARGS[@]}")
    log "No --watchlist provided; defaulting to $DEFAULT_WATCHLIST"
  else
    log "Default watchlist not found at $DEFAULT_WATCHLIST; running without it"
  fi
else
  log "Using caller-provided arguments: ${ARGS[*]:-<none>}"
fi

log "Invoking trading-data-download with args: ${ARGS[*]:-<none>}"
trading-data-download "${ARGS[@]}"
status=$?
log "trading-data-download exited with status $status"
exit $status
