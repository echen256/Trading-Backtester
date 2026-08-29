"""H1 2026: $5k spot first on option-led campaigns, options only after stock confirms."""
from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_analysis.parse_orders import (
    FILLED_STATUSES,
    OPTION_CONTRACT_RE,
    Order,
    _normalize_instrument_type,
    _reconcile_order_action,
    analyze_orders,
)

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
ORDER_DIR = Path(__file__).resolve().parents[1] / "order-data"
CACHE_UND = ORDER_DIR / "market-data-cache" / "underlying" / "1d"
OUT_JSON = ORDER_DIR / "spot-then-options-h1-2026.json"
H1_END = date(2026, 6, 30)
Y0, Y1 = date(2026, 1, 1), date(2026, 8, 27)
SPOT_NOTIONAL = 5000.0
CONFIRM_PCT = 0.005  # 0.5% in the trade's favor by T0 close
PRIOR_STOCK_DAYS = 21
FILES = [
    "webull_orders_2026.csv",
    "webull_orders_2026-06-01_to_2026-08-12.csv",
    "webull_orders_2026-08-07_to_2026-08-19.csv",
    "webull_orders_2026-08-10_to_2026-08-26.csv",
    "webull_orders_2026-08-25_to_2026-08-27.csv",
    "webull_orders_2026-08-25_to_2026-08-28.csv",
]


@dataclass
class Bar:
    o: float
    c: float


@dataclass
class Campaign:
    underlying: str
    side: str  # long | short
    t0: date
    entry: float
    shares: int
    confirmed: bool
    confirm_on: date | None
    exit_date: date | None
    exit_px: float | None
    stock_pnl: float
    skip_reason: str
    first_option: str
    already_had_stock: bool = False
    option_fills_kept: int = 0


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
        has_valid = order.instrument_type != "OPTION" or OPTION_CONTRACT_RE.fullmatch(order.symbol)
        if (
            order.status in FILLED_STATUSES
            and order.quantity > 0
            and order.trade_price is not None
            and order.trade_date is not None
            and has_valid
        ):
            eligible.append(_reconcile_order_action(order))
    eligible.sort(key=lambda o: o.traded_at or datetime.min)
    return eligible


def bar_date(ts_ms: float) -> date:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(NY).date()


def load_bars() -> dict[str, dict[date, Bar]]:
    out: dict[str, dict[date, Bar]] = {}
    if not CACHE_UND.exists():
        return out
    for path in CACHE_UND.glob("*.json"):
        payload = json.loads(path.read_text())
        by_date: dict[date, Bar] = {}
        for raw in payload.get("results") or []:
            try:
                by_date[bar_date(float(raw["t"]))] = Bar(o=float(raw["o"]), c=float(raw["c"]))
            except (KeyError, TypeError, ValueError):
                continue
        out[path.stem.upper()] = by_date
    return out


def ny_session(order: Order) -> date:
    traded = order.traded_at
    if traded is None:
        return order.trade_date or date.min
    if traded.tzinfo is None:
        traded = traded.replace(tzinfo=UTC)
    return traded.astimezone(NY).date()


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


def next_session(session: date, bars: dict[date, Bar]) -> date | None:
    later = [d for d in bars if d > session]
    return min(later) if later else None


def last_session_on_or_before(session: date, bars: dict[date, Bar]) -> date | None:
    prior = [d for d in bars if d <= session]
    return max(prior) if prior else None


def stock_side(order: Order) -> str:
    """Align $5k spot with the first option's direction."""
    if order.option_type == "CALL":
        return "long" if order.action in {"BTO", "BUY"} else "short"
    if order.option_type == "PUT":
        return "short" if order.action in {"BTO", "BUY"} else "long"
    return "long" if order.side == "BUY" else "short"


def is_option_open(order: Order) -> bool:
    if order.instrument_type != "OPTION":
        return False
    return order.action in {"BTO", "STO"} or (
        order.action not in {"BTC", "STC"} and order.side in {"BUY", "SELL"}
    )


def signed_option_delta(order: Order) -> float:
    if order.instrument_type != "OPTION":
        return 0.0
    if order.action == "BTO":
        return order.quantity
    if order.action == "STC":
        return -order.quantity
    if order.action == "STO":
        return order.quantity
    if order.action == "BTC":
        return -order.quantity
    if order.side == "BUY":
        return order.quantity
    if order.side == "SELL":
        return -order.quantity
    return 0.0


def mstu_adj_pnl(trade) -> float:
    return trade.pnl


def bucket(trades) -> dict:
    if not trades:
        return {"n": 0, "pnl": 0.0, "wr": 0.0, "same_day_n": 0, "same_day_pnl": 0.0, "ovn_n": 0, "ovn_pnl": 0.0}
    pnls = [mstu_adj_pnl(t) for t in trades]
    same = [t for t in trades if open_session(t) == close_session(t)]
    ovn = [t for t in trades if open_session(t) != close_session(t)]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": len(trades),
        "pnl": round(sum(pnls), 2),
        "wr": round(wins / len(trades), 4),
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


def had_stock_recently(und: str, session: date, equity_sessions: dict[str, list[date]]) -> bool:
    prior = [d for d in equity_sessions.get(und, []) if d < session]
    if not prior:
        return False
    return (session - max(prior)).days <= PRIOR_STOCK_DAYS


def favorable_move(side: str, entry: float, mark: float) -> bool:
    if entry <= 0:
        return False
    if side == "long":
        return (mark / entry) - 1.0 >= CONFIRM_PCT
    return (entry / mark) - 1.0 >= CONFIRM_PCT if mark > 0 else False


def stock_pnl(side: str, shares: int, entry: float, exit_px: float) -> float:
    if side == "long":
        return (exit_px - entry) * shares
    return (entry - exit_px) * shares


GAP_DAYS = 7


def cluster_sessions(sessions: list[date]) -> list[list[date]]:
    if not sessions:
        return []
    uniq = sorted(set(sessions))
    groups: list[list[date]] = [[uniq[0]]]
    for day in uniq[1:]:
        if (day - groups[-1][-1]).days <= GAP_DAYS:
            groups[-1].append(day)
        else:
            groups.append([day])
    return groups


def main() -> None:
    orders = load_orders()
    bars = load_bars()
    result = analyze_orders(orders, settle_expirations=True)
    official = [t for t in result.realized_trades if Y0 <= close_session(t) <= Y1]
    h1_official = [t for t in official if close_session(t) <= H1_END]
    h1_opt = [t for t in h1_official if t.instrument_type == "OPTION"]
    h1_eq = [t for t in h1_official if t.instrument_type == "EQUITY"]

    equity_sessions: dict[str, list[date]] = defaultdict(list)
    for order in orders:
        if order.instrument_type == "EQUITY":
            equity_sessions[order.underlying].append(ny_session(order))

    option_orders = [
        o for o in orders if o.instrument_type == "OPTION" and Y0 <= ny_session(o) <= Y1
    ]
    by_und: dict[str, list[Order]] = defaultdict(list)
    for order in option_orders:
        by_und[order.underlying].append(order)

    campaigns: list[Campaign] = []
    for und, und_orders in by_und.items():
        und_orders.sort(key=lambda o: o.traded_at or datetime.min)
        clusters = cluster_sessions([ny_session(o) for o in und_orders])
        chain = bars.get(und, {})
        for group in clusters:
            t0, end = group[0], group[-1]
            if t0 > H1_END:
                continue
            first_open = next((o for o in und_orders if ny_session(o) == t0 and is_option_open(o)), None)
            if first_open is None:
                first_open = next((o for o in und_orders if ny_session(o) == t0), und_orders[0])
            already_had_stock = had_stock_recently(und, t0, equity_sessions)
            t0_bar = chain.get(t0)
            if t0_bar is None:
                campaigns.append(
                    Campaign(
                        underlying=und,
                        side=stock_side(first_open),
                        t0=t0,
                        entry=0.0,
                        shares=0,
                        confirmed=False,
                        confirm_on=None,
                        exit_date=end,
                        exit_px=None,
                        stock_pnl=0.0,
                        skip_reason="no_daily_bar",
                        first_option=first_open.symbol,
                        already_had_stock=already_had_stock,
                    )
                )
                continue
            side = stock_side(first_open)
            entry = t0_bar.o
            shares = int(SPOT_NOTIONAL // entry) if entry > 0 else 0
            if shares <= 0:
                campaigns.append(
                    Campaign(
                        underlying=und,
                        side=side,
                        t0=t0,
                        entry=entry,
                        shares=0,
                        confirmed=False,
                        confirm_on=None,
                        exit_date=t0,
                        exit_px=t0_bar.c,
                        stock_pnl=0.0,
                        skip_reason="price_gt_5000",
                        first_option=first_open.symbol,
                        already_had_stock=already_had_stock,
                    )
                )
                continue
            confirmed = favorable_move(side, entry, t0_bar.c)
            t1 = next_session(t0, chain)
            if not confirmed:
                campaigns.append(
                    Campaign(
                        underlying=und,
                        side=side,
                        t0=t0,
                        entry=entry,
                        shares=shares,
                        confirmed=False,
                        confirm_on=None,
                        exit_date=t0,
                        exit_px=t0_bar.c,
                        stock_pnl=round(stock_pnl(side, shares, entry, t0_bar.c), 2),
                        skip_reason="failed_t0_close",
                        first_option=first_open.symbol,
                        already_had_stock=already_had_stock,
                    )
                )
                continue
            end_bar = chain.get(end) or chain.get(last_session_on_or_before(end, chain) or t0)
            exit_px = end_bar.c if end_bar else t0_bar.c
            campaigns.append(
                Campaign(
                    underlying=und,
                    side=side,
                    t0=t0,
                    entry=entry,
                    shares=shares,
                    confirmed=True,
                    confirm_on=t1,
                    exit_date=end,
                    exit_px=exit_px,
                    stock_pnl=round(stock_pnl(side, shares, entry, exit_px), 2),
                    skip_reason="",
                    first_option=first_open.symbol,
                    already_had_stock=already_had_stock,
                )
            )

    windows: dict[str, list[tuple[date, date]]] = defaultdict(list)
    for camp in campaigns:
        if camp.confirmed and camp.confirm_on and camp.exit_date:
            windows[camp.underlying].append((camp.confirm_on, camp.exit_date))

    def in_window(trade) -> bool:
        if trade.instrument_type != "OPTION":
            return False
        und = trade.underlying or trade.symbol
        opened = open_session(trade)
        for start, end in windows.get(und, []):
            if start <= opened <= end:
                return True
        return False

    delayed_opt = [t for t in official if in_window(t)]
    actual_windows: dict[str, list[tuple[date, date]]] = defaultdict(list)
    for camp in campaigns:
        end = camp.exit_date or camp.t0
        actual_windows[camp.underlying].append((camp.t0, end))

    def in_actual_campaign(trade) -> bool:
        if trade.instrument_type != "OPTION":
            return False
        und = trade.underlying or trade.symbol
        opened = open_session(trade)
        for start, end in actual_windows.get(und, []):
            if start <= opened <= end:
                return True
        return False

    actual_campaign_opt = [t for t in official if in_actual_campaign(t)]
    skipped_opt = [t for t in actual_campaign_opt if t not in delayed_opt]

    by_name_actual: dict[str, float] = defaultdict(float)
    by_name_delayed: dict[str, float] = defaultdict(float)
    by_name_skipped: dict[str, float] = defaultdict(float)
    by_name_stock: dict[str, float] = defaultdict(float)
    for t in actual_campaign_opt:
        by_name_actual[t.underlying or t.symbol] += mstu_adj_pnl(t)
    for t in delayed_opt:
        by_name_delayed[t.underlying or t.symbol] += mstu_adj_pnl(t)
    for t in skipped_opt:
        by_name_skipped[t.underlying or t.symbol] += mstu_adj_pnl(t)
    for camp in campaigns:
        by_name_stock[camp.underlying] += camp.stock_pnl

    h1_by_name: dict[str, float] = defaultdict(float)
    for t in h1_opt:
        h1_by_name[t.underlying or t.symbol] += mstu_adj_pnl(t)

    names = sorted(
        set(by_name_actual) | set(by_name_stock) | set(h1_by_name),
        key=lambda n: -(h1_by_name.get(n, 0) + by_name_stock.get(n, 0)),
    )
    name_rows = []
    for n in names:
        actual = by_name_actual.get(n, 0.0)
        stock = by_name_stock.get(n, 0.0)
        delayed = by_name_delayed.get(n, 0.0)
        skipped = by_name_skipped.get(n, 0.0)
        name_rows.append(
            {
                "name": n,
                "actual_opt": round(actual, 2),
                "h1_opt": round(h1_by_name.get(n, 0.0), 2),
                "skipped_opt": round(skipped, 2),
                "delayed_opt": round(delayed, 2),
                "stock": round(stock, 2),
                "sim": round(delayed + stock, 2),
                "delta": round(delayed + stock - actual, 2),
                "campaigns": sum(1 for c in campaigns if c.underlying == n),
                "confirmed": sum(1 for c in campaigns if c.underlying == n and c.confirmed),
            }
        )

    confirmed = [c for c in campaigns if c.confirmed]
    failed = [c for c in campaigns if c.skip_reason == "failed_t0_close"]
    no_bar = [c for c in campaigns if c.skip_reason == "no_daily_bar"]
    winner_names = {n for n, pnl in h1_by_name.items() if pnl > 0}
    winners_actual = [r for r in name_rows if r["name"] in winner_names]
    winner_sim = sum(r["sim"] for r in winners_actual)
    winner_actual = sum(h1_by_name[r["name"]] for r in winners_actual)
    winner_stock = sum(r["stock"] for r in winners_actual)
    winner_delayed = sum(r["delayed_opt"] for r in winners_actual)

    additive_rows = []
    for name in sorted(winner_names, key=lambda n: -h1_by_name[n]):
        und_orders = sorted(by_und.get(name, []), key=lambda o: o.traded_at or datetime.min)
        h1_opens = [o for o in und_orders if ny_session(o) <= H1_END and is_option_open(o)]
        h1_fills = [o for o in und_orders if ny_session(o) <= H1_END]
        if not h1_opens or not h1_fills:
            continue
        first = h1_opens[0]
        t0 = ny_session(first)
        end = ny_session(h1_fills[-1])
        chain = bars.get(name, {})
        t0_bar = chain.get(t0)
        end_bar = chain.get(end) or (chain.get(last_session_on_or_before(end, chain)) if chain else None)
        if t0_bar is None or end_bar is None:
            continue
        side = stock_side(first)
        shares = int(SPOT_NOTIONAL // t0_bar.o) if t0_bar.o > 0 else 0
        if shares <= 0:
            continue
        pnl = round(stock_pnl(side, shares, t0_bar.o, end_bar.c), 2)
        additive_rows.append(
            {
                "name": name,
                "h1_opt": round(h1_by_name[name], 2),
                "side": side,
                "t0": t0.isoformat(),
                "end": end.isoformat(),
                "shares": shares,
                "entry": round(t0_bar.o, 2),
                "exit": round(end_bar.c, 2),
                "stock": pnl,
                "combined": round(h1_by_name[name] + pnl, 2),
            }
        )
    additive_stock = round(sum(r["stock"] for r in additive_rows), 2)
    additive_combined = round(sum(r["combined"] for r in additive_rows), 2)

    # Peak concurrent $5k
    events: list[tuple[date, int]] = []
    for c in campaigns:
        if c.shares <= 0:
            continue
        events.append((c.t0, 1))
        if c.exit_date:
            events.append((c.exit_date, -1))
    events.sort()
    peak = cur = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)

    stock_monthly: dict[str, float] = defaultdict(float)
    for c in campaigns:
        d = c.exit_date or c.t0
        stock_monthly[d.strftime("%Y-%m")] += c.stock_pnl
    opt_monthly = monthly(delayed_opt)
    sim_monthly = {
        m: round(opt_monthly.get(m, 0.0) + stock_monthly.get(m, 0.0), 2)
        for m in sorted(set(opt_monthly) | set(stock_monthly))
        if m <= "2026-06"
    }
    actual_h1_monthly = monthly(h1_opt)

    payload = {
        "range": "H1 2026 option clusters (Jan 1–Jun 30 start). $5k spot at first option, options only after T0 confirms.",
        "rule": (
            f"Cluster option fills in a name (gap > {GAP_DAYS}d starts a new campaign). "
            f"Buy/short ${SPOT_NOTIONAL:.0f} of the common at that session's open. Skip T0 options. "
            f"Confirm if T0 close is ≥ {CONFIRM_PCT:.1%} in favor. Then replay actual option opens from the next session "
            "through the last fill in the cluster. Failed T0: scratch stock at the close, no options. "
            "Calls → long stock, long puts → short stock."
        ),
        "h1_actual_options": bucket(h1_opt),
        "h1_actual_equity": bucket(h1_eq),
        "h1_actual_total": bucket(h1_official),
        "campaigns": len(campaigns),
        "confirmed": len(confirmed),
        "failed_t0": len(failed),
        "no_bar": len(no_bar),
        "failed_t0_stock_pnl": round(sum(c.stock_pnl for c in failed), 2),
        "confirmed_stock_pnl": round(sum(c.stock_pnl for c in confirmed), 2),
        "all_stock_pnl": round(sum(c.stock_pnl for c in campaigns), 2),
        "delayed_options": bucket(delayed_opt),
        "skipped_options": bucket(skipped_opt),
        "actual_campaign_options": bucket(actual_campaign_opt),
        "sim_total_pnl": round(sum(c.stock_pnl for c in campaigns) + bucket(delayed_opt)["pnl"], 2),
        "peak_concurrent_names": peak,
        "peak_capital": peak * SPOT_NOTIONAL,
        "winners_only": {
            "names": len(winners_actual),
            "actual_opt": round(winner_actual, 2),
            "stock": round(winner_stock, 2),
            "delayed_opt": round(winner_delayed, 2),
            "sim": round(winner_sim, 2),
            "delta": round(winner_sim - winner_actual, 2),
        },
        "additive_winners": {
            "names": len(additive_rows),
            "h1_opt": round(sum(r["h1_opt"] for r in additive_rows), 2),
            "stock": additive_stock,
            "combined": additive_combined,
        },
        "additive_rows": additive_rows[:16],
        "monthly_actual_h1_opt": actual_h1_monthly,
        "monthly_sim_h1": sim_monthly,
        "monthly_stock": {m: round(v, 2) for m, v in sorted(stock_monthly.items()) if m <= "2026-08"},
        "top_names": name_rows[:20],
        "winner_names": [r for r in name_rows if r["name"] in winner_names and r["h1_opt"] > 200][:15],
        "loser_names": sorted(
            [r for r in name_rows if r["h1_opt"] < -200], key=lambda r: r["h1_opt"]
        )[:12],
        "failed_examples": [
            {
                "name": c.underlying,
                "t0": c.t0.isoformat(),
                "side": c.side,
                "stock_pnl": c.stock_pnl,
                "first_option": c.first_option,
            }
            for c in sorted(failed, key=lambda c: c.stock_pnl)[:12]
        ],
        "confirmed_examples": [
            {
                "name": c.underlying,
                "t0": c.t0.isoformat(),
                "side": c.side,
                "confirm_on": c.confirm_on.isoformat() if c.confirm_on else None,
                "exit": c.exit_date.isoformat() if c.exit_date else None,
                "stock_pnl": c.stock_pnl,
                "shares": c.shares,
                "entry": round(c.entry, 2),
                "exit_px": round(c.exit_px, 2) if c.exit_px else None,
            }
            for c in sorted(confirmed, key=lambda c: -c.stock_pnl)[:15]
        ],
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print("H1 actual opt", payload["h1_actual_options"])
    print("H1 actual eq", payload["h1_actual_equity"])
    print("campaigns", payload["campaigns"], "confirmed", payload["confirmed"], "failed", payload["failed_t0"], "no_bar", payload["no_bar"])
    print("stock all", payload["all_stock_pnl"], "failed scratch", payload["failed_t0_stock_pnl"], "confirmed stock", payload["confirmed_stock_pnl"])
    print("delayed opt", payload["delayed_options"])
    print("skipped opt", payload["skipped_options"])
    print("sim total", payload["sim_total_pnl"], "actual campaign opt", payload["actual_campaign_options"]["pnl"])
    print("winners only gated", payload["winners_only"])
    print("additive winners", payload["additive_winners"])
    print("additive top", payload["additive_rows"][:8])
    print("peak names", peak, "capital", peak * SPOT_NOTIONAL)
    print("top", payload["top_names"][:8])
    print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
