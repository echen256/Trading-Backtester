"""SQLite-backed catalog for normalized market datasets and study runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import artifact_root


class DatasetCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or artifact_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "catalog.sqlite"
        self.datasets_root = self.root / "datasets"
        self.studies_root = self.root / "studies"
        self.datasets_root.mkdir(exist_ok=True)
        self.studies_root.mkdir(exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    first_timestamp TEXT,
                    last_timestamp TEXT,
                    row_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS datasets_symbol_idx ON datasets(symbol, interval_seconds);
                CREATE TABLE IF NOT EXISTS study_runs (
                    id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL,
                    study_name TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS study_runs_study_idx ON study_runs(study_id, generated_at DESC);
                """
            )

    def upsert_dataset(self, metadata: dict[str, Any]) -> None:
        quality = metadata["quality"]
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, symbol, asset_class, interval_seconds, provider,
                    first_timestamp, last_timestamp, row_count, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    metadata_json=excluded.metadata_json,
                    row_count=excluded.row_count,
                    first_timestamp=excluded.first_timestamp,
                    last_timestamp=excluded.last_timestamp,
                    updated_at=excluded.updated_at
                """,
                (
                    metadata["id"], metadata["symbol"], metadata["asset_class"],
                    metadata["interval_seconds"], metadata["source"]["provider"],
                    quality["first_timestamp"], quality["last_timestamp"], quality["row_count"],
                    json.dumps(metadata, separators=(",", ":")), datetime.now(UTC).isoformat(),
                ),
            )

    def list_datasets(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT metadata_json FROM datasets ORDER BY asset_class, symbol, interval_seconds"
            ).fetchall()
        return [json.loads(row["metadata_json"]) for row in rows]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM datasets WHERE id = ?", (dataset_id,)
            ).fetchone()
        return json.loads(row["metadata_json"]) if row else None

    def register_study(self, manifest: dict[str, Any], manifest_path: Path) -> None:
        run = manifest["run"]
        study = manifest["study"]
        now = datetime.now(UTC).isoformat()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO study_runs (
                    id, study_id, study_name, generated_at, status,
                    manifest_path, manifest_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    manifest_path=excluded.manifest_path,
                    manifest_json=excluded.manifest_json,
                    updated_at=excluded.updated_at
                """,
                (
                    run["id"], study["id"], study["name"], run["generated_at"], run["status"],
                    str(manifest_path), json.dumps(manifest, separators=(",", ":")), now,
                ),
            )

    def list_studies(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, study_id, study_name, generated_at, status, manifest_json
                FROM study_runs ORDER BY generated_at DESC
                """
            ).fetchall()
        output = []
        for row in rows:
            manifest = json.loads(row["manifest_json"])
            output.append({
                "id": row["id"],
                "study_id": row["study_id"],
                "study_name": row["study_name"],
                "generated_at": row["generated_at"],
                "status": row["status"],
                "view_count": len(manifest.get("views") or []),
                "symbols": sorted({view.get("symbol", "") for view in manifest.get("views") or [] if view.get("symbol")}),
            })
        return output

    def get_study(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM study_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["manifest_json"]) if row else None

    def rebuild_study_index(self) -> int:
        count = 0
        for path in self.studies_root.glob("*/*/manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                self.register_study(manifest, path)
                count += 1
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return count
