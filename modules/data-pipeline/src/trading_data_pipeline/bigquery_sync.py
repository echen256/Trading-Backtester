"""Upload downloaded CSVs to BigQuery."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd
from google.cloud import bigquery

from .downloader import DEFAULT_DATA_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--project", help="Optional override for the GCP project ID")
    parser.add_argument("--dataset", required=True, help="Destination BigQuery dataset")
    parser.add_argument("--table", required=True, help="Destination BigQuery table name")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Truncate the table before uploading the first file",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        help="Upload at most N files (useful for dry runs)",
    )
    return parser


def iter_csv_files(source_dir: Path, pattern: str) -> Iterable[Path]:
    for csv_file in sorted(source_dir.glob(pattern)):
        if csv_file.is_file():
            yield csv_file


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    timeframe_dir = args.source_dir / args.timeframe
    if not timeframe_dir.exists():
        raise SystemExit(f"Timeframe directory not found: {timeframe_dir}")

    client = bigquery.Client(project=args.project) if args.project else bigquery.Client()
    target_project = args.project or client.project
    table_id = f"{target_project}.{args.dataset}.{args.table}"

    csv_files = list(iter_csv_files(timeframe_dir, args.pattern))
    if not csv_files:
        raise SystemExit(f"No CSV files matching {args.pattern} in {timeframe_dir}")
    if args.limit_files:
        csv_files = csv_files[: args.limit_files]

    write_disposition = (
        bigquery.WriteDisposition.WRITE_TRUNCATE
        if args.replace
        else bigquery.WriteDisposition.WRITE_APPEND
    )

    for index, csv_file in enumerate(csv_files):
        df = load_csv(csv_file)
        if df.empty:
            print(f"Skipping {csv_file.name}: empty file")
            continue

        current_disposition = write_disposition
        if args.replace and index > 0:
            current_disposition = bigquery.WriteDisposition.WRITE_APPEND

        config = bigquery.LoadJobConfig(write_disposition=current_disposition)
        print(f"Uploading {csv_file.name} ({len(df)} rows) -> {table_id} ...", end=" ")
        job = client.load_table_from_dataframe(df, table_id, job_config=config)
        job.result()
        print("done")

    table = client.get_table(table_id)
    print(f"Upload complete. {table_id} now contains {table.num_rows} rows.")


if __name__ == "__main__":  # pragma: no cover
    main()
