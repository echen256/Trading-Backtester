"""Classic Market Profile / TPO builder from RTH minute bars."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from .bars import parse_bar_timestamp
from .schema import SessionProfileSummary
from .sessions import tpo_letter, tpo_period_index


@dataclass
class MarketProfile:
    session: date
    bracket_size: float
    period_minutes: int
    brackets: dict[float, list[str]]  # mid price -> letters
    tpo_counts: dict[float, int]
    poc: float
    vah: float
    val: float
    ib_high: float
    ib_low: float
    session_high: float
    session_low: float
    shape_tags: list[str] = field(default_factory=list)
    single_print_high: bool = False
    single_print_low: bool = False
    total_tpos: int = 0

    def to_summary(self, *, ascii_width: int = 40) -> SessionProfileSummary:
        return SessionProfileSummary(
            date=self.session.isoformat(),
            poc=self.poc,
            vah=self.vah,
            val=self.val,
            ib_high=self.ib_high,
            ib_low=self.ib_low,
            session_high=self.session_high,
            session_low=self.session_low,
            bracket_size=self.bracket_size,
            tpo_count=self.total_tpos,
            shape_tags=list(self.shape_tags),
            tpo_ascii=render_profile_ascii(self, max_width=ascii_width),
            single_print_high=self.single_print_high,
            single_print_low=self.single_print_low,
        )


def adaptive_bracket_size(session_high: float, session_low: float) -> float:
    day_range = max(session_high - session_low, 0.01)
    raw = day_range / 24.0
    # Snap to a readable increment
    if raw >= 1.0:
        return max(0.25, round(raw * 4) / 4)
    if raw >= 0.25:
        return max(0.05, round(raw * 20) / 20)
    if raw >= 0.05:
        return max(0.01, round(raw * 100) / 100)
    return max(0.01, round(raw, 2))


def _bracket_mid(price: float, bracket_size: float) -> float:
    if bracket_size <= 0:
        return price
    idx = math.floor(price / bracket_size)
    return round((idx + 0.5) * bracket_size, 6)


def build_market_profile(
    session: date,
    bars: Sequence[dict[str, object]],
    *,
    period_minutes: int = 30,
    bracket_size: float | None = None,
) -> MarketProfile | None:
    if not bars:
        return None

    highs: list[float] = []
    lows: list[float] = []
    period_ranges: dict[int, tuple[float, float]] = {}

    for bar in bars:
        try:
            ts = parse_bar_timestamp(bar.get("t"))
            high = float(bar["h"])
            low = float(bar["l"])
        except (TypeError, ValueError, KeyError):
            continue
        highs.append(high)
        lows.append(low)
        idx = tpo_period_index(ts, period_minutes=period_minutes)
        if idx in period_ranges:
            prev_h, prev_l = period_ranges[idx]
            period_ranges[idx] = (max(prev_h, high), min(prev_l, low))
        else:
            period_ranges[idx] = (high, low)

    if not highs or not lows or not period_ranges:
        return None

    session_high = max(highs)
    session_low = min(lows)
    size = bracket_size if bracket_size is not None else adaptive_bracket_size(session_high, session_low)

    brackets: dict[float, list[str]] = defaultdict(list)
    for idx in sorted(period_ranges):
        high, low = period_ranges[idx]
        letter = tpo_letter(idx)
        mid = _bracket_mid(low, size)
        top = _bracket_mid(high, size)
        # Walk brackets from low to high
        level = mid
        # Ensure we cover from floor(low) to floor(high)
        start_idx = math.floor(low / size)
        end_idx = math.floor(high / size)
        for b_idx in range(start_idx, end_idx + 1):
            level = round((b_idx + 0.5) * size, 6)
            if letter not in brackets[level]:
                brackets[level].append(letter)

    if not brackets:
        return None

    tpo_counts = {level: len(letters) for level, letters in brackets.items()}
    total_tpos = sum(tpo_counts.values())
    # POC: highest count; tie-break toward middle of range
    mid_price = (session_high + session_low) / 2
    poc = max(
        tpo_counts.keys(),
        key=lambda level: (tpo_counts[level], -abs(level - mid_price)),
    )

    vah, val = _value_area(tpo_counts, poc, total_tpos)

    # Initial balance: first two TPO periods (A+B)
    ib_periods = [period_ranges[i] for i in (0, 1) if i in period_ranges]
    if ib_periods:
        ib_high = max(h for h, _ in ib_periods)
        ib_low = min(l for _, l in ib_periods)
    else:
        first = next(iter(period_ranges.values()))
        ib_high, ib_low = first

    shape_tags = _classify_shape(
        session_high=session_high,
        session_low=session_low,
        poc=poc,
        vah=vah,
        val=val,
        ib_high=ib_high,
        ib_low=ib_low,
        tpo_counts=tpo_counts,
    )

    # Single prints at extremes
    sorted_levels = sorted(tpo_counts.keys(), reverse=True)
    single_print_high = bool(sorted_levels) and tpo_counts[sorted_levels[0]] == 1
    single_print_low = bool(sorted_levels) and tpo_counts[sorted_levels[-1]] == 1

    return MarketProfile(
        session=session,
        bracket_size=size,
        period_minutes=period_minutes,
        brackets=dict(brackets),
        tpo_counts=tpo_counts,
        poc=poc,
        vah=vah,
        val=val,
        ib_high=ib_high,
        ib_low=ib_low,
        session_high=session_high,
        session_low=session_low,
        shape_tags=shape_tags,
        single_print_high=single_print_high,
        single_print_low=single_print_low,
        total_tpos=total_tpos,
    )


def _value_area(
    tpo_counts: dict[float, int],
    poc: float,
    total_tpos: int,
    *,
    coverage: float = 0.70,
) -> tuple[float, float]:
    if total_tpos <= 0:
        return poc, poc
    target = total_tpos * coverage
    levels = sorted(tpo_counts.keys())
    if poc not in tpo_counts:
        return poc, poc

    included = {poc}
    running = tpo_counts[poc]
    below = [level for level in levels if level < poc]
    above = [level for level in levels if level > poc]
    below.reverse()  # nearest below first
    bi = 0
    ai = 0
    while running < target and (bi < len(below) or ai < len(above)):
        next_below = below[bi] if bi < len(below) else None
        next_above = above[ai] if ai < len(above) else None
        if next_below is None and next_above is None:
            break
        if next_below is None:
            included.add(next_above)  # type: ignore[arg-type]
            running += tpo_counts[next_above]  # type: ignore[index]
            ai += 1
            continue
        if next_above is None:
            included.add(next_below)
            running += tpo_counts[next_below]
            bi += 1
            continue
        # Prefer the side with more TPOs; tie → expand both
        below_count = tpo_counts[next_below]
        above_count = tpo_counts[next_above]
        if above_count > below_count:
            included.add(next_above)
            running += above_count
            ai += 1
        elif below_count > above_count:
            included.add(next_below)
            running += below_count
            bi += 1
        else:
            included.add(next_above)
            included.add(next_below)
            running += above_count + below_count
            ai += 1
            bi += 1

    return max(included), min(included)


def _classify_shape(
    *,
    session_high: float,
    session_low: float,
    poc: float,
    vah: float,
    val: float,
    ib_high: float,
    ib_low: float,
    tpo_counts: dict[float, int],
) -> list[str]:
    tags: list[str] = []
    day_range = max(session_high - session_low, 1e-9)
    ib_range = max(ib_high - ib_low, 1e-9)
    extension = day_range / ib_range

    # POC location in range
    poc_pct = (poc - session_low) / day_range
    if poc_pct >= 0.65:
        tags.append("b_shape")  # buying tail / POC high → often short-covering day ending high
    elif poc_pct <= 0.35:
        tags.append("p_shape")
    else:
        tags.append("D_normal")

    if extension >= 2.0:
        tags.append("trend_day")
    elif extension <= 1.2 and (vah - val) / day_range >= 0.5:
        tags.append("neutral")
    else:
        tags.append("balance_or_moderate")

    return tags


def locate_price(profile: MarketProfile, price: float) -> str:
    if price > profile.vah:
        return "above_vah"
    if price < profile.val:
        return "below_val"
    return "inside_va"


def price_extreme_score(profile: MarketProfile, price: float) -> float:
    """1.0 = at session extreme, 0.0 = at mid-range."""
    mid = (profile.session_high + profile.session_low) / 2
    half = max((profile.session_high - profile.session_low) / 2, 1e-9)
    return min(1.0, abs(price - mid) / half)


def render_profile_ascii(profile: MarketProfile, *, max_width: int = 48) -> str:
    if not profile.tpo_counts:
        return ""
    levels = sorted(profile.tpo_counts.keys(), reverse=True)
    max_count = max(profile.tpo_counts.values()) or 1
    lines: list[str] = []
    lines.append(
        f"Session {profile.session.isoformat()}  POC={profile.poc:.2f}  "
        f"VA=[{profile.val:.2f},{profile.vah:.2f}]  IB=[{profile.ib_low:.2f},{profile.ib_high:.2f}]"
    )
    for level in levels:
        count = profile.tpo_counts[level]
        letters = "".join(profile.brackets.get(level, []))
        bar_len = max(1, int(round(count / max_count * min(max_width, 30))))
        marker = ""
        if abs(level - profile.poc) < profile.bracket_size / 2:
            marker = " <POC"
        elif abs(level - profile.vah) < profile.bracket_size / 2:
            marker = " <VAH"
        elif abs(level - profile.val) < profile.bracket_size / 2:
            marker = " <VAL"
        lines.append(f"{level:8.2f} | {'#' * bar_len:<30} {letters}{marker}")
    return "\n".join(lines)
