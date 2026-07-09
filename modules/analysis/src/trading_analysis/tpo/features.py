"""Deterministic TPO execution features from RealizedTrade + profiles."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Sequence

from ..display_common import extract_underlying_symbol
from ..parse_orders import RealizedTrade
from .bars import fetch_sessions_minute_bars, underlying_price_at
from .profile import (
    MarketProfile,
    build_market_profile,
    locate_price,
    price_extreme_score,
)
from .schema import ContextSummary, SessionProfileSummary, TpoFeatures
from .sessions import (
    attach_fill_to_session,
    expand_session_window,
    iter_sessions,
)


def _as_utc(dt: datetime | None, fallback_date: date) -> datetime:
    if dt is None:
        return datetime.combine(fallback_date, datetime.min.time(), tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def build_context_summary(profiles: Sequence[MarketProfile]) -> ContextSummary:
    if not profiles:
        return ContextSummary(
            poc_migration="balance",
            balance_days=0,
            trend_days=0,
            session_count=0,
            poc_trail=[],
        )

    trail = [{"date": p.session.isoformat(), "poc": p.poc} for p in profiles]
    balance_days = sum(1 for p in profiles if "neutral" in p.shape_tags or "balance_or_moderate" in p.shape_tags)
    trend_days = sum(1 for p in profiles if "trend_day" in p.shape_tags)

    if len(profiles) >= 2:
        delta = profiles[-1].poc - profiles[0].poc
        span = max(abs(profiles[0].poc) * 0.01, profiles[0].bracket_size * 2)
        if delta > span:
            migration = "up"
        elif delta < -span:
            migration = "down"
        else:
            migration = "balance"
    else:
        migration = "balance"

    return ContextSummary(
        poc_migration=migration,
        balance_days=balance_days,
        trend_days=trend_days,
        session_count=len(profiles),
        poc_trail=trail,
    )


def _ib_break_context(profile: MarketProfile, price: float, direction: str) -> str:
    if price > profile.ib_high:
        break_side = "above_ib"
    elif price < profile.ib_low:
        break_side = "below_ib"
    else:
        return "inside_ib"

    if direction == "long":
        return "with_ib_break" if break_side == "above_ib" else "against_ib_break"
    return "with_ib_break" if break_side == "below_ib" else "against_ib_break"


def _deterministic_score_and_hits(
    *,
    direction: str,
    entry_vs_prior_va: str,
    entry_vs_day_va: str,
    entry_extreme_score: float,
    short_bottom_flag: bool,
    long_top_flag: bool,
    ib_break_context: str,
    exit_vs_va: str,
    gave_back_to_value: bool,
) -> tuple[float, list[str]]:
    score = 70.0
    hits: list[str] = []

    if entry_vs_day_va == "inside_va" and entry_extreme_score < 0.45:
        score -= 25
        hits.append("mid_range_entry")

    if direction == "short" and short_bottom_flag:
        score -= 40
        hits.append("short_at_bottom")

    if direction == "long" and long_top_flag:
        score -= 30
        hits.append("long_at_top")

    if direction == "short" and entry_vs_prior_va == "above_vah":
        score += 15
        hits.append("short_at_prior_vah")
    if direction == "long" and entry_vs_prior_va == "below_val":
        score += 15
        hits.append("long_at_prior_val")

    if entry_extreme_score >= 0.75:
        score += 10
        hits.append("entry_at_extreme")
    elif entry_extreme_score < 0.35:
        score -= 10

    if ib_break_context == "against_ib_break":
        score -= 15
        hits.append("against_ib_break")
    elif ib_break_context == "with_ib_break":
        score += 5

    if gave_back_to_value:
        score -= 10
        hits.append("gave_back_to_value")

    if direction == "long" and exit_vs_va == "above_vah":
        score += 5
        hits.append("exit_above_value")
    if direction == "short" and exit_vs_va == "below_val":
        score += 5
        hits.append("exit_below_value")

    return max(0.0, min(100.0, score)), hits


def extract_features_for_trade(
    trade: RealizedTrade,
    *,
    context_before: int = 10,
    context_after: int = 10,
    period_minutes: int = 30,
    cache_dir=None,
    api_key: str | None = None,
    throttle_seconds: float = 0.12,
) -> tuple[
    TpoFeatures,
    SessionProfileSummary | None,
    SessionProfileSummary | None,
    ContextSummary,
    float | None,
    float | None,
    dict[date, MarketProfile],
]:
    from pathlib import Path

    from .bars import DEFAULT_CACHE_DIR

    underlying = extract_underlying_symbol(trade.symbol) or trade.underlying or trade.symbol
    open_dt = _as_utc(trade.open_datetime, trade.open_date)
    close_dt = _as_utc(trade.trade_datetime, trade.trade_date)

    entry_session, entry_attachment = attach_fill_to_session(open_dt)
    exit_session, exit_attachment = attach_fill_to_session(close_dt)
    if exit_session < entry_session:
        exit_session = entry_session
        exit_attachment = entry_attachment

    window = expand_session_window(
        entry_session,
        exit_session,
        before=context_before,
        after=context_after,
    )
    resolved_cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    bars_by_day = fetch_sessions_minute_bars(
        underlying,
        window,
        cache_dir=resolved_cache,
        api_key=api_key,
        throttle_seconds=throttle_seconds,
    )

    profiles: dict[date, MarketProfile] = {}
    for session in window:
        profile = build_market_profile(
            session,
            bars_by_day.get(session, []),
            period_minutes=period_minutes,
        )
        if profile is not None:
            profiles[session] = profile

    entry_profile = profiles.get(entry_session)
    exit_profile = profiles.get(exit_session)

    # Prior session relative to entry
    prior_candidates = [d for d in window if d < entry_session and d in profiles]
    prior_profile = profiles[prior_candidates[-1]] if prior_candidates else None

    entry_bars = bars_by_day.get(entry_session, [])
    exit_bars = bars_by_day.get(exit_session, [])

    if trade.instrument_type == "EQUITY":
        entry_px, entry_src = trade.open_price, "equity_fill"
        exit_px, exit_src = trade.price, "equity_fill"
    else:
        entry_px, entry_src = underlying_price_at(entry_bars, open_dt)
        exit_px, exit_src = underlying_price_at(exit_bars, close_dt)

    # Fallbacks if minute lookup failed
    if entry_px is None and entry_profile is not None:
        entry_px, entry_src = entry_profile.poc, "session_poc_fallback"
    if exit_px is None and exit_profile is not None:
        exit_px, exit_src = exit_profile.poc, "session_poc_fallback"

    if prior_profile is not None and entry_px is not None:
        entry_vs_prior_va = locate_price(prior_profile, entry_px)
    else:
        entry_vs_prior_va = "unknown"

    if entry_profile is not None and entry_px is not None:
        entry_vs_day_va = locate_price(entry_profile, entry_px)
        entry_vs_poc_pct = (entry_px - entry_profile.poc) / max(entry_profile.poc, 1e-9) * 100
        extreme = price_extreme_score(entry_profile, entry_px)
        ib_ctx = _ib_break_context(entry_profile, entry_px, trade.direction)
        day_third = (entry_profile.session_high - entry_profile.session_low) / 3
        lower_third = entry_profile.session_low + day_third
        upper_third = entry_profile.session_high - day_third
        short_bottom = trade.direction == "short" and (
            entry_px <= lower_third or entry_vs_day_va == "below_val"
        )
        long_top = trade.direction == "long" and (
            entry_px >= upper_third or entry_vs_day_va == "above_vah"
        )
        shape_tags = list(entry_profile.shape_tags)
    else:
        entry_vs_day_va = "unknown"
        entry_vs_poc_pct = 0.0
        extreme = 0.0
        ib_ctx = "unknown"
        short_bottom = False
        long_top = False
        shape_tags = []

    if exit_profile is not None and exit_px is not None:
        exit_vs_va = locate_price(exit_profile, exit_px)
        exit_vs_poc_pct = (exit_px - exit_profile.poc) / max(exit_profile.poc, 1e-9) * 100
    else:
        exit_vs_va = "unknown"
        exit_vs_poc_pct = 0.0

    # Gave back to value: winner that exited back inside VA after being outside
    gave_back = False
    if trade.pnl > 0 and entry_profile is not None and exit_profile is not None and exit_px is not None:
        if entry_session == exit_session:
            if entry_vs_day_va != "inside_va" and exit_vs_va == "inside_va":
                gave_back = True
        elif exit_vs_va == "inside_va" and entry_vs_day_va != "inside_va":
            gave_back = True

    hold_sessions = iter_sessions(entry_session, exit_session)
    intraday = entry_session == exit_session

    score, rule_hits = _deterministic_score_and_hits(
        direction=trade.direction,
        entry_vs_prior_va=entry_vs_prior_va,
        entry_vs_day_va=entry_vs_day_va,
        entry_extreme_score=extreme,
        short_bottom_flag=short_bottom,
        long_top_flag=long_top,
        ib_break_context=ib_ctx,
        exit_vs_va=exit_vs_va,
        gave_back_to_value=gave_back,
    )

    features = TpoFeatures(
        entry_vs_prior_va=entry_vs_prior_va,
        entry_vs_day_va=entry_vs_day_va,
        entry_vs_poc_pct=round(entry_vs_poc_pct, 4),
        entry_extreme_score=round(extreme, 4),
        short_bottom_flag=short_bottom,
        long_top_flag=long_top,
        ib_break_context=ib_ctx,
        exit_vs_va=exit_vs_va,
        exit_vs_poc_pct=round(exit_vs_poc_pct, 4),
        gave_back_to_value=gave_back,
        hold_session_count=len(hold_sessions),
        profile_shape_tags=shape_tags,
        intraday_round_trip=intraday,
        entry_session_attachment=entry_attachment,
        exit_session_attachment=exit_attachment,
        entry_price_source=entry_src,
        exit_price_source=exit_src,
        deterministic_score=round(score, 2),
        rule_hits=rule_hits,
    )

    context = build_context_summary([profiles[d] for d in window if d in profiles])
    entry_summary = entry_profile.to_summary() if entry_profile else None
    exit_summary = exit_profile.to_summary() if exit_profile else None

    return features, entry_summary, exit_summary, context, entry_px, exit_px, profiles
