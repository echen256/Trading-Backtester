#!/usr/bin/env bash
# Run one compliance-monitor pass (used by cron).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/venv/bin/activate"

LOG_DIR="$REPO_ROOT/modules/analysis/order-data"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/compliance-monitor.cron.log"

{
  echo "==== $(date -u '+%Y-%m-%dT%H:%M:%SZ') / local $(date '+%Y-%m-%dT%H:%M:%S%z') ===="
  # Scheduled digests always email (tagged [TRADING-COMPLIANCE]).
  trading-compliance-monitor --once --force-email --no-rth-only
  echo "exit=$?"
} >>"$LOG_FILE" 2>&1
