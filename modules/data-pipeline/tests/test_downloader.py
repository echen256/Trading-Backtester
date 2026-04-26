"""Tests for downloader market routing."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd

from trading_data_pipeline.downloader import DownloadSettings, PolygonDownloader


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def test_fetch_range_uses_indices_endpoint() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(
        {
            "results": [
                {"o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "t": 1711929600000},
            ]
        }
    )
    downloader = PolygonDownloader(api_key="test-key", request_session=session)

    frame = downloader._fetch_range(
        "I:SPX",
        datetime(2024, 4, 1),
        datetime(2024, 4, 2),
        1440,
        market="indices",
    )

    assert list(frame.columns) == ["open", "high", "low", "close"]
    assert frame.index[0] == pd.Timestamp("2024-04-01 00:00:00+0000", tz=timezone.utc)
    request_url = session.get.call_args[0][0]
    assert "/v2/aggs/ticker/I:SPX/range/1/day/2024-04-01/2024-04-02" in request_url
    assert session.get.call_args[1]["params"]["limit"] == 50000


def test_download_watchlist_skips_market_cap_for_indices() -> None:
    downloader = PolygonDownloader(api_key="test-key", request_session=MagicMock())
    downloader._passes_market_cap = MagicMock(side_effect=AssertionError("should not be called"))
    downloader.download_symbol = MagicMock(return_value=None)

    downloader.download_watchlist(
        ["I:SPX"],
        settings=DownloadSettings(market="indices"),
        minimum_market_cap=1_000_000_000,
    )

    downloader._passes_market_cap.assert_not_called()


def test_fetch_range_infers_indices_market_from_symbol_prefix() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse({"results": []})
    downloader = PolygonDownloader(api_key="test-key", request_session=session)

    downloader._fetch_range(
        "I:NDX",
        datetime(2024, 4, 1),
        datetime(2024, 4, 2),
        1440,
    )

    request_url = session.get.call_args[0][0]
    assert "/v2/aggs/ticker/I:NDX/range/1/day/2024-04-01/2024-04-02" in request_url
