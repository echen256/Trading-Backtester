"""Validated, atomic study artifact publishing for dashboard consumers."""

from __future__ import annotations

import hashlib
import csv
import json
import math
import re
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping

from .catalog import DatasetCatalog
from .schemas import validate_document


def _strict_json(value: Any) -> Any:
    """Normalize common analysis scalar types into portable strict JSON."""

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _strict_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict_json(item) for item in value]
    scalar = getattr(value, "item", None)
    if callable(scalar):
        try:
            return _strict_json(scalar())
        except (TypeError, ValueError):
            pass
    return value


def annotation_v1_to_chart_v2(document: Mapping[str, Any] | None) -> dict[str, Any]:
    """Adapt the established annotation v1 contract into the dashboard contract."""

    raw = dict(document or {})
    version = raw.get("schema_version", "trading-chart-annotations/v1")
    if version not in {"trading-chart-annotations/v1", "trading-chart-study/v2"}:
        raise ValueError(f"Unsupported chart annotation schema: {version}")
    if version == "trading-chart-study/v2":
        chart = raw
    else:
        chart = {
            "schema_version": "trading-chart-study/v2",
            "groups": list(raw.get("groups") or []),
            "panels": list(raw.get("panels") or []),
            "points": list(raw.get("points") or []),
            "links": list(raw.get("links") or []),
            "spans": list(raw.get("spans") or []),
            "levels": [],
        }
    group_ids = {str(group.get("id")) for group in chart.get("groups") or []}
    for collection in ("points", "links", "spans", "levels"):
        for item in chart.get(collection) or []:
            if item.get("group") not in group_ids:
                raise ValueError(f"{collection} item {item.get('id')!r} references unknown group {item.get('group')!r}")
    validate_document(chart, "chart-study-v2")
    return chart


class StudyArtifactWriter:
    def __init__(self, catalog: DatasetCatalog | None = None) -> None:
        self.catalog = catalog or DatasetCatalog()

    def build_manifest(
        self,
        *,
        study_id: str,
        study_name: str,
        version: str,
        views: list[dict[str, Any]],
        description: str = "",
        generator: str = "",
        parameters: Mapping[str, Any] | None = None,
        metrics: list[dict[str, Any]] | None = None,
        tables: list[dict[str, Any]] | None = None,
        resources: Mapping[str, Any] | None = None,
        methodology: str | None = None,
        run_id: str | None = None,
        status: str = "complete",
        code_revision: str | None = None,
    ) -> dict[str, Any]:
        normalized_id = self._slug(study_id)
        normalized_views = []
        inputs: dict[str, dict[str, Any]] = {}
        for view in views:
            item = dict(view)
            item["chart"] = annotation_v1_to_chart_v2(item.get("chart"))
            dataset_id = str(item["dataset_id"])
            dataset = self.catalog.get_dataset(dataset_id)
            if dataset is None:
                raise ValueError(f"Study view references unknown dataset: {dataset_id}")
            quality = dataset["quality"]
            item.setdefault("symbol", dataset["symbol"])
            item.setdefault("timeframe", self._timeframe_label(dataset["interval_seconds"]))
            item.setdefault("default_start", quality["first_timestamp"])
            item.setdefault("default_end", quality["last_timestamp"])
            normalized_views.append(item)
            inputs[dataset_id] = {
                "dataset_id": dataset_id,
                "fingerprint": dataset["source"]["fingerprint"],
                "start": quality["first_timestamp"],
                "end": quality["last_timestamp"],
            }

        generated_at = datetime.now(UTC).isoformat()
        if run_id is None:
            seed = json.dumps(
                {"study": normalized_id, "views": normalized_views, "parameters": dict(parameters or {})},
                sort_keys=True,
                default=str,
            )
            suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"{normalized_id}-{stamp}-{suffix}"
        manifest: dict[str, Any] = _strict_json({
            "schema_version": "trading-study-run/v1",
            "study": {
                "id": normalized_id,
                "name": study_name,
                "version": version,
                "description": description,
                "generator": generator,
            },
            "run": {
                "id": run_id,
                "generated_at": generated_at,
                "status": status,
                "parameters": dict(parameters or {}),
                "code_revision": code_revision,
            },
            "inputs": list(inputs.values()),
            "views": normalized_views,
            "metrics": list(metrics or []),
            "tables": list(tables or []),
            "resources": dict(resources or {}),
            "methodology": methodology,
        })
        validate_document(manifest, "study-run-v1")
        json.dumps(manifest, allow_nan=False)
        return manifest

    def publish(
        self,
        manifest: dict[str, Any],
        *,
        resource_files: Mapping[str, Path | str | bytes | dict[str, Any] | list[Any]] | None = None,
    ) -> Path:
        validate_document(manifest, "study-run-v1")
        study_id = self._slug(str(manifest["study"]["id"]))
        run_id = self._safe_name(str(manifest["run"]["id"]))
        parent = self.catalog.studies_root / study_id
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / run_id
        temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}-", dir=parent))
        try:
            resources_dir = temporary / "resources"
            for name, value in (resource_files or {}).items():
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Unsafe artifact resource path: {name}")
                destination = resources_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(value, Path):
                    shutil.copy2(value, destination)
                elif isinstance(value, bytes):
                    destination.write_bytes(value)
                elif isinstance(value, str):
                    destination.write_text(value, encoding="utf-8")
                else:
                    destination.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            manifest_path = temporary / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            if target.exists():
                shutil.rmtree(target)
            temporary.rename(target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        final_path = target / "manifest.json"
        self.catalog.register_study(manifest, final_path)
        return final_path

    def publish_annotation_study(
        self,
        *,
        study_id: str,
        study_name: str,
        version: str,
        dataset_id: str,
        annotations: Mapping[str, Any],
        view_id: str = "default",
        view_label: str = "Overview",
        **kwargs: Any,
    ) -> Path:
        manifest = self.build_manifest(
            study_id=study_id,
            study_name=study_name,
            version=version,
            views=[{
                "id": view_id,
                "label": view_label,
                "dataset_id": dataset_id,
                "chart": annotation_v1_to_chart_v2(annotations),
            }],
            **kwargs,
        )
        return self.publish(manifest)

    def publish_report_study(
        self,
        *,
        study_id: str,
        study_name: str,
        version: str,
        generator: str,
        files: Mapping[str, Path],
        description: str = "",
        parameters: Mapping[str, Any] | None = None,
        metrics: list[dict[str, Any]] | None = None,
        tables: list[dict[str, Any]] | None = None,
        methodology: str | None = None,
    ) -> Path:
        """Publish report-oriented studies that do not yet have chart views."""

        resources: dict[str, Any] = {}
        resource_files: dict[str, Path] = {}
        inferred_metrics = list(metrics or [])
        inferred_tables = list(tables or [])
        for logical_name, raw_path in files.items():
            path = Path(raw_path)
            if not path.exists():
                continue
            safe_name = self._safe_resource_name(logical_name, path.suffix)
            resource_files[safe_name] = path
            resources[logical_name] = {
                "path": f"resources/{safe_name}",
                "media_type": self._media_type(path),
                "bytes": path.stat().st_size,
            }
            if path.suffix.lower() == ".json" and len(inferred_metrics) < 30:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    inferred_metrics.extend(self._scalar_metrics(payload, limit=30 - len(inferred_metrics)))
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            if path.suffix.lower() == ".csv" and not inferred_tables:
                inferred = self._csv_table(path, logical_name)
                if inferred:
                    inferred_tables.append(inferred)
            if methodology is None and path.suffix.lower() in {".md", ".txt"} and path.stat().st_size <= 200_000:
                methodology = path.read_text(encoding="utf-8")

        manifest = self.build_manifest(
            study_id=study_id,
            study_name=study_name,
            version=version,
            description=description,
            generator=generator,
            parameters=parameters,
            views=[],
            metrics=inferred_metrics[:30],
            tables=inferred_tables,
            resources=resources,
            methodology=methodology,
        )
        return self.publish(manifest, resource_files=resource_files)

    @staticmethod
    def _slug(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")
        if not normalized:
            raise ValueError("study id must contain a letter or number")
        return normalized

    @staticmethod
    def _safe_name(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError(f"Unsafe artifact name: {value}")
        return value

    @staticmethod
    def _safe_resource_name(logical_name: str, suffix: str) -> str:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", logical_name).strip("-") or "resource"
        return stem if stem.lower().endswith(suffix.lower()) else f"{stem}{suffix.lower()}"

    @staticmethod
    def _media_type(path: Path) -> str:
        return {
            ".json": "application/json", ".csv": "text/csv", ".md": "text/markdown",
            ".txt": "text/plain", ".png": "image/png", ".svg": "image/svg+xml",
            ".html": "text/html",
        }.get(path.suffix.lower(), "application/octet-stream")

    @classmethod
    def _scalar_metrics(cls, payload: Any, *, limit: int, prefix: str = "") -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        if not isinstance(payload, dict):
            return output
        for key, value in payload.items():
            label = f"{prefix} · {key}" if prefix else str(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                if not isinstance(value, str) or len(value) <= 120:
                    output.append({"label": label.replace("_", " "), "value": value})
            elif isinstance(value, dict) and len(output) < limit:
                output.extend(cls._scalar_metrics(value, limit=limit - len(output), prefix=label))
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _csv_table(path: Path, label: str, *, limit: int = 1000) -> dict[str, Any] | None:
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                columns = list(reader.fieldnames or [])
                rows = []
                for index, row in enumerate(reader):
                    if index >= limit:
                        break
                    rows.append({key: value for key, value in row.items()})
            return {"id": re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"), "label": label, "columns": columns, "rows": rows}
        except (OSError, csv.Error, UnicodeDecodeError):
            return None

    @staticmethod
    def _timeframe_label(seconds: int) -> str:
        if seconds % 604800 == 0:
            return f"{seconds // 604800}w"
        if seconds % 86400 == 0:
            return f"{seconds // 86400}d"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"
