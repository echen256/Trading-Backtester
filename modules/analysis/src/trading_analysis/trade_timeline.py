from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, time
from typing import TYPE_CHECKING, List, Sequence

from .daily_timeline import render_day_detail, render_timeline_page
from .display_common import (
    describe_contract,
    describe_contract_timing,
    extract_underlying_symbol,
    format_currency,
)
from .trade_review import analyze_trade

if TYPE_CHECKING:
    from .parse_orders import DayPnL, RealizedTrade


def render_symbol_trade_breakdown(symbol: str, trades: Sequence[RealizedTrade]) -> str:
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
        lines.append("")
        lines.append(f"[{index:03d}] {describe_contract(trade.symbol)}")
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
    lines.append("Navigation: [B] Back | [N] Next symbol | [P] Previous symbol | [F] Filter symbol | [A] Analyze trade | [Q] Quit")
    return "\n".join(lines)


def render_all_trades(trades: Sequence[RealizedTrade]) -> str:
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
        lines.append("")
        lines.append(f"[{index:03d}] {extract_underlying_symbol(trade.symbol)} | {describe_contract(trade.symbol)}")
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
    lines.append("Navigation: [B] Back | [A] Analyze trade | [Q] Quit")
    return "\n".join(lines)


def run_interactive_report(
    day_entries: Sequence[DayPnL],
    realized_trades: Sequence[RealizedTrade],
    symbol_chart: str | None = None,
) -> None:
    if not day_entries:
        print("No realized trades available to display.")
        return

    all_day_entries = list(day_entries)
    visible_day_entries = list(day_entries)
    trades_by_symbol: dict[str, List[RealizedTrade]] = defaultdict(list)
    for trade in realized_trades:
        trades_by_symbol[extract_underlying_symbol(trade.symbol)].append(trade)

    page = 0
    page_size = 20
    view_mode = "symbol" if symbol_chart else "timeline"
    selected_index = 0
    previous_view = "timeline"
    selected_symbol: str | None = None
    symbol_order = sorted(trades_by_symbol.keys())
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
                if symbol_chart:
                    previous_view = "timeline"
                    view_mode = "symbol"
                else:
                    print("Symbol PnL chart unavailable.")
                continue
            if command == "t":
                previous_view = "timeline"
                view_mode = "all-trades"
                continue
            if command == "f":
                filtered_entries, filter_label = _prompt_for_timeline_filter(all_day_entries)
                visible_day_entries = filtered_entries
                timeline_filter_label = filter_label
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
                if symbol_chart:
                    previous_view = "detail"
                    view_mode = "symbol"
                else:
                    print("Symbol PnL chart unavailable.")
                continue
            if command == "t":
                previous_view = "detail"
                view_mode = "all-trades"
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
                print(symbol_chart or "No data available.")
                print("=" * 72)
                print("Navigation: [B] Back | [F] Filter symbol | [T] Profitable timeline | [Q] Quit")
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
                if command == "t":
                    previous_view = "symbol"
                    view_mode = "all-trades"
                    continue
                print(f"Unknown command: {command}")
            elif view_mode == "symbol-detail":
                current_symbol_trades = trades_by_symbol.get(selected_symbol or "", [])
                print(render_symbol_trade_breakdown(selected_symbol or "", current_symbol_trades))
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
                if command == "a":
                    try:
                        _analyze_trade_from_list(current_symbol_trades, sorter=_sort_symbol_trade_list)
                    except Exception as exc:
                        print(exc)
                        input("Press Enter to continue...")
                    continue
                print(f"Unknown command: {command}")
            else:
                print(render_all_trades(realized_trades))
                command = input("Command: ").strip().lower()
                if not command:
                    continue
                if command == "q":
                    break
                if command == "b":
                    view_mode = previous_view
                    continue
                if command == "a":
                    try:
                        _analyze_trade_from_list(realized_trades, sorter=_sort_trade_list)
                    except Exception as exc:
                        print(exc)
                        input("Press Enter to continue...")
                    continue
                print(f"Unknown command: {command}")


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


def _prompt_for_timeline_filter(day_entries: Sequence[DayPnL]) -> tuple[list[DayPnL], str | None]:
    start_text = input("Start date YYYY-MM-DD (blank to clear filter): ").strip()
    if not start_text:
        return list(day_entries), None

    try:
        start_date = datetime.strptime(start_text, "%Y-%m-%d").date()
    except ValueError:
        print(f"Invalid start date: {start_text}")
        input("Press Enter to continue...")
        return list(day_entries), None

    end_text = input("End date YYYY-MM-DD (blank to use start date): ").strip()
    if end_text:
        try:
            end_date = datetime.strptime(end_text, "%Y-%m-%d").date()
        except ValueError:
            print(f"Invalid end date: {end_text}")
            input("Press Enter to continue...")
            return list(day_entries), None
    else:
        end_date = start_date

    if start_date > end_date:
        print("Start date must be on or before end date.")
        input("Press Enter to continue...")
        return list(day_entries), None

    filtered_entries = [
        entry
        for entry in day_entries
        if start_date <= datetime.strptime(entry.date_label, "%Y-%m-%d").date() <= end_date
    ]
    filter_label = (
        start_date.isoformat()
        if start_date == end_date
        else f"{start_date.isoformat()} to {end_date.isoformat()}"
    )
    if not filtered_entries:
        print(f"No timeline entries found for {filter_label}.")
        input("Press Enter to continue...")
    return filtered_entries, filter_label
