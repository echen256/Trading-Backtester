"""Versioned annotation and indicator-pane contract for local chart viewers."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "trading-chart-annotations/v1"
BUILTIN_PANES = {"price", "fisher", "macd"}
SERIES_TYPES = {"line", "histogram", "area"}
MARKERS = {
    "circle", "square", "diamond", "triangle-up", "triangle-down",
    "cross", "x", "star",
}


def _identifier(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must be a non-empty string")
    return normalized


def _time(value: object, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value: object, field: str, *, optional: bool = False) -> float | None:
    if optional and value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _metadata(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("annotation metadata must be an object")
    return {str(key): item for key, item in value.items()}


def empty_annotation_document() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "groups": [],
        "panels": [],
        "points": [],
        "links": [],
        "spans": [],
    }


def normalize_annotation_document(raw: dict[str, object] | None) -> dict[str, object]:
    """Validate and normalize the public annotation JSON contract."""

    if raw is None:
        return empty_annotation_document()
    if not isinstance(raw, dict):
        raise ValueError("annotation document must be a JSON object")
    version = raw.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported annotation schema: {version!r}; expected {SCHEMA_VERSION!r}")

    groups: list[dict[str, object]] = []
    group_ids: set[str] = set()
    for index, item in enumerate(raw.get("groups") or []):
        if not isinstance(item, dict):
            raise ValueError(f"groups[{index}] must be an object")
        group_id = _identifier(item.get("id"), f"groups[{index}].id")
        if group_id in group_ids:
            raise ValueError(f"duplicate annotation group id: {group_id}")
        group_ids.add(group_id)
        groups.append({
            "id": group_id,
            "label": str(item.get("label") or group_id),
            "color": str(item.get("color") or "#56b6c2"),
            "visible": bool(item.get("visible", True)),
        })

    panels: list[dict[str, object]] = []
    pane_ids = set(BUILTIN_PANES)
    for index, item in enumerate(raw.get("panels") or []):
        if not isinstance(item, dict):
            raise ValueError(f"panels[{index}] must be an object")
        panel_id = _identifier(item.get("id"), f"panels[{index}].id")
        if panel_id in pane_ids:
            raise ValueError(f"duplicate or reserved pane id: {panel_id}")
        pane_ids.add(panel_id)
        series_items: list[dict[str, object]] = []
        for series_index, series in enumerate(item.get("series") or []):
            if not isinstance(series, dict):
                raise ValueError(f"panels[{index}].series[{series_index}] must be an object")
            series_type = str(series.get("type") or "line")
            if series_type not in SERIES_TYPES:
                raise ValueError(f"unsupported series type: {series_type}")
            points: list[dict[str, object]] = []
            for point_index, point in enumerate(series.get("points") or []):
                if not isinstance(point, dict):
                    raise ValueError(f"panel series point {point_index} must be an object")
                points.append({
                    "time": _time(point.get("time"), f"panel series point {point_index}.time"),
                    "value": _number(point.get("value"), f"panel series point {point_index}.value", optional=True),
                    **({"color": str(point["color"])} if point.get("color") else {}),
                })
            series_items.append({
                "id": _identifier(series.get("id") or series.get("name"), f"panels[{index}].series[{series_index}].id"),
                "name": str(series.get("name") or series.get("id") or "Series"),
                "type": series_type,
                "color": str(series.get("color") or "#56b6c2"),
                "line_width": _number(series.get("line_width", 2), "line_width"),
                "points": points,
            })
        panels.append({
            "id": panel_id,
            "label": str(item.get("label") or panel_id),
            "height": int(_number(item.get("height", 260), "panel height") or 260),
            "visible": bool(item.get("visible", True)),
            "zero_line": bool(item.get("zero_line", False)),
            "series": series_items,
        })

    def require_group(item: dict[str, object], field: str) -> str:
        group = _identifier(item.get("group"), field)
        if group not in group_ids:
            raise ValueError(f"{field} references unknown group {group!r}")
        return group

    points: list[dict[str, object]] = []
    point_ids: set[str] = set()
    for index, item in enumerate(raw.get("points") or []):
        if not isinstance(item, dict):
            raise ValueError(f"points[{index}] must be an object")
        point_id = _identifier(item.get("id"), f"points[{index}].id")
        if point_id in point_ids:
            raise ValueError(f"duplicate annotation point id: {point_id}")
        point_ids.add(point_id)
        pane = str(item.get("pane") or "price")
        if pane not in pane_ids:
            raise ValueError(f"points[{index}].pane references unknown pane {pane!r}")
        marker = str(item.get("marker") or "circle")
        if marker not in MARKERS:
            raise ValueError(f"unsupported annotation marker: {marker}")
        points.append({
            "id": point_id,
            "group": require_group(item, f"points[{index}].group"),
            "time": _time(item.get("time"), f"points[{index}].time"),
            "pane": pane,
            "value": _number(item.get("value"), f"points[{index}].value"),
            "label": str(item.get("label") or ""),
            "role": str(item.get("role") or "event"),
            "marker": marker,
            "color": str(item.get("color") or ""),
            "size": _number(item.get("size", 11), f"points[{index}].size"),
            "metadata": _metadata(item.get("metadata")),
        })

    annotation_ids = set(point_ids)
    links: list[dict[str, object]] = []
    for index, item in enumerate(raw.get("links") or []):
        if not isinstance(item, dict):
            raise ValueError(f"links[{index}] must be an object")
        pane = str(item.get("pane") or "price")
        if pane not in pane_ids:
            raise ValueError(f"links[{index}].pane references unknown pane {pane!r}")
        link_id = _identifier(item.get("id"), f"links[{index}].id")
        if link_id in annotation_ids:
            raise ValueError(f"duplicate annotation id: {link_id}")
        annotation_ids.add(link_id)
        links.append({
            "id": link_id,
            "group": require_group(item, f"links[{index}].group"),
            "pane": pane,
            "start_time": _time(item.get("start_time"), f"links[{index}].start_time"),
            "end_time": _time(item.get("end_time"), f"links[{index}].end_time"),
            "start_value": _number(item.get("start_value"), f"links[{index}].start_value"),
            "end_value": _number(item.get("end_value"), f"links[{index}].end_value"),
            "label": str(item.get("label") or ""),
            "color": str(item.get("color") or ""),
            "dash": str(item.get("dash") or "dot"),
            "metadata": _metadata(item.get("metadata")),
        })

    spans: list[dict[str, object]] = []
    for index, item in enumerate(raw.get("spans") or []):
        if not isinstance(item, dict):
            raise ValueError(f"spans[{index}] must be an object")
        pane = str(item.get("pane") or "price")
        if pane not in pane_ids:
            raise ValueError(f"spans[{index}].pane references unknown pane {pane!r}")
        span_id = _identifier(item.get("id"), f"spans[{index}].id")
        if span_id in annotation_ids:
            raise ValueError(f"duplicate annotation id: {span_id}")
        annotation_ids.add(span_id)
        spans.append({
            "id": span_id,
            "group": require_group(item, f"spans[{index}].group"),
            "pane": pane,
            "start_time": _time(item.get("start_time"), f"spans[{index}].start_time"),
            "end_time": _time(item.get("end_time"), f"spans[{index}].end_time"),
            "lower": _number(item.get("lower"), f"spans[{index}].lower", optional=True),
            "upper": _number(item.get("upper"), f"spans[{index}].upper", optional=True),
            "label": str(item.get("label") or ""),
            "color": str(item.get("color") or ""),
            "opacity": _number(item.get("opacity", 0.12), f"spans[{index}].opacity"),
            "metadata": _metadata(item.get("metadata")),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "groups": groups,
        "panels": panels,
        "points": points,
        "links": links,
        "spans": spans,
    }


def load_annotation_document(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid annotation JSON in {path}: {exc}") from exc
    return normalize_annotation_document(raw)


__all__ = [
    "BUILTIN_PANES",
    "SCHEMA_VERSION",
    "empty_annotation_document",
    "load_annotation_document",
    "normalize_annotation_document",
]
