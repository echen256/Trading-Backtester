"""Tests for CoinMarketCap downloader CLI/module."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from trading_data_pipeline.coinmarketcap_downloader import (
    _parse_datetime,
    build_parser,
    fetch_ohlcv,
    main,
    write_csv,
)


class TestBuildParser:
    def test_parses_required_and_optional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "BTC",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
                "--time-period",
                "hourly",
                "--interval",
                "6h",
            ]
        )
        assert args.ticker == "BTC"
        assert args.start_date == "2025-01-01"
        assert args.end_date == "2025-01-31"
        assert args.time_period == "hourly"
        assert args.interval == "6h"


class TestParseDatetime:
    def test_parses_date_only_as_utc(self) -> None:
        dt = _parse_datetime("2025-02-01")
        assert dt == datetime(2025, 2, 1, tzinfo=timezone.utc)

    def test_parses_iso_z(self) -> None:
        dt = _parse_datetime("2025-02-01T06:30:00Z")
        assert dt == datetime(2025, 2, 1, 6, 30, tzinfo=timezone.utc)


class TestFetchOhlcv:
    def test_fetches_and_normalizes(self) -> None:
        payload = {
            "status": {"error_code": 0},
            "data": {
                "symbol": "BTC",
                "quotes": [
                    {
                        "time_open": "2025-01-01T00:00:00Z",
                        "quote": {
                            "USD": {
                                "open": 100.0,
                                "high": 110.0,
                                "low": 90.0,
                                "close": 105.0,
                                "volume": 1000.0,
                                "market_cap": 2000.0,
                            }
                        },
                    }
                ],
            },
        }
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        session = MagicMock()
        session.get.return_value = response

        frame = fetch_ohlcv(
            "BTC",
            api_key="k",
            convert="USD",
            time_period="daily",
            start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
            session=session,
        )

        assert len(frame) == 1
        assert frame.iloc[0]["ticker"] == "BTC"
        assert frame.iloc[0]["open"] == 100.0
        assert frame.iloc[0]["source"] == "coinmarketcap"
        _, kwargs = session.get.call_args
        assert kwargs["headers"]["X-CMC_PRO_API_KEY"] == "k"
        assert kwargs["params"]["symbol"] == "BTC"

    def test_raises_for_invalid_range(self) -> None:
        with pytest.raises(ValueError, match="start-date must be earlier than end-date"):
            fetch_ohlcv(
                "BTC",
                api_key="k",
                convert="USD",
                time_period="daily",
                start_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
                end_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            )


class TestWriteCsv:
    def test_writes_into_separate_timeframe_folder(self, tmp_path: Path) -> None:
        frame = pd.DataFrame(
            {
                "timestamp": ["2025-01-01T00:00:00Z"],
                "open": [1.0],
                "high": [2.0],
                "low": [0.5],
                "close": [1.5],
                "volume": [10.0],
                "market_cap": [100.0],
                "ticker": ["BTC"],
                "source": ["coinmarketcap"],
            }
        )
        output = write_csv(frame, "BTC", tmp_path, "daily")
        assert output.exists()
        assert output.name == "BTC-CMC-daily.csv"
        assert output.parent == tmp_path / "daily"


class TestMain:
    @patch("trading_data_pipeline.coinmarketcap_downloader.fetch_ohlcv")
    @patch("trading_data_pipeline.coinmarketcap_downloader.os.getenv")
    def test_main_uses_coin_market_cap_env(
        self,
        mock_getenv: MagicMock,
        mock_fetch_ohlcv: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_getenv.side_effect = lambda key: "cmc-key" if key == "COIN_MARKET_CAP" else None
        mock_fetch_ohlcv.return_value = pd.DataFrame(
            {
                "timestamp": ["2025-01-01T00:00:00Z"],
                "open": [1.0],
                "high": [2.0],
                "low": [0.5],
                "close": [1.5],
                "volume": [10.0],
                "market_cap": [100.0],
                "ticker": ["BTC"],
                "source": ["coinmarketcap"],
            }
        )

        main(
            [
                "BTC",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-02",
                "--output-dir",
                str(tmp_path),
            ]
        )

        output = tmp_path / "daily" / "BTC-CMC-daily.csv"
        assert output.exists()
