from __future__ import annotations

import math
import statistics
import webbrowser
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, List, Sequence

from .daily_timeline import render_day_detail, render_timeline_page
from .display_common import (
    describe_contract,
    describe_contract_timing,
    extract_underlying_symbol,
    format_currency,
)
from .symbol_pnl import analyze_symbols, compute_symbol_avg_rr, render_contract_pnl_chart
from .trade_review import analyze_trade

if TYPE_CHECKING:
    from .parse_orders import DayPnL, RealizedTrade
    from .tpo.schema import TpoGradeRecord, TpoGradesDocument


def render_symbol_trade_breakdown(
    symbol: str,
    trades: Sequence[RealizedTrade],
    *,
    tpo_grades: "TpoGradesDocument | None" = None,
) -> str:
    from .tpo.render import grade_badge
    from .tpo.schema import find_grade_for_trade

    total_pnl = sum(trade.pnl for trade in trades)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl < 0)
    flats = len(trades) - wins - losses

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(f"Trade Breakdown - {symbol}")
    lines.append(f"Trades: {len(trades)}")
    lines.append(f"Net PnL: {format_currency(total_pnl)}")
    lines.append(f"Wins: {wins} | Losses: {losses} | Flats: {flats}")
    lines.append("-" * 72)
    for index, trade in enumerate(_sort_symbol_trade_list(trades), start=1):
        badge = grade_badge(find_grade_for_trade(tpo_grades, trade))
        badge_suffix = f" {badge}" if badge else ""
        lines.append("")
        lines.append(f"[{index:03d}] {describe_contract(trade.symbol)}{badge_suffix}")
        lines.append(f"  Direction : {trade.direction}")
        lines.append(f"  Quantity  : {trade.quantity:g}")
        lines.append(f"  Open      : {trade.open_date.isoformat()} @ {trade.open_price:.2f}")
        lines.append(f"  Close     : {trade.trade_date.isoformat()} @ {trade.price:.2f}")
        timing_detail = describe_contract_timing(trade.symbol, trade.open_date)
        if timing_detail:
            lines.append(f"  {timing_detail}")
        lines.append(f"  PnL       : {format_currency(trade.pnl)}")
        lines.append("  " + "-" * 66)
    lines.append("")
    lines.append("=" * 72)
    lines.append(
        "Navigation: [B] Back | [R] Date range | [N] Next symbol | [P] Previous symbol | "
        "[F] Filter symbol | [K] Kelly | [A] Analyze trade | [G] Grade trade | [Q] Quit"
    )
    return "\n".join(lines)


def render_all_trades(
    trades: Sequence[RealizedTrade],
    *,
    tpo_grades: "TpoGradesDocument | None" = None,
) -> str:
    from .tpo.render import grade_badge
    from .tpo.schema import find_grade_for_trade

    total_pnl = sum(trade.pnl for trade in trades)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl < 0)
    flats = len(trades) - wins - losses

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("All Trades")
    lines.append(f"Trades: {len(trades)}")
    lines.append(f"Net PnL: {format_currency(total_pnl)}")
    lines.append(f"Wins: {wins} | Losses: {losses} | Flats: {flats}")
    lines.append("-" * 72)
    for index, trade in enumerate(_sort_trade_list(trades), start=1):
        badge = grade_badge(find_grade_for_trade(tpo_grades, trade))
        badge_suffix = f" {badge}" if badge else ""
        lines.append("")
        lines.append(
            f"[{index:03d}] {extract_underlying_symbol(trade.symbol)} | "
            f"{describe_contract(trade.symbol)}{badge_suffix}"
        )
        lines.append(f"  Direction : {trade.direction}")
        lines.append(f"  Quantity  : {trade.quantity:g}")
        lines.append(f"  Open      : {trade.open_date.isoformat()} @ {trade.open_price:.2f}")
        lines.append(f"  Close     : {trade.trade_date.isoformat()} @ {trade.price:.2f}")
        timing_detail = describe_contract_timing(trade.symbol, trade.open_date)
        if timing_detail:
            lines.append(f"  {timing_detail}")
        lines.append(f"  PnL       : {format_currency(trade.pnl)}")
        lines.append("  " + "-" * 66)
    lines.append("")
    lines.append("=" * 72)
    lines.append(
        "Navigation: [B] Back | [R] Date range | [K] Kelly | [A] Analyze trade | "
        "[G] Grade trade | [Q] Quit"
    )
    return "\n".join(lines)


def render_kelly_breakdown(
    trades: Sequence[RealizedTrade],
    *,
    title: str = "Kelly Criterion Breakdown",
) -> str:
    rows: list[tuple[str, Sequence[RealizedTrade]]] = [("ALL", trades)]
    trades_by_option_type: dict[str, list[RealizedTrade]] = defaultdict(list)
    trades_by_symbol: dict[str, list[RealizedTrade]] = defaultdict(list)
    for trade in trades:
        option_type = _trade_option_type(trade)
        if option_type in {"CALL", "PUT"}:
            trades_by_option_type[option_type].append(trade)
        trades_by_symbol[_trade_underlying(trade)].append(trade)
    rows.extend(
        (option_type, trades_by_option_type[option_type])
        for option_type in ("CALL", "PUT")
        if trades_by_option_type.get(option_type)
    )
    rows.extend(
        sorted(
            trades_by_symbol.items(),
            key=lambda item: sum(trade.pnl for trade in item[1]),
            reverse=True,
        )
    )

    lines: List[str] = []
    lines.append("=" * 118)
    lines.append(title)
    lines.append("Kelly = W - ((1 - W) / R), where W = win rate and R = average win / average loss")
    lines.append("-" * 118)
    lines.append(
        f"{'Symbol':<10} {'Trades':>6} {'Wins':>5} {'Loss':>5} {'Flat':>5} "
        f"{'Win %':>8} {'Avg Win':>12} {'Avg Loss':>12} {'R':>8} "
        f"{'Exp/Trade':>12} {'Kelly':>9} {'Half':>9} {'Net PnL':>12}"
    )
    lines.append("-" * 118)

    for symbol, symbol_trades in rows:
        metrics = _kelly_metrics(symbol_trades)
        lines.append(
            f"{symbol[:10]:<10} {metrics['trades']:>6.0f} {metrics['wins']:>5.0f} "
            f"{metrics['losses']:>5.0f} {metrics['flats']:>5.0f} "
            f"{_format_rate(metrics['win_rate']):>8} "
            f"{format_currency(metrics['avg_win']):>12} "
            f"{format_currency(-metrics['avg_loss']):>12} "
            f"{_format_ratio(metrics['payoff_ratio']):>8} "
            f"{format_currency(metrics['expectancy']):>12} "
            f"{_format_rate(metrics['kelly']):>9} "
            f"{_format_rate(metrics['half_kelly']):>9} "
            f"{format_currency(metrics['net_pnl']):>12}"
        )

    lines.append("-" * 118)
    lines.append("Avg Loss is shown as a negative dollar value for readability. Kelly is a sizing model, not a risk cap.")
    lines.append("=" * 118)
    return "\n".join(lines)


def run_interactive_report(
    day_entries: Sequence[DayPnL],
    realized_trades: Sequence[RealizedTrade],
    symbol_chart: str | None = None,
    tpo_grades: "TpoGradesDocument | None" = None,
) -> None:
    if not day_entries:
        print("No realized trades available to display.")
        return

    all_day_entries = list(day_entries)
    all_realized_trades = list(realized_trades)
    visible_day_entries = list(day_entries)
    visible_realized_trades = list(realized_trades)
    trades_by_symbol, symbol_order, current_symbol_chart = _build_symbol_context(
        visible_realized_trades,
        fallback_chart=symbol_chart,
    )
    grades_doc = tpo_grades
    if grades_doc is not None:
        print(f"Loaded {len(grades_doc.trades)} TPO grades for interactive review.")

    page = 0
    page_size = 20
    view_mode = "timeline"
    selected_index = 0
    previous_view = "timeline"
    selected_symbol: str | None = None
    selected_symbol_index = -1
    timeline_filter_label: str | None = None

    while True:
        total_days = len(visible_day_entries)
        total_pages = max(1, math.ceil(total_days / page_size)) if total_days else 1
        if total_days:
            page = min(page, total_pages - 1)
            selected_index = min(selected_index, total_days - 1)
        else:
            page = 0
            selected_index = 0

        if view_mode == "timeline":
            print(
                render_timeline_page(
                    visible_day_entries,
                    page,
                    page_size,
                    filter_label=timeline_filter_label,
                )
            )
            command = input("Command: ").strip().lower()
            if not command:
                continue
            if command == "q":
                break
            if command == "n":
                page = (page + 1) % total_pages
                continue
            if command == "p":
                page = (page - 1) % total_pages
                continue
            if command == "s":
                if current_symbol_chart:
                    previous_view = "timeline"
                    view_mode = "symbol"
                else:
                    print("Symbol PnL chart unavailable.")
                continue
            if command == "k":
                _show_kelly_breakdown(visible_realized_trades)
                continue
            if command == "u":
                if grades_doc is None or not grades_doc.trades:
                    print("No TPO grades loaded. Run trading-tpo-grade or use [G] on a trade.")
                    input("Press Enter to continue...")
                else:
                    from .tpo.render import summarize_quality_buckets

                    print(summarize_quality_buckets(grades_doc.trades))
                    input("Press Enter to continue...")
                continue
            if command == "t":
                previous_view = "timeline"
                view_mode = "all-trades"
                continue
            if command == "r":
                (
                    visible_day_entries,
                    visible_realized_trades,
                    timeline_filter_label,
                ) = _prompt_for_global_date_filter(all_day_entries, all_realized_trades)
                trades_by_symbol, symbol_order, current_symbol_chart = _build_symbol_context(
                    visible_realized_trades,
                    fallback_chart=symbol_chart,
                )
                if selected_symbol and selected_symbol not in trades_by_symbol:
                    selected_symbol = None
                    selected_symbol_index = -1
                    if view_mode == "symbol-detail":
                        view_mode = "symbol"
                page = 0
                selected_index = 0
                continue
            if command.isdigit():
                idx = int(command) - 1
                if 0 <= idx < total_days:
                    selected_index = idx
                    view_mode = "detail"
                else:
                    print(f"Invalid day number: {command}")
                continue
            print(f"Unknown command: {command}")
        elif view_mode == "detail":
            if not visible_day_entries:
                print("No timeline entries match the current filter.")
                input("Press Enter to continue...")
                view_mode = "timeline"
                continue
            print(render_day_detail(visible_day_entries, selected_index))
            command = input("Command: ").strip().lower()
            if not command:
                continue
            if command == "q":
                break
            if command == "b":
                view_mode = "timeline"
                continue
            if command == "s":
                if current_symbol_chart:
                    previous_view = "detail"
                    view_mode = "symbol"
                else:
                    print("Symbol PnL chart unavailable.")
                continue
            if command == "k":
                selected_day = datetime.strptime(visible_day_entries[selected_index].date_label, "%Y-%m-%d").date()
                day_trades = [trade for trade in visible_realized_trades if trade.trade_date == selected_day]
                _show_kelly_breakdown(day_trades, title=f"Kelly Criterion Breakdown - {selected_day.isoformat()}")
                continue
            if command == "u":
                if grades_doc is None or not grades_doc.trades:
                    print("No TPO grades loaded. Run trading-tpo-grade or use [G] on a trade.")
                else:
                    from .tpo.render import summarize_quality_buckets

                    print(summarize_quality_buckets(grades_doc.trades))
                input("Press Enter to continue...")
                continue
            if command == "t":
                previous_view = "detail"
                view_mode = "all-trades"
                continue
            if command == "r":
                (
                    visible_day_entries,
                    visible_realized_trades,
                    timeline_filter_label,
                ) = _prompt_for_global_date_filter(all_day_entries, all_realized_trades)
                trades_by_symbol, symbol_order, current_symbol_chart = _build_symbol_context(
                    visible_realized_trades,
                    fallback_chart=symbol_chart,
                )
                page = 0
                selected_index = 0
                if selected_symbol and selected_symbol not in trades_by_symbol:
                    selected_symbol = None
                    selected_symbol_index = -1
                view_mode = "timeline"
                continue
            if command == "n":
                selected_index = (selected_index + 1) % total_days
                continue
            if command == "p":
                selected_index = (selected_index - 1) % total_days
                continue
            print(f"Unknown command: {command}")
        else:
            if view_mode == "symbol":
                print("=" * 72)
                print("Symbol PnL Chart")
                print(current_symbol_chart or "No data available.")
                print("=" * 72)
                print("Navigation: [B] Back | [F] Filter symbol | [R] Date range | [K] Kelly | [T] Profitable timeline | [Q] Quit")
                command = input("Command: ").strip().lower()
                if not command:
                    continue
                if command == "q":
                    break
                if command == "b":
                    view_mode = previous_view
                    continue
                if command == "f":
                    symbol_input = input("Symbol: ").strip().upper()
                    if not symbol_input:
                        continue
                    if symbol_input not in trades_by_symbol:
                        print(f"No trades found for symbol: {symbol_input}")
                        continue
                    selected_symbol = symbol_input
                    selected_symbol_index = symbol_order.index(symbol_input)
                    previous_view = "symbol"
                    view_mode = "symbol-detail"
                    continue
                if command == "k":
                    _show_kelly_breakdown(visible_realized_trades)
                    continue
                if command == "t":
                    previous_view = "symbol"
                    view_mode = "all-trades"
                    continue
                if command == "r":
                    (
                        visible_day_entries,
                        visible_realized_trades,
                        timeline_filter_label,
                    ) = _prompt_for_global_date_filter(all_day_entries, all_realized_trades)
                    trades_by_symbol, symbol_order, current_symbol_chart = _build_symbol_context(
                        visible_realized_trades,
                        fallback_chart=symbol_chart,
                    )
                    page = 0
                    selected_index = 0
                    if selected_symbol and selected_symbol not in trades_by_symbol:
                        selected_symbol = None
                        selected_symbol_index = -1
                    continue
                print(f"Unknown command: {command}")
            elif view_mode == "symbol-detail":
                current_symbol_trades = trades_by_symbol.get(selected_symbol or "", [])
                print(
                    render_symbol_trade_breakdown(
                        selected_symbol or "",
                        current_symbol_trades,
                        tpo_grades=grades_doc,
                    )
                )
                command = input("Command: ").strip().lower()
                if not command:
                    continue
                if command == "q":
                    break
                if command == "b":
                    view_mode = previous_view
                    continue
                if command == "f":
                    symbol_input = input("Symbol: ").strip().upper()
                    if not symbol_input:
                        continue
                    if symbol_input not in trades_by_symbol:
                        print(f"No trades found for symbol: {symbol_input}")
                        continue
                    selected_symbol = symbol_input
                    selected_symbol_index = symbol_order.index(symbol_input)
                    continue
                if command == "r":
                    (
                        visible_day_entries,
                        visible_realized_trades,
                        timeline_filter_label,
                    ) = _prompt_for_global_date_filter(all_day_entries, all_realized_trades)
                    trades_by_symbol, symbol_order, current_symbol_chart = _build_symbol_context(
                        visible_realized_trades,
                        fallback_chart=symbol_chart,
                    )
                    page = 0
                    selected_index = 0
                    if selected_symbol and selected_symbol not in trades_by_symbol:
                        selected_symbol = None
                        selected_symbol_index = -1
                        view_mode = "symbol"
                    continue
                if command == "n":
                    if not symbol_order:
                        continue
                    selected_symbol_index = (selected_symbol_index + 1) % len(symbol_order)
                    selected_symbol = symbol_order[selected_symbol_index]
                    continue
                if command == "p":
                    if not symbol_order:
                        continue
                    selected_symbol_index = (selected_symbol_index - 1) % len(symbol_order)
                    selected_symbol = symbol_order[selected_symbol_index]
                    continue
                if command == "k":
                    _show_kelly_breakdown(
                        current_symbol_trades,
                        title=f"Kelly Criterion Breakdown - {selected_symbol or ''}",
                    )
                    continue
                if command == "a":
                    try:
                        _analyze_trade_from_list(current_symbol_trades, sorter=_sort_symbol_trade_list)
                    except Exception as exc:
                        print(exc)
                        input("Press Enter to continue...")
                    continue
                if command == "g":
                    try:
                        grades_doc = _grade_trade_from_list(
                            current_symbol_trades,
                            sorter=_sort_symbol_trade_list,
                            tpo_grades=grades_doc,
                        )
                    except Exception as exc:
                        print(exc)
                        input("Press Enter to continue...")
                    continue
                print(f"Unknown command: {command}")
            else:
                print(render_all_trades(visible_realized_trades, tpo_grades=grades_doc))
                command = input("Command: ").strip().lower()
                if not command:
                    continue
                if command == "q":
                    break
                if command == "b":
                    view_mode = previous_view
                    continue
                if command == "r":
                    (
                        visible_day_entries,
                        visible_realized_trades,
                        timeline_filter_label,
                    ) = _prompt_for_global_date_filter(all_day_entries, all_realized_trades)
                    trades_by_symbol, symbol_order, current_symbol_chart = _build_symbol_context(
                        visible_realized_trades,
                        fallback_chart=symbol_chart,
                    )
                    page = 0
                    selected_index = 0
                    continue
                if command == "k":
                    _show_kelly_breakdown(visible_realized_trades)
                    continue
                if command == "a":
                    try:
                        _analyze_trade_from_list(visible_realized_trades, sorter=_sort_trade_list)
                    except Exception as exc:
                        print(exc)
                        input("Press Enter to continue...")
                    continue
                if command == "g":
                    try:
                        grades_doc = _grade_trade_from_list(
                            visible_realized_trades,
                            sorter=_sort_trade_list,
                            tpo_grades=grades_doc,
                        )
                    except Exception as exc:
                        print(exc)
                        input("Press Enter to continue...")
                    continue
                print(f"Unknown command: {command}")


def _grade_trade_from_list(
    trades: Sequence[RealizedTrade],
    *,
    sorter,
    tpo_grades: "TpoGradesDocument | None" = None,
) -> "TpoGradesDocument | None":
    from .export_tpo_grades import grade_realized_trade
    from .tpo.grade import get_grade_api_key
    from .tpo.render import build_tpo_plotly_chart, render_grade_console
    from .tpo.schema import TpoGradesDocument, find_grade_for_trade

    if not trades:
        print("No trades available to grade.")
        return tpo_grades

    selection = input("Trade #: ").strip()
    if not selection:
        return tpo_grades
    if not selection.isdigit():
        print(f"Invalid trade number: {selection}")
        return tpo_grades

    ordered_trades = sorter(trades)
    trade_index = int(selection) - 1
    if trade_index < 0 or trade_index >= len(ordered_trades):
        print(f"Trade number out of range: {selection}")
        input("Press Enter to continue...")
        return tpo_grades

    trade = ordered_trades[trade_index]
    cached = find_grade_for_trade(tpo_grades, trade)
    record = cached
    if record is None:
        use_llm = False
        if get_grade_api_key():
            answer = input("LLM API key detected (DeepSeek/OpenAI). Run LLM grade? [y/N]: ").strip().lower()
            use_llm = answer in {"y", "yes"}
        print("Building underlying TPO features (Polygon minute bars)...")
        record = grade_realized_trade(trade, use_llm=use_llm)
        if tpo_grades is None:
            tpo_grades = TpoGradesDocument(
                metadata={"source": "interactive", "trade_count": 1},
                trades=[record],
            )
        else:
            tpo_grades.trades = [
                existing
                for existing in tpo_grades.trades
                if existing.trade_id != record.trade_id
            ] + [record]
    else:
        print("Using cached TPO grade from loaded JSON.")

    print(render_grade_console(record))
    nav = input(
        "Press Enter to return, 'o' to open Plotly TPO chart, 'r' to regrade live: "
    ).strip().lower()
    if nav == "o":
        path = build_tpo_plotly_chart(record)
        webbrowser.open(path.resolve().as_uri())
        print(f"Opened TPO chart: {path}")
        input("Press Enter to continue...")
    elif nav == "r":
        use_llm = False
        if get_grade_api_key():
            answer = input("Run LLM grade on regrade? [y/N]: ").strip().lower()
            use_llm = answer in {"y", "yes"}
        print("Rebuilding TPO features...")
        record = grade_realized_trade(trade, use_llm=use_llm)
        if tpo_grades is None:
            tpo_grades = TpoGradesDocument(
                metadata={"source": "interactive", "trade_count": 1},
                trades=[record],
            )
        else:
            tpo_grades.trades = [
                existing
                for existing in tpo_grades.trades
                if existing.trade_id != record.trade_id
            ] + [record]
        print(render_grade_console(record))
        input("Press Enter to continue...")
    return tpo_grades


def _analyze_trade_from_list(
    trades: Sequence[RealizedTrade],
    *,
    sorter,
) -> None:
    if not trades:
        print("No trades available to analyze.")
        return

    selection = input("Trade #: ").strip()
    if not selection:
        return
    if not selection.isdigit():
        print(f"Invalid trade number: {selection}")
        return

    ordered_trades = sorter(trades)
    trade_index = int(selection) - 1
    if trade_index < 0 or trade_index >= len(ordered_trades):
        print(f"Trade number out of range: {selection}")
        input("Press Enter to continue...")
        return

    while True:
        trade = ordered_trades[trade_index]
        print("Fetching market data and building trade analysis...")
        output_path = analyze_trade(trade)
        print(f"Opened trade analysis: {output_path}")
        print(f"[{trade_index + 1:03d}/{len(ordered_trades):03d}] {extract_underlying_symbol(trade.symbol)} | {describe_contract(trade.symbol)}")
        print(
            f"Date: {trade.trade_date.isoformat()} | Open: {trade.open_date.isoformat()} | "
            f"Contracts: {trade.quantity:g} | PnL: ${trade.pnl:,.2f}"
        )
        open_time_label = _format_trade_time_label(trade.open_datetime)
        close_time_label = _format_trade_time_label(trade.trade_datetime)
        if open_time_label or close_time_label:
            print(
                f"Opened at: {open_time_label or 'unknown'} | "
                f"Closed at: {close_time_label or 'unknown'}"
            )
        timing_detail = describe_contract_timing(trade.symbol, trade.open_date)
        if timing_detail:
            print(f"Timing: {timing_detail}")
        navigation = input(
            "Trade loaded. Press Enter to return, 'a' for previous trade, or 'd' for next trade: "
        ).strip().lower()
        if not navigation:
            return
        if navigation == "a":
            trade_index = (trade_index - 1) % len(ordered_trades)
            continue
        if navigation == "d":
            trade_index = (trade_index + 1) % len(ordered_trades)
            continue
        print(f"Unknown command: {navigation}")


def _show_kelly_breakdown(
    trades: Sequence[RealizedTrade],
    *,
    title: str = "Kelly Criterion Breakdown",
) -> None:
    print(render_kelly_breakdown(trades, title=title))
    input("Press Enter to continue...")


def _kelly_metrics(trades: Sequence[RealizedTrade]) -> dict[str, float]:
    pnl_values = [trade.pnl for trade in trades]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    trades_count = len(pnl_values)
    wins_count = len(wins)
    losses_count = len(losses)
    flats_count = trades_count - wins_count - losses_count
    win_rate = wins_count / trades_count if trades_count else 0.0
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = abs(statistics.mean(losses)) if losses else 0.0
    if avg_loss > 0:
        payoff_ratio = avg_win / avg_loss if avg_win > 0 else 0.0
    elif avg_win > 0:
        payoff_ratio = math.inf
    else:
        payoff_ratio = 0.0
    expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)
    kelly: float | None = None
    if avg_loss > 0 and payoff_ratio > 0:
        kelly = win_rate - ((1.0 - win_rate) / payoff_ratio)
    half_kelly = kelly / 2.0 if kelly is not None else None
    return {
        "trades": float(trades_count),
        "wins": float(wins_count),
        "losses": float(losses_count),
        "flats": float(flats_count),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "expectancy": expectancy,
        "kelly": kelly,
        "half_kelly": half_kelly,
        "net_pnl": sum(pnl_values),
    }


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _format_ratio(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def _trade_underlying(trade: RealizedTrade) -> str:
    underlying = getattr(trade, "underlying", "")
    return underlying or extract_underlying_symbol(trade.symbol)


def _trade_option_type(trade: RealizedTrade) -> str:
    option_type = getattr(trade, "option_type", "")
    if option_type:
        return option_type
    if " Call " in describe_contract(trade.symbol):
        return "CALL"
    if " Put " in describe_contract(trade.symbol):
        return "PUT"
    return "UNKNOWN"


def _sort_trade_list(trades: Sequence[RealizedTrade]) -> list[RealizedTrade]:
    return sorted(
        trades,
        key=lambda item: (
            item.open_date.isoformat(),
            item.trade_date.isoformat(),
            extract_underlying_symbol(item.symbol),
            item.symbol,
            item.pnl,
        ),
    )


def _sort_symbol_trade_list(trades: Sequence[RealizedTrade]) -> list[RealizedTrade]:
    return sorted(
        trades,
        key=lambda item: (
            item.trade_date.isoformat(),
            item.open_date.isoformat(),
            item.symbol,
            item.pnl,
        ),
    )


def _format_trade_time_label(value: datetime | None) -> str | None:
    if value is None:
        return None
    return f"{value.strftime('%H:%M:%S')} ({_session_bucket(value)})"


def _session_bucket(value: datetime) -> str:
    current = value.time()
    first_hour_end = time(10, 30)
    last_hour_start = time(15, 0)
    if current < first_hour_end:
        return "first hour"
    if current >= last_hour_start:
        return "last hour"
    return "middle"


def _prompt_for_global_date_filter(
    day_entries: Sequence[DayPnL],
    realized_trades: Sequence[RealizedTrade],
) -> tuple[list[DayPnL], list[RealizedTrade], str | None]:
    start_text = input("Start date YYYY-MM-DD (blank to clear filter): ").strip()
    if not start_text:
        return list(day_entries), list(realized_trades), None

    try:
        start_date = datetime.strptime(start_text, "%Y-%m-%d").date()
    except ValueError:
        print(f"Invalid start date: {start_text}")
        input("Press Enter to continue...")
        return list(day_entries), list(realized_trades), None

    end_text = input("End date YYYY-MM-DD (blank to use start date): ").strip()
    if end_text:
        try:
            end_date = datetime.strptime(end_text, "%Y-%m-%d").date()
        except ValueError:
            print(f"Invalid end date: {end_text}")
            input("Press Enter to continue...")
            return list(day_entries), list(realized_trades), None
    else:
        end_date = start_date

    if start_date > end_date:
        print("Start date must be on or before end date.")
        input("Press Enter to continue...")
        return list(day_entries), list(realized_trades), None

    filtered_entries = [
        entry
        for entry in day_entries
        if start_date <= datetime.strptime(entry.date_label, "%Y-%m-%d").date() <= end_date
    ]
    filtered_trades = [
        trade
        for trade in realized_trades
        if start_date <= trade.trade_date <= end_date
    ]
    filter_label = (
        start_date.isoformat()
        if start_date == end_date
        else f"{start_date.isoformat()} to {end_date.isoformat()}"
    )
    if not filtered_entries and not filtered_trades:
        print(f"No timeline entries found for {filter_label}.")
        input("Press Enter to continue...")
    return filtered_entries, filtered_trades, filter_label


def _build_symbol_context(
    trades: Sequence[RealizedTrade],
    *,
    fallback_chart: str | None = None,
) -> tuple[dict[str, List[RealizedTrade]], list[str], str | None]:
    trades_by_symbol: dict[str, List[RealizedTrade]] = defaultdict(list)
    for trade in trades:
        trades_by_symbol[_trade_underlying(trade)].append(trade)
    symbol_order = sorted(trades_by_symbol.keys())
    if not trades:
        return trades_by_symbol, symbol_order, None
    contract_pnl: dict[str, float] = {}
    for trade in trades:
        contract_pnl[trade.symbol] = contract_pnl.get(trade.symbol, 0.0) + trade.pnl
    if not contract_pnl:
        return trades_by_symbol, symbol_order, fallback_chart
    symbol_pnl = analyze_symbols(contract_pnl)
    symbol_rr = compute_symbol_avg_rr(trades)
    try:
        chart_text = render_contract_pnl_chart(symbol_pnl, symbol_rr) if symbol_pnl else fallback_chart
    except RuntimeError:
        chart_text = fallback_chart
    return trades_by_symbol, symbol_order, chart_text
