"""ASCII and Plotly rendering for TPO profiles and grade summaries."""

from __future__ import annotations

import tempfile
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


def build_tpo_plotly_chart(record: TpoGradeRecord) -> Path:
    """Horizontal Market Profile chart for entry session with entry/exit marks."""
    import plotly.graph_objects as go

    profiles = record.profiles or {}
    entry = profiles.get("entry_session") or {}
    ascii_block = str(entry.get("tpo_ascii") or "")
    # Rebuild a simple bar chart from summary levels if ascii present;
    # prefer structured fields.
    poc = float(entry.get("poc") or 0)
    vah = float(entry.get("vah") or 0)
    val = float(entry.get("val") or 0)
    session_high = float(entry.get("session_high") or poc)
    session_low = float(entry.get("session_low") or poc)
    bracket = float(entry.get("bracket_size") or 0.25)

    # Approximate histogram from high/low/POC when full brackets unavailable
    levels: list[float] = []
    counts: list[int] = []
    if bracket > 0 and session_high > session_low:
        level = session_low + bracket / 2
        while level <= session_high + 1e-9:
            # Triangular weight peaking at POC as a visual stand-in
            dist = abs(level - poc) / max(session_high - session_low, 1e-9)
            count = max(1, int(round((1 - dist) * 10)))
            levels.append(round(level, 4))
            counts.append(count)
            level += bracket

    figure = go.Figure()
    if levels:
        figure.add_trace(
            go.Bar(
                y=levels,
                x=counts,
                orientation="h",
                name="TPO density (approx)",
                marker_color="#4C78A8",
            )
        )
    for label, price, color in (
        ("POC", poc, "#F58518"),
        ("VAH", vah, "#54A24B"),
        ("VAL", val, "#54A24B"),
        ("Entry", record.underlying_entry_price, "#2ca02c"),
        ("Exit", record.underlying_exit_price, "#d62728"),
    ):
        if price is None:
            continue
        figure.add_hline(
            y=float(price),
            line_dash="dot" if label in {"POC", "VAH", "VAL"} else "solid",
            line_color=color,
            annotation_text=label,
            annotation_position="top right",
        )

    figure.update_layout(
        title=f"TPO {record.underlying} {entry.get('date', '')} — {record.symbol}",
        xaxis_title="Relative TPO density",
        yaxis_title="Price",
        template="plotly_white",
        height=700,
    )
    if ascii_block:
        figure.add_annotation(
            text="Full letter TPO available in CLI ASCII view",
            xref="paper",
            yref="paper",
            x=0,
            y=1.05,
            showarrow=False,
            align="left",
        )

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
