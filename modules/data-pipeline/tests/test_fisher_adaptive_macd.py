"""Tests for the Fisher Transform + Adaptive MACD archive translator."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_data_pipeline.fisher_adaptive_macd import (
    StrategyConfig,
    compute_archived_indicator_payload,
    compute_fisher_adaptive_macd_strategy,
)


def _make_rows(count: int = 120) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for index in range(count):
        wave = math.sin(index / 5.0) * 4.0
        trend = index * 0.05
        close_price = 100.0 + trend + wave
        open_price = close_price - math.cos(index / 7.0)
        high_price = max(open_price, close_price) + 1.25
        low_price = min(open_price, close_price) - 1.1
        timestamp = start + timedelta(days=index)
        rows.append(
            {
                "timestamp": timestamp,
                "time": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": round(open_price, 6),
                "high": round(high_price, 6),
                "low": round(low_price, 6),
                "close": round(close_price, 6),
                "volume": float(1_000_000 + index),
            }
        )
    return rows


def test_compute_strategy_returns_series_and_events() -> None:
    rows = _make_rows()

    result = compute_fisher_adaptive_macd_strategy(
        rows,
        ticker="TEST",
        timeframe_minutes=1440,
        config=StrategyConfig(ft_len=20, r2_period=10, short_max_bars_in_trade=15),
    )

    assert result.ticker == "TEST"
    assert len(result.rows) == len(rows)
    assert len(result.series["fisher"]) == len(rows)
    assert len(result.series["adaptive_macd"]) == len(rows)
    assert any(value is not None for value in result.series["histogram"][10:])
    assert "short_entries" in result.events
    assert "short_exits" in result.events
    assert isinstance(result.summary["short_entries"], int)
    assert "closed_trades" in result.statistics
    assert isinstance(result.trades, list)


def test_compute_archived_indicator_payload_matches_frontend_shape(tmp_path: Path) -> None:
    csv_path = tmp_path / "1440" / "TEST-1440M.csv"
    csv_path.parent.mkdir(parents=True)
    rows = _make_rows(90)
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        + "\n".join(
            f"{row['time']},{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']}"
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )

    payload = compute_archived_indicator_payload("TEST", "D", data_dir=tmp_path)

    indicator_names = [indicator["name"] for indicator in payload["customIndicators"]]

    assert payload["ticker"] == "TEST"
    assert payload["timeframe_minutes"] == 1440
    assert payload["source_csv"] == str(csv_path)
    assert "Fisher" in indicator_names
    assert "Adaptive MACD" in indicator_names
    assert "Histogram Positive" in indicator_names
    assert "events" in payload
    assert "statistics" in payload
    assert "closed_trades" in payload["statistics"]
    assert "trades" in payload
    assert payload["customIndicators"][0]["data"][0]["time"].endswith("Z")
