#!/usr/bin/env python3
"""Upload downloaded CSV data into a Google BigQuery table."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd
from google.cloud import bigquery


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data_download" / "data",
        help="Directory containing timeframe folders (default: backend/app/data_download/data)",
    )
    parser.add_argument(
        "--timeframe",
        default="1440",
        help="Subfolder inside source-dir to upload from (default: 1440 for daily bars).",
    )
    parser.add_argument(
        "--pattern",
        default="*.csv",
        help="Glob pattern for files to upload inside the timeframe folder (default: *.csv).",
    )
    parser.add_argument(
        "--project",
        help="BigQuery project ID. Defaults to the value inferred by the Google client if omitted.",
    )
    parser.add_argument("--dataset", required=True, help="Target BigQuery dataset name.")
    parser.add_argument("--table", required=True, help="Target BigQuery table name.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Truncate the destination table before loading the first file.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        help="Upload at most this many files (useful for dry runs)",
    )
    return parser.parse_args()


def iter_csv_files(source_dir: Path, pattern: str) -> Iterable[Path]:
    for csv_file in sorted(source_dir.glob(pattern)):
        if csv_file.is_file():
            yield csv_file


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def main() -> None:
    args = parse_args()
    timeframe_dir = args.source_dir / args.timeframe
    if not timeframe_dir.exists():
        raise SystemExit(f"Timeframe directory not found: {timeframe_dir}")

    client = bigquery.Client(project=args.project) if args.project else bigquery.Client()
    target_project = args.project or client.project
    table_id = f"{target_project}.{args.dataset}.{args.table}"

    csv_files = list(iter_csv_files(timeframe_dir, args.pattern))
    if not csv_files:
        raise SystemExit(f"No CSV files matching {args.pattern} found in {timeframe_dir}")

    if args.limit_files:
        csv_files = csv_files[: args.limit_files]

    print(f"Uploading {len(csv_files)} file(s) to {table_id}...")
    write_disposition = (
        bigquery.WriteDisposition.WRITE_TRUNCATE
        if args.replace
        else bigquery.WriteDisposition.WRITE_APPEND
    )

    for index, csv_path in enumerate(csv_files):
        df = load_csv(csv_path)
        if df.empty:
            print(f"Skipping {csv_path.name}: no rows")
            continue

        current_disposition = write_disposition
        if args.replace and index > 0:
            current_disposition = bigquery.WriteDisposition.WRITE_APPEND

        job_config = bigquery.LoadJobConfig(write_disposition=current_disposition)
        print(f"\tLoading {csv_path.name} ({len(df)} rows)...", end="")
        job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
        job.result()
        print("done")

    table = client.get_table(table_id)
    print(f"Upload complete. Table {table_id} now contains {table.num_rows} rows.")


if __name__ == "__main__":
    main()
