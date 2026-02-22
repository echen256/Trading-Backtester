"""Pytest fixtures for data-pipeline tests."""
from __future__ import annotations

from pathlib import Path

import pytest

DATA_PIPELINE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DATA_PIPELINE_DIR.parent.parent
DOWNLOAD_SCRIPT = REPO_ROOT / "download_data.sh"


@pytest.fixture
def tmp_watchlist(tmp_path: Path) -> Path:
    """Create a temporary watchlist CSV."""
    watchlist = tmp_path / "test_watchlist.csv"
    watchlist.write_text("Symbol\nAAPL\nMSFT\nGOOG\n")
    return watchlist


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a temporary download config."""
    config = tmp_path / "download.json"
    config.write_text('{"minimum_market_cap": 0, "limit": 5}')
    return config


@pytest.fixture(autouse=True)
def isolate_polygon_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure POLYGON_API_KEY is set for downloader init (avoid RuntimeError in tests)."""
    monkeypatch.setenv("POLYGON_API_KEY", "test-key-for-unit-tests")
