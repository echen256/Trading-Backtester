"""Analyze Webull OpenAPI order CSV exports."""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
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

    @property
    def option_type(self) -> str:
        return _option_type_label(self.symbol) if self.instrument_type == "OPTION" else "EQUITY"


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
    option_type: str = ""
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


def _option_type_label(symbol: str) -> str:
    match = OPTION_CONTRACT_RE.fullmatch(symbol)
    if not match:
        return "UNKNOWN"
    return "CALL" if match.group(3) == "C" else "PUT"


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


def filter_trades_by_close_date(
    trades: Sequence[RealizedTrade], start_date: date | None, end_date: date | None
) -> list[RealizedTrade]:
    filtered: list[RealizedTrade] = []
    for trade in trades:
        if start_date and trade.trade_date < start_date:
            continue
        if end_date and trade.trade_date > end_date:
            continue
        filtered.append(trade)
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
                option_type=order.option_type,
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


def _option_strike(symbol: str) -> float | None:
    match = OPTION_CONTRACT_RE.fullmatch(symbol)
    if not match:
        return None
    return int(match.group(4)) / 1000.0


def _option_right(symbol: str) -> str | None:
    match = OPTION_CONTRACT_RE.fullmatch(symbol)
    if not match:
        return None
    return match.group(3)


def _fill_group_key(order: Order) -> str:
    return order.filled_time or order.placed_time or ""


def _with_trade_price(order: Order, price: float) -> Order:
    return replace(order, avg_price=price, price=price)


def _vertical_primary_leg(option_legs: Sequence[Order]) -> Order | None:
    """Contract that should carry the net package premium for a 2-leg vertical."""
    if len(option_legs) != 2:
        return None
    rights = {_option_right(leg.symbol) for leg in option_legs}
    if rights not in [{"C"}, {"P"}]:
        return None
    strikes = [_option_strike(leg.symbol) for leg in option_legs]
    if any(strike is None for strike in strikes):
        return None
    if rights == {"C"}:
        return min(option_legs, key=lambda leg: _option_strike(leg.symbol) or 0.0)
    return max(option_legs, key=lambda leg: _option_strike(leg.symbol) or 0.0)


def _allocate_package_prices(orders: Sequence[Order]) -> list[Order]:
    """
    Fix Webull multi-leg exports that stamp the *net package* (or stock) price on every leg.

    - Verticals: same fill time/qty/avg on both legs → put net premium on the primary
      strike only; other leg gets 0 so package PnL is not double-canceled.
    - Stock+option combos: option avg equals stock price → reprice option to intrinsic.
    """
    grouped: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        grouped[_fill_group_key(order)].append(order)

    rewritten: dict[int, Order] = {}
    for legs in grouped.values():
        if len(legs) < 2:
            continue

        option_legs = [leg for leg in legs if leg.instrument_type == "OPTION"]
        equity_legs = [leg for leg in legs if leg.instrument_type != "OPTION"]

        # Stock + option combo priced at the stock print.
        if equity_legs and option_legs:
            equity = equity_legs[0]
            equity_px = equity.trade_price
            if equity_px is None:
                continue
            for opt in option_legs:
                opt_px = opt.trade_price
                if opt_px is None or abs(opt_px - equity_px) > 0.02:
                    continue
                strike = _option_strike(opt.symbol)
                right = _option_right(opt.symbol)
                if strike is None or right is None:
                    continue
                if right == "C":
                    intrinsic = max(0.0, equity_px - strike)
                else:
                    intrinsic = max(0.0, strike - equity_px)
                rewritten[id(opt)] = _with_trade_price(opt, intrinsic)
            continue

        # Net-priced vertical (identical avg on both legs).
        if len(option_legs) == 2:
            px0 = option_legs[0].trade_price
            px1 = option_legs[1].trade_price
            q0 = option_legs[0].quantity
            q1 = option_legs[1].quantity
            sides = {leg.side for leg in option_legs}
            if (
                px0 is None
                or px1 is None
                or abs(px0 - px1) > 1e-9
                or abs(q0 - q1) > 1e-9
                or sides != {"BUY", "SELL"}
                or option_legs[0].underlying != option_legs[1].underlying
            ):
                continue
            primary = _vertical_primary_leg(option_legs)
            if primary is None:
                continue
            for opt in option_legs:
                if opt.symbol == primary.symbol:
                    rewritten[id(opt)] = _with_trade_price(opt, px0)
                else:
                    rewritten[id(opt)] = _with_trade_price(opt, 0.0)

        # 4-leg / multi packages with a single shared net price: put net on BUY legs'
        # primary only when balanced and identical — allocate to first BUY, zero others.
        elif len(option_legs) >= 3:
            prices = {leg.trade_price for leg in option_legs}
            qtys = {leg.quantity for leg in option_legs}
            underlyings = {leg.underlying for leg in option_legs}
            sides = {leg.side for leg in option_legs}
            if (
                len(prices) == 1
                and None not in prices
                and len(qtys) == 1
                and len(underlyings) == 1
                and sides == {"BUY", "SELL"}
            ):
                net = next(iter(prices))
                assert net is not None
                buys = [leg for leg in option_legs if leg.side == "BUY"]
                priced_id = id(buys[0]) if buys else id(option_legs[0])
                for opt in option_legs:
                    if id(opt) == priced_id:
                        rewritten[id(opt)] = _with_trade_price(opt, net)
                    else:
                        rewritten[id(opt)] = _with_trade_price(opt, 0.0)

    return [rewritten.get(id(order), order) for order in orders]


def _reconcile_order_action(order: Order) -> Order:
    """
    Prefer Side as cash-flow truth when it conflicts with Action/PositionIntent.

    Webull multi-leg rows often label both legs BTO/STC while Side correctly shows
    BUY vs SELL. Trust Side + OPEN/CLOSE so shorts open/cover on the right book.
    """
    side = order.side
    intent = order.position_intent
    action = order.action

    if action == "SHORT" or side == "SHORT":
        return replace(order, side="SELL", action="SHORT") if side == "SHORT" else order
    if action in {"COVER", "BTC"} and order.instrument_type == "EQUITY":
        return order

    open_close = ""
    if intent:
        if "OPEN" in intent:
            open_close = "OPEN"
        elif "CLOSE" in intent:
            open_close = "CLOSE"
    elif action in {"BTO", "STO"}:
        open_close = "OPEN"
    elif action in {"BTC", "STC"}:
        open_close = "CLOSE"

    if side in {"BUY", "SELL"} and open_close:
        if side == "BUY" and open_close == "OPEN":
            reconciled_action, reconciled_intent = "BTO", "BUY_TO_OPEN"
        elif side == "BUY" and open_close == "CLOSE":
            reconciled_action, reconciled_intent = "BTC", "BUY_TO_CLOSE"
        elif side == "SELL" and open_close == "OPEN":
            reconciled_action, reconciled_intent = "STO", "SELL_TO_OPEN"
        else:
            reconciled_action, reconciled_intent = "STC", "SELL_TO_CLOSE"

        if action != reconciled_action or (intent and intent != reconciled_intent):
            return replace(
                order,
                action=reconciled_action,
                position_intent=reconciled_intent,
            )
        return order

    if action in {"BTO", "BTC"} and side == "SELL":
        return replace(order, action=side, position_intent="")
    if action in {"STO", "STC"} and side == "BUY":
        return replace(order, action=side, position_intent="")
    return order


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
    # Combo exports sometimes label the stock leg STC/BTO; Side is authoritative.
    if order.action == "SHORT" or order.side == "SHORT":
        _open_lot(order, positions, "short", qty)
    elif order.action in {"COVER", "BTC"} and order.side == "BUY":
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


def _normalize_instrument_type(order: Order) -> Order:
    """Webull combo exports often tag the stock leg as OPTION with a non-OCC symbol."""
    if order.instrument_type == "OPTION" and not OPTION_CONTRACT_RE.fullmatch(order.symbol):
        order = replace(order, instrument_type="EQUITY")
    elif order.instrument_type in {"", "UNKNOWN"}:
        inferred = "OPTION" if OPTION_CONTRACT_RE.fullmatch(order.symbol) else "EQUITY"
        order = replace(order, instrument_type=inferred)
    return _normalize_combo_equity_quantity(order)


def _normalize_combo_equity_quantity(order: Order) -> Order:
    """
    Stock+option combo rows often set Filled to the *contract* count while
    Total Qty holds the share count (e.g. Filled=3, Total Qty=300).

    Prefer share quantity for equity legs when Total Qty == Filled * 100.
    """
    if order.instrument_type != "EQUITY":
        return order
    if order.filled <= 0 or order.total_qty <= 0:
        return order
    if abs(order.total_qty - order.filled * OPTION_MULTIPLIER) > 1e-6:
        return order
    return replace(order, filled=order.total_qty)


def _settle_expired_option_lots(
    positions: dict[str, dict[str, Deque[PositionLot]]],
    realized: list[RealizedTrade],
    *,
    as_of: date | None = None,
) -> None:
    """
    Realize worthless expiration for option lots still open after their expiry date.

    Webull order history often omits explicit expire/assignment fills. Settling
    remaining long lots to 0 (and short lots to 0 credit keep) matches broker
    realized P&L much more closely for 0DTE / held-to-expiry trades.
    """
    from .display_common import extract_contract_expiration

    cutoff = as_of or date.max
    for symbol, sides in list(positions.items()):
        expiration = extract_contract_expiration(symbol)
        if expiration is None or expiration > cutoff:
            continue
        match = OPTION_CONTRACT_RE.fullmatch(symbol)
        underlying = match.group(1) if match else symbol
        for side_name in ("long", "short"):
            lots = sides.get(side_name)
            if not lots:
                continue
            while lots:
                lot = lots.popleft()
                if lot.quantity <= 1e-9:
                    continue
                if side_name == "long":
                    pnl = (0.0 - lot.price) * lot.quantity * OPTION_MULTIPLIER
                    direction = "long"
                    close_action = "EXPIRE"
                else:
                    pnl = (lot.price - 0.0) * lot.quantity * OPTION_MULTIPLIER
                    direction = "short"
                    close_action = "EXPIRE"
                realized.append(
                    RealizedTrade(
                        trade_date=expiration,
                        symbol=symbol,
                        quantity=lot.quantity,
                        price=0.0,
                        pnl=pnl,
                        open_date=lot.opened,
                        open_price=lot.price,
                        direction=direction,
                        trade_datetime=datetime.combine(expiration, datetime.min.time()),
                        open_datetime=lot.opened_at,
                        underlying=underlying,
                        instrument_type="OPTION",
                        option_type=_option_type_label(symbol),
                        open_action=lot.action,
                        close_action=close_action,
                    )
                )


def analyze_orders(orders: Sequence[Order], *, settle_expirations: bool = True) -> AnalysisResult:
    eligible_orders: list[Order] = []
    skipped_orders: list[Order] = []
    for order in orders:
        order = _normalize_instrument_type(order)
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
            eligible_orders.append(_reconcile_order_action(order))
        else:
            skipped_orders.append(order)

    eligible_orders = _allocate_package_prices(eligible_orders)
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

    if settle_expirations:
        last_fill = max(
            (order.trade_date for order in eligible_orders if order.trade_date is not None),
            default=None,
        )
        _settle_expired_option_lots(positions, realized, as_of=last_fill)

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


def summarize_by_option_type(trades: Sequence[RealizedTrade]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = defaultdict(
        lambda: {"trades": 0.0, "wins": 0.0, "losses": 0.0, "flats": 0.0, "pnl": 0.0}
    )
    for trade in trades:
        key = trade.option_type or ("EQUITY" if trade.instrument_type == "EQUITY" else "UNKNOWN")
        bucket = summary[key]
        bucket["trades"] += 1
        bucket["pnl"] += trade.pnl
        if trade.pnl > 0:
            bucket["wins"] += 1
        elif trade.pnl < 0:
            bucket["losses"] += 1
        else:
            bucket["flats"] += 1
    return dict(summary)


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
    by_option_type = summarize_by_option_type(trades)

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
    if by_option_type:
        print()
        print("Calls/Puts Split")
        print("-" * 72)
        for option_type in ("CALL", "PUT", "EQUITY", "UNKNOWN"):
            bucket = by_option_type.get(option_type)
            if not bucket:
                continue
            trades_count = int(bucket["trades"])
            wins_count = int(bucket["wins"])
            losses_count = int(bucket["losses"])
            flats_count = int(bucket["flats"])
            win_rate = (wins_count / trades_count) if trades_count else 0.0
            print(
                f"{option_type.title():<8} trades={trades_count:>5} "
                f"pnl={_money(bucket['pnl']):>12} "
                f"win={win_rate:>6.2%} "
                f"W/L/F={wins_count}/{losses_count}/{flats_count}"
            )


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
        "OptionType",
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
                "OptionType": trade.option_type,
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
    parser.add_argument(
        "--tpo-grades",
        type=Path,
        help="Path to trade-tpo-grades JSON for interactive [G] badges (auto-discovers if omitted)",
    )
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
    orders = filter_orders_by_date(orders, None, end_date)
    result = analyze_orders(orders)
    report_trades = filter_trades_by_close_date(result.realized_trades, start_date, end_date)
    report_result = replace(result, realized_trades=report_trades)

    if args.summary:
        _print_totals(report_result)
    if report_trades and not args.interactive_report:
        _print_group("PnL By Underlying", aggregate_pnl(report_trades, "underlying"), args.limit)
        _print_group("PnL By Symbol", aggregate_pnl(report_trades, "symbol"), args.limit)
        _print_largest_trades(report_trades, args.limit)
    if not args.no_open_positions and (args.summary or not args.interactive_report):
        _print_open_positions(result, args.limit)
    if args.realized_output:
        write_realized_csv(report_trades, args.realized_output)
        print(f"\nWrote realized trades to {args.realized_output}")
    if args.interactive_report:
        from .daily_timeline import summarize_daily_realized_pnl as summarize_timeline_pnl
        from .export_tpo_grades import discover_tpo_grades_file, load_tpo_grades
        from .trade_timeline import run_interactive_report

        day_entries = summarize_timeline_pnl(report_trades)
        tpo_grades = None
        grades_path = args.tpo_grades
        if grades_path is None:
            grades_path = discover_tpo_grades_file(
                ORDER_DATA_DIR,
                start_date=start_date,
                end_date=end_date,
            )
        if grades_path and grades_path.exists():
            try:
                tpo_grades = load_tpo_grades(grades_path)
                print(f"Loaded TPO grades from {grades_path}")
            except Exception as exc:
                print(f"Could not load TPO grades from {grades_path}: {exc}")
        run_interactive_report(
            day_entries,
            report_trades,
            symbol_chart=_build_symbol_chart(report_trades),
            tpo_grades=tpo_grades,
        )


if __name__ == "__main__":
    main()
