"""Utility script for parsing and manipulating broker order CSV files."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence, Tuple

import plotly.graph_objects as go
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


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Expected YYYY-MM-DD format.") from exc


def filter_orders_by_date(
    orders: Sequence[Order], start_date: date | None, end_date: date | None
) -> List[Order]:
    if not start_date and not end_date:
        return list(orders)

    filtered: List[Order] = []
    for order in orders:
        trade_date = _order_trade_date(order)
        if trade_date is None:
            continue
        if start_date and trade_date < start_date:
            continue
        if end_date and trade_date > end_date:
            continue
        filtered.append(order)
    return filtered


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


OLD_ORDERS_DIR = "old-orders"


def _date_range_label(orders: Sequence[Order]) -> str:
    """Derive a ``MM-DD-YY-MM-DD-YY`` directory name from order dates."""
    dates: List[date] = []
    for order in orders:
        d = _order_trade_date(order)
        if d:
            dates.append(d)
    if not dates:
        raise ValueError("No valid dates found in orders to determine a date range.")
    min_d, max_d = min(dates), max(dates)
    return (
        f"{min_d.month:02d}-{min_d.day:02d}-{min_d.strftime('%y')}"
        f"-{max_d.month:02d}-{max_d.day:02d}-{max_d.strftime('%y')}"
    )


def save_to_archive(csv_path: Path, orders: Sequence[Order]) -> Path:
    """Copy *csv_path* into ``old-orders/<date-range>/``."""
    label = _date_range_label(orders)
    archive_dir = csv_path.parent / OLD_ORDERS_DIR / label
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / csv_path.name
    shutil.copy2(csv_path, dest)
    return dest


def _list_archives(csv_path: Path) -> List[Path]:
    """Return sorted list of archive directories under ``old-orders/``."""
    base = csv_path.parent / OLD_ORDERS_DIR
    if not base.exists():
        return []
    return sorted(
        (d for d in base.iterdir() if d.is_dir()),
        key=lambda p: p.name,
    )


def load_from_archive(csv_path: Path, archive_name: str | None = None) -> Path | None:
    """Replace *csv_path* with an archived orders file.

    When *archive_name* is ``None`` or empty the user is prompted
    interactively to pick from available archives.
    """
    archives = _list_archives(csv_path)
    if not archives:
        print("No saved order archives found.")
        return None

    if not archive_name:
        print("Available order archives:")
        for i, d in enumerate(archives, 1):
            print(f"  [{i}] {d.name}")
        choice = input("Select archive number (or 'q' to cancel): ").strip()
        if choice.lower() == "q":
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(archives):
                archive_name = archives[idx].name
            else:
                print(f"Invalid selection: {choice}")
                return None
        except ValueError:
            archive_name = choice

    source_dir = csv_path.parent / OLD_ORDERS_DIR / archive_name
    if not source_dir.exists():
        print(f"Archive '{archive_name}' not found.")
        return None

    source_file = source_dir / csv_path.name
    if not source_file.exists():
        csvs = list(source_dir.glob("orders.csv"))
        if not csvs:
            csvs = list(source_dir.glob("*.csv"))
        if csvs:
            source_file = csvs[0]
        else:
            print(f"No CSV file found in archive '{archive_name}'.")
            return None

    shutil.copy2(source_file, csv_path)
    return csv_path


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


def aggregate_contract_pnl(trades: Sequence[RealizedTrade]) -> dict[str, float]:
    """Return realized PnL aggregated per contract symbol."""

    contract_pnl: dict[str, float] = {}
    for trade in trades:
        contract_pnl[trade.symbol] = contract_pnl.get(trade.symbol, 0.0) + trade.pnl
    return contract_pnl


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
    parser.add_argument(
        "--timeline-html",
        type=Path,
        help="Write an interactive Plotly timeline to the given HTML path",
    )
    parser.add_argument(
        "--start-date",
        help="Filter analytics to orders filled on/after this YYYY-MM-DD date",
    )
    parser.add_argument(
        "--end-date",
        help="Filter analytics to orders filled on/before this YYYY-MM-DD date",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Archive the current orders CSV to old-orders/ using the date range of its contents",
    )
    parser.add_argument(
        "--load",
        nargs="?",
        const="",
        default=None,
        metavar="ARCHIVE",
        help="Load an archived orders CSV from old-orders/. "
        "Pass an archive name directly or omit to pick interactively.",
    )
    return parser.parse_args()


def analyze_symbols(contract_pnl: Mapping[str, float]) -> dict[str, float]:
    """Return PnL aggregated per symbol."""
    symbol_pnl: dict[str, float] = {}
    for contract_name, pnl in contract_pnl.items():
        symbol = re.split(r'\d+', contract_name)[0]
        if (symbol_pnl.get(symbol) is None):
            symbol_pnl[symbol] = 0.0
        symbol_pnl[symbol] += pnl
    return symbol_pnl


def compute_symbol_avg_rr(trades: Sequence[RealizedTrade]) -> dict[str, float]:
    """Return average risk-reward ratio per underlying symbol.

    R:R is defined as ``avg_win / abs(avg_loss)``.  Symbols with no
    losing trades or no winning trades get ``float('inf')`` or ``0.0``
    respectively.
    """
    wins_by_symbol: dict[str, List[float]] = defaultdict(list)
    losses_by_symbol: dict[str, List[float]] = defaultdict(list)

    for trade in trades:
        symbol = re.split(r'\d+', trade.symbol)[0]
        if trade.pnl > 0:
            wins_by_symbol[symbol].append(trade.pnl)
        elif trade.pnl < 0:
            losses_by_symbol[symbol].append(trade.pnl)

    all_symbols = set(wins_by_symbol) | set(losses_by_symbol)
    rr: dict[str, float] = {}
    for symbol in all_symbols:
        wins = wins_by_symbol.get(symbol, [])
        losses = losses_by_symbol.get(symbol, [])
        avg_win = statistics.mean(wins) if wins else 0.0
        avg_loss = abs(statistics.mean(losses)) if losses else 0.0
        if avg_loss == 0:
            rr[symbol] = float('inf') if avg_win > 0 else 0.0
        else:
            rr[symbol] = avg_win / avg_loss
    return rr
        


def render_contract_pnl_chart(
    contract_pnl: Mapping[str, float],
    symbol_rr: Mapping[str, float] | None = None,
) -> str:
    """Render a horizontal ASCII bar chart for contract PnL values."""

    sorted_items = sorted(contract_pnl.items(), key=lambda kv: kv[1], reverse=True)

    def _rr_tag(symbol: str) -> str:
        if symbol_rr is None or symbol not in symbol_rr:
            return ""
        rr = symbol_rr[symbol]
        if math.isinf(rr):
            return " [R:R inf]"
        return f" [R:R {rr:.2f}]"

    labels = [
        f"{index + 1:03d}. {symbol} ({value:,.2f}){_rr_tag(symbol)}"
        for index, (symbol, value) in enumerate(sorted_items)
    ]
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

    wins = sum(1 for value in pnl_list if value > 0)
    losses = sum(1 for value in pnl_list if value < 0)
    flats = len(pnl_list) - wins - losses
    denominator = len(pnl_list) or 1
    win_rate = (wins / denominator) * 100
    loss_rate = (losses / denominator) * 100

    # Compute aggregate R:R across all symbols
    avg_rr_text = "N/A"
    if symbol_rr:
        finite_rrs = [v for v in symbol_rr.values() if not math.isinf(v) and v > 0]
        if finite_rrs:
            avg_rr_text = f"{statistics.mean(finite_rrs):.2f}"

    lines.append("--------------------------------")
    lines.append(f"Total: {total:,.2f}")
    lines.append(f"Average: {average:,.2f}")
    lines.append(f"Median: {median:,.2f}")
    lines.append(f"Mode: {mode_value:,.2f}")
    lines.append(f"Range: {pnl_range[0]:,.2f} - {pnl_range[1]:,.2f}")
    lines.append(f"Standard Deviation: {stdev:,.2f}")
    lines.append(f"Win rate: {win_rate:5.2f}% ({wins}/{len(pnl_list)})")
    lines.append(f"Loss rate: {loss_rate:5.2f}% ({losses}/{len(pnl_list)})")
    lines.append(f"Flat positions: {flats}")
    lines.append(f"Avg R:R: {avg_rr_text}")

    # Kelly Criterion: K = W - (1 - W) / R
    kelly_text = "N/A"
    w = wins / denominator if denominator else 0.0
    if symbol_rr:
        finite_rrs = [v for v in symbol_rr.values() if not math.isinf(v) and v > 0]
        if finite_rrs:
            r = statistics.mean(finite_rrs)
            if r > 0:
                kelly = w - (1 - w) / r
                kelly_text = f"{kelly * 100:.2f}%"
    lines.append(f"Kelly Criterion: {kelly_text}")
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
        "Navigation: [Enter day #] View | [N] Next page | [P] Previous page | [S] Symbol PnL | [Q] Quit"
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
    lines.append("Navigation: [B] Back | [N] Next day | [P] Previous day | [S] Symbol PnL | [Q] Quit")
    return "\n".join(lines)


def run_interactive_report(day_entries: Sequence[DayPnL], symbol_chart: str | None = None) -> None:
    if not day_entries:
        print("No realized trades available to display.")
        return

    page = 0
    page_size = 20
    total_days = len(day_entries)
    total_pages = max(1, math.ceil(total_days / page_size))
    view_mode = "timeline"
    selected_index = 0
    previous_view = "timeline"

    while True:
        if view_mode == "timeline":
            print(_render_timeline_page(day_entries, page, page_size))
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
            print(_render_day_detail(day_entries, selected_index))
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
            if command == "n":
                selected_index = (selected_index + 1) % total_days
                continue
            if command == "p":
                selected_index = (selected_index - 1) % total_days
                continue
            print(f"Unknown command: {command}")
        else:
            print("=" * 72)
            print("Symbol PnL Chart")
            print(symbol_chart or "No data available.")
            print("=" * 72)
            print("Navigation: [B] Back | [Q] Quit")
            command = input("Command: ").strip().lower()
            if not command:
                continue
            if command == "q":
                break
            if command == "b":
                view_mode = previous_view
                continue
            print(f"Unknown command: {command}")


def build_timeline_figure(day_entries: Sequence[DayPnL]) -> go.Figure:
    if not day_entries:
        raise ValueError("No realized PnL data available for plotting.")

    dates = [day.date_label for day in day_entries]
    winners = [day.winners_total for day in day_entries]
    losers = [day.losers_total for day in day_entries]

    fig = go.Figure()
    fig.add_bar(
        name="Winners",
        x=dates,
        y=winners,
        marker_color="#2ca02c",
        hovertemplate="%{x}<br>Winners: %{y:$,.2f}<extra></extra>",
    )
    fig.add_bar(
        name="Losers",
        x=dates,
        y=losers,
        marker_color="#d62728",
        hovertemplate="%{x}<br>Losers: %{y:$,.2f}<extra></extra>",
    )
    fig.update_layout(
        title="Daily Realized Contract PnL",
        barmode="relative",
        bargap=0.25,
        template="plotly_white",
        xaxis_title="Date",
        yaxis_title="Realized PnL (USD)",
        hovermode="x unified",
        legend_title_text="",
    )
    fig.update_traces(marker_line_width=1, marker_line_color="#222")
    return fig


def write_timeline_html(fig: go.Figure, output_path: Path, day_entries: Sequence[DayPnL]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    breakdown = {
        day.date_label: {
            "Winners": {
                "total": day.winners_total,
                "lines": [[summary, detail] for summary, detail in day.winners_lines],
            },
            "Losers": {
                "total": day.losers_total,
                "lines": [[summary, detail] for summary, detail in day.losers_lines],
            },
        }
        for day in day_entries
    }
    breakdown_json = json.dumps(breakdown)
    div_id = "daily-pnl-timeline"
    post_script = f""";(function() {{
  const pnlBreakdown = {breakdown_json};
  const graphDiv = document.getElementById('{div_id}');
  if (!graphDiv || typeof graphDiv.on !== 'function') {{
    return;
  }}
  graphDiv.on('plotly_click', function(eventData) {{
    if (!eventData.points || !eventData.points.length) {{
      return;
    }}
    const point = eventData.points[0];
    const date = point.x;
    const traceName = point.data.name;
    const dayData = pnlBreakdown[date];
    const bucket = dayData ? dayData[traceName] : null;
    if (!bucket) {{
      window.alert(traceName + ' on ' + date + '\\n\\nNo trades recorded.');
      return;
    }}
    const total = typeof bucket.total === 'number' ? bucket.total : 0;
    const formatter = new Intl.NumberFormat('en-US', {{ style: 'currency', currency: 'USD' }});
    const totalText = formatter.format(total);
    let details = '';
    const lines = Array.isArray(bucket.lines) ? bucket.lines : [];
    if (lines.length === 0) {{
      details = 'No trades recorded.';
    }} else {{
      for (const pair of lines) {{
        if (Array.isArray(pair)) {{
          if (pair[0]) {{
            details += pair[0] + '\\n';
          }}
          if (pair[1]) {{
            details += '  ' + pair[1] + '\\n';
          }}
        }} else if (typeof pair === 'string') {{
          details += pair + '\\n';
        }}
      }}
      details = details.trimEnd();
    }}
    let message = traceName + ' on ' + date + '\\nTotal: ' + totalText;
    if (details) {{
      message += '\\n\\n' + details;
    }}
    window.alert(message);
  }});
}})();
"""
    fig.write_html(
        output_path,
        include_plotlyjs="cdn",
        full_html=True,
        div_id=div_id,
        post_script=post_script,
    )

def main() -> None:
    args = parse_args()

    # ---------- save / load shortcuts ----------
    if args.save:
        orders = load_orders(args.csv)
        dest = save_to_archive(args.csv, orders)
        print(f"Archived {args.csv} -> {dest}")
        return

    if args.load is not None:
        archive_name = args.load or None
        result = load_from_archive(args.csv, archive_name)
        if result:
            print(f"Loaded archive into {result}")
        return
    # -------------------------------------------

    orders = load_orders(args.csv)
    orders = filter_orders(orders, symbol=args.symbol)
    orders = scale_quantities(orders, args.quantity_multiplier)

    output_path = args.output or args.csv
    save_orders(orders, output_path)

    try:
        start_date = _parse_iso_date(args.start_date)
        end_date = _parse_iso_date(args.end_date)
        if start_date and end_date and start_date > end_date:
            raise ValueError("Start date must be on or before end date.")
    except ValueError as exc:
        print(exc)
        return

    analysis_orders = filter_orders_by_date(orders, start_date, end_date)

    contract_pnl: dict[str, float] | None = None
    symbol_pnl: dict[str, float] | None = None
    symbol_chart_text: str | None = None

    realized_trades: List[RealizedTrade] = []
    if analysis_orders and (
        args.show_pnl_chart or args.interactive_report or args.timeline_html
    ):
        realized_trades = compute_realized_trades(analysis_orders)

    symbol_rr: dict[str, float] | None = None
    if (args.show_pnl_chart or args.interactive_report) and realized_trades:
        contract_pnl = aggregate_contract_pnl(realized_trades)
        if contract_pnl:
            symbol_pnl = analyze_symbols(contract_pnl)
            symbol_rr = compute_symbol_avg_rr(realized_trades)
            if symbol_pnl:
                symbol_chart_text = render_contract_pnl_chart(symbol_pnl, symbol_rr)

    if args.show_pnl_chart:
        if not symbol_chart_text:
            print("No realized trades in the selected date range to analyze.")
        else:
            print("Symbol PnL:")
            print(symbol_chart_text)

    daily_summary: List[DayPnL] | None = None
    if args.interactive_report or args.timeline_html:
        daily_summary = summarize_daily_realized_pnl(realized_trades) if realized_trades else []

    if args.interactive_report:
        if not daily_summary:
            print("No realized trades available to display.")
        else:
            run_interactive_report(daily_summary, symbol_chart_text)

    if args.timeline_html:
        if not daily_summary:
            print("No realized trades available to plot a timeline.")
        else:
            fig = build_timeline_figure(daily_summary)
            write_timeline_html(fig, args.timeline_html, daily_summary)
            print(f"Wrote realized PnL timeline to {args.timeline_html}")


if __name__ == "__main__":
    main()
