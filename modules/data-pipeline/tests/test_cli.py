"""Tests for the trading-data-download CLI."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trading_data_pipeline.cli import build_parser, main
from trading_data_pipeline.config import read_watchlist


class TestBuildParser:
    """Tests for build_parser()."""

    def test_parses_ticker_positional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["AAPL"])
        assert args.ticker == "AAPL"

    def test_parses_watchlist_flag(self, tmp_watchlist: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["--watchlist", str(tmp_watchlist)])
        assert args.watchlist == tmp_watchlist

    def test_parses_output_dir(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["--output-dir", str(tmp_path)])
        assert args.output_dir == tmp_path

    def test_parses_interval(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--interval", "60"])
        assert args.interval == 60

    def test_parses_limit(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--limit", "10"])
        assert args.limit == 10

    def test_parses_skip_filter(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--skip-filter"])
        assert args.skip_filter is True

    def test_parses_start_end_date(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--start-date", "2024-01-01", "--end-date", "2024-12-31"])
        assert args.start_date == "2024-01-01"
        assert args.end_date == "2024-12-31"

    def test_default_values(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.ticker is None
        assert args.interval == 1440
        assert args.chunk_days == 30
        assert args.lookback_years == 5
        assert args.skip_filter is False


class TestReadWatchlist:
    """Tests for read_watchlist (via config module)."""

    def test_reads_csv_with_header(self, tmp_watchlist: Path) -> None:
        symbols = read_watchlist(tmp_watchlist)
        assert symbols == ["AAPL", "MSFT", "GOOG"]

    def test_skips_header_symbol(self, tmp_path: Path) -> None:
        csv = tmp_path / "watch.csv"
        csv.write_text("Symbol\nAAPL\n")
        assert read_watchlist(csv) == ["AAPL"]

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError, match="Watchlist not found"):
            read_watchlist(Path("/nonexistent/watchlist.csv"))

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        csv = tmp_path / "watch.csv"
        csv.write_text("AAPL\n\nMSFT\n\n")
        assert read_watchlist(csv) == ["AAPL", "MSFT"]


class TestMain:
    """Tests for main() with mocked downloader."""

    @patch("trading_data_pipeline.cli.PolygonDownloader")
    def test_main_single_ticker_calls_download_symbol(
        self, mock_downloader_class: MagicMock, tmp_config: Path
    ) -> None:
        mock_downloader = MagicMock()
        mock_downloader_class.return_value = mock_downloader

        main(["AAPL", "--config", str(tmp_config)])

        mock_downloader.download_symbol.assert_called_once()
        call_kwargs = mock_downloader.download_symbol.call_args[1]
        assert "settings" in call_kwargs

    @patch("trading_data_pipeline.cli.PolygonDownloader")
    def test_main_watchlist_calls_download_watchlist(
        self,
        mock_downloader_class: MagicMock,
        tmp_watchlist: Path,
        tmp_config: Path,
    ) -> None:
        mock_downloader = MagicMock()
        mock_downloader_class.return_value = mock_downloader

        main(["--watchlist", str(tmp_watchlist), "--config", str(tmp_config)])

        mock_downloader.download_watchlist.assert_called_once()
        call_args = mock_downloader.download_watchlist.call_args[0]
        assert call_args[0] == ["AAPL", "MSFT", "GOOG"]

    @patch("trading_data_pipeline.cli.PolygonDownloader")
    def test_main_respects_limit(
        self,
        mock_downloader_class: MagicMock,
        tmp_watchlist: Path,
        tmp_config: Path,
    ) -> None:
        mock_downloader = MagicMock()
        mock_downloader_class.return_value = mock_downloader

        main(["--watchlist", str(tmp_watchlist), "--config", str(tmp_config), "--limit", "2"])

        call_kwargs = mock_downloader.download_watchlist.call_args[1]
        assert call_kwargs["limit"] == 2

    @patch("trading_data_pipeline.cli.PolygonDownloader")
    def test_main_skip_filter_passes_zero_cap(
        self,
        mock_downloader_class: MagicMock,
        tmp_watchlist: Path,
        tmp_config: Path,
    ) -> None:
        mock_downloader = MagicMock()
        mock_downloader_class.return_value = mock_downloader

        main(["--watchlist", str(tmp_watchlist), "--config", str(tmp_config), "--skip-filter"])

        call_kwargs = mock_downloader.download_watchlist.call_args[1]
        assert call_kwargs["minimum_market_cap"] == 0
