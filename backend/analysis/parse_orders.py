"""Utility script for parsing and manipulating broker order CSV files."""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence

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
    positions: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"quantity": 0.0, "avg_price": 0.0}
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
        position = positions[order.symbol]
        remaining = qty

        if side == "buy":
            while remaining > 0:
                if position["quantity"] < 0:
                    close_qty = min(remaining, abs(position["quantity"]))
                    pnl = (position["avg_price"] - price) * close_qty * CONTRACT_MULTIPLIER
                    realized.append(
                        RealizedTrade(
                            trade_date=trade_date,
                            symbol=order.symbol,
                            quantity=close_qty,
                            price=price,
                            pnl=pnl,
                        )
                    )
                    position["quantity"] += close_qty
                    remaining -= close_qty
                    if position["quantity"] == 0:
                        position["avg_price"] = 0.0
                else:
                    total_qty = position["quantity"] + remaining
                    if total_qty == 0:
                        position["avg_price"] = 0.0
                    else:
                        weighted = (position["avg_price"] * position["quantity"]) + (price * remaining)
                        position["avg_price"] = weighted / total_qty
                    position["quantity"] = total_qty
                    remaining = 0
        elif side == "sell":
            while remaining > 0:
                if position["quantity"] > 0:
                    close_qty = min(remaining, position["quantity"])
                    pnl = (price - position["avg_price"]) * close_qty * CONTRACT_MULTIPLIER
                    realized.append(
                        RealizedTrade(
                            trade_date=trade_date,
                            symbol=order.symbol,
                            quantity=close_qty,
                            price=price,
                            pnl=pnl,
                        )
                    )
                    position["quantity"] -= close_qty
                    remaining -= close_qty
                    if position["quantity"] == 0:
                        position["avg_price"] = 0.0
                else:
                    abs_qty = abs(position["quantity"])
                    new_abs_qty = abs_qty + remaining
                    if new_abs_qty == 0:
                        position["avg_price"] = 0.0
                    else:
                        weighted = (position["avg_price"] * abs_qty) + (price * remaining)
                        position["avg_price"] = weighted / new_abs_qty
                    position["quantity"] -= remaining
                    remaining = 0

    return realized


def summarize_daily_realized_pnl(trades: Sequence[RealizedTrade]) -> dict[str, dict[str, dict[str, object]]]:
    """Aggregate realized trades into daily winner/loser buckets."""

    if not trades:
        return {}

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
        bucket.setdefault("lines", []).append(
            f"{trade.symbol}: {trade.quantity:g} @ {trade.price:.2f} -> {trade.pnl:,.2f}"
        )

    ordered_summary = dict(sorted(summary.items()))
    return ordered_summary


def build_timeline_figure(daily_summary: Mapping[str, Mapping[str, Mapping[str, object]]]) -> go.Figure:
    """Create a Plotly figure showing daily winner/loser bars."""

    if not daily_summary:
        raise ValueError("No realized PnL data available for plotting.")

    dates = list(daily_summary.keys())
    winners = [float(daily_summary[day]["Winners"].get("total", 0.0)) for day in dates]
    losers = [float(daily_summary[day]["Losers"].get("total", 0.0)) for day in dates]

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


def write_timeline_html(
    fig: go.Figure,
    output_path: Path,
    daily_summary: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> None:
    """Persist the Plotly figure to HTML with click popups for trade breakdowns."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    breakdown_json = json.dumps(daily_summary)
    div_id = "daily-pnl-timeline"
    post_script = f"""
const pnlBreakdown = {breakdown_json};
const graphDiv = document.getElementById('{div_id}');
if (graphDiv) {{
  graphDiv.on('plotly_click', function(eventData) {{
    if (!eventData.points || !eventData.points.length) {{
      return;
    }}
    const point = eventData.points[0];
    const date = point.x;
    const traceName = point.data.name;
    const bucket = pnlBreakdown[date] && pnlBreakdown[date][traceName];
    if (!bucket) {{
      alert(traceName + ' on ' + date + '\n\nNo trades recorded.');
      return;
    }}
    const lines = bucket.lines && bucket.lines.length ? bucket.lines : ['No trades recorded.'];
    alert(traceName + ' on ' + date + '\n\n' + lines.join('\n'));
  }});
}}
"""
    fig.write_html(
        output_path,
        include_plotlyjs="cdn",
        full_html=True,
        div_id=div_id,
        post_script=post_script,
    )

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
        "--timeline-html",
        type=Path,
        help="Write an interactive realized PnL timeline (Plotly HTML) to this path",
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
        return "\n".join(label.rjust(max_label_len) for label in labels)
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
    lines.append(f"Total: {total:,.2f}")
    lines.append(f"Average: {average:,.2f}")
    lines.append(f"Median: {median:,.2f}")
    lines.append(f"Mode: {mode_value:,.2f}")
    lines.append(f"Range: {pnl_range[0]:,.2f} - {pnl_range[1]:,.2f}")
    lines.append(f"Standard Deviation: {stdev:,.2f}")
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

    if args.timeline_html:
        realized_trades = compute_realized_trades(orders)
        daily_summary = summarize_daily_realized_pnl(realized_trades)
        if not daily_summary:
            print("No realized trades available to plot a timeline.")
        else:
            fig = build_timeline_figure(daily_summary)
            write_timeline_html(fig, args.timeline_html, daily_summary)
            print(f"Wrote realized PnL timeline to {args.timeline_html}")


if __name__ == "__main__":
    main()
