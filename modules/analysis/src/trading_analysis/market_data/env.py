"""Env helpers shared by market-data and graders."""

from __future__ import annotations

import os
from pathlib import Path

# market_data/env.py → trading_analysis → src → analysis → modules → Trading-Backtester
REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def load_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            os.environ[key] = cleaned
            return cleaned
    return None


def get_polygon_api_key(*, env_path: Path = DEFAULT_ENV_PATH) -> str | None:
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key:
        return api_key
    return load_env_value(env_path, "POLYGON_API_KEY")
