"""Break gated T0 skips and same-day option scratches by put vs call."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from simulate_spot_then_options_h1 import (
    H1_END,
    Y0,
    Y1,
    analyze_orders,
    cluster_sessions,
    close_session,
    favorable_move,
    is_option_open,
    load_bars,
    load_orders,
    mstu_adj_pnl,
    next_session,
    ny_session,
    open_session,
    stock_side,
)

NY = ZoneInfo("America/New_York")


def stats(trades) -> dict:
    if not trades:
        return {"n": 0, "pnl": 0.0, "wr": 0.0}
    pnls = [mstu_adj_pnl(t) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    return {"n": len(trades), "pnl": round(sum(pnls), 0), "wr": round(wins / len(pnls), 3)}


def same_day(t) -> bool:
    return open_session(t) == close_session(t)


def main() -> None:
    orders = load_orders()
    bars = load_bars()
    official = [
        t
        for t in analyze_orders(orders, settle_expirations=True).realized_trades
        if Y0 <= close_session(t) <= Y1
    ]
    opt = [t for t in official if t.instrument_type == "OPTION"]
    h1_opt = [t for t in opt if close_session(t) <= H1_END]

    print("=== YTD options ===")
    for kind in ("CALL", "PUT"):
        sub = [t for t in opt if t.option_type == kind]
        same = [t for t in sub if same_day(t)]
        ovn = [t for t in sub if not same_day(t)]
        scratch = [t for t in same if abs(mstu_adj_pnl(t)) < 100]
        print(kind, "all", stats(sub), "same", stats(same), "ovn", stats(ovn), "same |pnl|<100", stats(scratch))

    print("=== H1 options ===")
    for kind in ("CALL", "PUT"):
        sub = [t for t in h1_opt if t.option_type == kind]
        same = [t for t in sub if same_day(t)]
        ovn = [t for t in sub if not same_day(t)]
        scratch = [t for t in same if abs(mstu_adj_pnl(t)) < 100]
        print(kind, "all", stats(sub), "same", stats(same), "ovn", stats(ovn), "same |pnl|<100", stats(scratch))

    option_orders = [o for o in orders if o.instrument_type == "OPTION" and Y0 <= ny_session(o) <= Y1]
    by_und: dict[str, list] = defaultdict(list)
    for order in option_orders:
        by_und[order.underlying].append(order)

    t0_windows: list[tuple[str, date, date | None, bool, str]] = []
    fail_windows: list[tuple[str, date, date]] = []
    delayed_windows: dict[str, list[tuple[date, date]]] = defaultdict(list)

    for und, und_orders in by_und.items():
        und_orders.sort(key=lambda o: o.traded_at or datetime.min)
        chain = bars.get(und, {})
        for group in cluster_sessions([ny_session(o) for o in und_orders]):
            t0, end = group[0], group[-1]
            if t0 > H1_END:
                continue
            first_open = next((o for o in und_orders if ny_session(o) == t0 and is_option_open(o)), None)
            if first_open is None:
                continue
            t0_bar = chain.get(t0)
            if t0_bar is None or t0_bar.o <= 0:
                continue
            side = stock_side(first_open)
            confirmed = favorable_move(side, t0_bar.o, t0_bar.c)
            t1 = next_session(t0, chain)
            t0_windows.append((und, t0, t1, confirmed, first_open.option_type))
            if confirmed and t1:
                delayed_windows[und].append((t1, end))
            else:
                fail_windows.append((und, t0, end))

    def is_delayed(t) -> bool:
        opened = open_session(t)
        for start, end in delayed_windows.get(t.underlying or t.symbol, []):
            if start <= opened <= end:
                return True
        return False

    def in_fail(t) -> bool:
        opened = open_session(t)
        for und, t0, end in fail_windows:
            if (t.underlying or t.symbol) == und and t0 <= opened <= end:
                return True
        return False

    def is_t0(t) -> bool:
        opened = open_session(t)
        for und, t0, _t1, _c, _k in t0_windows:
            if (t.underlying or t.symbol) == und and opened == t0:
                return True
        return False

    skipped = [t for t in opt if (is_t0(t) or in_fail(t)) and not is_delayed(t)]
    t0_lots = [t for t in opt if is_t0(t)]
    print("=== H1 cluster T0 lots (open on cluster start) ===")
    for kind in ("CALL", "PUT"):
        sub = [t for t in t0_lots if t.option_type == kind]
        same = [t for t in sub if same_day(t)]
        ovn = [t for t in sub if not same_day(t)]
        print(kind, "all", stats(sub), "same-day", stats(same), "held ovn", stats(ovn))

    print("=== first impulse of each H1 cluster ===")
    first_by = defaultdict(lambda: {"n": 0, "confirmed": 0})
    for _und, _t0, _t1, confirmed, kind in t0_windows:
        first_by[kind]["n"] += 1
        if confirmed:
            first_by[kind]["confirmed"] += 1
    print(dict(first_by))

    focus = ("MU", "MSTR", "CAR", "IREN", "QCOM", "GLD", "UAL")
    print("=== T0 lots by name x type ===")
    for name in focus:
        lots = [t for t in t0_lots if (t.underlying or t.symbol) == name]
        for kind in ("CALL", "PUT"):
            sub = [t for t in lots if t.option_type == kind]
            if sub:
                print(name, kind, stats(sub), "same", stats([t for t in sub if same_day(t)]), "ovn", stats([t for t in sub if not same_day(t)]))

    print("=== skipped (T0 + failed clusters) by type ===")
    for kind in ("CALL", "PUT"):
        print(kind, stats([t for t in skipped if t.option_type == kind]))

    # Same-day put scratches vs large same-day put wins YTD
    puts_sd = [t for t in opt if t.option_type == "PUT" and same_day(t)]
    bins = [(-1e9, -500), (-500, -100), (-100, 0), (0, 100), (100, 500), (500, 1e9)]
    print("=== YTD same-day PUT pnl bins ===")
    for a, b in bins:
        sub = [t for t in puts_sd if a <= mstu_adj_pnl(t) < b]
        print(f"{a:.0f}..{b:.0f}", stats(sub))
    calls_sd = [t for t in opt if t.option_type == "CALL" and same_day(t)]
    print("=== YTD same-day CALL pnl bins ===")
    for a, b in bins:
        sub = [t for t in calls_sd if a <= mstu_adj_pnl(t) < b]
        print(f"{a:.0f}..{b:.0f}", stats(sub))


if __name__ == "__main__":
    main()
