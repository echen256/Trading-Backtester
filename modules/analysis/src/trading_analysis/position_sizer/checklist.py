"""Load and run the swing sanity checklist. Add evaluators here as they grow."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from trading_analysis.market_data.underlying_dailies import fetch_underlying_daily_bars
from trading_analysis.position_sizer.macd import MacdHistogramState, classify_closes
from trading_analysis.position_sizer.price import resolve_polygon_ticker
from trading_analysis.position_sizer.size import PositionSize

Status = Literal["pass", "fail", "warn", "pending", "skip"]

CHECKLIST_DIR = Path(__file__).resolve().parent / "checklists"


@dataclass(frozen=True, slots=True)
class CheckResult:
    id: str
    label: str
    evaluator: str
    status: Status
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChecklistReport:
    name: str
    results: tuple[CheckResult, ...]
    macd: MacdHistogramState | None

    @property
    def blocked(self) -> bool:
        return any(item.status == "fail" for item in self.results)

    @property
    def pending(self) -> tuple[CheckResult, ...]:
        return tuple(item for item in self.results if item.status == "pending")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "blocked": self.blocked,
            "results": [item.to_dict() for item in self.results],
            "macd": None if self.macd is None else self.macd.to_dict(),
        }


def load_catalog(name: str = "swing") -> dict[str, Any]:
    path = CHECKLIST_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"checklist {name!r} not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _manual(status: Status, label: str, check_id: str) -> CheckResult:
    if status not in ("pass", "fail", "pending"):
        status = "pending"
    detail = {
        "pending": "Fill from the ticket: pass or fail. Until then this is not a green light.",
        "pass": "Marked pass on the ticket.",
        "fail": "Marked fail on the ticket.",
    }[status]
    return CheckResult(check_id, label, "manual", status, detail)


def _eval_stop_side(size: PositionSize, **_: Any) -> CheckResult:
    return CheckResult(
        "stop_side",
        "Stop is on the correct side of entry",
        "stop_side",
        "pass",
        f"Entry {size.entry} / stop {size.stop} / ${size.r_dollars_per_unit:,.2f} per unit · account 1R ${size.risk_dollars:,.0f}",
    )


def _eval_qty(size: PositionSize, **_: Any) -> CheckResult:
    if size.quantity <= 0:
        return CheckResult(
            "qty_nonzero",
            "1R can actually buy at least one unit",
            "qty_nonzero",
            "fail",
            "Quantity is 0. Skip.",
        )
    return CheckResult(
        "qty_nonzero",
        "1R can actually buy at least one unit",
        "qty_nonzero",
        "pass",
        f"{size.quantity} units · notional ${size.notional:,.0f} ({size.debit_pct:.1%} of equity)",
    )


def _eval_debit_cap(size: PositionSize, **_: Any) -> CheckResult:
    if size.instrument != "option":
        return CheckResult(
            "debit_cap",
            "Options debit ≤ 4% of equity (stock: skip)",
            "debit_cap",
            "skip",
            "Stock/ETF — debit cap does not apply.",
        )
    if size.debit_pct - 1e-9 > size.debit_cap_pct:
        return CheckResult(
            "debit_cap",
            "Options debit ≤ 4% of equity (stock: skip)",
            "debit_cap",
            "fail",
            f"Debit is {size.debit_pct:.1%} of equity; cap is {size.debit_cap_pct:.0%}.",
        )
    status: Status = "warn" if size.capped_by_debit else "pass"
    return CheckResult(
        "debit_cap",
        "Options debit ≤ 4% of equity (stock: skip)",
        "debit_cap",
        status,
        f"Debit {size.debit_pct:.1%} of equity"
        + (" (qty cut to cap)" if size.capped_by_debit else ""),
    )


def _eval_three_r(size: PositionSize, **_: Any) -> CheckResult:
    return CheckResult(
        "three_r",
        "3R target is defined (price that pays 3× the stop distance)",
        "three_r",
        "pass",
        f"3R print is {size.three_r_price}. If that is not plausible, this is a skip, not a 4% lottery.",
    )


def _eval_macd(
    size: PositionSize,
    *,
    macd: MacdHistogramState | None,
    **_: Any,
) -> CheckResult:
    label = "Long is not buying the top of a MACD histogram; short is not selling the bottom"
    if macd is None:
        return CheckResult(
            "macd_histogram",
            label,
            "macd_histogram",
            "pending",
            "No histogram (not enough daily bars or fetch failed).",
        )
    long = size.side == "long"
    if long and macd.at_top:
        status: Status = "fail"
        detail = (
            f"Histogram {macd.last} is at a local top ({macd.extension}, "
            f"{macd.sign}, {macd.slope}). Longs here are buying extension."
        )
    elif not long and macd.at_bottom:
        status = "fail"
        detail = (
            f"Histogram {macd.last} is at a local bottom ({macd.extension}, "
            f"{macd.sign}, {macd.slope}). Shorts here are selling extension."
        )
    elif macd.extension == "extreme":
        status = "fail"
        detail = f"MACD histogram is extreme ({macd.sign}, pctl {macd.percentile}). No new add."
    elif macd.extension == "mature":
        status = "warn"
        detail = f"MACD histogram is mature / contracting ({macd.sign}). Cap size; do not add."
    elif long and macd.sign == "negative":
        status = "warn"
        detail = f"Histogram is still negative ({macd.extension}). Long is against the clock."
    elif not long and macd.sign == "positive":
        status = "warn"
        detail = f"Histogram is still positive ({macd.extension}). Short is against the clock."
    else:
        status = "pass"
        detail = (
            f"Histogram {macd.last} · {macd.extension} · {macd.sign} · {macd.slope}"
            + (f" · pctl {macd.percentile}" if macd.percentile is not None else "")
        )
    return CheckResult("macd_histogram", label, "macd_histogram", status, detail)


EVALUATORS: dict[str, Callable[..., CheckResult]] = {
    "stop_side": _eval_stop_side,
    "qty_nonzero": _eval_qty,
    "debit_cap": _eval_debit_cap,
    "three_r": _eval_three_r,
    "macd_histogram": _eval_macd,
}


def fetch_daily_closes(symbol: str, *, days: int = 200) -> list[float]:
    ticker = resolve_polygon_ticker(symbol)
    end = date.today()
    start = end - timedelta(days=days)
    bars = fetch_underlying_daily_bars(ticker, start_date=start, end_date=end)
    closes: list[float] = []
    for bar in bars:
        close = bar.get("c") if isinstance(bar, dict) else None
        if close is not None:
            closes.append(float(close))
    return closes


def run_checklist(
    size: PositionSize,
    *,
    symbol: str,
    catalog: str = "swing",
    manual: dict[str, Status] | None = None,
    macd: MacdHistogramState | None = None,
    fetch_macd: bool = True,
) -> ChecklistReport:
    spec = load_catalog(catalog)
    manual = {key.lower(): value for key, value in (manual or {}).items()}
    state = macd
    if fetch_macd and state is None:
        try:
            closes = fetch_daily_closes(symbol)
            if len(closes) >= 40:
                state = classify_closes(closes)
        except Exception as exc:  # noqa: BLE001 — checklist must still return
            state = None
            macd_error = str(exc)
        else:
            macd_error = None
    else:
        macd_error = None

    results: list[CheckResult] = []
    for check in spec["checks"]:
        check_id = str(check["id"])
        label = str(check["label"])
        evaluator = str(check["evaluator"])
        if evaluator == "manual":
            marked = manual.get(check_id, "pending")
            results.append(_manual(marked, label, check_id))
            continue
        fn = EVALUATORS.get(evaluator)
        if fn is None:
            results.append(
                CheckResult(
                    check_id,
                    label,
                    evaluator,
                    "pending",
                    f"No evaluator registered for {evaluator!r}. Add it in checklist.py.",
                )
            )
            continue
        result = fn(size, macd=state)
        if result.id == "macd_histogram" and macd_error and result.status == "pending":
            result = CheckResult(
                result.id, result.label, result.evaluator, "pending", macd_error
            )
        results.append(result)

    return ChecklistReport(name=str(spec["name"]), results=tuple(results), macd=state)
