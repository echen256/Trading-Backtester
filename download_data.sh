#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
BACKEND_DIR="$REPO_ROOT/backend"
LOG_DIR="$BACKEND_DIR/logs"
ENV_FILE="$REPO_ROOT/.env"
mkdir -p "$LOG_DIR"

cd "$BACKEND_DIR"
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

trading-data-download "$@" >> "$LOG_DIR/data_download.txt" 2>&1
