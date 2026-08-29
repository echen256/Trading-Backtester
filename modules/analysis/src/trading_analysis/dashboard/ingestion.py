"""Import heterogeneous OHLCV files into the dashboard's canonical Parquet store."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .catalog import DatasetCatalog
from .config import ensure_allowed_path
from .schemas import validate_document


SCHEMA_VERSION = "trading-market-dataset/v1"
ALIASES = {
    "timestamp": ("timestamp", "time", "datetime", "date", "open_time_utc", "open_time", "t"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "v", "base_volume"),
}


@dataclass(slots=True)
class ImportOptions:
    symbol: str | None = None
    asset_class: str | None = None
    venue: str | None = None
    base_asset: str | None = None
    quote_asset: str | None = None
    interval_seconds: int | None = None
    timezone: str = "UTC"
    calendar: str | None = None
    adjustment: str | None = None
    provider: str | None = None
    column_map: Mapping[str, str] | None = None


class DatasetImporter:
    def __init__(self, catalog: DatasetCatalog | None = None) -> None:
        self.catalog = catalog or DatasetCatalog()

    def import_file(self, path: Path, options: ImportOptions | None = None) -> dict[str, Any]:
        source_path = ensure_allowed_path(path)
        resolved = options or ImportOptions()
        frame = self._read_frame(source_path)
        fingerprint = self._file_fingerprint(source_path)
        return self._import_frame(frame, source_path=source_path, fingerprint=fingerprint, options=resolved)

    def import_rows(
        self,
        rows: list[dict[str, Any]] | pd.DataFrame,
        *,
        source_label: str,
        options: ImportOptions,
    ) -> dict[str, Any]:
        frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        hashed = pd.util.hash_pandas_object(frame, index=True).values.tobytes()
        fingerprint = hashlib.sha256(hashed).hexdigest()
        return self._import_frame(
            frame,
            source_path=Path(source_label),
            fingerprint=fingerprint,
            options=options,
            enforce_path=False,
        )

    @staticmethod
    def _read_frame(path: Path) -> pd.DataFrame:
        lower = path.name.lower()
        if lower.endswith((".parquet", ".pq")):
            return pd.read_parquet(path)
        if lower.endswith((".csv", ".csv.gz", ".csv.gzip")):
            return pd.read_csv(path, low_memory=False)
        raise ValueError(f"Unsupported market-data file: {path.name}")

    @staticmethod
    def _file_fingerprint(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _import_frame(
        self,
        raw: pd.DataFrame,
        *,
        source_path: Path,
        fingerprint: str,
        options: ImportOptions,
        enforce_path: bool = True,
    ) -> dict[str, Any]:
        if raw.empty:
            raise ValueError("Market-data file contains no rows")
        columns = self._resolve_columns(raw, options.column_map)
        frame = pd.DataFrame()
        frame["timestamp"] = self._parse_timestamps(raw[columns["timestamp"]])
        for name in ("open", "high", "low", "close"):
            frame[name] = pd.to_numeric(raw[columns[name]], errors="coerce")
        volume_column = columns.get("volume")
        frame["volume"] = pd.to_numeric(raw[volume_column], errors="coerce") if volume_column else float("nan")
        invalid = frame[["timestamp", "open", "high", "low", "close"]].isna().any(axis=1)
        dropped_invalid = int(invalid.sum())
        frame = frame.loc[~invalid].copy()
        if frame.empty:
            raise ValueError("No valid timestamp/OHLC rows remain after normalization")

        frame.sort_values("timestamp", inplace=True)
        duplicate_count = int(frame.duplicated("timestamp").sum())
        frame.drop_duplicates("timestamp", keep="last", inplace=True)
        frame.reset_index(drop=True, inplace=True)
        if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
            raise ValueError("Invalid OHLC row: high is below open, close, or low")
        if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
            raise ValueError("Invalid OHLC row: low is above open, close, or high")

        symbol, inferred_asset, inferred_base, inferred_quote = self._infer_identity(source_path.name, raw)
        symbol = (options.symbol or symbol).upper()
        asset_class = options.asset_class or inferred_asset
        interval_seconds = options.interval_seconds or self._infer_interval(frame)
        provider = options.provider or self._infer_provider(source_path.name, raw)
        dataset_slug = self._slug(
            "-".join(filter(None, (asset_class, options.venue or provider, symbol, str(interval_seconds))))
        )
        dataset_id = f"{dataset_slug}-{fingerprint[:12]}"
        target = self.catalog.datasets_root / dataset_id
        parquet_path = target / "bars.parquet"

        missing_intervals, gap_ranges = self._quality_gaps(frame, interval_seconds, asset_class)
        warnings: list[str] = []
        if dropped_invalid:
            warnings.append(f"Dropped {dropped_invalid} rows with invalid timestamp or OHLC values")
        if asset_class != "crypto":
            warnings.append("Gap counting skipped because no exchange calendar is configured")

        source_string = str(source_path.resolve()) if enforce_path else str(source_path)
        metadata: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "id": dataset_id,
            "asset_class": asset_class,
            "symbol": symbol,
            "base_asset": options.base_asset or inferred_base,
            "quote_asset": options.quote_asset or inferred_quote,
            "venue": options.venue or provider,
            "interval_seconds": interval_seconds,
            "timezone": options.timezone,
            "calendar": options.calendar or ("24/7" if asset_class == "crypto" else None),
            "adjustment": options.adjustment,
            "source": {"provider": provider, "path": source_string, "fingerprint": fingerprint},
            "storage": {"format": "parquet", "path": str(parquet_path)},
            "quality": {
                "row_count": len(frame),
                "first_timestamp": self._iso(frame.timestamp.iloc[0]),
                "last_timestamp": self._iso(frame.timestamp.iloc[-1]),
                "duplicates_removed": duplicate_count,
                "missing_intervals": missing_intervals,
                "gap_ranges": gap_ranges,
                "warnings": warnings,
            },
            "created_at": datetime.now(UTC).isoformat(),
        }
        validate_document(metadata, "market-dataset-v1")

        if not target.exists():
            temporary = Path(tempfile.mkdtemp(prefix=f".{dataset_id}-", dir=self.catalog.datasets_root))
            try:
                frame.to_parquet(
                    temporary / "bars.parquet",
                    index=False,
                    compression="zstd",
                    row_group_size=100_000,
                )
                (temporary / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
                temporary.rename(target)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        self.catalog.upsert_dataset(metadata)
        return metadata

    @staticmethod
    def _resolve_columns(frame: pd.DataFrame, explicit: Mapping[str, str] | None) -> dict[str, str]:
        lookup = {str(column).strip().lower(): str(column) for column in frame.columns}
        result: dict[str, str] = {}
        for canonical, aliases in ALIASES.items():
            requested = explicit.get(canonical) if explicit else None
            if requested:
                if requested not in frame.columns:
                    raise ValueError(f"Configured {canonical} column does not exist: {requested}")
                result[canonical] = requested
                continue
            for alias in aliases:
                if alias in lookup:
                    result[canonical] = lookup[alias]
                    break
        missing = [name for name in ("timestamp", "open", "high", "low", "close") if name not in result]
        if missing:
            raise ValueError(f"Missing required market-data columns: {', '.join(missing)}")
        return result

    @staticmethod
    def _parse_timestamps(series: pd.Series) -> pd.Series:
        if pd.api.types.is_numeric_dtype(series):
            clean = pd.to_numeric(series, errors="coerce")
            magnitude = clean.dropna().abs().median()
            if magnitude >= 10**14:
                unit = "us"
            elif magnitude >= 10**11:
                unit = "ms"
            elif magnitude >= 10**9:
                unit = "s"
            else:
                unit = "s"
            return pd.to_datetime(clean, unit=unit, utc=True, errors="coerce")
        return pd.to_datetime(series, utc=True, errors="coerce")

    @staticmethod
    def _infer_interval(frame: pd.DataFrame) -> int:
        differences = frame.timestamp.diff().dropna().dt.total_seconds()
        differences = differences[differences > 0]
        if differences.empty:
            raise ValueError("Cannot infer interval from fewer than two distinct timestamps")
        return max(1, int(differences.median()))

    @staticmethod
    def _infer_identity(filename: str, frame: pd.DataFrame) -> tuple[str, str, str | None, str | None]:
        if "ticker" in frame.columns:
            values = frame["ticker"].dropna().astype(str).str.upper().unique()
            if len(values) == 1:
                symbol = values[0]
            else:
                symbol = filename.split("-")[0].split("_")[0]
        else:
            symbol = filename.split("-")[0].split("_")[0]
        symbol = re.sub(r"[^A-Za-z0-9:._-]", "", symbol).upper()
        for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                return symbol, "crypto", symbol[: -len(quote)], quote
        if symbol.startswith("I:") or symbol.startswith("I_"):
            return symbol, "index", None, None
        return symbol, "stock", None, None

    @staticmethod
    def _infer_provider(filename: str, frame: pd.DataFrame) -> str:
        if "source" in frame.columns:
            values = frame["source"].dropna().astype(str).unique()
            if len(values) == 1:
                return values[0].lower()
        lower = filename.lower()
        if "usdt" in lower:
            return "binance"
        if "cmc" in lower:
            return "coinmarketcap"
        return "local"

    @staticmethod
    def _quality_gaps(frame: pd.DataFrame, interval_seconds: int, asset_class: str) -> tuple[int, list[dict[str, Any]]]:
        if asset_class != "crypto" or len(frame) < 2:
            return 0, []
        differences = frame.timestamp.diff().dt.total_seconds()
        gap_rows = differences[differences > interval_seconds]
        missing_total = 0
        ranges = []
        for index, difference in gap_rows.items():
            missing = max(0, int(difference // interval_seconds) - 1)
            missing_total += missing
            ranges.append({
                "after": DatasetImporter._iso(frame.timestamp.iloc[index - 1]),
                "before": DatasetImporter._iso(frame.timestamp.iloc[index]),
                "missing_intervals": missing,
            })
        return missing_total, ranges

    @staticmethod
    def _iso(value: Any) -> str:
        return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
