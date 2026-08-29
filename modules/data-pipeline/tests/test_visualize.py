"""Tests for the local archive visualizer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trading_data_pipeline.visualize import (
    _find_data_file,
    _load_rows,
    _load_workspace_manifest,
    _parse_timeframe,
    main,
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


def test_parse_timeframe_accepts_multiplied_hour_day_and_week_suffixes() -> None:
    assert _parse_timeframe("2h") == 120
    assert _parse_timeframe("3d") == 4320
    assert _parse_timeframe("2w") == 20160


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
    assert 'data-feature="sessionGaps"' in html
    assert 'id="gap-min-pct"' in html
    assert 'id="gap-min-abs"' in html
    assert 'data-feature="dealingRanges"' in html
    assert "function dealingRangeShapes()" in html
    assert "function dealingRangeEventTraces()" in html
    assert payload.dealing_ranges["config"] == {"lookback": 5, "lookahead": 1}
    assert "Strategy Statistics" in html
    assert "Strategy overlay" in html
    assert 'rangebreaks: [{ bounds: ["sat", "mon"] }]' in html
    assert "function computeSessionGaps()" in html
    assert '...annotationSpanShapes("price")' in html


def test_render_chart_html_includes_universal_annotations() -> None:
    rows = _make_rows()
    payload = make_chart_payload(
        ticker="MU",
        timeframe_minutes=1440,
        rows=rows,
        annotations={
            "schema_version": "trading-chart-annotations/v1",
            "groups": [{"id": "signals", "label": "Signals", "color": "#ff00ff"}],
            "panels": [
                {
                    "id": "adaptive_macd",
                    "label": "Adaptive MACD",
                    "series": [
                        {
                            "id": "line",
                            "type": "line",
                            "points": [{"time": rows[0]["time"], "value": 0.5}],
                        }
                    ],
                }
            ],
            "points": [
                {
                    "id": "signal-1",
                    "group": "signals",
                    "time": rows[0]["time"],
                    "pane": "price",
                    "value": rows[0]["close"],
                    "marker": "triangle-up",
                }
            ],
        },
    )

    html = render_chart_html(payload)

    assert 'id="annotation-controls"' in html
    assert 'id="custom-indicator-panels"' in html
    assert "trading-chart-annotations/v1" in html
    assert "function annotationPointTraces" in html
    assert "function renderCustomPanels" in html
    assert "Adaptive MACD" in html


def test_load_workspace_manifest_builds_selectable_views(tmp_path: Path) -> None:
    csv_path = tmp_path / "MU.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,100,102,99,101,1000\n"
        "2024-01-02T00:00:00Z,101,104,100,103,1100\n",
        encoding="utf-8",
    )
    annotations_path = tmp_path / "study.json"
    annotations_path.write_text(
        '{"schema_version":"trading-chart-annotations/v1","groups":[],"panels":[],"points":[],"links":[],"spans":[]}',
        encoding="utf-8",
    )
    manifest_path = tmp_path / "workspace.json"
    manifest_path.write_text(
        """{
          "schema_version": "trading-chart-workspace/v1",
          "title": "Test workspace",
          "views": [{
            "id": "mu-daily-macd",
            "ticker": "MU",
            "timeframe": "D",
            "study_id": "macd",
            "study_label": "MACD",
            "data": "MU.csv",
            "annotations": "study.json"
          }]
        }""",
        encoding="utf-8",
    )

    title, views = _load_workspace_manifest(manifest_path)

    assert title == "Test workspace"
    assert len(views) == 1
    assert views[0].timeframe == "D"
    assert views[0].study_label == "MACD"
    assert "MU" in views[0].html

    output_path = tmp_path / "workspace.html"
    main(["--workspace", str(manifest_path), "--output", str(output_path), "--no-open"])
    workspace_html = output_path.read_text(encoding="utf-8")
    assert 'id="timeframe"' in workspace_html
    assert 'id="study"' in workspace_html


def test_load_workspace_manifest_requires_supported_schema(tmp_path: Path) -> None:
    manifest_path = tmp_path / "workspace.json"
    manifest_path.write_text('{"schema_version":"old","views":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        _load_workspace_manifest(manifest_path)
