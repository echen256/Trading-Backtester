"""Replay 2026 fills: while in a working overnight winner, block unrelated entries.

Also simulate a same-session harvest cooldown (flatten a winner → no new names).
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_analysis.display_common import describe_contract
from trading_analysis.parse_orders import (
    FILLED_STATUSES,
    OPTION_CONTRACT_RE,
    OPTION_MULTIPLIER,
    Order,
    RealizedTrade,
    _normalize_instrument_type,
    _reconcile_order_action,
    analyze_orders,
)

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
ORDER_DIR = Path(__file__).resolve().parents[1] / "order-data"
CACHE_UND = ORDER_DIR / "market-data-cache" / "underlying" / "1d"
CACHE_OPT = ORDER_DIR / "market-data-cache" / "options" / "1d"
OUT_JSON = ORDER_DIR / "winning-trade-lock-2026.json"
MSTU_SPLIT = date(2026, 8, 24)
Y0, Y1 = date(2026, 1, 1), date(2026, 8, 27)
LOOKBACK_DAYS = 14
MIN_MARK = 50.0
MIN_COST = 250.0
MIN_HARVEST = 50.0
FILES = [
    "webull_orders_2026.csv",
    "webull_orders_2026-06-01_to_2026-08-12.csv",
    "webull_orders_2026-08-07_to_2026-08-19.csv",
    "webull_orders_2026-08-10_to_2026-08-26.csv",
    "webull_orders_2026-08-25_to_2026-08-27.csv",
    "webull_orders_2026-08-25_to_2026-08-28.csv",
]


@dataclass
class Lot:
    qty: float
    price: float
    opened: date
    side: str
    symbol: str
    underlying: str
    instrument: str
    option_type: str
    expiration: date | None
    opened_at: datetime | None = None
    blocked_open: bool = False


def row_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        row.get(k, "")
        for k in (
            "Symbol",
            "Side",
            "Status",
            "Filled",
            "Avg Price",
            "Placed Time",
            "Filled Time",
            "Action",
            "Total Qty",
        )
    )


def load_orders() -> list[Order]:
    seen: set[tuple[str, ...]] = set()
    rows: list[dict[str, str]] = []
    for name in FILES:
        path = ORDER_DIR / name
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    eligible: list[Order] = []
    for order in (Order.from_row(row) for row in rows):
        order = _normalize_instrument_type(order)
        has_valid_contract = order.instrument_type != "OPTION" or OPTION_CONTRACT_RE.fullmatch(order.symbol)
        if (
            order.status in FILLED_STATUSES
            and order.quantity > 0
            and order.trade_price is not None
            and order.trade_date is not None
            and has_valid_contract
        ):
            eligible.append(_reconcile_order_action(order))
    eligible.sort(key=lambda o: o.traded_at or datetime.min)
    return eligible


def bar_date(ts_ms: float) -> date:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(NY).date()


def load_close_map(path: Path) -> dict[date, float]:
    payload = json.loads(path.read_text())
    out: dict[date, float] = {}
    for bar in payload.get("results") or []:
        try:
            out[bar_date(float(bar["t"]))] = float(bar["c"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_underlying_closes() -> dict[str, dict[date, float]]:
    closes: dict[str, dict[date, float]] = {}
    if not CACHE_UND.exists():
        return closes
    for path in CACHE_UND.glob("*.json"):
        closes[path.stem.upper()] = load_close_map(path)
    return closes


class OptionCloseCache:
    def __init__(self) -> None:
        self._loaded: dict[str, dict[date, float]] = {}

    def get(self, symbol: str) -> dict[date, float]:
        key = symbol.upper()
        if key not in self._loaded:
            path = CACHE_OPT / f"{key}.json"
            self._loaded[key] = load_close_map(path) if path.exists() else {}
        return self._loaded[key]


def prior_close(closes: dict[date, float], session: date) -> float | None:
    prior = [d for d in closes if d < session]
    if not prior:
        return None
    return closes[max(prior)]


def ny_session(order: Order) -> date:
    traded = order.traded_at
    if traded is None:
        return order.trade_date or date.min
    if traded.tzinfo is None:
        traded = traded.replace(tzinfo=UTC)
    return traded.astimezone(NY).date()


def occ_expiration(symbol: str) -> date | None:
    match = OPTION_CONTRACT_RE.fullmatch(symbol)
    if not match:
        return None
    raw = match.group(2)
    year = 2000 + int(raw[0:2])
    month = int(raw[2:4])
    day = int(raw[4:6])
    try:
        return date(year, month, day)
    except ValueError:
        return None


def lot_cost(lot: Lot) -> float:
    mult = OPTION_MULTIPLIER if lot.instrument == "OPTION" else 1.0
    return lot.qty * lot.price * mult


def expire_options(
    lots: dict[str, dict[str, deque[Lot]]], session: date, realized: list[RealizedTrade]
) -> None:
    expire_dt = datetime(session.year, session.month, session.day, 16, 0, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)
    for symbol, sides in list(lots.items()):
        for side in ("long", "short"):
            keep: deque[Lot] = deque()
            for lot in sides[side]:
                if lot.instrument == "OPTION" and lot.expiration is not None and lot.expiration < session:
                    if lot.qty > 1e-9:
                        pnl = (0.0 - lot.price) * lot.qty * OPTION_MULTIPLIER if side == "long" else lot.price * lot.qty * OPTION_MULTIPLIER
                        realized.append(
                            RealizedTrade(
                                trade_date=lot.expiration,
                                symbol=lot.symbol,
                                quantity=lot.qty,
                                price=0.0,
                                pnl=pnl,
                                open_date=lot.opened,
                                open_price=lot.price,
                                direction=side,
                                trade_datetime=expire_dt,
                                open_datetime=lot.opened_at,
                                underlying=lot.underlying,
                                instrument_type="OPTION",
                                option_type=lot.option_type,
                                close_action="EXPIRE",
                                open_action="BLOCKED" if lot.blocked_open else "",
                            )
                        )
                    continue
                if lot.qty > 1e-9:
                    keep.append(lot)
            sides[side] = keep


def mstu_adjust_lots(lots: dict[str, dict[str, deque[Lot]]], session: date, done: set[str]) -> None:
    if session < MSTU_SPLIT or "MSTU" in done:
        return
    sides = lots.get("MSTU")
    if not sides:
        return
    for side in ("long", "short"):
        new_q: deque[Lot] = deque()
        for lot in sides[side]:
            if lot.opened < MSTU_SPLIT and lot.instrument == "EQUITY":
                new_q.append(
                    Lot(
                        qty=lot.qty / 10.0,
                        price=lot.price * 10.0,
                        opened=lot.opened,
                        side=lot.side,
                        symbol=lot.symbol,
                        underlying=lot.underlying,
                        instrument=lot.instrument,
                        option_type=lot.option_type,
                        expiration=lot.expiration,
                        opened_at=lot.opened_at,
                        blocked_open=lot.blocked_open,
                    )
                )
            else:
                new_q.append(lot)
        sides[side] = new_q
    done.add("MSTU")


def mark_lot(lot: Lot, session: date, und_closes: dict[str, dict[date, float]], opt_closes: OptionCloseCache) -> float | None:
    if lot.opened >= session:
        return None
    signed = 1.0 if lot.side == "long" else -1.0
    if lot.instrument == "EQUITY":
        px = prior_close(und_closes.get(lot.underlying, {}), session)
        if px is None:
            return None
        return signed * (px - lot.price) * lot.qty
    opt_px = prior_close(opt_closes.get(lot.symbol), session)
    if opt_px is not None:
        return signed * (opt_px - lot.price) * lot.qty * OPTION_MULTIPLIER
    und_now = prior_close(und_closes.get(lot.underlying, {}), session)
    und_then = prior_close(und_closes.get(lot.underlying, {}), lot.opened)
    if und_now is None or und_then is None or und_then <= 0 or lot.price <= 0:
        return None
    move = (und_now / und_then) - 1.0
    if lot.option_type == "PUT":
        move = -move
    if lot.side == "short":
        move = -move
    # Directional proxy only: 0.5 delta on premium. Used when the option chain is uncached.
    return move * 0.5 * lot.price * lot.qty * OPTION_MULTIPLIER


def working_winners(
    lots: dict[str, dict[str, deque[Lot]]],
    session: date,
    und_closes: dict[str, dict[date, float]],
    opt_closes: OptionCloseCache,
    *,
    lookback: bool,
    min_cost: float,
) -> dict[str, float]:
    cutoff = session - timedelta(days=LOOKBACK_DAYS) if lookback else date.min
    by_und: dict[str, float] = defaultdict(float)
    cost_und: dict[str, float] = defaultdict(float)
    for sides in lots.values():
        for side in ("long", "short"):
            for lot in sides[side]:
                if lot.qty <= 1e-9 or lot.opened < cutoff:
                    continue
                pnl = mark_lot(lot, session, und_closes, opt_closes)
                if pnl is None:
                    continue
                by_und[lot.underlying] += pnl
                cost_und[lot.underlying] += lot_cost(lot)
    return {
        und: pnl
        for und, pnl in by_und.items()
        if pnl > MIN_MARK and cost_und[und] >= min_cost
    }


def net_open(sides: dict[str, deque[Lot]], side: str) -> float:
    return sum(lot.qty for lot in sides[side])


def is_opening_fill(order: Order, lots: dict[str, dict[str, deque[Lot]]]) -> bool:
    sides = lots.setdefault(order.symbol, {"long": deque(), "short": deque()})
    qty = order.quantity
    if order.instrument_type == "OPTION":
        if order.action in {"BTO", "STO"}:
            return True
        if order.action == "STC":
            return qty > net_open(sides, "long") + 1e-9
        if order.action == "BTC":
            return qty > net_open(sides, "short") + 1e-9
        if order.side == "BUY":
            return qty > net_open(sides, "short") + 1e-9
        if order.side == "SELL":
            return qty > net_open(sides, "long") + 1e-9
        return False
    if order.side == "BUY":
        return qty > net_open(sides, "short") + 1e-9
    if order.side == "SELL":
        return qty > net_open(sides, "long") + 1e-9
    return False


def apply_fill(
    order: Order, lots: dict[str, dict[str, deque[Lot]]], *, block_new_opens: bool
) -> list[RealizedTrade]:
    sides = lots.setdefault(order.symbol, {"long": deque(), "short": deque()})
    qty = order.quantity
    opened = ny_session(order)
    und = order.underlying
    opt_type = order.option_type if order.instrument_type == "OPTION" else "EQUITY"
    exp = occ_expiration(order.symbol) if order.instrument_type == "OPTION" else None
    realized: list[RealizedTrade] = []
    mult = OPTION_MULTIPLIER if order.instrument_type == "OPTION" else 1.0
    px = order.trade_price or 0.0

    def open_side(side: str, amount: float) -> None:
        if amount <= 1e-9 or order.trade_price is None:
            return
        sides[side].append(
            Lot(
                qty=amount,
                price=order.trade_price,
                opened=opened,
                side=side,
                symbol=order.symbol,
                underlying=und,
                instrument=order.instrument_type,
                option_type=opt_type,
                expiration=exp,
                opened_at=order.traded_at,
                blocked_open=block_new_opens,
            )
        )

    def close_side(side: str, amount: float) -> float:
        left = amount
        q = sides[side]
        while left > 1e-9 and q:
            lot = q[0]
            take = min(lot.qty, left)
            if side == "long":
                pnl = (px - lot.price) * take * mult
            else:
                pnl = (lot.price - px) * take * mult
            realized.append(
                RealizedTrade(
                    trade_date=opened,
                    symbol=order.symbol,
                    quantity=take,
                    price=px,
                    pnl=pnl,
                    open_date=lot.opened,
                    open_price=lot.price,
                    direction=side,
                    trade_datetime=order.traded_at,
                    open_datetime=lot.opened_at,
                    underlying=lot.underlying,
                    instrument_type=lot.instrument,
                    option_type=lot.option_type,
                    close_action=order.action,
                    open_action="BLOCKED" if lot.blocked_open else lot.side,
                )
            )
            lot.qty -= take
            left -= take
            if lot.qty <= 1e-9:
                q.popleft()
        return left

    if order.instrument_type == "OPTION":
        if order.action == "BTO":
            open_side("long", qty)
        elif order.action == "STC":
            close_side("long", qty)
        elif order.action == "STO":
            open_side("short", qty)
        elif order.action == "BTC":
            close_side("short", qty)
        elif order.side == "BUY":
            rem = close_side("short", qty)
            open_side("long", rem)
        elif order.side == "SELL":
            rem = close_side("long", qty)
            open_side("short", rem)
    elif order.side == "BUY":
        rem = close_side("short", qty)
        open_side("long", rem)
    elif order.side == "SELL":
        rem = close_side("long", qty)
        open_side("short", rem)
    return realized


def mstu_adj_pnl(trade) -> float:
    und = trade.underlying or trade.symbol
    if trade.instrument_type != "EQUITY" or und != "MSTU":
        return trade.pnl
    open_d = trade.open_date
    close_d = trade.trade_date
    if trade.open_datetime:
        dt = trade.open_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        open_d = dt.astimezone(NY).date()
    if trade.trade_datetime:
        dt = trade.trade_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        close_d = dt.astimezone(NY).date()
    if open_d < MSTU_SPLIT <= close_d:
        return trade.quantity * (trade.price - trade.open_price * 10.0)
    return trade.pnl


def dt_stamp(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat()


def et_clock(iso_utc: str) -> str:
    try:
        raw = iso_utc.replace("Z", "")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(NY).strftime("%H:%M")
    except ValueError:
        return iso_utc


def close_session(trade) -> date:
    if trade.trade_datetime:
        dt = trade.trade_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(NY).date()
    return trade.trade_date


def open_session(trade) -> date:
    if trade.open_datetime:
        dt = trade.open_datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(NY).date()
    return trade.open_date


def in_year(trade) -> bool:
    return Y0 <= close_session(trade) <= Y1


def bucket_stats(trades) -> dict:
    pnls = [mstu_adj_pnl(t) for t in trades]
    if not pnls:
        return {"n": 0, "pnl": 0.0, "wr": 0.0, "same_day_n": 0, "same_day_pnl": 0.0, "ovn_n": 0, "ovn_pnl": 0.0}
    wins = sum(1 for p in pnls if p > 0)
    same = [t for t in trades if open_session(t) == close_session(t)]
    ovn = [t for t in trades if open_session(t) != close_session(t)]
    return {
        "n": len(pnls),
        "pnl": round(sum(pnls), 2),
        "wr": round(wins / len(pnls), 4),
        "same_day_n": len(same),
        "same_day_pnl": round(sum(mstu_adj_pnl(t) for t in same), 2),
        "ovn_n": len(ovn),
        "ovn_pnl": round(sum(mstu_adj_pnl(t) for t in ovn), 2),
    }


def monthly(trades) -> dict[str, float]:
    by: dict[str, float] = defaultdict(float)
    for t in trades:
        by[close_session(t).strftime("%Y-%m")] += mstu_adj_pnl(t)
    return {m: round(by[m], 2) for m in sorted(by)}


def by_kind(trades, kind: str):
    if kind == "EQUITY":
        return bucket_stats([t for t in trades if t.instrument_type == "EQUITY"])
    if kind == "CALL":
        return bucket_stats([t for t in trades if t.option_type == "CALL"])
    if kind == "PUT":
        return bucket_stats([t for t in trades if t.option_type == "PUT"])
    if kind == "OPTION":
        return bucket_stats([t for t in trades if t.instrument_type == "OPTION"])
    return bucket_stats(trades)


def allowed(
    order: Order,
    winners: dict[str, float],
    harvested: bool,
    *,
    use_hold: bool,
    use_harvest: bool,
) -> bool:
    lock: set[str] = set()
    if use_hold:
        lock |= set(winners)
    if use_harvest and harvested:
        if lock:
            pass
        else:
            return False
    if not lock:
        return True
    return order.underlying in lock


def simulate(
    orders: list[Order],
    und_closes: dict[str, dict[date, float]],
    official: list,
    *,
    use_hold: bool,
    use_harvest: bool,
    lookback: bool,
    min_cost: float,
    mode: str,
) -> dict:
    lots: dict[str, dict[str, deque[Lot]]] = {}
    blocked: list[dict] = []
    blocked_opens: set[tuple[str, str]] = set()
    split_done: set[str] = set()
    opt_closes = OptionCloseCache()
    harvested = False
    current_session: date | None = None
    lock_days: set[str] = set()
    realized_buf: list[RealizedTrade] = []
    closes_by_time: dict[str, list] = defaultdict(list)
    for trade in official:
        closes_by_time[dt_stamp(trade.trade_datetime)].append(trade)

    for order in orders:
        session = ny_session(order)
        if current_session != session:
            current_session = session
            harvested = False
        expire_options(lots, session, realized_buf)
        mstu_adjust_lots(lots, session, split_done)
        winners = working_winners(
            lots, session, und_closes, opt_closes, lookback=lookback, min_cost=min_cost
        )
        opening = is_opening_fill(order, lots)
        block_new = opening and not allowed(
            order, winners, harvested, use_hold=use_hold, use_harvest=use_harvest
        )
        if block_new:
            blocked_opens.add((order.symbol, dt_stamp(order.traded_at)))
            blocked.append(
                {
                    "session": session.isoformat(),
                    "time": dt_stamp(order.traded_at),
                    "clock": et_clock(dt_stamp(order.traded_at)),
                    "underlying": order.underlying,
                    "symbol": order.symbol,
                    "label": describe_contract(order.symbol),
                    "action": order.action,
                    "side": order.side,
                    "qty": order.quantity,
                    "price": order.trade_price,
                    "lock": sorted(winners),
                    "harvested": harvested,
                    "lock_pnl": {k: round(v, 0) for k, v in sorted(winners.items(), key=lambda kv: -kv[1])[:5]},
                }
            )
        apply_fill(order, lots, block_new_opens=False)
        if any(mstu_adj_pnl(t) >= MIN_HARVEST for t in closes_by_time.get(dt_stamp(order.traded_at), [])):
            harvested = True
        if winners:
            lock_days.add(session.isoformat())

    spray_tr = [
        t
        for t in official
        if (t.symbol, dt_stamp(t.open_datetime)) in blocked_opens
    ]
    sim_tr = [
        t
        for t in official
        if (t.symbol, dt_stamp(t.open_datetime)) not in blocked_opens
    ]
    spray_by: dict[str, float] = defaultdict(float)
    for t in spray_tr:
        spray_by[t.underlying or t.symbol] += mstu_adj_pnl(t)
    spray_items = [(k, round(v, 2)) for k, v in spray_by.items()]

    blocked_by_und: dict[str, int] = defaultdict(int)
    blocked_by_lock: dict[str, int] = defaultdict(int)
    blocked_by_day: dict[str, int] = defaultdict(int)
    for row in blocked:
        blocked_by_und[row["underlying"]] += 1
        blocked_by_day[row["session"]] += 1
        for name in row["lock"]:
            blocked_by_lock[name] += 1
        if row["harvested"] and not row["lock"]:
            blocked_by_lock["[harvest-flat]"] += 1

    day_826 = [row for row in blocked if row["session"] == "2026-08-26"]
    return {
        "mode": mode,
        "fills_blocked": len(blocked),
        "fills_kept": len(orders) - len(blocked),
        "lock_sessions": len(lock_days),
        "sim": bucket_stats(sim_tr),
        "spray": bucket_stats(spray_tr),
        "sim_equity": by_kind(sim_tr, "EQUITY"),
        "sim_option": by_kind(sim_tr, "OPTION"),
        "sim_call": by_kind(sim_tr, "CALL"),
        "sim_put": by_kind(sim_tr, "PUT"),
        "monthly": monthly(sim_tr),
        "spray_hurt": dict(sorted(spray_items, key=lambda kv: kv[1])[:10]),
        "spray_helped": dict(sorted(spray_items, key=lambda kv: -kv[1])[:8]),
        "blocked_by_entry": dict(sorted(blocked_by_und.items(), key=lambda kv: -kv[1])[:12]),
        "blocked_by_winner": dict(sorted(blocked_by_lock.items(), key=lambda kv: -kv[1])[:12]),
        "blocked_busiest_days": dict(sorted(blocked_by_day.items(), key=lambda kv: -kv[1])[:8]),
        "aug26_blocked_n": len(day_826),
        "aug26_blocked": [
            {
                "clock": row["clock"],
                "name": row["label"] or row["underlying"],
                "lock": row["lock"],
                "harvested": row["harvested"],
            }
            for row in day_826[:24]
        ],
    }


def main() -> None:
    orders = load_orders()
    und_closes = load_underlying_closes()
    actual = analyze_orders(orders, settle_expirations=True)
    act_tr = [t for t in actual.realized_trades if in_year(t)]
    actual_stats = {
        "actual": bucket_stats(act_tr),
        "actual_equity": by_kind(act_tr, "EQUITY"),
        "actual_option": by_kind(act_tr, "OPTION"),
        "actual_call": by_kind(act_tr, "CALL"),
        "actual_put": by_kind(act_tr, "PUT"),
        "monthly_actual": monthly(act_tr),
        "fills_in": len(orders),
    }

    modes = {
        "hold": simulate(
            orders,
            und_closes,
            act_tr,
            use_hold=True,
            use_harvest=False,
            lookback=True,
            min_cost=MIN_COST,
            mode="hold",
        ),
        "harvest": simulate(
            orders,
            und_closes,
            act_tr,
            use_hold=False,
            use_harvest=True,
            lookback=True,
            min_cost=MIN_COST,
            mode="harvest",
        ),
        "combined": simulate(
            orders,
            und_closes,
            act_tr,
            use_hold=True,
            use_harvest=True,
            lookback=True,
            min_cost=MIN_COST,
            mode="combined",
        ),
        "naive": simulate(
            orders,
            und_closes,
            act_tr,
            use_hold=True,
            use_harvest=False,
            lookback=False,
            min_cost=0.0,
            mode="naive",
        ),
    }

    payload = {
        "range": "2026-01-02 to 2026-08-27",
        "rule_hold": (
            f"Overnight lots opened in the last {LOOKBACK_DAYS} days, cost >= ${MIN_COST:.0f}, "
            f"prior-session mark > ${MIN_MARK:.0f} lock the book to that underlying. "
            "Exits always allowed. Same-day opens never count as winning. Options expire off the lock."
        ),
        "rule_harvest": (
            f"After a realized close >= ${MIN_HARVEST:.0f} this session, no new underlyings "
            "for the rest of the day unless a working overnight winner is still open."
        ),
        "related": "same underlying (stock and options)",
        "mstu": "1-for-10 reverse split applied to open lots on 2026-08-24; realized PnL restated",
        **actual_stats,
    }
    for name, result in modes.items():
        result["delta"] = round(result["sim"]["pnl"] - actual_stats["actual"]["pnl"], 2)
        payload[name] = result
        print(name.upper())
        recon = round(result["sim"]["pnl"] + result["spray"]["pnl"], 2)
        print(
            f"  kept {result['fills_kept']} blocked {result['fills_blocked']} "
            f"sim {result['sim']['pnl']} spray {result['spray']['pnl']} "
            f"delta {result['delta']} recon {recon} vs {actual_stats['actual']['pnl']} "
            f"aug26 blocked {result['aug26_blocked_n']}"
        )
        print("  blocked entries", result["blocked_by_entry"])
        print("  locked by", result["blocked_by_winner"])
        print("  spray hurt", result["spray_hurt"])
        print("  spray helped", result["spray_helped"])
        print("  aug26", result["aug26_blocked"][:10])

    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
