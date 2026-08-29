"""Adapter from options-premium payloads to canonical dashboard artifacts."""

from __future__ import annotations

import math
from typing import Any

from trading_analysis.dashboard import DatasetImporter, ImportOptions, StudyArtifactWriter


COLORS = ("#56b6c2", "#f6c85f", "#ef6f91", "#9b8cff", "#42d392", "#ff9f43", "#4da3ff")


def _json_safe(value: Any) -> Any:
    """Replace non-finite provider values before strict artifact serialization."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def publish_premium_payload(payload: dict[str, Any]) -> str:
    payload = _json_safe(payload)
    ticker = str(payload.get("ticker") or "UNKNOWN").upper()
    underlying = payload.get("underlying") or []
    if not underlying:
        raise ValueError("Options premium payload has no underlying bars")
    rows = [{
        "timestamp": item["date"], "open": item["o"], "high": item["h"],
        "low": item["l"], "close": item["c"], "volume": item.get("v"),
    } for item in underlying]
    importer = DatasetImporter()
    dataset = importer.import_rows(
        rows,
        source_label=f"options-premium://{ticker}/{payload.get('start_date')}/{payload.get('end_date')}",
        options=ImportOptions(
            symbol=ticker, asset_class="stock", venue="polygon", provider="polygon-option-study",
            interval_seconds=86400, calendar="XNYS",
        ),
    )
    premium_series = []
    for index, (symbol, values) in enumerate(sorted((payload.get("premiums") or {}).items())):
        color = COLORS[index % len(COLORS)]
        closes = values.get("close") or []
        highs = values.get("high") or []
        if closes:
            premium_series.append({
                "id": f"{symbol}-close", "name": f"{symbol} close", "type": "line", "color": color,
                "points": [{"time": point["date"], "value": point["value"]} for point in closes],
            })
        if highs:
            premium_series.append({
                "id": f"{symbol}-high", "name": f"{symbol} high", "type": "line", "color": color,
                "line_width": 1,
                "points": [{"time": point["date"], "value": point["value"]} for point in highs],
            })
    chart = {
        "schema_version": "trading-chart-study/v2",
        "groups": [],
        "panels": [{
            "id": "option-premiums", "label": "Option premiums", "height": 320,
            "visible": True, "zero_line": False, "series": premium_series,
        }],
        "points": [], "links": [], "spans": [], "levels": [],
    }
    liquidity = payload.get("liquidity") or {}
    writer = StudyArtifactWriter(importer.catalog)
    manifest = writer.build_manifest(
        study_id="options-premium-vs-underlying",
        study_name="Options Premium vs Underlying",
        version="2.0",
        description="Underlying OHLC with selectable option close and high premium series.",
        generator="trading_analysis.options_premium",
        parameters=payload.get("filters") or {},
        views=[{
            "id": f"{ticker.lower()}-{payload.get('start_date')}-{payload.get('end_date')}",
            "label": f"{ticker} · {payload.get('start_date')} to {payload.get('end_date')}",
            "dataset_id": dataset["id"],
            "chart": chart,
        }],
        metrics=[
            {"label": "Liquid contracts", "value": liquidity.get("contract_count", 0)},
            {"label": "Plotted contracts", "value": liquidity.get("plotted_count", 0)},
        ],
        tables=[{
            "id": "contracts", "label": "Contracts",
            "columns": ["symbol", "option_type", "strike", "expiration", "last_volume", "open_interest"],
            "rows": payload.get("contracts") or [],
        }],
        resources={"payload": {"path": "resources/payload.json", "media_type": "application/json"}},
    )
    return str(writer.publish(manifest, resource_files={"payload.json": payload}))
