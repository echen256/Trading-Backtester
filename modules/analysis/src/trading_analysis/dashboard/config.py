"""Filesystem configuration for the local analysis dashboard."""

from __future__ import annotations

import os
from pathlib import Path


ANALYSIS_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = ANALYSIS_ROOT.parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
CONTRACTS_ROOT = ANALYSIS_ROOT / "dashboard" / "contracts"
DEFAULT_ARTIFACT_ROOT = ANALYSIS_ROOT / "artifacts"
DEFAULT_WEB_ROOT = ANALYSIS_ROOT / "dashboard" / "dist"


def artifact_root() -> Path:
    configured = os.getenv("TRADING_ANALYSIS_ARTIFACT_ROOT")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ARTIFACT_ROOT


def allowed_data_roots() -> tuple[Path, ...]:
    configured = os.getenv("TRADING_DASHBOARD_DATA_ROOTS", "")
    roots = [WORKSPACE_ROOT.resolve(), REPOSITORY_ROOT.resolve()]
    roots.extend(
        Path(item).expanduser().resolve()
        for item in configured.split(os.pathsep)
        if item.strip()
    )
    return tuple(dict.fromkeys(roots))


def ensure_allowed_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed_data_roots()):
        allowed = ", ".join(str(root) for root in allowed_data_roots())
        raise PermissionError(f"Path is outside configured data roots ({allowed}): {resolved}")
    return resolved
