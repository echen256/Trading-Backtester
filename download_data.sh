#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)

DATA_PIPELINE_DIR="$REPO_ROOT/modules/data-pipeline"
LOG_DIR="$DATA_PIPELINE_DIR/logs"
WATCHLISTS_DIR="$DATA_PIPELINE_DIR/config/watchlists"
ENV_FILE="$REPO_ROOT/.env"
DEFAULT_WATCHLIST="$WATCHLISTS_DIR/NASDAQ.csv"
LOG_FILE="$LOG_DIR/data_download.txt"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

echo "LOG_FILE: $LOG_FILE"

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

add_watchlist=true
watchlist_name=""
pass_args=()
i=1
while [ $i -le $# ]; do
  arg="${!i}"
  case "$arg" in
    --watchlist-name=*)
      watchlist_name="${arg#*=}"
      add_watchlist=true
      ;;
    --watchlist-name)
      ((i++))
      watchlist_name="${!i:-}"
      add_watchlist=true
      ;;
    --watchlist|--watchlist=*)
      add_watchlist=false
      pass_args+=("$arg")
      ;;
    *)
      pass_args+=("$arg")
      ;;
  esac
  ((i++))
done

# Resolve watchlist path from name if given
watchlist_path=""
run_download() {
  if ((${#pass_args[@]} > 0)); then
    trading-data-download "$@" "${pass_args[@]}"
  else
    trading-data-download "$@"
  fi
}
if [[ -n "$watchlist_name" ]]; then
  if [[ "$watchlist_name" == *.csv ]]; then
    watchlist_path="$WATCHLISTS_DIR/$watchlist_name"
  else
    watchlist_path="$WATCHLISTS_DIR/${watchlist_name}.csv"
  fi
  if [[ -f "$watchlist_path" ]]; then
    log "Using watchlist $watchlist_name -> $watchlist_path"
    run_download --watchlist "$watchlist_path"
  else
    log "Watchlist not found: $watchlist_path"
    exit 1
  fi
elif [[ $add_watchlist == true ]] && [[ -f "$DEFAULT_WATCHLIST" ]]; then
  log "No --watchlist provided; defaulting to $DEFAULT_WATCHLIST"
  run_download --watchlist "$DEFAULT_WATCHLIST"
elif [[ $add_watchlist == true ]]; then
  log "Default watchlist not found at $DEFAULT_WATCHLIST; running without it"
  run_download
else
  log "Using caller-provided arguments: ${pass_args[*]:-<none>}"
  run_download
fi
status=$?
log "trading-data-download exited with status $status"
exit $status
