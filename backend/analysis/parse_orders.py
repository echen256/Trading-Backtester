"""Utility script for parsing and manipulating broker order CSV files."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, List, Mapping
import re
from asciichart import asciichart as asciichart_module
import statistics

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
    print(contract_pnl)
    return contract_pnl

def analyze_symbols(contract_pnl: Iterable[Order]) -> dict[str, float]:
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
        return "\n".join(label.rjust(max_label_len) for label in labels)
    width = max(10, 80 - max_label_len - 1)
    lines = []
    for label, magnitude in zip(labels, magnitudes):
        bar = asciichart_module.draw_bar("=", magnitude, all_integer, min_value, max_value, width)
        lines.append(f"{label.rjust(max_label_len)} {bar}")
    
    pnl_list =  list(contract_pnl.values())
    lines.append("--------------------------------")
    lines.append(f"Total: { sum(pnl_list):,.2f}")
    lines.append(f"Average: {sum(pnl_list) / len(pnl_list):,.2f}")
    lines.append(f"Median: {sorted(pnl_list)[len(pnl_list) // 2]:,.2f}")
    lines.append(f"Mode: {max(set(pnl_list), key=pnl_list.count):,.2f}")
    lines.append(f"Range: {min(pnl_list):,.2f} - {max(pnl_list):,.2f}")
    lines.append(f"Standard Deviation: {statistics.stdev(pnl_list):,.2f}")
    lines.append("--------------------------------")
    return "\n".join(lines)


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


if __name__ == "__main__":
    main()
