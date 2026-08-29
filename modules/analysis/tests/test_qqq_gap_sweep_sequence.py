"""Tests for the chronological QQQ opening-gap sweep classifier."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_qqq_gap_sweep_sequence.py"
SPEC = importlib.util.spec_from_file_location("qqq_gap_sweep", SCRIPT)
assert SPEC and SPEC.loader
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


def _day() -> pd.DataFrame:
    minute = np.arange(390)
    close = np.full(390, 102.2)
    high = np.full(390, 102.4)
    low = np.full(390, 102.1)
    close[:5] = [102.1, 102.3, 102.5, 102.4, 102.2]
    high[:5] = [102.3, 102.5, 102.8, 102.6, 102.5]
    low[:5] = [101.9, 102.0, 102.2, 102.1, 102.0]
    low[7] = 101.95  # Return through the 102.00 open.
    low[9] = 101.80  # Strictly sweep the initial 101.90 low.
    high[20] = 102.85
    low[30] = 99.9
    return pd.DataFrame({"minute": minute, "high": high, "low": low, "close": close})


def _daily() -> pd.Series:
    row = pd.Series({"open": 102.0, "prior_close": 100.0})
    row.name = "2026-01-02"
    return row


def test_detects_ordered_open_retest_sweep_and_high_first() -> None:
    result = study.classify_session(_day(), _daily())

    assert result is not None
    assert result["open_retest_minute"] == 7
    assert result["sweep_minute"] == 9
    assert result["resolution"] == "initial_high_first"
    assert result["initial_high_revisit_minute"] == 20
    assert result["prior_close_retest_minute"] == 30


def test_sweep_must_be_strictly_later_than_open_retest() -> None:
    day = _day()
    day.loc[day.minute.eq(7), "low"] = 101.7
    day.loc[day.minute.eq(9), "low"] = 101.95
    day.loc[day.minute.eq(30), "low"] = 102.1

    result = study.classify_session(day, _daily())

    assert result is not None
    assert result["open_retest_minute"] == 7
    assert result["swept_initial_low"] is False


def test_same_minute_target_touches_are_ambiguous() -> None:
    day = _day()
    day.loc[day.minute.eq(20), ["high", "low"]] = [102.85, 99.9]
    day.loc[day.minute.eq(30), "low"] = 101.0

    result = study.classify_session(day, _daily())

    assert result is not None
    assert result["resolution"] == "same_minute_ambiguous"
