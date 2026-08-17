"""Score long put trades against the core G/Y/R/H/D/N/F/B decision matrix."""
from __future__ import annotations

import csv
import json
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from trading_analysis.market_data import fetch_underlying_daily_bars, get_polygon_api_key
from trading_analysis.parse_orders import OPTION_CONTRACT_RE, analyze_orders, load_orders

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"

ORDER_DIR = Path(__file__).resolve().parents[1] / "order-data"
OUT_JSON = ORDER_DIR / "put-decision-matrix-review.json"
CONTRACT_RE = OPTION_CONTRACT_RE
INDEX_BETA = {
    "QQQ", "SPY", "IWM", "DIA", "TQQQ", "SQQQ", "SPX", "NDX", "VIX", "UVXY", "VXX",
}
NY = timezone.utc


def parse_bars(raw: list[dict]) -> list[dict]:
    rows = []
    for b in raw:
        ts = datetime.fromtimestamp(float(b["t"]) / 1000, tz=timezone.utc).date()
        rows.append(
            {
                "date": ts,
                "o": float(b["o"]),
                "h": float(b["h"]),
                "l": float(b["l"]),
                "c": float(b["c"]),
            }
        )
    rows.sort(key=lambda r: r["date"])
    return rows


def as_map(rows: list[dict]) -> dict[date, dict]:
    return {r["date"]: r for r in rows}


def nearest_on_or_before(rows: list[dict], day: date) -> dict | None:
    for r in reversed(rows):
        if r["date"] <= day:
            return r
    return None


def idx_on_or_before(rows: list[dict], day: date) -> int | None:
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["date"] <= day:
            return i
    return None


def ret(rows: list[dict], i: int, lookback: int) -> float | None:
    if i < lookback:
        return None
    a, b = rows[i - lookback]["c"], rows[i]["c"]
    if a <= 0:
        return None
    return b / a - 1


def rolling_ext(rows: list[dict], i: int, n: int, field: str, fn) -> float:
    window = rows[max(0, i - n + 1) : i + 1]
    return fn(r[field] for r in window)


def hh_hl(closes: list[float]) -> tuple[bool, bool]:
    if len(closes) < 6:
        return False, False
    mid = len(closes) // 2
    first_hi, second_hi = max(closes[:mid]), max(closes[mid:])
    first_lo, second_lo = min(closes[:mid]), min(closes[mid:])
    return second_hi > first_hi, second_lo > first_lo


def classify_state(qqq: list[dict], vix: list[dict], day: date) -> dict:
    qi = idx_on_or_before(qqq, day)
    vi = idx_on_or_before(vix, day)
    if qi is None or vi is None or qi < 20 or vi < 20:
        return {"state": "H", "reason": "insufficient history", "features": {}}

    q, v = qqq[qi], vix[vi]
    q5 = ret(qqq, qi, 5)
    q10 = ret(qqq, qi, 10)
    q1 = ret(qqq, qi, 1)
    q3 = ret(qqq, qi, 3)
    v5 = ret(vix, vi, 5)
    v10 = ret(vix, vi, 10)
    v1 = ret(vix, vi, 1)
    v3 = ret(vix, vi, 3)

    q20_high = rolling_ext(qqq, qi, 20, "h", max)
    q20_low = rolling_ext(qqq, qi, 20, "l", min)
    q10_high = rolling_ext(qqq, qi, 10, "h", max)
    q10_low = rolling_ext(qqq, qi, 10, "l", min)
    v20_low = rolling_ext(vix, vi, 20, "l", min)
    v20_high = rolling_ext(vix, vi, 20, "h", max)
    v10_low = rolling_ext(vix, vi, 10, "l", min)
    v5_low = rolling_ext(vix, vi, 5, "l", min)
    v5_high = rolling_ext(vix, vi, 5, "h", max)
    v60_low = rolling_ext(vix, vi, min(60, vi + 1), "l", min)

    dist_20h = (q["c"] / q20_high - 1) if q20_high else 0
    dist_20l = (q["c"] / q20_low - 1) if q20_low else 0
    vix_vs_20low = (v["c"] / v20_low - 1) if v20_low else 0
    vix_vs_60low = (v["c"] / v60_low - 1) if v60_low else 0
    vix_off_20h = (v["c"] / v20_high - 1) if v20_high else 0

    q_closes = [r["c"] for r in qqq[qi - 19 : qi + 1]]
    v_closes_10 = [r["c"] for r in vix[max(0, vi - 9) : vi + 1]]
    v_first, v_second = v_closes_10[: len(v_closes_10) // 2], v_closes_10[len(v_closes_10) // 2 :]
    vix_higher_lows = bool(v_second) and min(v_second) > min(v_first) if v_first else False
    q_hh, q_hl = hh_hl(q_closes)
    q_lh, q_ll = (not q_hh), (not q_hl and dist_20l < 0.015)

    range_10 = (q10_high - q10_low) / q["c"] if q["c"] else 0
    chop = range_10 < 0.045 and abs(q10 or 0) < 0.02

    sharp_eq_down = (q1 is not None and q1 <= -0.02) or (q3 is not None and q3 <= -0.035)
    vix_accel = (v1 is not None and v1 >= 0.12) or (v3 is not None and v3 >= 0.20)
    vix_smooth_up = (v5 is not None and v5 >= 0.08) and (v1 is None or v1 < 0.18)
    vix_falling = v5 is not None and v5 <= -0.08
    vix_flat = v5 is not None and abs(v5) < 0.06
    near_highs = dist_20h >= -0.015
    resilient = dist_20h >= -0.03 or (q5 is not None and q5 >= 0)
    equity_down = (q5 is not None and q5 <= -0.015) or (q10 is not None and q10 <= -0.025)
    vix_new_lows = v["c"] <= v20_low * 1.03 and vix_vs_60low < 0.15
    vix_elevated_floor = vix_vs_60low >= 0.20 and v["c"] >= 16.5
    vix_peaked = vix_off_20h <= -0.08 and v5_high >= v20_high * 0.92
    no_new_eq_low = q["l"] > q20_low * 1.008

    features = {
        "qqq_1d": q1,
        "qqq_3d": q3,
        "qqq_5d": q5,
        "qqq_10d": q10,
        "vix": v["c"],
        "vix_1d": v1,
        "vix_5d": v5,
        "dist_20h": dist_20h,
        "vix_higher_lows": vix_higher_lows,
        "vix_vs_60low": vix_vs_60low,
        "chop": chop,
    }

    # Most specific first.
    if sharp_eq_down and vix_accel:
        return {"state": "F", "reason": "sharp equity breakdown + VIX acceleration", "features": features}
    if vix_peaked and no_new_eq_low and (vix_falling or vix_off_20h <= -0.12):
        return {"state": "B", "reason": "VIX peaked/rolling over; equities not making new lows", "features": features}
    if equity_down and q_lh and q_ll and vix_smooth_up and not sharp_eq_down:
        return {"state": "R", "reason": "LH/LL equity + smooth VIX rise", "features": features}
    if equity_down and (vix_flat or vix_falling) and not vix_accel:
        return {"state": "D", "reason": "equities down while VIX flat/down", "features": features}
    if resilient and vix_higher_lows and (v5 is not None and v5 > 0) and vix_vs_20low >= 0.08:
        return {"state": "N", "reason": "equities resilient while VIX builds higher lows", "features": features}
    if near_highs and (vix_higher_lows or (v5 is not None and v5 >= 0) or vix_vs_20low >= 0.10) and not vix_new_lows:
        return {"state": "Y", "reason": "stocks near highs; VIX refuses to fall", "features": features}
    if chop and vix_elevated_floor:
        return {"state": "H", "reason": "overlapping swings + elevated VIX floor", "features": features}
    if q_hh and q_hl and (vix_falling or vix_new_lows) and dist_20h >= -0.04:
        return {"state": "G", "reason": "HH/HL trend + VIX making/holding lows", "features": features}
    if chop or (abs(q10 or 0) < 0.025 and vix_elevated_floor):
        return {"state": "H", "reason": "messy two-way tape", "features": features}
    if q_hh and q_hl:
        return {"state": "G", "reason": "uptrend structure without vol confirmation of stress", "features": features}
    return {"state": "H", "reason": "default two-way / unclassified", "features": features}


def expiration_from_symbol(symbol: str) -> date | None:
    m = CONTRACT_RE.fullmatch(symbol)
    if not m:
        return None
    raw = m.group(2)
    try:
        return datetime.strptime(raw, "%y%m%d").date()
    except ValueError:
        return None


def name_trend(bars: list[dict], day: date) -> str:
    i = idx_on_or_before(bars, day)
    if i is None or i < 15:
        return "unknown"
    r10 = ret(bars, i, 10)
    r20 = ret(bars, i, 20) if i >= 20 else r10
    high20 = rolling_ext(bars, i, 20, "h", max)
    dist = bars[i]["c"] / high20 - 1 if high20 else 0
    if r10 is not None and r10 <= -0.08 and dist <= -0.06:
        return "weak"
    if r20 is not None and r20 <= -0.12:
        return "weak"
    if r10 is not None and r10 >= 0.06 and dist >= -0.03:
        return "strong"
    return "mixed"


def score_put(entry: dict, exit_: dict, trade: dict, name_state: str) -> dict:
    s0, s1 = entry["state"], exit_["state"]
    hold = trade["hold_days"]
    index_put = trade["underlying"] in INDEX_BETA
    dte = trade["dte_at_entry"]

    verdict = "other"
    why = ""

    if s0 == "G":
        verdict = "chase_nonexistent"
        why = "Clean risk-on: playbook is long pullbacks, not puts."
    elif s0 == "Y":
        verdict = "too_early"
        why = "Event divergence: wait for resolution instead of paying put premium."
    elif s0 == "B":
        verdict = "chase_nonexistent"
        why = "Exhaustion/repair: cover shorts and relever, not initiate puts."
    elif s0 == "F":
        q3 = entry["features"].get("qqq_3d") or 0
        if q3 <= -0.05:
            verdict = "chase_extension"
            why = "Forced recognition already extended; new puts chase the obvious move."
        else:
            verdict = "good_swing"
            why = "Forced recognition with structure still intact — follow, don't fade."
    elif s0 == "R":
        verdict = "good_swing"
        why = "Price and vol agree on a correction — short/hedge trend."
    elif s0 == "N":
        verdict = "good_swing"
        why = "Latent shock: proactive convexity is the playbook."
    elif s0 == "D":
        if index_put:
            verdict = "chase_nonexistent"
            why = "Low-vol deleveraging: index crash is not the default. Dispersion only."
        elif name_state == "weak":
            verdict = "good_swing"
            why = "Low-vol tape + already-weak name: short the laggard, not the index."
        else:
            verdict = "too_early"
            why = "Deleveraging without a weak-group confirmation on this name."
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

    # Exit override: good entry that was held into repair / risk-on.
    if verdict == "good_swing" and s1 in {"B", "G"} and hold is not None and hold >= 2:
        if s0 in {"R", "F", "N", "H"}:
            verdict = "outstayed"
            why = f"Entry {s0} was valid, but exit landed in {s1} (cover/relever). Held the fade too long."

    return {
        "verdict": verdict,
        "why": why,
        "entry_state": s0,
        "exit_state": s1,
        "entry_reason": entry["reason"],
        "exit_reason": exit_["reason"],
        "name_trend": name_state,
        "index_put": index_put,
    }


def money(x: float) -> float:
    return round(float(x), 2)


def bucket_stats(rows: list[dict]) -> dict:
    n = len(rows)
    pnl = sum(r["pnl"] for r in rows)
    wins = sum(1 for r in rows if r["pnl"] > 0)
    return {
        "n": n,
        "pnl": money(pnl),
        "win_rate": round(100 * wins / n, 1) if n else None,
        "avg_pnl": money(pnl / n) if n else None,
        "avg_hold": round(sum(r["hold_days"] for r in rows) / n, 2) if n else None,
        "median_pnl": money(sorted(r["pnl"] for r in rows)[n // 2]) if n else None,
    }


def top_examples(rows: list[dict], key: str, n: int = 8, reverse: bool = True) -> list[dict]:
    ranked = sorted(rows, key=lambda r: r[key], reverse=reverse)
    out = []
    for r in ranked[:n]:
        out.append(
            {
                "symbol": r["symbol"],
                "underlying": r["underlying"],
                "open": r["open_date"],
                "close": r["close_date"],
                "hold_days": r["hold_days"],
                "dte": r["dte_at_entry"],
                "qty": r["quantity"],
                "pnl": r["pnl"],
                "entry_state": r["entry_state"],
                "exit_state": r["exit_state"],
                "verdict": r["verdict"],
                "why": r["why"],
                "name_trend": r["name_trend"],
            }
        )
    return out


def load_vix(start: date, end: date) -> tuple[list[dict], str]:
    rows: list[dict] = []
    try:
        with urllib.request.urlopen(CBOE_VIX_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        reader = csv.DictReader(StringIO(text))
        for raw in reader:
            day = datetime.strptime(raw["DATE"], "%m/%d/%Y").date()
            if day < start or day > end:
                continue
            rows.append(
                {
                    "date": day,
                    "o": float(raw["OPEN"]),
                    "h": float(raw["HIGH"]),
                    "l": float(raw["LOW"]),
                    "c": float(raw["CLOSE"]),
                }
            )
        if rows:
            rows.sort(key=lambda r: r["date"])
            return rows, "Cboe VIX_History.csv"
    except Exception as exc:
        print("Cboe VIX fetch failed:", exc)

    local = ORDER_DIR / "vix-daily-cboe-overlay-2024-07-28-to-2026-07-29.csv"
    if local.exists():
        with local.open() as handle:
            for raw in csv.DictReader(handle):
                day = date.fromisoformat(raw["date"])
                if day < start or day > end:
                    continue
                rows.append(
                    {
                        "date": day,
                        "o": float(raw["open"]),
                        "h": float(raw["high"]),
                        "l": float(raw["low"]),
                        "c": float(raw["close"]),
                    }
                )
        if rows:
            rows.sort(key=lambda r: r["date"])
            return rows, local.name
    raise SystemExit("Could not load VIX")


def main() -> None:
    key = get_polygon_api_key()
    if not key:
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
    puts = [
        t
        for t in result.realized_trades
        if t.option_type == "PUT" and t.direction == "long"
    ]
    if not puts:
        raise SystemExit("No long PUT trades found")

    start = min(t.open_date for t in puts) - timedelta(days=90)
    end = max(t.trade_date for t in puts) + timedelta(days=5)

    qqq = parse_bars(fetch_underlying_daily_bars("QQQ", start_date=start, end_date=end, throttle_seconds=0.12))
    vix, vix_ticker = load_vix(start, end)

    underlyings = sorted({t.underlying for t in puts if t.underlying and t.underlying not in INDEX_BETA})
    name_bars: dict[str, list[dict]] = {}
    for i, u in enumerate(underlyings):
        try:
            name_bars[u] = parse_bars(
                fetch_underlying_daily_bars(u, start_date=start, end_date=end, throttle_seconds=0.12)
            )
        except Exception:
            name_bars[u] = []
        if (i + 1) % 15 == 0:
            print(f"names {i+1}/{len(underlyings)}")

    state_cache: dict[date, dict] = {}

    def state_for(day: date) -> dict:
        if day not in state_cache:
            state_cache[day] = classify_state(qqq, vix, day)
        return state_cache[day]

    scored = []
    for t in puts:
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
        rec.update(score_put(entry, exit_, rec, nt))
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

    early_chase = by_verdict["too_early"] + by_verdict["chase_nonexistent"] + by_verdict["chase_extension"]
    clusters = defaultdict(list)
    for r in early_chase:
        clusters[f"{r['open_date'][:7]}|{r['entry_state']}|{r['underlying']}"].append(r)
    cluster_rows = []
    for key, rows in clusters.items():
        month, state, und = key.split("|")
        cluster_rows.append(
            {
                "month": month,
                "entry_state": state,
                "underlying": und,
                **bucket_stats(rows),
            }
        )
    cluster_rows.sort(key=lambda x: x["pnl"])

    # Daily put pnl by entry state for timeline
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

    summary = {
        "source": {
            "orders": [p.name for p in files if p.exists()],
            "equity_proxy": "QQQ",
            "vix_ticker": vix_ticker,
            "range": [min(t.open_date for t in puts).isoformat(), max(t.trade_date for t in puts).isoformat()],
            "matrix": "modules/analysis/decision_matrix.md",
        },
        "n_long_puts": len(scored),
        "total_pnl": money(sum(r["pnl"] for r in scored)),
        "by_verdict": {k: bucket_stats(v) for k, v in sorted(by_verdict.items())},
        "by_entry_state": {k: bucket_stats(v) for k, v in sorted(by_entry.items())},
        "by_month": {k: bucket_stats(v) for k, v in sorted(by_month.items())},
        "examples": {
            "good_swings_best": top_examples(by_verdict["good_swing"], "pnl", 10, True),
            "outstayed_worst": top_examples(by_verdict["outstayed"], "pnl", 10, False),
            "too_early_worst": top_examples(by_verdict["too_early"], "pnl", 10, False),
            "chase_nonexistent_worst": top_examples(by_verdict["chase_nonexistent"], "pnl", 10, False),
            "chase_extension_worst": top_examples(by_verdict["chase_extension"], "pnl", 8, False),
            "early_or_chase_clusters": cluster_rows[:18],
        },
        "timeline": timeline,
        "trades": scored,
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2))
    print("wrote", OUT_JSON)
    print("n", summary["n_long_puts"], "pnl", summary["total_pnl"])
    print("verdicts", json.dumps(summary["by_verdict"], indent=2))
    print("entry", json.dumps(summary["by_entry_state"], indent=2))


if __name__ == "__main__":
    main()
