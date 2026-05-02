#!/usr/bin/env bash
set -euo pipefail

target="${1:-backend}"
port="${2:-8765}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

case "${target}" in
  backend)
    report_dir="${repo_root}/reports/emerge/backend/html"
    ;;
  data-pipeline)
    report_dir="${repo_root}/reports/emerge/data-pipeline/html"
    ;;
  analysis)
    report_dir="${repo_root}/reports/emerge/analysis/html"
    ;;
  frontend)
    report_dir="${repo_root}/reports/emerge/frontend/html"
    ;;
  *)
    echo "Usage: $0 [backend|data-pipeline|analysis|frontend] [port]" >&2
    exit 1
    ;;
esac

if [[ ! -f "${report_dir}/emerge.html" ]]; then
  echo "Missing report at ${report_dir}/emerge.html" >&2
  echo "Run ./scripts/run_emerge.sh first." >&2
  exit 1
fi

python_bin="${repo_root}/venv/bin/python"
if [[ ! -x "${python_bin}" ]]; then
  python_bin="$(command -v python3 || true)"
fi

if [[ -z "${python_bin}" ]]; then
  echo "Could not find a Python interpreter." >&2
  exit 1
fi

echo "Serving ${target} report from ${report_dir}"
echo "Open: http://127.0.0.1:${port}/emerge.html"
cd "${report_dir}"
exec "${python_bin}" -m http.server "${port}"
