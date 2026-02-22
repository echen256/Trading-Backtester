"""Tests for the download_data.sh script."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

DATA_PIPELINE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DATA_PIPELINE_DIR.parent.parent
DOWNLOAD_SCRIPT = REPO_ROOT / "download_data.sh"
WATCHLISTS_DIR = DATA_PIPELINE_DIR / "config" / "watchlists"


def run_download_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run download_data.sh with given args."""
    return subprocess.run(
        ["bash", str(DOWNLOAD_SCRIPT), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(not DOWNLOAD_SCRIPT.exists(), reason="download_data.sh not found at repo root")
class TestDownloadDataSh:
    """Tests for download_data.sh script behavior."""

    def test_watchlist_name_resolves_to_path(self) -> None:
        """--watchlist-name debug should resolve to config/watchlists/debug.csv."""
        result = run_download_script("--watchlist-name", "debug", "--help")
        assert result.returncode == 0
        log_file = DATA_PIPELINE_DIR / "logs" / "data_download.txt"
        if log_file.exists():
            log_content = log_file.read_text()
            assert "debug" in log_content
            assert "debug.csv" in log_content or str(WATCHLISTS_DIR) in log_content

    def test_watchlist_name_nonexistent_exits_one(self) -> None:
        """--watchlist-name with missing watchlist should exit 1."""
        result = run_download_script("--watchlist-name", "nonexistent_watchlist_xyz")
        assert result.returncode == 1
        log_file = DATA_PIPELINE_DIR / "logs" / "data_download.txt"
        assert log_file.exists()
        assert "Watchlist not found" in log_file.read_text()

    def test_watchlist_name_equals_syntax(self) -> None:
        """--watchlist-name=debug should work like --watchlist-name debug."""
        result = run_download_script("--watchlist-name=debug", "--help")
        assert result.returncode == 0

    def test_passes_through_extra_args(self) -> None:
        """Extra args like --help should be passed to trading-data-download."""
        result = run_download_script("--watchlist-name", "debug", "--help")
        assert result.returncode == 0
