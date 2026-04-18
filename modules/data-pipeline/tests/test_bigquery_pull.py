"""Tests for BigQuery -> local pull CLI."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from trading_data_pipeline.bigquery_pull import build_parser, main


class TestBuildParser:
    def test_parses_required_ticker(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["TSLA"])
        assert args.ticker == "TSLA"

    def test_parses_optional_args(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "TSLA",
                "--table-id",
                "proj1:dataset1.table1",
                "--dataset",
                "d1",
                "--table",
                "t1",
                "--location",
                "US",
                "--timeframe",
                "60",
                "--output-dir",
                str(tmp_path),
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
                "--dry-run",
            ]
        )
        assert args.table_id == "proj1:dataset1.table1"
        assert args.dataset == "d1"
        assert args.table == "t1"
        assert args.location == "US"
        assert args.timeframe == "60"
        assert args.output_dir == tmp_path
        assert args.start_date == "2025-01-01"
        assert args.end_date == "2025-01-31"
        assert args.dry_run is True


class TestMain:
    @patch("trading_data_pipeline.bigquery_pull.bigquery.Client")
    def test_writes_csv_for_ticker(self, mock_client_class: MagicMock, tmp_path: Path) -> None:
        frame = pd.DataFrame(
            {
                "ticker": ["TSLA", "TSLA"],
                "timestamp": ["2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"],
                "open": [10.0, 11.0],
                "high": [12.0, 13.0],
                "low": [9.0, 10.0],
                "close": [11.0, 12.0],
                "volume": [1000, 1200],
                "vwap": [10.5, 11.5],
                "transactions": [1, 2],
                "otc": [None, None],
            }
        )
        mock_job = MagicMock()
        mock_job.to_dataframe.return_value = frame
        mock_client = MagicMock()
        mock_client.project = "proj1"
        mock_client.query.return_value = mock_job
        mock_client_class.return_value = mock_client

        main(
            [
                "TSLA",
                "--table-id",
                "proj1:dataset1.table1",
                "--location",
                "US",
                "--timeframe",
                "1440",
                "--output-dir",
                str(tmp_path),
            ]
        )

        output = tmp_path / "1440" / "TSLA-1440M.csv"
        assert output.exists()
        written = pd.read_csv(output)
        assert list(written["ticker"].unique()) == ["TSLA"]
        assert len(written) == 2
        _, kwargs = mock_client.query.call_args
        assert kwargs["location"] == "US"

    @patch("trading_data_pipeline.bigquery_pull.bigquery.Client")
    def test_raises_when_no_rows(self, mock_client_class: MagicMock) -> None:
        mock_job = MagicMock()
        mock_job.to_dataframe.return_value = pd.DataFrame()
        mock_client = MagicMock()
        mock_client.project = "proj1"
        mock_client.query.return_value = mock_job
        mock_client_class.return_value = mock_client

        with pytest.raises(SystemExit, match="No rows found for ticker TSLA"):
            main(["TSLA", "--dataset", "d1", "--table", "t1"])

    @patch("trading_data_pipeline.bigquery_pull.bigquery.Client")
    def test_parses_dataset_with_project_prefix(
        self, mock_client_class: MagicMock, tmp_path: Path
    ) -> None:
        frame = pd.DataFrame(
            {
                "ticker": ["TSLA"],
                "timestamp": ["2025-01-01T00:00:00Z"],
                "open": [10.0],
                "high": [12.0],
                "low": [9.0],
                "close": [11.0],
                "volume": [1000],
                "vwap": [10.5],
                "transactions": [1],
                "otc": [None],
            }
        )
        mock_job = MagicMock()
        mock_job.to_dataframe.return_value = frame
        mock_client = MagicMock()
        mock_client.project = "fallback-proj"
        mock_client.query.return_value = mock_job
        mock_client_class.return_value = mock_client

        main(
            [
                "TSLA",
                "--dataset",
                "proj1:dataset1",
                "--table",
                "table1",
                "--output-dir",
                str(tmp_path),
            ]
        )

        query = mock_client.query.call_args.args[0]
        assert "`proj1.dataset1.table1`" in query
