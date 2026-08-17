"""Score long call trades against the core G/Y/R/H/D/N/F/B decision matrix."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_puts_decision_matrix import (
    INDEX_BETA,
    ORDER_DIR,
    analyze_orders,
    bucket_stats,
    classify_state,
    expiration_from_symbol,
    fetch_underlying_daily_bars,
    get_polygon_api_key,
    load_orders,
    load_vix,
    money,
    name_trend,
    nearest_on_or_before,
    parse_bars,
    top_examples,
)

OUT_JSON = ORDER_DIR / "call-decision-matrix-review.json"


def score_call(entry: dict, exit_: dict, trade: dict, name_state: str) -> dict:
    s0, s1 = entry["state"], exit_["state"]
    hold = trade["hold_days"]
    index_call = trade["underlying"] in INDEX_BETA
    dte = trade["dte_at_entry"]

    verdict = "other"
    why = ""

    if s0 == "G":
        verdict = "good_swing"
        why = "Clean risk-on: long pullbacks and let winners run."
    elif s0 == "B":
        verdict = "good_swing"
        why = "Exhaustion/repair: cover shorts and relever into repaired structure."
    elif s0 == "Y":
        verdict = "too_early"
        why = "Event divergence: stop adding, wait for resolution, then attack."
    elif s0 == "R":
        verdict = "chase_nonexistent"
        why = "Clean correction: price and vol agree down. Calls fade a real trend."
    elif s0 == "N":
        verdict = "chase_nonexistent"
        why = "Latent shock: delever and add put convexity, not calls."
    elif s0 == "F":
        q3 = entry["features"].get("qqq_3d") or 0
        if q3 <= -0.035:
            verdict = "chase_extension"
            why = "Forced recognition still extending. Calls here are a knife-catch. Wait for B."
        else:
            verdict = "too_early"
            why = "Forced recognition just starting. Do not buy the breakdown; wait for B."
    elif s0 == "D":
        if name_state == "strong":
            verdict = "good_swing"
            why = "Low-vol deleveraging: long the leader, not the weak group."
        elif index_call:
            verdict = "too_early"
            why = "Capital is leaving without panic. Index calls fight the bid, not a crash bounce."
        else:
            verdict = "chase_nonexistent"
            why = "Deleveraging + mixed/weak name: catching a laggard, not trading dispersion."
    elif s0 == "H":
        if hold is not None and hold > 7:
            verdict = "outstayed"
            why = "Hard mode allows 3–7D swings; this hold became conviction beta."
        elif (dte is not None and dte <= 2) or (trade["quantity"] >= 10 and abs(trade["pnl"]) > 800):
            verdict = "too_early"
            why = "Hard mode: size/DTE looks like conviction, not a small two-way swing."
        else:
            verdict = "good_swing"
            why = "Hard-mode 3–7D / two-way swing is allowed."

    if verdict == "good_swing" and hold is not None and hold >= 2:
        if s0 == "G" and s1 in {"R", "F", "N"}:
            verdict = "outstayed"
            why = f"Entry G was valid, but exit landed in {s1}. Did not delever when the tape left risk-on."
        elif s0 == "B" and s1 == "F":
            verdict = "outstayed"
            why = "Repair failed and the tape returned to F. The relever was held into a new breakdown."
        elif s0 in {"H", "D"} and s1 in {"R", "F", "N"}:
            verdict = "outstayed"
            why = f"Entry {s0} was a small long, but exit landed in {s1}."

    return {
        "verdict": verdict,
        "why": why,
        "entry_state": s0,
        "exit_state": s1,
        "entry_reason": entry["reason"],
        "exit_reason": exit_["reason"],
        "name_trend": name_state,
        "index_call": index_call,
    }


def main() -> None:
    if not get_polygon_api_key():
        raise SystemExit("POLYGON_API_KEY missing")

    files = [
        ORDER_DIR / "webull_orders_2024h2.csv",
        ORDER_DIR / "webull_orders_2025.csv",
        ORDER_DIR / "webull_orders_2026.csv",
    ]
    orders = []
    for path in files:
        if path.exists():
            orders.extend(load_orders(path))
    result = analyze_orders(orders)
    calls = [
        t
        for t in result.realized_trades
        if t.option_type == "CALL" and t.direction == "long"
    ]
    if not calls:
        raise SystemExit("No long CALL trades found")

    start = min(t.open_date for t in calls) - timedelta(days=90)
    end = max(t.trade_date for t in calls) + timedelta(days=5)

    qqq = parse_bars(fetch_underlying_daily_bars("QQQ", start_date=start, end_date=end, throttle_seconds=0.12))
    vix, vix_ticker = load_vix(start, end)

    underlyings = sorted({t.underlying for t in calls if t.underlying and t.underlying not in INDEX_BETA})
    name_bars: dict[str, list] = {}
    for i, u in enumerate(underlyings):
        try:
            name_bars[u] = parse_bars(
                fetch_underlying_daily_bars(u, start_date=start, end_date=end, throttle_seconds=0.12)
            )
        except Exception:
            name_bars[u] = []
        if (i + 1) % 20 == 0:
            print(f"names {i+1}/{len(underlyings)}")

    state_cache: dict = {}

    def state_for(day):
        if day not in state_cache:
            state_cache[day] = classify_state(qqq, vix, day)
        return state_cache[day]

    scored = []
    for t in calls:
        exp = expiration_from_symbol(t.symbol)
        dte = (exp - t.open_date).days if exp else None
        hold = (t.trade_date - t.open_date).days
        entry = state_for(t.open_date)
        exit_ = state_for(t.trade_date)
        nt = name_trend(name_bars.get(t.underlying, []), t.open_date)
        rec = {
            "symbol": t.symbol,
            "underlying": t.underlying,
            "open_date": t.open_date.isoformat(),
            "close_date": t.trade_date.isoformat(),
            "open_price": t.open_price,
            "close_price": t.price,
            "quantity": t.quantity,
            "pnl": money(t.pnl),
            "hold_days": hold,
            "dte_at_entry": dte,
            "expiration": exp.isoformat() if exp else None,
        }
        rec.update(score_call(entry, exit_, rec, nt))
        q_open = nearest_on_or_before(qqq, t.open_date)
        q_close = nearest_on_or_before(qqq, t.trade_date)
        v_open = nearest_on_or_before(vix, t.open_date)
        v_close = nearest_on_or_before(vix, t.trade_date)
        rec["qqq_hold_ret"] = (
            round(q_close["c"] / q_open["c"] - 1, 4) if q_open and q_close else None
        )
        rec["vix_hold_ret"] = (
            round(v_close["c"] / v_open["c"] - 1, 4) if v_open and v_close else None
        )
        scored.append(rec)

    by_verdict = defaultdict(list)
    by_entry = defaultdict(list)
    by_month = defaultdict(list)
    for r in scored:
        by_verdict[r["verdict"]].append(r)
        by_entry[r["entry_state"]].append(r)
        by_month[r["open_date"][:7]].append(r)

    early_chase = (
        by_verdict["too_early"] + by_verdict["chase_nonexistent"] + by_verdict["chase_extension"]
    )
    clusters = defaultdict(list)
    for r in early_chase:
        clusters[f"{r['open_date'][:7]}|{r['entry_state']}|{r['underlying']}"].append(r)
    cluster_rows = []
    for key, rows in clusters.items():
        month, state, und = key.split("|")
        cluster_rows.append({"month": month, "entry_state": state, "underlying": und, **bucket_stats(rows)})
    cluster_rows.sort(key=lambda x: x["pnl"])

    daily = defaultdict(lambda: {"pnl": 0.0, "n": 0, "states": Counter()})
    for r in scored:
        d = daily[r["open_date"]]
        d["pnl"] += r["pnl"]
        d["n"] += 1
        d["states"][r["entry_state"]] += 1
    timeline = [
        {
            "date": day,
            "pnl": money(v["pnl"]),
            "n": v["n"],
            "top_state": v["states"].most_common(1)[0][0],
        }
        for day, v in sorted(daily.items())
    ]

    g_same = [r for r in by_entry.get("G", []) if r["hold_days"] == 0]
    g_held = [r for r in by_entry.get("G", []) if r["hold_days"] >= 2]
    b_after_context = by_entry.get("B", [])
    f_calls = by_entry.get("F", [])

    summary = {
        "source": {
            "orders": [p.name for p in files if p.exists()],
            "equity_proxy": "QQQ",
            "vix_ticker": vix_ticker,
            "range": [
                min(t.open_date for t in calls).isoformat(),
                max(t.trade_date for t in calls).isoformat(),
            ],
            "matrix": "modules/analysis/decision_matrix.md",
        },
        "n_long_calls": len(scored),
        "total_pnl": money(sum(r["pnl"] for r in scored)),
        "by_verdict": {k: bucket_stats(v) for k, v in sorted(by_verdict.items())},
        "by_entry_state": {k: bucket_stats(v) for k, v in sorted(by_entry.items())},
        "by_month": {k: bucket_stats(v) for k, v in sorted(by_month.items())},
        "g_hold_split": {
            "same_day": bucket_stats(g_same),
            "held_2d_plus": bucket_stats(g_held),
        },
        "f_vs_b": {
            "F": bucket_stats(f_calls),
            "B": bucket_stats(b_after_context),
        },
        "examples": {
            "good_swings_best": top_examples(by_verdict.get("good_swing", []), "pnl", 10, True),
            "outstayed_worst": top_examples(by_verdict.get("outstayed", []), "pnl", 10, False),
            "too_early_worst": top_examples(by_verdict.get("too_early", []), "pnl", 10, False),
            "chase_nonexistent_worst": top_examples(by_verdict.get("chase_nonexistent", []), "pnl", 10, False),
            "chase_extension_worst": top_examples(by_verdict.get("chase_extension", []), "pnl", 8, False),
            "f_best": top_examples(f_calls, "pnl", 8, True),
            "f_worst": top_examples(f_calls, "pnl", 8, False),
            "b_best": top_examples(b_after_context, "pnl", 8, True),
            "early_or_chase_clusters": cluster_rows[:18],
        },
        "timeline": timeline,
        "trades": scored,
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2))
    print("wrote", OUT_JSON)
    print("n", summary["n_long_calls"], "pnl", summary["total_pnl"])
    print("verdicts", json.dumps(summary["by_verdict"], indent=2))
    print("entry", json.dumps(summary["by_entry_state"], indent=2))
    print("G hold split", json.dumps(summary["g_hold_split"], indent=2))
    print("F vs B", json.dumps(summary["f_vs_b"], indent=2))


if __name__ == "__main__":
    main()
