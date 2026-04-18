"""Tests for the local archive visualizer."""
from __future__ import annotations

from pathlib import Path

import pytest

from trading_data_pipeline.visualize import _find_data_file, _parse_timeframe


def test_parse_timeframe_accepts_daily_aliases() -> None:
    assert _parse_timeframe("D") == 1440
    assert _parse_timeframe("1d") == 1440


def test_parse_timeframe_accepts_minute_suffix() -> None:
    assert _parse_timeframe("15m") == 15


def test_find_data_file_prefers_timeframe_directory(tmp_path: Path) -> None:
    csv_path = tmp_path / "1440" / "AAPL-1440M.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("timestamp,open,high,low,close\n2024-01-01T00:00:00Z,1,2,0.5,1.5\n")

    result = _find_data_file(tmp_path, "AAPL", 1440)

    assert result == csv_path


def test_find_data_file_reports_available_timeframes(tmp_path: Path) -> None:
    csv_path = tmp_path / "60" / "AAPL-60M.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("timestamp,open,high,low,close\n2024-01-01T00:00:00Z,1,2,0.5,1.5\n")

    with pytest.raises(FileNotFoundError, match="Available files for AAPL: AAPL-60M.csv"):
        _find_data_file(tmp_path, "AAPL", 1440)
