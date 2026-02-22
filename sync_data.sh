#!/bin/bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")" && pwd)
DATA_DIR="$REPO_ROOT/modules/data-pipeline/data/1440"

gsutil -m cp "$DATA_DIR"/*.csv gs://stock-data-bucket-256/data/1440
