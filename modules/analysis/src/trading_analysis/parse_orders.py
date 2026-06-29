"""Analyze Webull OpenAPI order CSV exports."""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Deque, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]
ORDER_DATA_DIR = REPO_ROOT / "modules" / "analysis" / "order-data"
DEFAULT_WEBULL_ORDERS_CSV = ORDER_DATA_DIR / "webull_orders_2026.csv"
DEFAULT_ORDERS_CSV = DEFAULT_WEBULL_ORDERS_CSV
OPTION_CONTRACT_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")
OPTION_MULTIPLIER = 100.0
EQUITY_MULTIPLIER = 1.0
FILLED_STATUSES = {"FILLED", "PARTIAL_FILLED"}


@dataclass
class Order:
    name: str
    symbol: str
    instrument_type: str
    side: str
    action: str
    position_intent: str
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
            name=(row.get("Name") or row.get("Symbol") or "").strip(),
            symbol=(row.get("Symbol") or row.get("Name") or "").strip(),
            instrument_type=(row.get("InstrumentType") or _infer_instrument_type(row)).strip().upper(),
            side=(row.get("Side") or "").strip().upper(),
            action=(row.get("Action") or row.get("Side") or "").strip().upper(),
            position_intent=(row.get("PositionIntent") or "").strip().upper(),
            status=(row.get("Status") or "").strip().upper(),
            filled=_parse_numeric(row.get("Filled")) or 0.0,
            total_qty=_parse_numeric(row.get("Total Qty")) or 0.0,
            price=_parse_numeric(row.get("Price")),
            avg_price=_parse_numeric(row.get("Avg Price")),
            time_in_force=(row.get("Time-in-Force") or "").strip().upper(),
            placed_time=(row.get("Placed Time") or "").strip(),
            filled_time=(row.get("Filled Time") or "").strip(),
        )

    @property
    def multiplier(self) -> float:
        return OPTION_MULTIPLIER if self.instrument_type == "OPTION" else EQUITY_MULTIPLIER

    @property
    def trade_price(self) -> float | None:
        return self.avg_price if self.avg_price is not None else self.price

    @property
    def quantity(self) -> float:
        return self.filled if self.filled > 0 else self.total_qty

    @property
    def traded_at(self) -> datetime | None:
        return _parse_order_datetime(self.filled_time) or _parse_order_datetime(self.placed_time)

    @property
    def trade_date(self) -> date | None:
        traded_at = self.traded_at
        return traded_at.date() if traded_at else None

    @property
    def underlying(self) -> str:
        if self.instrument_type != "OPTION":
            return self.symbol
        match = OPTION_CONTRACT_RE.fullmatch(self.symbol)
        return match.group(1) if match else self.symbol


@dataclass
class PositionLot:
    quantity: float
    price: float
    opened: date
    opened_at: datetime | None = None
    action: str = ""


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
    trade_datetime: datetime | None = None
    open_datetime: datetime | None = None
    underlying: str = ""
    instrument_type: str = ""
    open_action: str = ""
    close_action: str = ""


@dataclass
class DayPnL:
    date_label: str
    winners_total: float
    losers_total: float
    winners_lines: list[tuple[str, str]]
    losers_lines: list[tuple[str, str]]


@dataclass
class UnmatchedClose:
    order: Order
    direction: str
    quantity: float


@dataclass
class AnalysisResult:
    orders: list[Order]
    eligible_orders: list[Order]
    skipped_orders: list[Order]
    realized_trades: list[RealizedTrade]
    open_positions: dict[str, dict[str, Deque[PositionLot]]]
    unmatched_closes: list[UnmatchedClose]


def _parse_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().lstrip("@")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_order_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw_value = value.strip()
    try:
        return datetime.fromisoformat(raw_value.removesuffix("Z"))
    except ValueError:
        pass

    tokens = raw_value.split()
    trimmed = " ".join(tokens[:2]) if len(tokens) >= 2 else raw_value
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(trimmed, fmt)
        except ValueError:
            continue
    return None


def _infer_instrument_type(row: dict[str, str]) -> str:
    symbol = (row.get("Symbol") or row.get("Name") or "").strip().upper()
    return "OPTION" if OPTION_CONTRACT_RE.fullmatch(symbol) else "EQUITY"


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from exc


def load_orders(csv_path: Path) -> list[Order]:
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            return [Order.from_row(row) for row in csv.DictReader(handle)]
    except FileNotFoundError as exc:
        resolved_path = csv_path.expanduser().resolve(strict=False)
        raise FileNotFoundError(f"Could not find orders file: {resolved_path}") from exc


def filter_orders_by_date(
    orders: Sequence[Order], start_date: date | None, end_date: date | None
) -> list[Order]:
    filtered: list[Order] = []
    for order in orders:
        trade_date = order.trade_date
        if trade_date is None:
            continue
        if start_date and trade_date < start_date:
            continue
        if end_date and trade_date > end_date:
            continue
        filtered.append(order)
    return filtered


def filter_orders(
    orders: Iterable[Order],
    *,
    symbol: str | None = None,
    instrument_type: str = "ALL",
) -> list[Order]:
    symbol_filter = symbol.upper() if symbol else None
    instrument_filter = instrument_type.upper()
    filtered: list[Order] = []
    for order in orders:
        if instrument_filter != "ALL" and order.instrument_type != instrument_filter:
            continue
        if symbol_filter and symbol_filter not in {order.symbol.upper(), order.underlying.upper()}:
            continue
        filtered.append(order)
    return filtered


def _open_lot(order: Order, positions: dict[str, dict[str, Deque[PositionLot]]], side: str, qty: float) -> None:
    price = order.trade_price
    trade_date = order.trade_date
    if price is None or trade_date is None or qty <= 0:
        return
    positions[order.symbol][side].append(
        PositionLot(
            quantity=qty,
            price=price,
            opened=trade_date,
            opened_at=order.traded_at,
            action=order.action,
        )
    )


def _close_lots(
    order: Order,
    positions: dict[str, dict[str, Deque[PositionLot]]],
    realized: list[RealizedTrade],
    unmatched: list[UnmatchedClose],
    side_to_close: str,
    qty: float,
) -> float:
    price = order.trade_price
    trade_date = order.trade_date
    if price is None or trade_date is None or qty <= 0:
        return qty

    lots = positions[order.symbol][side_to_close]
    remaining = qty
    while remaining > 1e-9 and lots:
        lot = lots[0]
        close_qty = min(remaining, lot.quantity)
        if side_to_close == "long":
            pnl = (price - lot.price) * close_qty * order.multiplier
            direction = "long"
        else:
            pnl = (lot.price - price) * close_qty * order.multiplier
            direction = "short"

        realized.append(
            RealizedTrade(
                trade_date=trade_date,
                symbol=order.symbol,
                quantity=close_qty,
                price=price,
                pnl=pnl,
                open_date=lot.opened,
                open_price=lot.price,
                direction=direction,
                trade_datetime=order.traded_at,
                open_datetime=lot.opened_at,
                underlying=order.underlying,
                instrument_type=order.instrument_type,
                open_action=lot.action,
                close_action=order.action,
            )
        )
        lot.quantity -= close_qty
        remaining -= close_qty
        if lot.quantity <= 1e-9:
            lots.popleft()

    if remaining > 1e-9:
        unmatched.append(UnmatchedClose(order=order, direction=side_to_close, quantity=remaining))
    return remaining


def _apply_option_order(
    order: Order,
    positions: dict[str, dict[str, Deque[PositionLot]]],
    realized: list[RealizedTrade],
    unmatched: list[UnmatchedClose],
) -> None:
    qty = order.quantity
    if order.action == "BTO":
        _open_lot(order, positions, "long", qty)
    elif order.action == "STC":
        _close_lots(order, positions, realized, unmatched, "long", qty)
    elif order.action == "STO":
        _open_lot(order, positions, "short", qty)
    elif order.action == "BTC":
        _close_lots(order, positions, realized, unmatched, "short", qty)
    elif order.side == "BUY":
        remaining = _close_lots(order, positions, realized, unmatched, "short", qty)
        if remaining > 1e-9:
            _open_lot(order, positions, "long", remaining)
    elif order.side == "SELL":
        remaining = _close_lots(order, positions, realized, unmatched, "long", qty)
        if remaining > 1e-9:
            _open_lot(order, positions, "short", remaining)


def _apply_equity_order(
    order: Order,
    positions: dict[str, dict[str, Deque[PositionLot]]],
    realized: list[RealizedTrade],
    unmatched: list[UnmatchedClose],
) -> None:
    qty = order.quantity
    if order.action == "SHORT":
        _open_lot(order, positions, "short", qty)
    elif order.action in {"COVER", "BTC"}:
        _close_lots(order, positions, realized, unmatched, "short", qty)
    elif order.side == "BUY":
        remaining = _close_lots(order, positions, realized, unmatched, "short", qty)
        if remaining > 1e-9:
            _open_lot(order, positions, "long", remaining)
    elif order.side == "SELL":
        remaining = _close_lots(order, positions, realized, unmatched, "long", qty)
        if remaining > 1e-9:
            _open_lot(order, positions, "short", remaining)


def compute_realized_trades(orders: Sequence[Order]) -> list[RealizedTrade]:
    return analyze_orders(orders).realized_trades


def analyze_orders(orders: Sequence[Order]) -> AnalysisResult:
    eligible_orders: list[Order] = []
    skipped_orders: list[Order] = []
    for order in orders:
        has_valid_contract = (
            order.instrument_type != "OPTION" or OPTION_CONTRACT_RE.fullmatch(order.symbol)
        )
        is_eligible = (
            order.status in FILLED_STATUSES
            and order.quantity > 0
            and order.trade_price is not None
            and order.trade_date is not None
            and bool(has_valid_contract)
        )
        if is_eligible:
            eligible_orders.append(order)
        else:
            skipped_orders.append(order)
    eligible_orders.sort(key=lambda order: order.traded_at or datetime.min)

    positions: dict[str, dict[str, Deque[PositionLot]]] = defaultdict(
        lambda: {"long": deque(), "short": deque()}
    )
    realized: list[RealizedTrade] = []
    unmatched: list[UnmatchedClose] = []

    for order in eligible_orders:
        if order.instrument_type == "OPTION":
            _apply_option_order(order, positions, realized, unmatched)
        else:
            _apply_equity_order(order, positions, realized, unmatched)

    return AnalysisResult(
        orders=list(orders),
        eligible_orders=eligible_orders,
        skipped_orders=skipped_orders,
        realized_trades=realized,
        open_positions=positions,
        unmatched_closes=unmatched,
    )


def aggregate_pnl(trades: Sequence[RealizedTrade], attr: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for trade in trades:
        totals[str(getattr(trade, attr))] += trade.pnl
    return dict(totals)


def summarize_daily_realized_pnl(trades: Sequence[RealizedTrade]) -> list[DayPnL]:
    by_day: dict[str, list[RealizedTrade]] = defaultdict(list)
    for trade in trades:
        by_day[trade.trade_date.isoformat()].append(trade)

    summaries: list[DayPnL] = []
    for day, day_trades in sorted(by_day.items()):
        winners = [trade for trade in day_trades if trade.pnl > 0]
        losers = [trade for trade in day_trades if trade.pnl < 0]
        summaries.append(
            DayPnL(
                date_label=day,
                winners_total=sum(trade.pnl for trade in winners),
                losers_total=sum(trade.pnl for trade in losers),
                winners_lines=[(trade.symbol, _money(trade.pnl)) for trade in winners],
                losers_lines=[(trade.symbol, _money(trade.pnl)) for trade in losers],
            )
        )
    return summaries


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _print_totals(result: AnalysisResult) -> None:
    trades = result.realized_trades
    total = sum(trade.pnl for trade in trades)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl < 0)
    flats = len(trades) - wins - losses
    by_instrument = aggregate_pnl(trades, "instrument_type")

    print("Webull PnL Analysis")
    print("=" * 72)
    print(f"Rows loaded:        {len(result.orders):>8}")
    print(f"Eligible fills:     {len(result.eligible_orders):>8}")
    print(f"Skipped rows:       {len(result.skipped_orders):>8}")
    print(f"Realized trades:    {len(trades):>8}")
    print(f"Total realized PnL: {_money(total):>12}")
    print(f"Win/Loss/Flat:      {wins}/{losses}/{flats}")
    print(f"Unmatched closes:   {len(result.unmatched_closes):>8}")
    for instrument, pnl in sorted(by_instrument.items()):
        print(f"{instrument.title():<18}{_money(pnl):>12}")


def _print_group(title: str, totals: dict[str, float], limit: int) -> None:
    print()
    print(title)
    print("-" * 72)
    for index, (key, pnl) in enumerate(
        sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit],
        start=1,
    ):
        print(f"{index:>3}. {key:<24} {_money(pnl):>12}")


def _print_largest_trades(trades: Sequence[RealizedTrade], limit: int) -> None:
    print()
    print("Largest Realized Trades")
    print("-" * 72)
    for index, trade in enumerate(sorted(trades, key=lambda t: abs(t.pnl), reverse=True)[:limit], start=1):
        print(
            f"{index:>3}. {trade.trade_date} {trade.instrument_type:<6} "
            f"{trade.symbol:<24} {trade.direction:<5} qty={trade.quantity:g} "
            f"open={trade.open_price:g} close={trade.price:g} pnl={_money(trade.pnl)}"
        )


def _print_open_positions(result: AnalysisResult, limit: int) -> None:
    rows: list[tuple[str, str, float, float]] = []
    for symbol, sides in result.open_positions.items():
        for side, lots in sides.items():
            qty = sum(lot.quantity for lot in lots)
            if qty <= 1e-9:
                continue
            avg_price = sum(lot.quantity * lot.price for lot in lots) / qty
            rows.append((symbol, side, qty, avg_price))
    if not rows:
        return

    print()
    print("Open Positions")
    print("-" * 72)
    for symbol, side, qty, avg_price in sorted(rows)[:limit]:
        print(f"{symbol:<24} {side:<5} qty={qty:g} avg={avg_price:g}")


def _build_symbol_chart(trades: Sequence[RealizedTrade]) -> str | None:
    if not trades:
        return None
    try:
        from .symbol_pnl import analyze_symbols, compute_symbol_avg_rr, render_contract_pnl_chart
    except Exception as exc:
        print(f"Symbol chart unavailable: {exc}")
        return None

    contract_pnl = aggregate_pnl(trades, "symbol")
    symbol_pnl = analyze_symbols(contract_pnl)
    symbol_rr = compute_symbol_avg_rr(trades)
    if not symbol_pnl:
        return None
    try:
        return render_contract_pnl_chart(symbol_pnl, symbol_rr)
    except Exception as exc:
        print(f"Symbol chart unavailable: {exc}")
        return None


def write_realized_csv(trades: Sequence[RealizedTrade], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Trade Date",
        "InstrumentType",
        "Underlying",
        "Symbol",
        "Direction",
        "Quantity",
        "Open Date",
        "Open Price",
        "Close Price",
        "PnL",
        "Open Time",
        "Close Time",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow({
                "Trade Date": trade.trade_date.isoformat(),
                "InstrumentType": trade.instrument_type,
                "Underlying": trade.underlying,
                "Symbol": trade.symbol,
                "Direction": trade.direction,
                "Quantity": f"{trade.quantity:g}",
                "Open Date": trade.open_date.isoformat(),
                "Open Price": f"{trade.open_price:g}",
                "Close Price": f"{trade.price:g}",
                "PnL": f"{trade.pnl:.2f}",
                "Open Time": trade.open_datetime.isoformat() if trade.open_datetime else "",
                "Close Time": trade.trade_datetime.isoformat() if trade.trade_datetime else "",
            })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv",
        nargs="?",
        default=DEFAULT_WEBULL_ORDERS_CSV,
        type=Path,
        help=f"Webull orders CSV path (default: {DEFAULT_WEBULL_ORDERS_CSV})",
    )
    parser.add_argument("--symbol", help="Filter by underlying or exact symbol")
    parser.add_argument(
        "--instrument-type",
        default="ALL",
        choices=["ALL", "OPTION", "EQUITY"],
        help="Instrument type to include",
    )
    parser.add_argument("--start-date", help="Only include orders on/after YYYY-MM-DD")
    parser.add_argument("--end-date", help="Only include orders on/before YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=25, help="Rows to show in each section")
    parser.add_argument("--realized-output", type=Path, help="Write realized trades to CSV")
    parser.add_argument(
        "--interactive-report",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Launch the interactive timeline report after parsing (default: true)",
    )
    parser.add_argument(
        "--summary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print the console summary before any interactive report (default: true)",
    )
    parser.add_argument("--no-open-positions", action="store_true", help="Hide open positions")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        start_date = _parse_iso_date(args.start_date)
        end_date = _parse_iso_date(args.end_date)
    except ValueError as exc:
        print(exc)
        return
    if start_date and end_date and start_date > end_date:
        print("Start date must be on or before end date.")
        return

    orders = load_orders(args.csv)
    orders = filter_orders(orders, symbol=args.symbol, instrument_type=args.instrument_type)
    orders = filter_orders_by_date(orders, start_date, end_date)
    result = analyze_orders(orders)

    if args.summary:
        _print_totals(result)
    if result.realized_trades and not args.interactive_report:
        _print_group("PnL By Underlying", aggregate_pnl(result.realized_trades, "underlying"), args.limit)
        _print_group("PnL By Symbol", aggregate_pnl(result.realized_trades, "symbol"), args.limit)
        _print_largest_trades(result.realized_trades, args.limit)
    if not args.no_open_positions and (args.summary or not args.interactive_report):
        _print_open_positions(result, args.limit)
    if args.realized_output:
        write_realized_csv(result.realized_trades, args.realized_output)
        print(f"\nWrote realized trades to {args.realized_output}")
    if args.interactive_report:
        from .daily_timeline import summarize_daily_realized_pnl as summarize_timeline_pnl
        from .trade_timeline import run_interactive_report

        day_entries = summarize_timeline_pnl(result.realized_trades)
        run_interactive_report(
            day_entries,
            result.realized_trades,
            symbol_chart=_build_symbol_chart(result.realized_trades),
        )


if __name__ == "__main__":
    main()
