from __future__ import annotations

import pytest

from trading_analysis.position_sizer.checklist import run_checklist
from trading_analysis.position_sizer.macd import classify_histogram, ema, macd_histogram
from trading_analysis.position_sizer.size import compute_size


def test_stock_long_size():
    sized = compute_size(entry=100, stop=98, equity=20_000, side="long", risk_pct=0.02)
    # 1R = $400, $2 per share → 200 shares
    assert sized.quantity == 200
    assert sized.notional == 20_000
    assert sized.three_r_price == pytest.approx(106)


def test_stock_short_rejects_stop_below():
    with pytest.raises(ValueError, match="above entry"):
        compute_size(entry=100, stop=99, equity=20_000, side="short")


def test_option_debit_cap_cuts_qty():
    sized = compute_size(
        entry=4.0,
        stop=2.0,
        equity=20_000,
        side="long",
        instrument="option",
        risk_pct=0.02,
        debit_cap_pct=0.04,
    )
    # 1R $400 / ($2 * 100) = 2 contracts; debit 2*400=800 = 4% → ok
    assert sized.quantity == 2
    assert sized.debit_pct == pytest.approx(0.04)
    fat = compute_size(
        entry=8.0,
        stop=4.0,
        equity=20_000,
        side="long",
        instrument="option",
        risk_pct=0.02,
        debit_cap_pct=0.04,
    )
    # 1R $400 / ($4*100) = 1; debit $800 = 4%
    assert fat.quantity == 1


def test_option_zero_qty_when_contract_too_rich():
    sized = compute_size(
        entry=50.0,
        stop=25.0,
        equity=20_000,
        side="long",
        instrument="option",
        risk_pct=0.02,
    )
    # 1R $400 vs $2500 per contract
    assert sized.quantity == 0


def test_ema_and_histogram_length():
    closes = [float(100 + i) for i in range(80)]
    hist = macd_histogram(closes)
    assert len(hist) == 80
    clean = [value for value in hist if value == value]
    assert len(clean) >= 40


def test_histogram_top_fails_long_checklist():
    # Rolled over from a local high — buying the top of the histogram
    hist = [0.2, 0.5, 1.0, 1.6, 2.0, 1.7]
    state = classify_histogram(hist)
    assert state.at_top
    sized = compute_size(entry=100, stop=98, equity=20_000, side="long")
    report = run_checklist(sized, symbol="TEST", fetch_macd=False, macd=state)
    macd_row = next(item for item in report.results if item.id == "macd_histogram")
    assert macd_row.status == "fail"
    assert report.blocked


def test_histogram_bottom_fails_short():
    hist = [-0.2, -0.5, -1.0, -1.6, -2.0, -1.7]
    state = classify_histogram(hist)
    assert state.at_bottom
    sized = compute_size(entry=100, stop=102, equity=20_000, side="short")
    report = run_checklist(sized, symbol="TEST", fetch_macd=False, macd=state)
    macd_row = next(item for item in report.results if item.id == "macd_histogram")
    assert macd_row.status == "fail"


def test_manual_pending_does_not_block():
    hist = [0.1, 0.12, 0.11, 0.13, 0.14]
    state = classify_histogram(hist)
    sized = compute_size(entry=100, stop=98, equity=20_000, side="long")
    report = run_checklist(sized, symbol="TEST", fetch_macd=False, macd=state)
    assert any(item.status == "pending" and item.evaluator == "manual" for item in report.results)
    macd_row = next(item for item in report.results if item.id == "macd_histogram")
    if macd_row.status != "fail":
        assert not report.blocked


def test_manual_fail_blocks():
    sized = compute_size(entry=100, stop=98, equity=20_000, side="long")
    report = run_checklist(
        sized,
        symbol="TEST",
        fetch_macd=False,
        macd=classify_histogram([0.05, 0.06, 0.05, 0.07, 0.08]),
        manual={"hurry": "fail"},
    )
    assert report.blocked
    hurry = next(item for item in report.results if item.id == "hurry")
    assert hurry.status == "fail"


def test_ema_seed():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    out = ema(values, 3)
    assert out[0] != out[0]
    assert out[1] != out[1]
    assert out[2] == pytest.approx(2.0)
