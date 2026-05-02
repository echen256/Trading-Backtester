#!/usr/bin/env bash
set -euo pipefail

mode="${1:-auto}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
template_path="${repo_root}/tools/emerge/trading-backtester.template.yaml"
runtime_dir="${repo_root}/reports/emerge/.runtime"
config_path="${runtime_dir}/trading-backtester.generated.yaml"
docker_image="${EMERGE_IMAGE:-achtelik/emerge:2.0.0}"
local_emerge_bin=""
postprocess_script="${repo_root}/tools/emerge/postprocess_reports.py"

usage() {
  echo "Usage: $0 [auto|local|docker]" >&2
  exit 1
}

case "${mode}" in
  auto|local|docker)
    ;;
  *)
    usage
    ;;
esac

mkdir -p "${runtime_dir}"
mkdir -p \
  "${repo_root}/reports/emerge/backend" \
  "${repo_root}/reports/emerge/data-pipeline" \
  "${repo_root}/reports/emerge/analysis" \
  "${repo_root}/reports/emerge/frontend"
sed "s|__ROOT__|${repo_root}|g" "${template_path}" > "${config_path}"

run_local() {
  if [[ -x "${repo_root}/venv/bin/emerge" ]]; then
    local_emerge_bin="${repo_root}/venv/bin/emerge"
  elif command -v emerge >/dev/null 2>&1; then
    local_emerge_bin="$(command -v emerge)"
  else
    return 1
  fi

  echo "Running Emerge with local install using ${config_path}"
  "${local_emerge_bin}" -c "${config_path}"
  "${repo_root}/venv/bin/python" "${postprocess_script}" "${repo_root}/reports/emerge"
}

run_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi

  sed "s|${repo_root}|/workspace|g" "${config_path}" > "${runtime_dir}/trading-backtester.docker.yaml"
  echo "Running Emerge with Docker image ${docker_image}"
  docker run --rm \
    -v "${repo_root}:/workspace" \
    "${docker_image}" \
    /workspace/reports/emerge/.runtime/trading-backtester.docker.yaml
  "${repo_root}/venv/bin/python" "${postprocess_script}" "${repo_root}/reports/emerge"
}

case "${mode}" in
  local)
    if [[ ! -x "${repo_root}/venv/bin/emerge" ]] && ! command -v emerge >/dev/null 2>&1; then
      echo "Local Emerge binary not found on PATH." >&2
      exit 1
    fi
    run_local
    ;;
  docker)
    if ! command -v docker >/dev/null 2>&1; then
      echo "Docker is not available on PATH." >&2
      exit 1
    fi
    run_docker
    ;;
  auto)
    if run_local; then
      exit 0
    fi
    if run_docker; then
      exit 0
    fi
    echo "Neither a local 'emerge' binary nor Docker is available." >&2
    echo "Install Emerge with 'pip install emerge-viz' or run with Docker installed." >&2
    exit 1
    ;;
esac
