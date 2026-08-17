"""Evaluate size, duration, and quality of a proposed option ticket.

The function does not forecast. It applies the G/Y/R/H/D/N/F/B decision
matrix, hold clocks, TPO location, MACD extension, and sit-through sizing
from the Aug 2026 CRCL lesson: short-dated premium must be holdable.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

REGIMES = ("G", "Y", "R", "H", "D", "N", "F", "B")
LOCATIONS = ("extreme_with", "mid", "extreme_against", "unknown")
MACD_STATES = ("fresh", "developed", "mature", "extreme", "unknown")
DIRECTIONS = ("long", "call", "short", "put")

RATING_LABELS = {
    1: "No go",
    2: "Probe only",
    3: "Standard",
    4: "Full size",
    5: "Double up",
}

# Sit-through first ticket. Double-up is a second ticket after 2x, not a $2.5k flyer.
SIZE_BY_RATING = {
    1: 0,
    2: 500,
    3: 800,
    4: 1200,
    5: 800,
}

# Hold clock (days) from optimized_trading_flow.md
HOLD_CLOCK = {
    ("G", "call"): (4, 14),
    ("G", "put"): None,
    ("Y", "call"): None,  # wait, then 2-7 after resolution
    ("Y", "put"): None,
    ("R", "call"): None,
    ("R", "put"): (1, 9),
    ("H", "call"): (3, 7),
    ("H", "put"): (1, 7),
    ("D", "call"): (4, 7),
    ("D", "put"): (4, 7),
    ("N", "call"): None,
    ("N", "put"): (1, 4),
    ("F", "call"): None,
    ("F", "put"): (0, 3),
    ("B", "call"): (4, 14),
    ("B", "put"): None,
}

# DTE to cover the clock with theta margin
DURATION_DTE = {
    ("G", "call"): (21, 30),
    ("B", "call"): (21, 30),
    ("R", "put"): (7, 21),
    ("F", "put"): (3, 10),
    ("H", "call"): (7, 14),
    ("H", "put"): (7, 14),
    ("D", "call"): (7, 14),
    ("D", "put"): (7, 14),
    ("N", "put"): (7, 14),
}

FULL_CALL_STATES = {"G", "B"}
FULL_PUT_STATES = {"R", "F"}
PROBE_STATES = {"H", "D"}


@dataclass(frozen=True, slots=True)
class TradeEvaluation:
    ticket: str
    date: str
    timeframe: str
    direction: str
    side: str
    regime: str
    rating: int
    rating_label: str
    permission: str
    size_usd: int
    size_note: str
    duration_dte: str
    hold_clock: str
    requested_hold_days: int
    location: str
    macd_extension: str
    vetoes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_trade(
    ticket: str,
    date: str | date,
    timeframe: str,
    direction: str,
    *,
    regime: str,
    location: str = "unknown",
    macd_extension: str = "unknown",
    weekend_hold: bool | None = None,
    name_lost_today: bool = False,
    name_lost_this_week: bool = False,
    leader: bool | None = None,
    after_paid_theme: bool = False,
) -> TradeEvaluation:
    """Score a proposed ticket and recommend size plus instrument duration.

    Parameters
    ----------
    ticket:
        Underlying symbol (e.g. CRCL, QQQ, XLE).
    date:
        Intended entry date (YYYY-MM-DD or date).
    timeframe:
        Intended hold, e.g. ``0dte``, ``3d``, ``7d``, ``14d``, ``30d``, ``swing``.
    direction:
        ``long`` / ``call`` or ``short`` / ``put``.
    regime:
        Decision-matrix state G, Y, R, H, D, N, F, or B.
    location:
        TPO location vs direction: extreme_with, mid, extreme_against, unknown.
    macd_extension:
        Continuation extension vs prior MACD peak: fresh, developed, mature,
        extreme, unknown.
    """
    entry = _parse_date(date)
    side = _normalize_side(direction)
    regime = regime.strip().upper()
    location = location.strip().lower()
    macd_extension = macd_extension.strip().lower()
    requested_days = _parse_timeframe_days(timeframe)
    ticket = ticket.strip().upper()

    if regime not in REGIMES:
        raise ValueError(f"regime must be one of {REGIMES}, got {regime!r}")
    if location not in LOCATIONS:
        raise ValueError(f"location must be one of {LOCATIONS}, got {location!r}")
    if macd_extension not in MACD_STATES:
        raise ValueError(f"macd_extension must be one of {MACD_STATES}, got {macd_extension!r}")

    if weekend_hold is None:
        # Friday entry into a ≤14d ticket is weekend event risk (CRCL 8/7).
        weekend_hold = entry.weekday() == 4 and requested_days <= 14

    clock = HOLD_CLOCK[(regime, side)]
    vetoes: list[str] = []
    reasons: list[str] = []
    rating = 3
    permission = "yes"

    aligned = clock is not None
    if not aligned:
        if regime == "Y":
            permission = "wait"
            vetoes.append("Y: stop adding; wait for resolution, then attack")
        else:
            permission = "no"
            vetoes.append(f"{regime} does not permit {side}s at entry")
        rating = 1

    if name_lost_today:
        permission = "no"
        vetoes.append("one loss in this name today ends the name")
        rating = 1

    if location == "extreme_against":
        permission = "no"
        vetoes.append("TPO: short-at-bottom or long-at-top")
        rating = 1

    if aligned and requested_days == 0 and regime in FULL_CALL_STATES and side == "call":
        vetoes.append("same-day G/B calls are a leak; minimum 4d hold")
        rating = min(rating, 1)
        permission = "no"

    if aligned and regime == "F" and side == "put" and requested_days == 0:
        reasons.append("F puts: 0DTE only if not chasing a ≥5% 3-day dump")

    if aligned and regime == "D":
        if leader is False and side == "call":
            vetoes.append("D calls only on leaders")
            rating = 1
            permission = "no"
        elif leader is False and side == "put":
            reasons.append("D puts: weak names only; no index-crash bet")
        elif leader is True and side == "put":
            vetoes.append("D: do not put leaders / index beta")
            rating = min(rating, 1)
            permission = "no"

    if permission == "yes":
        rating = _base_rating(regime, side, location, macd_extension)
        if weekend_hold and requested_days <= 14:
            rating = min(rating, 2)
            reasons.append("weekend + ≤14D is an event ticket, not full size")
        if requested_days == 0 and regime not in {"F"}:
            rating = min(rating, 2)
            reasons.append("0DTE is event risk, not a swing")
        if requested_days > 0 and clock is not None and requested_days < clock[0]:
            rating = min(rating, 2)
            reasons.append(
                f"requested {requested_days}d is shorter than {regime} {side} clock {clock[0]}-{clock[1]}d"
            )
        dte_lo, dte_hi = DURATION_DTE.get((regime, side), (clock[1] if clock else 7, 30))
        if clock is not None and requested_days > clock[1]:
            if requested_days >= dte_lo:
                reasons.append(
                    f"use {dte_lo}-{dte_hi} DTE paper; still exit on the {clock[0]}-{clock[1]}d hold clock"
                )
            else:
                rating = min(rating, 2)
                reasons.append(f"hold >{clock[1]}d outstays the {regime} {side} clock")
        if macd_extension in {"mature", "extreme"}:
            rating = min(rating, 2)
            reasons.append(f"MACD {macd_extension}: no new continuation / no pyramid")
        if location == "mid":
            rating = min(rating, 3)
            reasons.append("mid-value entry: prefer range extreme")
        if location == "unknown":
            rating = min(rating, 3)
        if macd_extension == "unknown":
            rating = min(rating, 4)
        if name_lost_this_week:
            rating = min(rating, 2)
            reasons.append("re-entry after a failed name this week")
        if after_paid_theme:
            rating = min(rating, 2)
            reasons.append("overworking a paid theme")
        if regime == "H":
            rating = min(rating, 3)
            reasons.append("H: 1/3 size, no 10+ lot conviction, 3-7d only")
        if regime == "N" and side == "put":
            rating = min(rating, 3)
            reasons.append("N puts are convexity; dead if no F by day 4")

    rating = max(1, min(5, rating))
    if permission != "yes":
        rating = 1

    size_usd = SIZE_BY_RATING[rating]
    duration = _duration_for(regime, side, requested_days, clock)
    hold_label = "do not enter" if clock is None else f"{clock[0]}-{clock[1]}d"
    size_note = _size_note(rating, regime, requested_days, weekend_hold)

    if permission == "yes" and location == "extreme_with":
        reasons.append("location aligned with direction at a range extreme")
    if permission == "yes" and macd_extension == "fresh" and rating >= 4:
        reasons.append("fresh MACD: continuation allowed, let it work the clock")
    if permission == "yes" and rating == 5:
        reasons.append("double-up is a second holdable ticket after 2×, not a larger first flyer")

    return TradeEvaluation(
        ticket=ticket,
        date=entry.isoformat(),
        timeframe=timeframe,
        direction=direction.strip().lower(),
        side=side,
        regime=regime,
        rating=rating,
        rating_label=RATING_LABELS[rating],
        permission=permission,
        size_usd=size_usd,
        size_note=size_note,
        duration_dte=duration,
        hold_clock=hold_label,
        requested_hold_days=requested_days,
        location=location,
        macd_extension=macd_extension,
        vetoes=vetoes,
        reasons=reasons,
    )


def _base_rating(regime: str, side: str, location: str, macd: str) -> int:
    if regime in FULL_CALL_STATES and side == "call":
        rating = 4
        if location == "extreme_with" and macd in {"fresh", "developed"}:
            rating = 5
        return rating
    if regime in FULL_PUT_STATES and side == "put":
        rating = 4
        if location == "extreme_with" and macd in {"fresh", "developed"} and regime == "F":
            rating = 5
        if regime == "R":
            rating = 4
        return rating
    if regime in PROBE_STATES:
        return 2 if location != "extreme_with" else 3
    if regime == "N" and side == "put":
        return 2
    return 2


def _duration_for(regime: str, side: str, requested_days: int, clock: tuple[int, int] | None) -> str:
    if clock is None:
        return "n/a — do not enter"
    lo, hi = DURATION_DTE.get((regime, side), (max(clock[1], 7), max(clock[1] + 7, 14)))
    # Never recommend 0-2 DTE as a swing. Event 0DTE only if they asked and F puts.
    if requested_days == 0 and regime == "F" and side == "put":
        return "3-7 DTE (no 0DTE chase after a dump)"
    return f"{lo}-{hi} DTE"


def _size_note(rating: int, regime: str, requested_days: int, weekend_hold: bool) -> str:
    if rating == 1:
        return "flat"
    if rating == 2:
        extra = " weekend event" if weekend_hold else ""
        return f"$500 sit-through{extra}; size so a 40% MTM is survivable"
    if rating == 3:
        if regime == "H":
            return "$800 max; 1/3 book; no 10-lot short-dated conviction"
        return "$800 standard tactical; hold the clock, do not scalp a valid swing"
    if rating == 4:
        return "$1,200 full first ticket; still holdable; scale 2-5× then house-money re-entry"
    return (
        "$800 first ticket, double only after 2× with house money "
        f"(max 2.00x). Do not open a ${2500} {requested_days or 'short'}-day flyer"
    )


def _normalize_side(direction: str) -> str:
    raw = direction.strip().lower()
    if raw in {"long", "call", "calls", "buy"}:
        return "call"
    if raw in {"short", "put", "puts", "sell"}:
        return "put"
    raise ValueError(f"direction must be long/call or short/put, got {direction!r}")


def _parse_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date {value!r}; use YYYY-MM-DD")


def _parse_timeframe_days(timeframe: str) -> int:
    raw = timeframe.strip().lower().replace(" ", "")
    aliases = {
        "0dte": 0,
        "0d": 0,
        "sameday": 0,
        "intraday": 0,
        "1d": 1,
        "1-3d": 3,
        "3d": 3,
        "5d": 5,
        "7d": 7,
        "1w": 7,
        "week": 7,
        "weekly": 7,
        "10d": 10,
        "14d": 14,
        "2w": 14,
        "21d": 21,
        "30d": 30,
        "1m": 30,
        "monthly": 30,
        "swing": 14,
    }
    if raw in aliases:
        return aliases[raw]
    match = re.fullmatch(r"(\d+)\s*d(?:te|ay|ays)?", raw)
    if match:
        return int(match.group(1))
    raise ValueError(
        f"timeframe {timeframe!r} not understood; use 0dte, 3d, 7d, 14d, 30d, or swing"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate trade size, duration, and 1-5 quality rating.",
    )
    parser.add_argument("ticket", help="Underlying ticker")
    parser.add_argument("date", help="Entry date YYYY-MM-DD")
    parser.add_argument("timeframe", help="Intended hold: 0dte, 3d, 7d, 14d, 30d, swing")
    parser.add_argument("direction", help="long/call or short/put")
    parser.add_argument("--regime", required=True, choices=REGIMES, help="Decision-matrix state")
    parser.add_argument("--location", default="unknown", choices=LOCATIONS)
    parser.add_argument("--macd", dest="macd_extension", default="unknown", choices=MACD_STATES)
    parser.add_argument("--weekend", action="store_true", help="Force weekend-hold flag")
    parser.add_argument("--lost-today", action="store_true")
    parser.add_argument("--lost-week", action="store_true")
    parser.add_argument("--leader", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--after-paid-theme", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = evaluate_trade(
        args.ticket,
        args.date,
        args.timeframe,
        args.direction,
        regime=args.regime,
        location=args.location,
        macd_extension=args.macd_extension,
        weekend_hold=True if args.weekend else None,
        name_lost_today=args.lost_today,
        name_lost_this_week=args.lost_week,
        leader=args.leader,
        after_paid_theme=args.after_paid_theme,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return
    _print_result(result)


def _print_result(result: TradeEvaluation) -> None:
    print(f"{result.ticket} {result.date} {result.direction} {result.timeframe}")
    print(f"Regime {result.regime}  permission {result.permission}")
    print(f"Rating {result.rating}/5  {result.rating_label}")
    print(f"Size   ${result.size_usd:,}  {result.size_note}")
    print(f"Duration {result.duration_dte}  hold clock {result.hold_clock}")
    if result.vetoes:
        print("Vetoes:")
        for item in result.vetoes:
            print(f"  - {item}")
    if result.reasons:
        print("Notes:")
        for item in result.reasons:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
