"""ASCII and Plotly rendering for TPO profiles and grade summaries."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence

from .schema import TpoGradeRecord


def render_grade_console(record: TpoGradeRecord) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"TPO Grade — {record.underlying} | {record.symbol}")
    lines.append(
        f"Direction: {record.direction}  Qty: {record.quantity:g}  "
        f"PnL: ${record.realized_pnl:,.2f}"
    )
    lines.append(
        f"Open: {record.open_datetime or record.open_date} @ {record.open_price:g}  "
        f"(underlying {record.underlying_entry_price})"
    )
    lines.append(
        f"Close: {record.close_datetime or record.close_date} @ {record.close_price:g}  "
        f"(underlying {record.underlying_exit_price})"
    )
    lines.append("-" * 72)

    features = record.features or {}
    grade = record.grade or {}
    score = grade.get("overall_score")
    if score is None:
        score = features.get("deterministic_score")
    quality = grade.get("execution_quality") or _quality_from_score(float(score or 0))
    lines.append(f"Score: {score}  Quality: {quality}  Status: {grade.get('status', 'n/a')}")
    rule_hits = grade.get("rule_hits") or features.get("rule_hits") or []
    if rule_hits:
        lines.append(f"Rule hits: {', '.join(str(r) for r in rule_hits)}")
    note = grade.get("corrective_note")
    if note:
        lines.append(f"Corrective: {note}")
    for key in ("what_went_wrong", "what_went_right"):
        items = grade.get(key) or []
        if items:
            lines.append(f"{key.replace('_', ' ').title()}:")
            for item in items:
                lines.append(f"  - {item}")

    lines.append("-" * 72)
    lines.append(
        f"Entry vs prior VA: {features.get('entry_vs_prior_va')} | "
        f"day VA: {features.get('entry_vs_day_va')} | "
        f"extreme: {features.get('entry_extreme_score')}"
    )
    lines.append(
        f"IB: {features.get('ib_break_context')} | Exit VA: {features.get('exit_vs_va')} | "
        f"Hold sessions: {features.get('hold_session_count')}"
    )
    flags = []
    if features.get("short_bottom_flag"):
        flags.append("SHORT_BOTTOM")
    if features.get("long_top_flag"):
        flags.append("LONG_TOP")
    if features.get("gave_back_to_value"):
        flags.append("GAVE_BACK_TO_VALUE")
    if features.get("intraday_round_trip"):
        flags.append("INTRADAY")
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")

    profiles = record.profiles or {}
    entry = profiles.get("entry_session") or {}
    exit_ = profiles.get("exit_session") or {}
    if entry.get("tpo_ascii"):
        lines.append("")
        lines.append("Entry session TPO:")
        lines.append(str(entry["tpo_ascii"]))
        if record.underlying_entry_price is not None:
            lines.append(f"  >> entry underlying mark: {record.underlying_entry_price:.2f}")
    if exit_ and exit_.get("date") != entry.get("date") and exit_.get("tpo_ascii"):
        lines.append("")
        lines.append("Exit session TPO:")
        lines.append(str(exit_["tpo_ascii"]))
        if record.underlying_exit_price is not None:
            lines.append(f"  >> exit underlying mark: {record.underlying_exit_price:.2f}")

    context = profiles.get("context_summary") or {}
    if context:
        lines.append("")
        lines.append(
            f"Context (±sessions): POC migration={context.get('poc_migration')}  "
            f"balance={context.get('balance_days')} trend={context.get('trend_days')}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)


def _quality_from_score(score: float) -> str:
    if score >= 75:
        return "good"
    if score >= 55:
        return "acceptable"
    if score >= 30:
        return "poor"
    return "catastrophic"


def grade_badge(record: TpoGradeRecord | None) -> str:
    if record is None:
        return ""
    grade = record.grade or {}
    features = record.features or {}
    quality = grade.get("execution_quality")
    score = grade.get("overall_score")
    if score is None:
        score = features.get("deterministic_score")
    if not quality:
        quality = _quality_from_score(float(score or 0))
    if score is None:
        return f"[{quality}]"
    return f"[{quality} {float(score):.0f}]"


def _parse_session_date(record: TpoGradeRecord) -> date | None:
    profiles = record.profiles or {}
    entry = profiles.get("entry_session") or {}
    raw = entry.get("date") or record.open_date
    if not raw:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _aggregate_candles(
    bars: Sequence[dict[str, object]],
    *,
    candle_minutes: int = 5,
) -> list[dict[str, object]]:
    """Aggregate RTH minute bars into N-minute OHLCV candles (NY session clock)."""
    from .bars import parse_bar_timestamp
    from .sessions import to_ny

    if candle_minutes <= 1:
        candles: list[dict[str, object]] = []
        for bar in bars:
            try:
                ts = parse_bar_timestamp(bar.get("t"))
                candles.append(
                    {
                        "t": to_ny(ts),
                        "o": float(bar["o"]),
                        "h": float(bar["h"]),
                        "l": float(bar["l"]),
                        "c": float(bar["c"]),
                    }
                )
            except (TypeError, ValueError, KeyError):
                continue
        return candles

    buckets: dict[datetime, dict[str, float | datetime]] = {}
    order: list[datetime] = []
    for bar in bars:
        try:
            ts = to_ny(parse_bar_timestamp(bar.get("t")))
            o = float(bar["o"])
            h = float(bar["h"])
            l = float(bar["l"])
            c = float(bar["c"])
        except (TypeError, ValueError, KeyError):
            continue
        # Floor to candle_minutes on the NY clock.
        minute = (ts.minute // candle_minutes) * candle_minutes
        key = ts.replace(minute=minute, second=0, microsecond=0)
        if key not in buckets:
            buckets[key] = {"t": key, "o": o, "h": h, "l": l, "c": c}
            order.append(key)
        else:
            bucket = buckets[key]
            bucket["h"] = max(float(bucket["h"]), h)
            bucket["l"] = min(float(bucket["l"]), l)
            bucket["c"] = c
    return [buckets[key] for key in order]


def _parse_mark_time(raw: str | None, fallback_date: str | None) -> datetime | None:
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    if fallback_date:
        try:
            return datetime.fromisoformat(f"{fallback_date[:10]}T16:00:00+00:00")
        except ValueError:
            return None
    return None


def build_tpo_plotly_chart(
    record: TpoGradeRecord,
    *,
    cache_dir: Path | None = None,
    candle_minutes: int = 5,
    tpo_width_fraction: float = 0.25,
) -> Path:
    """
    Session chart: candlesticks for the full RTH day (~75% width) with a
    Market Profile / TPO strip on the right (≤25% width), shared price axis.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from ..market_data import DEFAULT_UNDERLYING_MINUTE_CACHE_DIR, fetch_session_minute_bars
    from .bars import parse_bar_timestamp
    from .profile import build_market_profile
    from .sessions import to_ny

    profiles = record.profiles or {}
    entry = profiles.get("entry_session") or {}
    session = _parse_session_date(record)
    underlying = (record.underlying or "").upper()
    if session is None or not underlying:
        raise RuntimeError("Cannot build TPO chart: missing underlying or entry session date.")

    resolved_cache = Path(cache_dir) if cache_dir else DEFAULT_UNDERLYING_MINUTE_CACHE_DIR
    minute_bars = fetch_session_minute_bars(
        underlying,
        session,
        cache_dir=resolved_cache,
        throttle_seconds=0.0,
        force_refresh=False,
    )
    if not minute_bars:
        raise RuntimeError(
            f"No RTH minute bars for {underlying} {session.isoformat()} "
            f"(cache: {resolved_cache}). Re-run TPO grade / rescan first."
        )

    profile = build_market_profile(session, minute_bars, period_minutes=30)
    candles = _aggregate_candles(minute_bars, candle_minutes=candle_minutes)
    if not candles:
        raise RuntimeError(f"Could not build candles for {underlying} {session.isoformat()}.")

    tpo_frac = min(max(tpo_width_fraction, 0.15), 0.25)
    candle_frac = 1.0 - tpo_frac

    figure = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        column_widths=[candle_frac, tpo_frac],
        horizontal_spacing=0.02,
        subplot_titles=(
            f"{underlying} {session.isoformat()}  ({candle_minutes}m)",
            "TPO",
        ),
    )

    figure.add_trace(
        go.Candlestick(
            x=[c["t"] for c in candles],
            open=[c["o"] for c in candles],
            high=[c["h"] for c in candles],
            low=[c["l"] for c in candles],
            close=[c["c"] for c in candles],
            name=f"{candle_minutes}m",
            increasing_line_color="#2ca02c",
            decreasing_line_color="#d62728",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # Entry / exit marks on the candle pane.
    entry_dt = _parse_mark_time(record.open_datetime, record.open_date)
    exit_dt = _parse_mark_time(record.close_datetime, record.close_date)
    if entry_dt is not None and record.underlying_entry_price is not None:
        figure.add_trace(
            go.Scatter(
                x=[to_ny(entry_dt)],
                y=[float(record.underlying_entry_price)],
                mode="markers+text",
                name="Entry",
                marker={"symbol": "triangle-up", "size": 12, "color": "#2ca02c"},
                text=["Entry"],
                textposition="top center",
                showlegend=True,
            ),
            row=1,
            col=1,
        )
    if (
        exit_dt is not None
        and record.underlying_exit_price is not None
        and (record.open_date != record.close_date or record.underlying_exit_price != record.underlying_entry_price)
    ):
        # Only draw exit on this session chart when exit falls on the same session day.
        if to_ny(exit_dt).date() == session:
            figure.add_trace(
                go.Scatter(
                    x=[to_ny(exit_dt)],
                    y=[float(record.underlying_exit_price)],
                    mode="markers+text",
                    name="Exit",
                    marker={"symbol": "triangle-down", "size": 12, "color": "#d62728"},
                    text=["Exit"],
                    textposition="bottom center",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

    # Real TPO density from rebuilt profile (fallback to summary fields).
    if profile is not None and profile.tpo_counts:
        levels = sorted(profile.tpo_counts.keys())
        counts = [profile.tpo_counts[level] for level in levels]
        poc = profile.poc
        vah = profile.vah
        val = profile.val
        ib_high = profile.ib_high
        ib_low = profile.ib_low
        bracket = profile.bracket_size
    else:
        poc = float(entry.get("poc") or 0)
        vah = float(entry.get("vah") or 0)
        val = float(entry.get("val") or 0)
        ib_high = float(entry.get("ib_high") or 0)
        ib_low = float(entry.get("ib_low") or 0)
        bracket = float(entry.get("bracket_size") or 0.25)
        session_high = float(entry.get("session_high") or poc)
        session_low = float(entry.get("session_low") or poc)
        levels = []
        counts = []
        if bracket > 0 and session_high > session_low:
            level = session_low + bracket / 2
            while level <= session_high + 1e-9:
                dist = abs(level - poc) / max(session_high - session_low, 1e-9)
                levels.append(round(level, 4))
                counts.append(max(1, int(round((1 - dist) * 10))))
                level += bracket

    bar_colors = []
    for level in levels:
        if val <= level <= vah:
            bar_colors.append("#4C78A8")
        else:
            bar_colors.append("#9ecae1")

    if levels:
        figure.add_trace(
            go.Bar(
                y=levels,
                x=counts,
                orientation="h",
                name="TPO count",
                marker_color=bar_colors,
                showlegend=False,
                hovertemplate="Price %{y:.2f}<br>TPOs %{x}<extra></extra>",
            ),
            row=1,
            col=2,
        )

    # Shared level lines across both panes.
    level_specs = [
        ("POC", poc, "#F58518", "dash"),
        ("VAH", vah, "#54A24B", "dot"),
        ("VAL", val, "#54A24B", "dot"),
        ("IB high", ib_high, "#B279A2", "dot"),
        ("IB low", ib_low, "#B279A2", "dot"),
    ]
    for label, price, color, dash in level_specs:
        if not price:
            continue
        for col in (1, 2):
            figure.add_hline(
                y=float(price),
                line_dash=dash,
                line_color=color,
                line_width=1.5 if label == "POC" else 1,
                annotation_text=label if col == 2 else None,
                annotation_position="top left",
                row=1,
                col=col,
            )

    features = record.features or {}
    grade = record.grade or {}
    score = grade.get("overall_score")
    if score is None:
        score = features.get("deterministic_score")
    quality = grade.get("execution_quality") or _quality_from_score(float(score or 0))
    flags = []
    if features.get("short_bottom_flag"):
        flags.append("short@bottom")
    if features.get("long_top_flag"):
        flags.append("long@top")
    if features.get("entry_vs_day_va") == "inside" or "mid_range_entry" in (
        grade.get("rule_hits") or features.get("rule_hits") or []
    ):
        flags.append("mid-range")
    flag_text = f" · {', '.join(flags)}" if flags else ""

    figure.update_layout(
        title=(
            f"{record.underlying} {session.isoformat()} — {record.symbol}  "
            f"[{quality} {float(score or 0):.0f}]{flag_text}"
        ),
        template="plotly_white",
        height=720,
        margin={"l": 60, "r": 30, "t": 70, "b": 50},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        xaxis_rangeslider_visible=False,
        bargap=0.05,
    )
    figure.update_xaxes(title_text="Session time (NY)", row=1, col=1)
    figure.update_xaxes(title_text="TPO count", row=1, col=2)
    figure.update_yaxes(title_text="Price", row=1, col=1)
    figure.update_yaxes(showticklabels=False, row=1, col=2)

    output_dir = Path(tempfile.gettempdir()) / "trading-analysis" / "tpo"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"tpo-{record.trade_id}.html"
    figure.write_html(output_path, auto_open=False, include_plotlyjs="cdn")
    return output_path


def summarize_quality_buckets(records: Sequence[TpoGradeRecord]) -> str:
    from collections import Counter

    qualities: Counter[str] = Counter()
    scores: list[float] = []
    for record in records:
        grade = record.grade or {}
        features = record.features or {}
        quality = grade.get("execution_quality")
        score = grade.get("overall_score")
        if score is None:
            score = features.get("deterministic_score")
        if not quality:
            quality = _quality_from_score(float(score or 0))
        qualities[str(quality)] += 1
        if score is not None:
            scores.append(float(score))

    lines = ["TPO Execution Quality Buckets", "-" * 40]
    for key in ("good", "acceptable", "poor", "catastrophic"):
        lines.append(f"  {key:<14} {qualities.get(key, 0):>5}")
    other = sum(v for k, v in qualities.items() if k not in {"good", "acceptable", "poor", "catastrophic"})
    if other:
        lines.append(f"  {'other':<14} {other:>5}")
    if scores:
        lines.append(f"  avg score      {sum(scores) / len(scores):>5.1f}")
    lines.append(f"  total          {len(records):>5}")
    return "\n".join(lines)
