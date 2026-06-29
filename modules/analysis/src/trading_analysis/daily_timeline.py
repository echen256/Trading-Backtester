from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING, List, Sequence

from .display_common import describe_contract, describe_contract_timing, format_currency

if TYPE_CHECKING:
    from .parse_orders import DayPnL, RealizedTrade


def summarize_daily_realized_pnl(trades: Sequence[RealizedTrade]) -> List[DayPnL]:
    if not trades:
        return []

    from .parse_orders import DayPnL

    summary: dict[str, dict[str, dict[str, object]]] = defaultdict(
        lambda: {
            "Winners": {"total": 0.0, "lines": []},
            "Losers": {"total": 0.0, "lines": []},
        }
    )

    for trade in trades:
        date_key = trade.trade_date.isoformat()
        bucket_name = "Winners" if trade.pnl >= 0 else "Losers"
        bucket = summary[date_key][bucket_name]
        bucket["total"] = bucket.get("total", 0.0) + trade.pnl
        summary_line = f"{describe_contract(trade.symbol)}: {trade.quantity:g} @ {trade.price:.2f} -> {trade.pnl:,.2f}"
        timing_detail = describe_contract_timing(trade.symbol, trade.open_date)
        initiated_line = f"Initiated: {trade.open_date.isoformat()}"
        if timing_detail:
            initiated_line = f"{initiated_line} | {timing_detail}"
        bucket.setdefault("lines", []).append((summary_line, initiated_line))

    day_entries: List[DayPnL] = []
    for date_label in sorted(summary.keys()):
        winners_bucket = summary[date_label]["Winners"]
        losers_bucket = summary[date_label]["Losers"]
        day_entries.append(
            DayPnL(
                date_label=date_label,
                winners_total=float(winners_bucket.get("total", 0.0)),
                losers_total=float(losers_bucket.get("total", 0.0)),
                winners_lines=list(winners_bucket.get("lines", [])),
                losers_lines=list(losers_bucket.get("lines", [])),
            )
        )
    return day_entries


def render_timeline_page(
    day_entries: Sequence[DayPnL],
    page: int,
    page_size: int,
    *,
    filter_label: str | None = None,
) -> str:
    total_days = len(day_entries)
    if total_days == 0:
        return "No realized trades available."

    total_pages = max(1, math.ceil(total_days / page_size))
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = min(start + page_size, total_days)
    max_abs = max(
        (max(abs(day.winners_total), abs(day.losers_total)) for day in day_entries),
        default=0,
    )
    max_abs = max_abs or 1.0

    lines: List[str] = []
    lines.append(f"Daily Realized PnL Timeline (page {page + 1}/{total_pages})")
    if filter_label:
        lines.append(f"Filter: {filter_label}")
    lines.append("-" * 72)
    for global_index in range(start, end):
        day = day_entries[global_index]
        label = f"[{global_index + 1:03d}] {day.date_label}"
        winners_bar = _build_bar(day.winners_total, max_abs)
        losers_bar = _build_bar(day.losers_total, max_abs)
        lines.append(label)
        lines.append(f"  Winners {format_currency(day.winners_total):>12}: {winners_bar or '(flat)'}")
        lines.append(f"  Losers  {format_currency(day.losers_total):>12}: {losers_bar or '(flat)'}")
    lines.append("")
    lines.append(
        "Navigation: [Enter day #] View | [R] Date range | [N] Next page | [P] Previous page | [S] Symbol PnL | [K] Kelly | [T] Profitable timeline | [Q] Quit"
    )
    return "\n".join(lines)


def render_day_detail(day_entries: Sequence[DayPnL], index: int) -> str:
    total_days = len(day_entries)
    day = day_entries[index]
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(f"Day {index + 1:03d}/{total_days} - {day.date_label}")
    net = day.winners_total + day.losers_total
    lines.append(f"Net PnL: {format_currency(net)}")
    lines.append(f"Winners Total: {format_currency(day.winners_total)}")
    lines.append(f"Losers Total: {format_currency(day.losers_total)}")
    lines.append("-- Winners --")
    if day.winners_lines:
        for summary, initiated in day.winners_lines:
            lines.append(f"  + {summary}")
            lines.append(f"    {initiated}")
    else:
        lines.append("  + None")
    lines.append("-- Losers --")
    if day.losers_lines:
        for summary, initiated in day.losers_lines:
            lines.append(f"  - {summary}")
            lines.append(f"    {initiated}")
    else:
        lines.append("  - None")
    lines.append("=" * 72)
    lines.append("Navigation: [B] Back | [R] Date range | [N] Next day | [P] Previous day | [S] Symbol PnL | [K] Kelly | [T] Profitable timeline | [Q] Quit")
    return "\n".join(lines)


def _build_bar(value: float, max_abs_value: float, width: int = 32) -> str:
    if max_abs_value <= 0 or value == 0:
        return ""
    units = max(1, int((abs(value) / max_abs_value) * width))
    char = "+" if value >= 0 else "-"
    return char * units
