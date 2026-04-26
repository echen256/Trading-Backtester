"""Tests for the local archive visualizer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trading_data_pipeline.visualize import (
    _find_data_file,
    _load_rows,
    _parse_timeframe,
    make_chart_payload,
    render_chart_html,
)


def _make_rows(count: int = 120) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for index in range(count):
        timestamp = start + timedelta(days=index)
        base_price = 100 + index * 0.4
        rows.append(
            {
                "timestamp": timestamp,
                "time": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": base_price - 0.7,
                "high": base_price + 1.1,
                "low": base_price - 1.4,
                "close": base_price + ((index % 5) - 2) * 0.3,
                "volume": 1_000_000 + index * 1000,
            }
        )
    return rows


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


def test_render_chart_html_includes_strategy_dropdown() -> None:
    rows = _make_rows()
    payload = make_chart_payload(
        ticker="MU",
        timeframe_minutes=1440,
        rows=rows,
        source_label="modules/data-pipeline/data/1440/MU-1440M.csv",
    )

    html = render_chart_html(payload)

    assert 'id="strategy-select"' in html
    assert 'id="strategy-stats-panel"' in html
    assert "Strategy Statistics" in html
    assert "Strategy overlay" in html
    assert 'rangebreaks: [{ bounds: ["sat", "mon"] }]' in html
