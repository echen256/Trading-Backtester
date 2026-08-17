---
name: evaluate-trade
description: >-
  Evaluate a proposed trade's size, option duration, and 1-5 quality rating
  from the G/Y/R/H/D/N/F/B decision matrix, hold clocks, TPO location, and
  sit-through sizing. Use when the user asks to size a ticket, rate a setup,
  evaluate a trade, or calls evaluate_trade with ticker, date, timeframe, and
  direction.
---

# Evaluate Trade

Score a **proposed** ticket before it is placed. This is permission + size +
duration, not a forecast.

## Function

```text
evaluate_trade(ticket, date, timeframe, direction) -> rating, size, duration
```

| Input | Meaning |
| --- | --- |
| `ticket` | Underlying (CRCL, QQQ, XLE) |
| `date` | Intended entry `YYYY-MM-DD` |
| `timeframe` | Intended hold: `0dte`, `3d`, `7d`, `14d`, `30d`, `swing` |
| `direction` | `long`/`call` or `short`/`put` |

Run the scorer after classifying regime (required):

```bash
trading-evaluate-trade CRCL 2026-08-07 10d long --regime H --location mid --macd unknown
```

Python:

```python
from trading_analysis.evaluate_trade import evaluate_trade

evaluate_trade("CRCL", "2026-08-07", "10d", "long", regime="H", location="mid")
```

Optional flags: `--location extreme_with|mid|extreme_against`, `--macd fresh|developed|mature|extreme`, `--weekend`, `--lost-today`, `--lost-week`, `--leader/--no-leader`, `--after-paid-theme`.

## Workflow

1. Classify **regime** from QQQ + VIX + catalyst using `modules/analysis/decision_matrix.md` (G Y R H D N F B). Do not skip this.
2. Check **direction permission** (table below). Denied → rating **1**, size **$0**.
3. Check **location**: longs at prior VAL / range bottom; shorts at prior VAH / range top. Extreme-against → **1**.
4. Check **MACD extension**: fresh/developed allow continuation; mature/extreme → no new add, cap **2**.
5. Map requested timeframe onto the **hold clock**. If the clock and the request disagree, change duration — do not keep an illegal 0DTE.
6. Call `evaluate_trade(...)`.
7. Return the template below. Do not raise the first ticket above sit-through size.

## 5-point rating

| Rating | Label | Meaning |
| ---: | --- | --- |
| **1** | No go | Direction denied, revenge, or catastrophic location. Flat. |
| **2** | Probe only | Legal but fragile: H/D, weekend ≤14D, 0DTE, MACD mature, re-entry. **$500** sit-through. |
| **3** | Standard | Aligned, location OK or mid. **$800**. Hold the clock. |
| **4** | Full size | G/B call or R/F put, location with, MACD not extreme. **$1,200** first ticket. |
| **5** | Double up | 4 plus extreme_with and fresh/developed MACD. First ticket still **$800**. Double only after **2×** with house money (max 2.00x). Never open a $2,500 short-dated flyer. |

## Direction permission

| State | Calls | Puts | Size |
| --- | --- | --- | --- |
| G | Yes — pullbacks, hold ≥4d | No | Full allowed |
| Y | No new. Wait, then attack | No new | Flat event risk |
| R | No | Yes — stay with red MACD | Trend size |
| H | Yes 3–7d | Yes 3–7d | 1/3, no 10+ lot conviction |
| D | Leaders only | Weak names only | Short duration |
| N | No | Convexity only | Small; cut if no F by day 4 |
| F | No | Yes if structure intact | Manage; no 0DTE chase after a ≥5% 3-day dump |
| B | Yes — the relever | No — cover | Build toward G |

## Hold clock → duration

Recommend **DTE that covers the clock**, not the thrill timeframe.

| State | Put clock | Call clock | Instrument DTE |
| --- | --- | --- | --- |
| F | 0–3d. Cover on B. Hard stop >7d | Do not enter | Puts 3–10 DTE |
| B | Do not enter | **4–14d** | Calls 21–30 DTE |
| G | Do not enter | **≥4d** | Calls 21–30 DTE |
| H | 1–7d. No 0d lottery, no 8d+ | 4–7d only | 7–14 DTE |
| N | 1–4d convexity. Dead if no F | Do not enter | Puts 7–14 DTE |
| R | While red MACD; hard exit ~day 9 or B | Do not enter | Puts 7–21 DTE |
| Y | Do not enter | After resolution only, 2–7d | Wait |
| D | 4–7d on weak names | 4–7d on leaders | 7–14 DTE |

## Sizing law (from CRCL 8/7)

Size so the ticket is **holdable through a ~40% MTM**. A valid setup that is oversized becomes a puke, then a flip.

- ≤14 DTE, especially Friday: **$500** unless the function already vetoed.
- H: never 10-lot short-dated conviction.
- Same-day G/B calls: illegal (rating 1).
- After 2–5×: scale. Re-enter only with house money, only if permission is still yes.
- One loss in a name that day ends that name.

## Output template

```markdown
**[TICKET] [DATE] [DIRECTION] [TIMEFRAME]**
- Regime: [state] — permission [yes/no/wait]
- Rating: **N/5 [label]**
- Size: $X — [size_note]
- Duration: [DTE range] (hold clock [clock])
- Why: [2-4 bullets from reasons/vetoes]
```

## Do not

- Invent a regime. If QQQ/VIX/catalyst is missing, ask or mark location/MACD unknown (caps rating).
- Raise size because the story is loud.
- Recommend 0–2 DTE as a G/B call swing.
- Treat a $2,500 10-DTE opener as a 5.

## Examples

See [examples.md](examples.md). Matrix: `modules/analysis/decision_matrix.md`. Flow: `modules/analysis/optimized_trading_flow.md`.
