"""RTH session calendar helpers for TPO windowing."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

# Fixed NYSE full-day holiday set covering the analysis window (extend as needed).
_NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 2, 19),
        date(2024, 3, 29),
        date(2024, 5, 27),
        date(2024, 6, 19),
        date(2024, 7, 4),
        date(2024, 9, 2),
        date(2024, 11, 28),
        date(2024, 12, 25),
        date(2025, 1, 1),
        date(2025, 1, 9),  # National Day of Mourning (Carter)
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),  # Independence Day observed
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),  # Juneteenth observed
        date(2027, 7, 5),  # Independence Day observed
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),  # Christmas observed
    }
)


def is_rth_session_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    return day not in _NYSE_HOLIDAYS


def to_ny(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(NY_TZ)


def session_date_for_datetime(dt: datetime) -> date:
    """Map a fill timestamp to its RTH session date (NY calendar day)."""
    return to_ny(dt).date()


def is_within_rth(dt: datetime) -> bool:
    local = to_ny(dt)
    if not is_rth_session_day(local.date()):
        return False
    clock = local.time()
    return RTH_OPEN <= clock <= RTH_CLOSE


def attach_fill_to_session(dt: datetime) -> tuple[date, str]:
    """
    Attach a fill to an RTH session.

    Returns (session_date, attachment) where attachment is:
      - "rth" for fills during regular hours
      - "prior_close" for after-hours / weekend → prior session
      - "next_open" for pre-market → same/next session
    """
    local = to_ny(dt)
    day = local.date()
    clock = local.time()

    if is_rth_session_day(day) and RTH_OPEN <= clock <= RTH_CLOSE:
        return day, "rth"

    if is_rth_session_day(day) and clock < RTH_OPEN:
        return day, "next_open"

    # After close or non-session day → prior RTH session
    cursor = day if (is_rth_session_day(day) and clock > RTH_CLOSE) else day - timedelta(days=1)
    while not is_rth_session_day(cursor):
        cursor -= timedelta(days=1)
    return cursor, "prior_close"


def iter_sessions(start: date, end: date) -> list[date]:
    if end < start:
        return []
    sessions: list[date] = []
    cursor = start
    while cursor <= end:
        if is_rth_session_day(cursor):
            sessions.append(cursor)
        cursor += timedelta(days=1)
    return sessions


def previous_sessions(anchor: date, count: int) -> list[date]:
    if count <= 0:
        return []
    sessions: list[date] = []
    cursor = anchor - timedelta(days=1)
    while len(sessions) < count:
        if is_rth_session_day(cursor):
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    sessions.reverse()
    return sessions


def next_sessions(anchor: date, count: int) -> list[date]:
    if count <= 0:
        return []
    sessions: list[date] = []
    cursor = anchor + timedelta(days=1)
    while len(sessions) < count:
        if is_rth_session_day(cursor):
            sessions.append(cursor)
        cursor += timedelta(days=1)
    return sessions


def expand_session_window(
    first_hold: date,
    last_hold: date,
    *,
    before: int = 10,
    after: int = 10,
) -> list[date]:
    hold = iter_sessions(first_hold, last_hold)
    if not hold:
        # Fallback: treat first_hold as a calendar day and find nearest sessions
        cursor = first_hold
        while not is_rth_session_day(cursor):
            cursor -= timedelta(days=1)
        hold = [cursor]
        last_hold = cursor
        first_hold = cursor
    prior = previous_sessions(hold[0], before)
    following = next_sessions(hold[-1], after)
    return prior + hold + following


def session_bounds_ny(session: date) -> tuple[datetime, datetime]:
    start = datetime.combine(session, RTH_OPEN, tzinfo=NY_TZ)
    end = datetime.combine(session, RTH_CLOSE, tzinfo=NY_TZ)
    return start, end


def tpo_period_index(dt: datetime, *, period_minutes: int = 30) -> int:
    """0-based TPO letter index within the RTH session (A=0)."""
    local = to_ny(dt)
    open_dt = datetime.combine(local.date(), RTH_OPEN, tzinfo=NY_TZ)
    elapsed = (local - open_dt).total_seconds()
    if elapsed < 0:
        return 0
    return int(elapsed // (period_minutes * 60))


def tpo_letter(index: int) -> str:
    if index < 0:
        index = 0
    if index < 26:
        return chr(ord("A") + index)
    # After Z continue with AA, AB... rarely needed for RTH
    return f"A{chr(ord('A') + (index - 26) % 26)}"
