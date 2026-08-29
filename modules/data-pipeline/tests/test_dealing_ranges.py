"""Tests for swing-confirmed dealing-range lifecycle detection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_data_pipeline.dealing_ranges import compute_dealing_ranges


def _rows(values: list[tuple[float, float, float]]) -> list[dict[str, object]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "time": (start + timedelta(days=index)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "high": high,
            "low": low,
            "close": close,
        }
        for index, (high, low, close) in enumerate(values)
    ]


def test_swing_is_available_only_after_lookahead_bar() -> None:
    rows = _rows(
        [
            (10, 8, 9),
            (11, 7, 10),
            (14, 9, 13),  # swing high, confirmed at index 3
            (12, 6, 7),   # swing low, confirmed at index 4
            (13, 8, 12),
        ]
    )

    before_confirmation = compute_dealing_ranges(rows[:3], lookback=2, lookahead=1)
    result = compute_dealing_ranges(rows, lookback=2, lookahead=1)

    assert before_confirmation["swings"] == []
    assert [(swing["kind"], swing["pivot_index"], swing["confirmed_index"]) for swing in result["swings"]] == [
        ("high", 2, 3),
        ("low", 3, 4),
    ]
    assert result["ranges"][0]["start_index"] == 4
    assert result["ranges"][0]["lower"] == 6
    assert result["ranges"][0]["midpoint"] == 10
    assert result["ranges"][0]["upper"] == 14


def test_wick_sweep_keeps_range_and_close_break_expands_it() -> None:
    rows = _rows(
        [
            (10, 8, 9),
            (11, 7, 10),
            (14, 9, 13),
            (12, 6, 7),
            (13, 8, 12),  # initial 6-14 range confirmed
            (15, 9, 13),  # sweep above, close back inside
            (16, 10, 15), # close above => expansion
            (17, 11, 16),
        ]
    )

    result = compute_dealing_ranges(rows, lookback=2, lookahead=1)

    assert [event["kind"] for event in result["events"][:2]] == ["sweep_high", "expansion_up"]
    assert result["ranges"][0]["status"] == "expansion_up"
    assert result["ranges"][0]["end_index"] == 6
    assert result["ranges"][1]["lower"] == 6
    assert result["ranges"][1]["upper"] == 16
    assert result["ranges"][1]["status"] == "active"


def test_old_range_revisit_is_distinguished_from_new_prices() -> None:
    rows = _rows(
        [
            (10, 8, 9),
            (20, 9, 18),
            (15, 6, 7),
            (16, 8, 14),   # initial 6-20
            (17, 5, 5.5),  # down expansion to 5-20: new prices
            (12, 7, 10),
            (13, 8, 11),
            (14, 9, 12),
            (12, 8, 10),   # confirms a newer swing high at 14
            (13, 4, 4.5),  # down expansion to 4-14: new prices
            (12, 6, 10),
            (15, 7, 14.5), # up expansion back inside old 6-20
        ]
    )

    result = compute_dealing_ranges(rows, lookback=1, lookahead=1)

    expansion_events = [event for event in result["events"] if event["kind"].startswith("expansion")]
    assert expansion_events[0]["target"] == "new_prices"
    assert expansion_events[-1]["target"] == "old_range"


def test_invalid_pivot_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="lookback"):
        compute_dealing_ranges([], lookback=0)
    with pytest.raises(ValueError, match="lookahead"):
        compute_dealing_ranges([], lookahead=0)
