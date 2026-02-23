"""Upload downloaded CSVs to BigQuery."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

import pandas as pd
from google.cloud import bigquery

from .downloader import DEFAULT_DATA_DIR

BQ_SCHEMA = [
    bigquery.SchemaField("ticker", "STRING"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
    bigquery.SchemaField("open", "FLOAT"),
    bigquery.SchemaField("high", "FLOAT"),
    bigquery.SchemaField("low", "FLOAT"),
    bigquery.SchemaField("close", "FLOAT"),
    bigquery.SchemaField("volume", "FLOAT"),
    bigquery.SchemaField("vwap", "FLOAT"),
    bigquery.SchemaField("transactions", "INTEGER"),
    bigquery.SchemaField("otc", "STRING"),
]

COLUMN_ORDER = [field.name for field in BQ_SCHEMA]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync local CSV data to BigQuery")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing timeframe folders (default: %(default)s)",
    )
    parser.add_argument(
        "--timeframe",
        default="1440",
        help="Subdirectory to upload from (default: %(default)s)",
    )
    parser.add_argument(
        "--pattern",
        default="*.csv",
        help="Glob pattern inside the timeframe directory (default: %(default)s)",
    )
    parser.add_argument(
        "--project",
        default=os.getenv("GCP_PROJECT"),
        help="GCP project ID (default: $GCP_PROJECT or client default)",
    )
    parser.add_argument(
        "--dataset",
        default=os.getenv("BQ_DATASET"),
        help="Destination BigQuery dataset (default: $BQ_DATASET)",
    )
    parser.add_argument(
        "--table",
        default=os.getenv("BQ_TABLE"),
        help="Destination BigQuery table name (default: $BQ_TABLE)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Truncate the table before uploading (full replace)",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        help="Upload at most N files (useful for dry runs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded without touching BigQuery",
    )
    return parser


def iter_csv_files(source_dir: Path, pattern: str) -> Iterable[Path]:
    for csv_file in sorted(source_dir.glob(pattern)):
        if csv_file.is_file():
            yield csv_file


def load_csv(csv_path: Path) -> pd.DataFrame:
    """Read a CSV and coerce columns to match the BigQuery schema."""
    df = pd.read_csv(csv_path)

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    for col in ("open", "high", "low", "close", "volume", "vwap"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "transactions" in df.columns:
        df["transactions"] = pd.to_numeric(df["transactions"], errors="coerce").astype("Int64")

    for col in ("ticker", "otc"):
        if col in df.columns:
            df[col] = df[col].astype(str).replace("nan", None)

    present = [c for c in COLUMN_ORDER if c in df.columns]
    return df[present]


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.dataset:
        raise SystemExit("--dataset is required (or set $BQ_DATASET)")
    if not args.table:
        raise SystemExit("--table is required (or set $BQ_TABLE)")

    timeframe_dir = args.source_dir / args.timeframe
    if not timeframe_dir.exists():
        raise SystemExit(f"Timeframe directory not found: {timeframe_dir}")

    csv_files = list(iter_csv_files(timeframe_dir, args.pattern))
    if not csv_files:
        raise SystemExit(f"No CSV files matching {args.pattern} in {timeframe_dir}")
    if args.limit_files:
        csv_files = csv_files[: args.limit_files]

    print(f"Found {len(csv_files)} CSV file(s) in {timeframe_dir}")

    if args.dry_run:
        total_rows = 0
        for csv_file in csv_files:
            df = load_csv(csv_file)
            total_rows += len(df)
            print(f"  [dry-run] {csv_file.name}: {len(df)} rows, columns={list(df.columns)}")
        print(f"  [dry-run] Total: {total_rows} rows would be uploaded")
        return

    client = bigquery.Client(project=args.project) if args.project else bigquery.Client()
    target_project = args.project or client.project
    table_id = f"{target_project}.{args.dataset}.{args.table}"

    total_rows = 0
    for index, csv_file in enumerate(csv_files):
        df = load_csv(csv_file)
        if df.empty:
            print(f"  Skipping {csv_file.name}: empty")
            continue

        if args.replace and index == 0:
            disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        else:
            disposition = bigquery.WriteDisposition.WRITE_APPEND

        job_config = bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=disposition,
        )

        print(f"  Uploading {csv_file.name} ({len(df)} rows) ...", end=" ", flush=True)
        job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
        job.result()
        total_rows += len(df)
        print("done")

    table = client.get_table(table_id)
    print(f"Sync complete. {table_id} has {table.num_rows} rows ({total_rows} uploaded this run).")


if __name__ == "__main__":  # pragma: no cover
    main()
