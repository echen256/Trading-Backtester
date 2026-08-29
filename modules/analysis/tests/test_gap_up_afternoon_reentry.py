"""Focused tests for the large-gap afternoon re-entry study."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_gap_up_afternoon_reentry.py"
SPEC = importlib.util.spec_from_file_location("gap_up_afternoon", SCRIPT)
assert SPEC and SPEC.loader
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


def _trend_day(*, same_bar_hod: bool = False) -> pd.DataFrame:
    minutes = np.arange(390)
    close = np.full(390, 106.0)
    close[:60] = np.linspace(100.05, 105.0, 60)
    close[60:101] = np.linspace(105.0, 106.0, 41)
    close[101:201] = np.linspace(106.0, 102.0, 100)
    close[201:211] = np.linspace(102.0, 104.5, 10)
    close[211:251] = np.linspace(104.5, 107.0, 40)
    high = close + 0.1
    low = close - 0.1
    if same_bar_hod:
        high[210] = 107.0
        high[211:] = np.minimum(high[211:], 106.0)
        close[211:] = 105.0
        low[211:] = 104.8
    return pd.DataFrame(
        {
            "ticker": "TEST",
            "date": "2026-01-02",
            "minute": minutes,
            "open": np.r_[100.0, close[:-1]],
            "high": high,
            "low": low,
            "close": close,
            "volume": 10_000,
        }
    )


def _candidate() -> pd.Series:
    return pd.Series({"ticker": "TEST", "date": "2026-01-02", "gap_pct": 12.0})


def test_detects_primary_runner_pullback_reclaim_and_later_hod() -> None:
    result = study.analyze_event(_trend_day(), _candidate())

    assert result is not None
    assert result["runner_primary"] is True
    assert result["afternoon_new_high"] is True
    assert result["pullback_before_afternoon_hod"] is True
    assert result["reclaim_signal"] is True
    assert result["reclaim_new_hod_after"] is True
    assert result["reclaim_signal_minute"] == 210


def test_reclaim_success_does_not_use_signal_bar_high() -> None:
    result = study.analyze_event(_trend_day(same_bar_hod=True), _candidate())

    assert result is not None
    assert result["afternoon_new_high"] is True
    assert result["reclaim_signal"] is True
    assert result["reclaim_new_hod_after"] is False


def test_wilson_interval_is_bounded() -> None:
    lower, upper = study.wilson_interval(8, 12)

    assert 0 < lower < 8 / 12 < upper < 1
