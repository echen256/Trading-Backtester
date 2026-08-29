"""Local HTTP API and static server for the analysis dashboard."""

from __future__ import annotations

import json
import math
import mimetypes
import posixpath
import traceback
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from .catalog import DatasetCatalog
from .config import CONTRACTS_ROOT, DEFAULT_WEB_ROOT
from .ingestion import DatasetImporter, ImportOptions
from .tpo import load_tpo_payload


MAX_RESPONSE_BARS = 100_000


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")
    return value


def load_bars_payload(
    catalog: DatasetCatalog,
    dataset_id: str,
    *,
    start: str | None = None,
    end: str | None = None,
    max_bars: int = 15_000,
) -> dict[str, Any]:
    """Load and, when necessary, correctly aggregate a viewport range."""

    metadata = catalog.get_dataset(dataset_id)
    if metadata is None:
        raise KeyError(f"Unknown dataset: {dataset_id}")
    max_bars = min(MAX_RESPONSE_BARS, max(100, int(max_bars)))
    start_time = pd.to_datetime(start, utc=True, errors="coerce")
    end_time = pd.to_datetime(end, utc=True, errors="coerce")
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    filters = []
    if not pd.isna(start_time):
        filters.append(("timestamp", ">=", start_time.to_pydatetime()))
    if not pd.isna(end_time):
        filters.append(("timestamp", "<=", end_time.to_pydatetime()))
    frame = pd.read_parquet(
        metadata["storage"]["path"],
        columns=columns,
        filters=filters or None,
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if not pd.isna(start_time):
        frame = frame[frame.timestamp >= start_time]
    if not pd.isna(end_time):
        frame = frame[frame.timestamp <= end_time]
    native_interval = int(metadata["interval_seconds"])
    response_interval = native_interval
    aggregated = False
    if len(frame) > max_bars:
        multiplier = math.ceil(len(frame) / max_bars)
        response_interval = native_interval * multiplier
        frame = (
            frame.set_index("timestamp")
            .resample(f"{response_interval}s", origin="epoch")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        aggregated = True
    frame = frame.sort_values("timestamp")
    return {
        "dataset_id": dataset_id,
        "symbol": metadata["symbol"],
        "native_interval_seconds": native_interval,
        "response_interval_seconds": response_interval,
        "aggregated": aggregated,
        "count": len(frame),
        "bars": {
            "time": [_json_safe(item) for item in frame.timestamp],
            "open": [_json_safe(float(item)) for item in frame.open],
            "high": [_json_safe(float(item)) for item in frame.high],
            "low": [_json_safe(float(item)) for item in frame.low],
            "close": [_json_safe(float(item)) for item in frame.close],
            "volume": [_json_safe(float(item)) for item in frame.volume],
        },
    }


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        catalog: DatasetCatalog,
        web_root: Path,
    ) -> None:
        super().__init__(address, DashboardRequestHandler)
        self.catalog = catalog
        self.importer = DatasetImporter(catalog)
        self.web_root = web_root.resolve()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if path == "/api/health":
                return self._send_json({"status": "ok", "time": datetime.now(UTC).isoformat()})
            if path == "/api/datasets":
                return self._send_json({"datasets": self.server.catalog.list_datasets()})
            if path.startswith("/api/datasets/") and path.endswith("/bars"):
                dataset_id = unquote(path[len("/api/datasets/") : -len("/bars")]).strip("/")
                return self._send_bars(dataset_id, query)
            if path.startswith("/api/datasets/") and path.endswith("/tpo"):
                dataset_id = unquote(path[len("/api/datasets/") : -len("/tpo")]).strip("/")
                return self._send_tpo(dataset_id, query)
            if path.startswith("/api/datasets/"):
                dataset_id = unquote(path[len("/api/datasets/") :]).strip("/")
                dataset = self.server.catalog.get_dataset(dataset_id)
                return self._send_json(dataset) if dataset else self._not_found("dataset", dataset_id)
            if path == "/api/studies":
                return self._send_json({"studies": self.server.catalog.list_studies()})
            if path.startswith("/api/studies/") and "/resources/" in path:
                run_id, resource = path[len("/api/studies/") :].split("/resources/", 1)
                return self._send_study_resource(unquote(run_id), unquote(resource))
            if path.startswith("/api/studies/"):
                run_id = unquote(path[len("/api/studies/") :]).strip("/")
                manifest = self.server.catalog.get_study(run_id)
                return self._send_json(manifest) if manifest else self._not_found("study run", run_id)
            if path.startswith("/api/contracts/"):
                filename = Path(unquote(path[len("/api/contracts/") :])).name
                contract = CONTRACTS_ROOT / filename
                if not contract.exists():
                    return self._not_found("contract", filename)
                return self._send_file(contract, "application/schema+json")
            if path.startswith("/api/"):
                return self._not_found("endpoint", path)
            return self._send_static(parsed.path)
        except Exception as exc:  # noqa: BLE001
            self._send_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/datasets/import":
                body = self._read_json_body()
                path = Path(str(body.pop("path")))
                allowed = {field.name for field in ImportOptions.__dataclass_fields__.values()}
                unknown = set(body).difference(allowed)
                if unknown:
                    raise ValueError(f"Unknown import options: {', '.join(sorted(unknown))}")
                metadata = self.server.importer.import_file(path, ImportOptions(**body))
                return self._send_json(metadata, status=HTTPStatus.CREATED)
            if parsed.path == "/api/studies/reindex":
                count = self.server.catalog.rebuild_study_index()
                return self._send_json({"indexed": count})
            return self._not_found("endpoint", parsed.path)
        except Exception as exc:  # noqa: BLE001
            self._send_error(exc)

    def _send_bars(self, dataset_id: str, query: dict[str, list[str]]) -> None:
        try:
            payload = load_bars_payload(
                self.server.catalog,
                dataset_id,
                start=query.get("from", [None])[0],
                end=query.get("to", [None])[0],
                max_bars=int(query.get("maxBars", ["15000"])[0]),
            )
        except KeyError:
            return self._not_found("dataset", dataset_id)
        self._send_json(payload)

    def _send_tpo(self, dataset_id: str, query: dict[str, list[str]]) -> None:
        try:
            payload = load_tpo_payload(
                self.server.catalog,
                dataset_id,
                at=query.get("at", [None])[0],
            )
        except KeyError:
            return self._not_found("dataset", dataset_id)
        self._send_json(payload)

    def _send_study_resource(self, run_id: str, resource: str) -> None:
        manifest = self.server.catalog.get_study(run_id)
        if manifest is None:
            return self._not_found("study run", run_id)
        relative = Path(posixpath.normpath(resource))
        if relative.is_absolute() or ".." in relative.parts:
            raise PermissionError("Unsafe study resource path")
        if relative.parts and relative.parts[0] == "resources":
            relative = Path(*relative.parts[1:])
        study_id = manifest["study"]["id"]
        target = (self.server.catalog.studies_root / study_id / run_id / "resources" / relative).resolve()
        root = (self.server.catalog.studies_root / study_id / run_id / "resources").resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return self._not_found("study resource", resource)
        self._send_file(target)

    def _send_static(self, raw_path: str) -> None:
        if not self.server.web_root.exists():
            return self._send_html(
                "<h1>Trading Analysis Dashboard</h1>"
                "<p>The API is running, but the React build is missing.</p>"
                "<pre>cd modules/analysis/dashboard && npm install && npm run build</pre>"
            )
        relative = Path(posixpath.normpath(unquote(raw_path).lstrip("/")))
        if relative.is_absolute() or ".." in relative.parts:
            raise PermissionError("Unsafe static path")
        target = (self.server.web_root / relative).resolve()
        if not target.is_relative_to(self.server.web_root) or not target.is_file():
            target = self.server.web_root / "index.html"
        self._send_file(target)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            raise ValueError("Request body must be JSON smaller than 2 MB")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("Request JSON must be an object")
        return payload

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, allow_nan=False, default=_json_safe, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_html(self, content: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = f"<!doctype html><html><body>{content}</body></html>".encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        payload = path.read_bytes()
        mime = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _not_found(self, kind: str, identifier: str) -> None:
        self._send_json({"error": f"Unknown {kind}: {identifier}"}, status=HTTPStatus.NOT_FOUND)

    def _send_error(self, exc: Exception) -> None:
        status = HTTPStatus.FORBIDDEN if isinstance(exc, PermissionError) else HTTPStatus.BAD_REQUEST
        traceback.print_exc()
        self._send_json({"error": str(exc), "type": type(exc).__name__}, status=status)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Vary", "Origin")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} {format % args}")


def serve_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    catalog: DatasetCatalog | None = None,
    web_root: Path = DEFAULT_WEB_ROOT,
) -> None:
    resolved_catalog = catalog or DatasetCatalog()
    resolved_catalog.rebuild_study_index()
    server = DashboardServer((host, port), catalog=resolved_catalog, web_root=web_root)
    print(f"Trading Analysis Dashboard: http://{host}:{port}")
    print(f"Artifacts: {resolved_catalog.root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
