#!/usr/bin/env python3
"""Convert VIX history CSV into the standard Massive daily archive format."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert alternate-source VIX history into the standard Massive CSV layout."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).with_name("VIX_History.csv"),
        help="Source VIX history CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "1440" / "I_VIX-1440M.csv",
        help="Destination Massive-format CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--ticker",
        default="I:VIX",
        help="Ticker value to write into the output file (default: %(default)s)",
    )
    return parser


def convert(input_path: Path, output_path: Path, ticker: str) -> int:
    rows: list[dict[str, str]] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date_value = datetime.strptime(row["DATE"], "%m/%d/%Y")
            rows.append(
                {
                    "timestamp": date_value.strftime("%Y-%m-%d 05:00:00+00:00"),
                    "open": row["OPEN"],
                    "high": row["HIGH"],
                    "low": row["LOW"],
                    "close": row["CLOSE"],
                    "volume": "",
                    "vwap": "",
                    "transactions": "",
                    "otc": "",
                    "ticker": ticker,
                }
            )

    rows.sort(key=lambda row: row["timestamp"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "vwap",
                "transactions",
                "otc",
                "ticker",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    args = build_parser().parse_args()
    written = convert(args.input, args.output, args.ticker)
    print(f"Wrote {written} rows to {args.output}")


if __name__ == "__main__":
    main()
