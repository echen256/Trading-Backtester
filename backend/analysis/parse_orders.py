"""Utility script for parsing and manipulating broker order CSV files."""
from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence, Tuple

from asciichart import asciichart as asciichart_module
from statistics import StatisticsError

CONTRACT_MULTIPLIER = 100


# Column names used by ``orders.csv``
FIELDNAMES = [
    "Name",
    "Symbol",
    "Side",
    "Status",
    "Filled",
    "Total Qty",
    "Price",
    "Avg Price",
    "Time-in-Force",
    "Placed Time",
    "Filled Time",
]


@dataclass
class Order:
    """Representation of a single row from ``orders.csv``."""

    name: str
    symbol: str
    side: str
    status: str
    filled: float
    total_qty: float
    price: float | None
    avg_price: float | None
    time_in_force: str
    placed_time: str
    filled_time: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Order":
        return cls(
            name=row.get("Name", ""),
            symbol=row.get("Symbol", ""),
            side=row.get("Side", ""),
            status=row.get("Status", ""),
            filled=_parse_numeric(row.get("Filled")) or 0.0,
            total_qty=_parse_numeric(row.get("Total Qty")) or 0.0,
            price=_parse_numeric(row.get("Price")),
            avg_price=_parse_numeric(row.get("Avg Price")),
            time_in_force=row.get("Time-in-Force", ""),
            placed_time=row.get("Placed Time", ""),
            filled_time=row.get("Filled Time", ""),
        )

    def to_row(self) -> dict[str, str]:
        return {
            "Name": self.name,
            "Symbol": self.symbol,
            "Side": self.side,
            "Status": self.status,
            "Filled": _format_quantity(self.filled),
            "Total Qty": _format_quantity(self.total_qty),
            "Price": _format_price(self.price),
            "Avg Price": _format_numeric(self.avg_price),
            "Time-in-Force": self.time_in_force,
            "Placed Time": self.placed_time,
            "Filled Time": self.filled_time,
        }


@dataclass
class RealizedTrade:
    trade_date: date
    symbol: str
    quantity: float
    price: float
    pnl: float
    open_date: date


@dataclass
class DayPnL:
    date_label: str
    winners_total: float
    losers_total: float
    winners_lines: List[Tuple[str, str]]
    losers_lines: List[Tuple[str, str]]


@dataclass
class PositionLot:
    quantity: float
    price: float
    opened: date


def _parse_numeric(value: str | None) -> float | None:
    """Parse broker-style numeric strings (optionally prefixed with '@')."""

    if value is None:
        return None
    cleaned = value.strip().lstrip("@")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_numeric(value: float | None) -> str:
    if value is None:
        return ""
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"@{_format_numeric(value)}"


def _format_quantity(value: float) -> str:
    return _format_numeric(value)


def _parse_order_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    tokens = value.strip().split()
    trimmed = " ".join(tokens[:2]) if len(tokens) >= 2 else value.strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(trimmed, fmt)
        except ValueError:
            continue
    return None


def _order_trade_date(order: Order) -> date | None:
    for raw_timestamp in (order.filled_time, order.placed_time):
        parsed = _parse_order_datetime(raw_timestamp)
        if parsed:
            return parsed.date()
    return None


def load_orders(csv_path: Path) -> List[Order]:
    """Read orders from a CSV file."""

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [Order.from_row(row) for row in reader]


def filter_orders(orders: Iterable[Order], *, symbol: str | None) -> List[Order]:
    """Return orders filtered by symbol when provided."""

    if not symbol:
        return list(orders)
    symbol = symbol.lower()
    return [order for order in orders if order.symbol.lower() == symbol]


def scale_quantities(orders: Iterable[Order], multiplier: float) -> List[Order]:
    """Scale filled and total quantities for all orders by ``multiplier``."""

    return [
        replace(
            order,
            filled=order.filled * multiplier,
            total_qty=order.total_qty * multiplier,
        )
        for order in orders
    ]


def save_orders(orders: Iterable[Order], csv_path: Path) -> None:
    """Write manipulated orders back out to a CSV file."""

    orders = list(orders)
    if not orders:
        return

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for order in orders:
            writer.writerow(order.to_row())


def compute_realized_trades(orders: Sequence[Order]) -> List[RealizedTrade]:
    """Return realized trade events derived from chronological orders."""

    sorted_orders = sorted(
        orders,
        key=lambda order: _parse_order_datetime(order.filled_time)
        or _parse_order_datetime(order.placed_time)
        or datetime.min,
    )
    positions: defaultdict[str, dict[str, deque[PositionLot]]] = defaultdict(
        lambda: {"long": deque(), "short": deque()}
    )
    realized: List[RealizedTrade] = []

    for order in sorted_orders:
        if order.status.lower() != "filled":
            continue
        trade_date = _order_trade_date(order)
        if trade_date is None:
            continue
        price = order.price if order.price is not None else order.avg_price
        if price is None:
            continue
        qty = order.total_qty or order.filled
        if qty <= 0:
            continue

        side = order.side.lower()
        instrument = positions[order.symbol]
        remaining = qty

        if side == "buy":
            while remaining > 0 and instrument["short"]:
                lot = instrument["short"][0]
                close_qty = min(remaining, lot.quantity)
                pnl = (lot.price - price) * close_qty * CONTRACT_MULTIPLIER
                realized.append(
                    RealizedTrade(
                        trade_date=trade_date,
                        symbol=order.symbol,
                        quantity=close_qty,
                        price=price,
                        pnl=pnl,
                        open_date=lot.opened,
                    )
                )
                lot.quantity -= close_qty
                remaining -= close_qty
                if lot.quantity <= 1e-9:
                    instrument["short"].popleft()
            if remaining > 0:
                instrument["long"].append(
                    PositionLot(quantity=remaining, price=price, opened=trade_date)
                )
        elif side == "sell":
            while remaining > 0 and instrument["long"]:
                lot = instrument["long"][0]
                close_qty = min(remaining, lot.quantity)
                pnl = (price - lot.price) * close_qty * CONTRACT_MULTIPLIER
                realized.append(
                    RealizedTrade(
                        trade_date=trade_date,
                        symbol=order.symbol,
                        quantity=close_qty,
                        price=price,
                        pnl=pnl,
                        open_date=lot.opened,
                    )
                )
                lot.quantity -= close_qty
                remaining -= close_qty
                if lot.quantity <= 1e-9:
                    instrument["long"].popleft()
            if remaining > 0:
                instrument["short"].append(
                    PositionLot(quantity=remaining, price=price, opened=trade_date)
                )

    return realized


def summarize_daily_realized_pnl(trades: Sequence[RealizedTrade]) -> List[DayPnL]:
    """Aggregate realized trades into daily winner/loser buckets."""

    if not trades:
        return []

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
        initiated_line = f"Initiated: {trade.open_date.isoformat()}"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Input order CSV file")
    parser.add_argument("--symbol", help="Only keep orders matching the given symbol")
    parser.add_argument(
        "--quantity-multiplier",
        type=float,
        default=1.0,
        help="Multiply all order quantities by this value",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for writing manipulated CSV. Defaults to overwriting input file.",
    )
    parser.add_argument(
        "--show-pnl-chart",
        action="store_true",
        help="Display an ASCII bar chart of contract PnL aggregated per symbol",
    )
    parser.add_argument(
        "--interactive-report",
        action="store_true",
        help="Launch an interactive ASCII timeline for realized PnL",
    )
    return parser.parse_args()


def analyze_orders(orders: Iterable[Order]) -> dict[str, float]:
    """Return notional contract PnL aggregated per symbol."""

    contract_pnl: dict[str, float] = {}
    for order in orders:
        if order.status.lower() != "filled":
            continue
        price = order.price if order.price is not None else order.avg_price
        if price is None:
            continue
        qty = order.total_qty or order.filled
        if qty == 0:
            continue

        direction = -1 if order.side.lower() == "buy" else 1
        contract_pnl.setdefault(order.symbol, 0.0)
        contract_pnl[order.symbol] += direction * qty * price * CONTRACT_MULTIPLIER
    return contract_pnl

def analyze_symbols(contract_pnl: Mapping[str, float]) -> dict[str, float]:
    """Return PnL aggregated per symbol."""
    symbol_pnl: dict[str, float] = {}
    for contract_name, pnl in contract_pnl.items():
        symbol = re.split(r'\d+', contract_name)[0]
        if (symbol_pnl.get(symbol) is None):
            symbol_pnl[symbol] = 0.0
        symbol_pnl[symbol] += pnl
    return symbol_pnl
        


def render_contract_pnl_chart(contract_pnl: Mapping[str, float]) -> str:
    """Render a horizontal ASCII bar chart for contract PnL values."""

    sorted_items = sorted(contract_pnl.items(), key=lambda kv: kv[1], reverse=True)
    labels = [f"{index + 1:03d}. {symbol} ({value:,.2f})" for index, (symbol, value) in enumerate(sorted_items)]
    magnitudes = [abs(value) for _, value in sorted_items]
    max_label_len = max(len(label) for label in labels)
    all_integer = all(float(magnitude).is_integer() for magnitude in magnitudes)
    min_value = min(magnitudes)
    max_value = max(magnitudes)
    if max_value == 0:
        return "".join(label.rjust(max_label_len) for label in labels)
    width = max(10, 80 - max_label_len - 1)
    lines = []
    for label, magnitude in zip(labels, magnitudes):
        bar = asciichart_module.draw_bar("=", magnitude, all_integer, min_value, max_value, width)
        lines.append(f"{label.rjust(max_label_len)} {bar}")
    
    pnl_list = list(contract_pnl.values())
    total = sum(pnl_list)
    average = total / len(pnl_list)
    median = statistics.median(pnl_list)
    try:
        mode_value = statistics.mode(pnl_list)
    except StatisticsError:
        mode_candidates = statistics.multimode(pnl_list)
        mode_value = mode_candidates[0] if mode_candidates else 0.0
    pnl_range = (min(pnl_list), max(pnl_list))
    stdev = statistics.stdev(pnl_list) if len(pnl_list) >= 2 else 0.0

    lines.append("--------------------------------")
    lines.append(f"Total: {total:,.2f}".strip("\n"))
    lines.append(f"Average: {average:,.2f}".strip("\""))
    lines.append(f"Median: {median:,.2f}".strip("\""))
    lines.append(f"Mode: {mode_value:,.2f}".strip("\""))
    lines.append(f"Range: {pnl_range[0]:,.2f} - {pnl_range[1]:,.2f}".strip("\""))
    lines.append(f"Standard Deviation: {stdev:,.2f}".strip("\""))
    lines.append("--------------------------------")
    return "\n".join(lines)


def describe_contract(name: str) -> str:
    match = re.match(r"([A-Z]+)(\d{6})([CP])(\d{8})", name)
    if not match:
        return name
    symbol, _, option_type, strike_raw = match.groups()
    option_label = "Call" if option_type == "C" else "Put"
    strike_value = int(strike_raw) / 1000.0
    if strike_value.is_integer():
        strike_text = f"{strike_value:.0f}"
    else:
        strike_text = f"{strike_value:.3f}".rstrip("0").rstrip(".")
    return f"{symbol} {option_label} {strike_text}"


def _format_currency(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f}"


def _build_bar(value: float, max_abs_value: float, width: int = 32) -> str:
    if max_abs_value <= 0 or value == 0:
        return ""
    units = max(1, int((abs(value) / max_abs_value) * width))
    char = "+" if value >= 0 else "-"
    return char * units


def _render_timeline_page(day_entries: Sequence[DayPnL], page: int, page_size: int) -> str:
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
    lines.append("-" * 72)
    for global_index in range(start, end):
        day = day_entries[global_index]
        label = f"[{global_index + 1:03d}] {day.date_label}"
        winners_bar = _build_bar(day.winners_total, max_abs)
        losers_bar = _build_bar(day.losers_total, max_abs)
        lines.append(label)
        lines.append(
            f"  Winners {_format_currency(day.winners_total):>12}: {winners_bar or '(flat)'}"
        )
        lines.append(
            f"  Losers  {_format_currency(day.losers_total):>12}: {losers_bar or '(flat)'}"
        )
        lines.append("")

    lines.append(
        "Navigation: [Enter day #] View | [N] Next page | [P] Previous page | [Q] Quit"
    )
    return "\n".join(lines)


def _render_day_detail(day_entries: Sequence[DayPnL], index: int) -> str:
    total_days = len(day_entries)
    day = day_entries[index]
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(f"Day {index + 1:03d}/{total_days} - {day.date_label}")
    net = day.winners_total + day.losers_total
    lines.append(f"Net PnL: {_format_currency(net)}")
    lines.append(f"Winners Total: {_format_currency(day.winners_total)}")
    lines.append(f"Losers Total: {_format_currency(day.losers_total)}")
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
    lines.append("Navigation: [B] Back to timeline | [N] Next day | [P] Previous day | [Q] Quit")
    return "\n".join(lines)


def run_interactive_report(day_entries: Sequence[DayPnL]) -> None:
    if not day_entries:
        print("No realized trades available to display.")
        return

    page = 0
    page_size = 20
    view_mode = "timeline"
    selected_index = 0

    while True:
        if view_mode == "timeline":
            print(_render_timeline_page(day_entries, page, page_size))
            command = input("Command: ").strip().lower()
            if not command:
                continue
            if command == "q":
                break
            if command == "n":
                page += 1
                continue
            if command == "p":
                page = max(0, page - 1)
                continue
            if command.isdigit():
                idx = int(command) - 1
                if 0 <= idx < len(day_entries):
                    selected_index = idx
                    view_mode = "detail"
                else:
                    print(f"Invalid day number: {command}")
                continue
            print(f"Unknown command: {command}")
        else:
            print(_render_day_detail(day_entries, selected_index))
            command = input("Command: ").strip().lower()
            if not command:
                continue
            if command == "q":
                break
            if command == "b":
                view_mode = "timeline"
                continue
            if command == "n":
                selected_index = min(len(day_entries) - 1, selected_index + 1)
                continue
            if command == "p":
                selected_index = max(0, selected_index - 1)
                continue
            print(f"Unknown command: {command}")

def main() -> None:
    args = parse_args()
    orders = load_orders(args.csv)
    orders = filter_orders(orders, symbol=args.symbol)
    orders = scale_quantities(orders, args.quantity_multiplier)

    output_path = args.output or args.csv
    save_orders(orders, output_path)

    if args.show_pnl_chart:
        contract_pnl = analyze_orders(orders)
        symbol_pnl = analyze_symbols(contract_pnl)
        if not symbol_pnl:
            print("No filled orders with price data to analyze.")
        else:
            print("Symbol PnL:")
            print(render_contract_pnl_chart(symbol_pnl))

    if args.interactive_report:
        realized_trades = compute_realized_trades(orders)
        daily_summary = summarize_daily_realized_pnl(realized_trades)
        run_interactive_report(daily_summary)


if __name__ == "__main__":
    main()
