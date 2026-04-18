"""Download ticker CSVs from BigQuery into the local data archive."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

from .downloader import DEFAULT_DATA_DIR

COLUMN_ORDER = [
    "ticker",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "transactions",
    "otc",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pull ticker data from BigQuery to local CSV")
    parser.add_argument("ticker", help="Ticker symbol to fetch from BigQuery")
    parser.add_argument(
        "--table-id",
        help="Fully-qualified table id: project.dataset.table or project:dataset.table",
    )
    parser.add_argument(
        "--project",
        default=os.getenv("GCP_PROJECT"),
        help="GCP project ID (default: $GCP_PROJECT or client default)",
    )
    parser.add_argument(
        "--dataset",
        default=os.getenv("BQ_DATASET"),
        help="BigQuery dataset (default: $BQ_DATASET)",
    )
    parser.add_argument(
        "--table",
        default=os.getenv("BQ_TABLE"),
        help="BigQuery table (default: $BQ_TABLE)",
    )
    parser.add_argument(
        "--location",
        default=os.getenv("BQ_LOCATION"),
        help="BigQuery job location, e.g. US/EU (default: $BQ_LOCATION)",
    )
    parser.add_argument(
        "--timeframe",
        default="1440",
        help="Output subdirectory name under data dir (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Destination directory for CSV files (default: %(default)s)",
    )
    parser.add_argument(
        "--start-date",
        help="Optional YYYY-MM-DD filter for earliest timestamp",
    )
    parser.add_argument(
        "--end-date",
        help="Optional YYYY-MM-DD filter for latest timestamp (inclusive by date)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show row count that would be written without touching disk",
    )
    return parser


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc)


def _sanitize_symbol(symbol: str) -> str:
    return symbol.replace(":", "_").replace("/", "-")


def _build_query(
    project: str,
    dataset: str,
    table: str,
    *,
    has_start: bool,
    has_end: bool,
) -> str:
    where = ["UPPER(ticker) = UPPER(@ticker)"]
    if has_start:
        where.append("timestamp >= @start_ts")
    if has_end:
        where.append("timestamp < @end_exclusive_ts")
    where_clause = " AND ".join(where)
    table_id = f"`{project}.{dataset}.{table}`"
    columns = ", ".join(COLUMN_ORDER)
    return f"SELECT {columns} FROM {table_id} WHERE {where_clause} ORDER BY timestamp"


def _parse_full_table_id(table_id: str) -> tuple[str, str, str]:
    normalized = table_id.strip()
    if ":" in normalized:
        project, rest = normalized.split(":", 1)
        parts = rest.split(".")
        if len(parts) != 2:
            raise SystemExit("--table-id must be project:dataset.table")
        return project, parts[0], parts[1]
    parts = normalized.split(".")
    if len(parts) != 3:
        raise SystemExit("--table-id must be project.dataset.table or project:dataset.table")
    return parts[0], parts[1], parts[2]


def _resolve_table_target(args: argparse.Namespace, client: bigquery.Client) -> tuple[str, str, str]:
    if args.table_id:
        return _parse_full_table_id(args.table_id)

    if not args.dataset:
        raise SystemExit("--dataset is required (or set $BQ_DATASET)")
    if not args.table:
        raise SystemExit("--table is required (or set $BQ_TABLE)")

    dataset = str(args.dataset).strip()
    table = str(args.table).strip()
    project = args.project or client.project
    if not project:
        raise SystemExit("--project is required (or configure ADC default project)")

    # Support accidental split like --dataset "project:dataset" --table "table"
    if ":" in dataset:
        parsed_project, parsed_dataset = dataset.split(":", 1)
        project = parsed_project
        dataset = parsed_dataset
    # Support accidental split like --dataset "project.dataset" --table "table"
    elif dataset.count(".") == 1:
        parsed_project, parsed_dataset = dataset.split(".", 1)
        project = parsed_project
        dataset = parsed_dataset

    return project, dataset, table


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    start_ts = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    end_exclusive_ts = end_date + timedelta(days=1) if end_date else None

    client = bigquery.Client(project=args.project) if args.project else bigquery.Client()
    target_project, target_dataset, target_table = _resolve_table_target(args, client)
    query = _build_query(
        target_project,
        target_dataset,
        target_table,
        has_start=start_ts is not None,
        has_end=end_exclusive_ts is not None,
    )

    query_params: list[bigquery.ScalarQueryParameter] = [
        bigquery.ScalarQueryParameter("ticker", "STRING", args.ticker),
    ]
    if start_ts is not None:
        query_params.append(bigquery.ScalarQueryParameter("start_ts", "TIMESTAMP", start_ts))
    if end_exclusive_ts is not None:
        query_params.append(bigquery.ScalarQueryParameter("end_exclusive_ts", "TIMESTAMP", end_exclusive_ts))

    query_job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=query_params),
        location=args.location,
    )
    df = query_job.to_dataframe()

    if df.empty:
        raise SystemExit(f"No rows found for ticker {args.ticker} in {target_project}.{target_dataset}.{target_table}")

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "volume", "vwap"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "transactions" in df.columns:
        df["transactions"] = pd.to_numeric(df["transactions"], errors="coerce").astype("Int64")

    present_columns = [column for column in COLUMN_ORDER if column in df.columns]
    output_df = df[present_columns].sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    if args.dry_run:
        print(
            f"[dry-run] {args.ticker} -> {len(output_df)} rows from "
            f"{target_project}.{target_dataset}.{target_table} (timeframe={args.timeframe})"
        )
        return

    timeframe_dir = args.output_dir / str(args.timeframe)
    timeframe_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize_symbol(args.ticker)}-{args.timeframe}M.csv"
    output_path = timeframe_dir / filename
    output_df.to_csv(output_path, index=False)
    print(f"Wrote {len(output_df)} rows to {output_path}")


if __name__ == "__main__":  # pragma: no cover
    main()
