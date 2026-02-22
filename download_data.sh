#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
DATA_PIPELINE_DIR="$REPO_ROOT/modules/data-pipeline"
LOG_DIR="$DATA_PIPELINE_DIR/logs"
ENV_FILE="$REPO_ROOT/.env"
DEFAULT_WATCHLIST="$DATA_PIPELINE_DIR/config/watchlists/NASDAQ.csv"
mkdir -p "$LOG_DIR"
 
source venv/bin/activate

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
elif [ -f ./.env ]; then
  set -a
  source ./.env
  set +a
fi

ARGS=("$@")
add_watchlist=true
for arg in "${ARGS[@]}"; do
  if [[ $arg == --watchlist* ]]; then
    add_watchlist=false
    break
  fi
done

if [[ $add_watchlist == true && -f "$DEFAULT_WATCHLIST" ]]; then
  ARGS=("--watchlist" "$DEFAULT_WATCHLIST" "${ARGS[@]}")
fi

trading-data-download "${ARGS[@]}" >> "$LOG_DIR/data_download.txt" 2>&1
