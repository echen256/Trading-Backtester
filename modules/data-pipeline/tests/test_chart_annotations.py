"""Tests for the universal chart annotation contract."""
from __future__ import annotations

import pytest

from trading_data_pipeline.chart_annotations import SCHEMA_VERSION, normalize_annotation_document


def _document() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "groups": [{"id": "trades", "label": "Trades", "color": "#22c55e"}],
        "panels": [
            {
                "id": "adaptive_macd",
                "label": "Adaptive MACD",
                "zero_line": True,
                "series": [
                    {
                        "id": "macd",
                        "name": "MACD",
                        "type": "line",
                        "points": [{"time": "2026-01-02", "value": 0.4}],
                    }
                ],
            }
        ],
        "points": [
            {
                "id": "entry-1",
                "group": "trades",
                "time": "2026-01-02",
                "pane": "price",
                "value": 101,
                "role": "entry",
                "marker": "triangle-up",
                "metadata": {"setup": "breakout"},
            }
        ],
        "links": [
            {
                "id": "trade-1",
                "group": "trades",
                "pane": "price",
                "start_time": "2026-01-02",
                "end_time": "2026-01-09",
                "start_value": 101,
                "end_value": 108,
            }
        ],
        "spans": [
            {
                "id": "holding-1",
                "group": "trades",
                "pane": "price",
                "start_time": "2026-01-02",
                "end_time": "2026-01-09",
            }
        ],
    }


def test_normalizes_complete_annotation_document() -> None:
    result = normalize_annotation_document(_document())

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["points"][0]["time"] == "2026-01-02T00:00:00Z"
    assert result["points"][0]["metadata"] == {"setup": "breakout"}
    assert result["panels"][0]["series"][0]["points"][0]["value"] == 0.4


def test_rejects_unknown_annotation_group() -> None:
    document = _document()
    document["points"][0]["group"] = "missing"

    with pytest.raises(ValueError, match="unknown group"):
        normalize_annotation_document(document)


def test_rejects_unknown_pane() -> None:
    document = _document()
    document["points"][0]["pane"] = "not-created"

    with pytest.raises(ValueError, match="unknown pane"):
        normalize_annotation_document(document)


def test_rejects_unsupported_schema() -> None:
    document = _document()
    document["schema_version"] = "future/v9"

    with pytest.raises(ValueError, match="Unsupported annotation schema"):
        normalize_annotation_document(document)
