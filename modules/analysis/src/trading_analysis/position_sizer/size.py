"""Charter position size from entry, stop, and % risk."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor
from typing import Any, Literal

Instrument = Literal["stock", "option"]
Side = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class PositionSize:
    instrument: Instrument
    side: Side
    entry: float
    stop: float
    equity: float
    risk_pct: float
    risk_dollars: float
    stop_distance: float
    r_dollars_per_unit: float
    quantity: int
    notional: float
    debit_pct: float
    debit_cap_pct: float
    capped_by_debit: bool
    three_r_price: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_size(
    *,
    entry: float,
    stop: float,
    equity: float,
    side: Side,
    instrument: Instrument = "stock",
    risk_pct: float = 0.02,
    debit_cap_pct: float = 0.04,
    multiplier: int | None = None,
) -> PositionSize:
    if entry <= 0 or stop <= 0:
        raise ValueError("entry and stop must be positive")
    if equity <= 0:
        raise ValueError("equity must be positive")
    if risk_pct <= 0 or risk_pct >= 1:
        raise ValueError("risk_pct must be between 0 and 1")
    if side == "long" and stop >= entry:
        raise ValueError("long stop must be below entry")
    if side == "short" and stop <= entry:
        raise ValueError("short stop must be above entry")

    unit = 100 if instrument == "option" else 1
    if multiplier is not None:
        unit = multiplier

    stop_distance = abs(entry - stop)
    risk_dollars = equity * risk_pct
    r_per_unit = stop_distance * unit
    raw_qty = floor(risk_dollars / r_per_unit) if r_per_unit > 0 else 0
    notes: list[str] = []
    capped = False
    qty = max(raw_qty, 0)

    if instrument == "option":
        debit_cap_dollars = equity * debit_cap_pct
        max_by_debit = floor(debit_cap_dollars / (entry * unit)) if entry * unit > 0 else 0
        if qty > max_by_debit:
            qty = max(max_by_debit, 0)
            capped = True
            notes.append(
                f"Qty cut to {qty} so debit stays ≤ {debit_cap_pct:.0%} of equity "
                f"(${debit_cap_dollars:,.0f})."
            )
        if stop_distance / entry > 0.51:
            notes.append(
                "Stop is more than ~50% of premium — a loser may exceed 1R "
                "(charter: stop ~50% of debit)."
            )
        elif stop_distance / entry < 0.35:
            notes.append(
                "Stop is tighter than ~35% of premium; 1R is small vs a 4% debit. Confirm the stop is real."
            )

    if qty == 0:
        notes.append(
            f"Risk ${risk_dollars:,.0f} cannot buy one unit (1R = ${r_per_unit:,.2f}). "
            "Widen nothing — skip or use a cheaper contract."
        )

    notional = qty * entry * unit
    debit_pct = notional / equity if equity else 0.0
    three_r = entry + 3 * (entry - stop) if side == "long" else entry - 3 * (stop - entry)

    return PositionSize(
        instrument=instrument,
        side=side,
        entry=entry,
        stop=stop,
        equity=equity,
        risk_pct=risk_pct,
        risk_dollars=round(risk_dollars, 2),
        stop_distance=round(stop_distance, 6),
        r_dollars_per_unit=round(r_per_unit, 4),
        quantity=qty,
        notional=round(notional, 2),
        debit_pct=round(debit_pct, 4),
        debit_cap_pct=debit_cap_pct,
        capped_by_debit=capped,
        three_r_price=round(three_r, 4),
        notes=tuple(notes),
    )
