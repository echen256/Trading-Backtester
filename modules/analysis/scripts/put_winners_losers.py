"""Dump 2026 put-trade winner/loser breakdown for the canvas."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from simulate_spot_then_options_h1 import (
    H1_END,
    Y0,
    Y1,
    analyze_orders,
    close_session,
    load_orders,
    open_session,
)

NY = ZoneInfo("America/New_York")
OUT = Path(__file__).resolve().parents[1] / "order-data" / "put-winners-losers-2026.json"


def pnl(t) -> float:
    return t.pnl


def main() -> None:
    official = [
        t
        for t in analyze_orders(load_orders(), settle_expirations=True).realized_trades
        if Y0 <= close_session(t) <= Y1 and t.instrument_type == "OPTION" and t.option_type == "PUT"
    ]

    def pack(trades):
        if not trades:
            return {"n": 0, "pnl": 0.0, "wr": 0.0, "avg": 0.0}
        pnls = [pnl(t) for t in trades]
        wins = [p for p in pnls if p > 0]
        return {
            "n": len(trades),
            "pnl": round(sum(pnls), 2),
            "wr": round(len(wins) / len(pnls), 4),
            "avg": round(sum(pnls) / len(pnls), 2),
        }

    wins = [t for t in official if pnl(t) > 0]
    loss = [t for t in official if pnl(t) <= 0]
    same = [t for t in official if open_session(t) == close_session(t)]
    ovn = [t for t in official if open_session(t) != close_session(t)]

    def by_name(trades):
        agg: dict[str, list] = defaultdict(list)
        for t in trades:
            agg[t.underlying or t.symbol].append(t)
        rows = []
        for name, ts in agg.items():
            w = [x for x in ts if pnl(x) > 0]
            l = [x for x in ts if pnl(x) <= 0]
            sd = [x for x in ts if open_session(x) == close_session(x)]
            ov = [x for x in ts if open_session(x) != close_session(x)]
            rows.append(
                {
                    "name": name,
                    "n": len(ts),
                    "pnl": round(sum(pnl(x) for x in ts), 2),
                    "win_n": len(w),
                    "win_pnl": round(sum(pnl(x) for x in w), 2),
                    "lose_n": len(l),
                    "lose_pnl": round(sum(pnl(x) for x in l), 2),
                    "same_n": len(sd),
                    "same_pnl": round(sum(pnl(x) for x in sd), 2),
                    "ovn_n": len(ov),
                    "ovn_pnl": round(sum(pnl(x) for x in ov), 2),
                }
            )
        rows.sort(key=lambda r: -r["pnl"])
        return rows

    def by_month(trades):
        agg: dict[str, float] = defaultdict(float)
        n: dict[str, int] = defaultdict(int)
        for t in trades:
            m = close_session(t).strftime("%Y-%m")
            agg[m] += pnl(t)
            n[m] += 1
        return {m: {"n": n[m], "pnl": round(agg[m], 2)} for m in sorted(agg)}

    long_puts = [t for t in official if t.direction == "long"]
    short_puts = [t for t in official if t.direction == "short"]

    bins = [
        ("≤ −500", -1e18, -500),
        ("−500 to −100", -500, -100),
        ("−100 to 0", -100, 0),
        ("0 to 100", 0, 100),
        ("100 to 500", 100, 500),
        ("> 500", 500, 1e18),
    ]

    def bin_rows(trades):
        out = []
        for label, a, b in bins:
            sub = [t for t in trades if a <= pnl(t) < b] if b < 1e17 else [t for t in trades if pnl(t) >= a]
            out.append({"bin": label, **pack(sub)})
        return out

    h1 = [t for t in official if close_session(t) <= H1_END]
    h2 = [t for t in official if close_session(t) > H1_END]

    names = by_name(official)
    payload = {
        "range": "2026-01-02 to 2026-08-27",
        "all": pack(official),
        "winners": pack(wins),
        "losers": pack(loss),
        "same_day": pack(same),
        "overnight": pack(ovn),
        "same_day_winners": pack([t for t in same if pnl(t) > 0]),
        "same_day_losers": pack([t for t in same if pnl(t) <= 0]),
        "overnight_winners": pack([t for t in ovn if pnl(t) > 0]),
        "overnight_losers": pack([t for t in ovn if pnl(t) <= 0]),
        "h1": pack(h1),
        "h2": pack(h2),
        "long_puts": pack(long_puts),
        "short_puts": pack(short_puts),
        "monthly": by_month(official),
        "monthly_same": by_month(same),
        "monthly_ovn": by_month(ovn),
        "top_winners": [r for r in names if r["pnl"] > 0][:12],
        "top_losers": sorted([r for r in names if r["pnl"] < 0], key=lambda r: r["pnl"])[:12],
        "ytd_bins": bin_rows(official),
        "same_day_bins": bin_rows(same),
        "overnight_bins": bin_rows(ovn),
        "biggest_win_lots": [
            {
                "name": t.underlying or t.symbol,
                "pnl": round(pnl(t), 2),
                "hold": "same-day" if open_session(t) == close_session(t) else "overnight",
                "open": open_session(t).isoformat(),
                "close": close_session(t).isoformat(),
                "direction": t.direction,
                "symbol": t.symbol,
            }
            for t in sorted(wins, key=lambda x: -pnl(x))[:12]
        ],
        "biggest_lose_lots": [
            {
                "name": t.underlying or t.symbol,
                "pnl": round(pnl(t), 2),
                "hold": "same-day" if open_session(t) == close_session(t) else "overnight",
                "open": open_session(t).isoformat(),
                "close": close_session(t).isoformat(),
                "direction": t.direction,
                "symbol": t.symbol,
            }
            for t in sorted(loss, key=lambda x: pnl(x))[:12]
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print("all", payload["all"])
    print("winners", payload["winners"], "losers", payload["losers"])
    print("same", payload["same_day"], "sd w", payload["same_day_winners"], "sd l", payload["same_day_losers"])
    print("ovn", payload["overnight"], "ov w", payload["overnight_winners"], "ov l", payload["overnight_losers"])
    print("h1", payload["h1"], "h2", payload["h2"])
    print("long", payload["long_puts"], "short", payload["short_puts"])
    print("top win", payload["top_winners"][:8])
    print("top lose", payload["top_losers"][:8])
    print("monthly", payload["monthly"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
