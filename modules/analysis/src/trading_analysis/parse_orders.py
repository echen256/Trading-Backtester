"""Utility script for parsing and manipulating broker order CSV files."""
from __future__ import annotations

import argparse
import csv
import re
import shutil
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .daily_timeline import summarize_daily_realized_pnl
from .symbol_pnl import analyze_symbols, compute_symbol_avg_rr, render_contract_pnl_chart
from .trade_timeline import run_interactive_report

CONTRACT_MULTIPLIER = 100
DEFAULT_ORDERS_CSV = Path(__file__).resolve().parents[2] / "order-data" / "orders.csv"


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
    open_price: float
    direction: str


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


@dataclass
class PreparedOrders:
    orders: List[Order]
    analysis_orders: List[Order]
    output_path: Path
    start_date: date | None
    end_date: date | None


@dataclass
class AnalysisComputation:
    realized_trades: List[RealizedTrade]
    contract_pnl: dict[str, float] | None
    symbol_pnl: dict[str, float] | None
    symbol_chart_text: str | None
    symbol_rr: dict[str, float] | None
    daily_summary: List[DayPnL] | None


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
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return [Order.from_row(row) for row in reader]
    except FileNotFoundError as exc:
        resolved_path = csv_path.expanduser().resolve(strict=False)
        raise FileNotFoundError(f"Could not find orders file: {resolved_path}") from exc


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
                        open_price=lot.price,
                        direction="short",
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
                        open_price=lot.price,
                        direction="long",
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




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv",
        nargs="?",
        default=DEFAULT_ORDERS_CSV,
        type=Path,
        help="Input order CSV file (default: modules/analysis/order-data/orders.csv)",
    )
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
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Launch an interactive ASCII timeline for realized PnL (default: enabled)",
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


def load_and_prepare_orders(args: argparse.Namespace) -> PreparedOrders:
    orders = load_orders(args.csv)
    orders = filter_orders(orders, symbol=args.symbol)
    orders = scale_quantities(orders, args.quantity_multiplier)

    output_path = args.output or args.csv
    save_orders(orders, output_path)

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be on or before end date.")

    analysis_orders = filter_orders_by_date(orders, start_date, end_date)
    return PreparedOrders(
        orders=orders,
        analysis_orders=analysis_orders,
        output_path=output_path,
        start_date=start_date,
        end_date=end_date,
    )


def compute_analysis_outputs(
    analysis_orders: Sequence[Order], args: argparse.Namespace
) -> AnalysisComputation:
    should_compute_trades = bool(
        analysis_orders
        and (args.show_pnl_chart or args.interactive_report)
    )
    realized_trades = compute_realized_trades(analysis_orders) if should_compute_trades else []

    contract_pnl: dict[str, float] | None = None
    symbol_pnl: dict[str, float] | None = None
    symbol_chart_text: str | None = None
    symbol_rr: dict[str, float] | None = None

    if (args.show_pnl_chart or args.interactive_report) and realized_trades:
        contract_pnl = aggregate_contract_pnl(realized_trades)
        if contract_pnl:
            symbol_pnl = analyze_symbols(contract_pnl)
            symbol_rr = compute_symbol_avg_rr(realized_trades)
            if symbol_pnl:
                symbol_chart_text = render_contract_pnl_chart(symbol_pnl, symbol_rr)

    daily_summary: List[DayPnL] | None = None
    if args.interactive_report:
        daily_summary = summarize_daily_realized_pnl(realized_trades) if realized_trades else []

    return AnalysisComputation(
        realized_trades=realized_trades,
        contract_pnl=contract_pnl,
        symbol_pnl=symbol_pnl,
        symbol_chart_text=symbol_chart_text,
        symbol_rr=symbol_rr,
        daily_summary=daily_summary,
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

    try:
        prepared = load_and_prepare_orders(args)
    except ValueError as exc:
        print(exc)
        return

    computed = compute_analysis_outputs(prepared.analysis_orders, args)

    if args.interactive_report:
        if not computed.daily_summary:
            print("No realized trades available to display.")
        else:
            run_interactive_report(
                computed.daily_summary,
                computed.realized_trades,
                computed.symbol_chart_text,
            )


if __name__ == "__main__":
    main()
