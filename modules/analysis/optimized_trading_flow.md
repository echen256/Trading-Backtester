# Optimized Trading Flow

Combines the VIX/equity decision matrix, realized hold analysis (3,456
long option trades, Jul 2024–Jun 2026), TPO location rules, and the
adaptive-MACD management stack already in this repo.

The old system asked “is this a good setup?” The new system asks, in
order: **what regime am I in, am I allowed this side, is location valid,
is MACD early enough, and what is the hold clock?**

---

## 1. What actually went wrong

The book is not missing ideas. Puts are flat (−$1.1k) and calls are
+$20k. Almost all call profit is **B held 4–14 days**. Almost all put
profit is **F held 0–3 days**. Everything else is a category error.

### Error A — Trading a signal that was not there

Puts in G / Y / B (−$38.5k) and calls in N / R / F.

- G puts invent a threat in a healthy bull.
- B puts fade a repair (same-day B puts alone: −$10.8k).
- N calls fight latent shock (−$8.2k).
- F calls buy the breakdown (Apr 1–7 2025 calls −$3.2k while puts +$35k).

This is the Icarus / spring mix-up in the setup document: fading
euphoria that is still printing HH/HL, or buying panic that has not
exhausted.

### Error B — Right regime, wrong hold

| Book | State | Same-day | Sweet hold | Late hold |
| --- | --- | ---: | ---: | ---: |
| Puts | F | +$17.5k | 1d +$26.5k | 15d+ −$2.3k |
| Puts | H | −$5.1k | 1d +$6.5k | 8–14d −$5.2k |
| Calls | B | −$2.1k | 4–7d +$22.0k | 15d+ flat |
| Calls | G | −$7.3k | 4–7d +$6.3k | 15d+ +$3.0k |

2025 Q2 put losers were 51% same-day scratches (−$18.9k). G calls
scratched the same way. The rulebook already said “let winners run” and
“take 2–5× then re-enter with house money.” The tape says that rule was
applied to the wrong book: F puts were cut correctly; G/B calls were
cut as if they were 0DTE lotteries.

### Error C — Outstaying a completed regime

April 2025 is the teaching month. F paid through Apr 7. From Apr 8 the
state mixed into B and you kept putting (−$15k) instead of flipping to
calls. May was 44/75 put entries in G. The 2026 failure-mode scan
repeats it: April is the first month where scattered, weekend, re-entry,
and overwork all cluster.

Outstayed puts: 83 trades, −$10.2k, 7.8-day average, 46 exits in B.
Hard-mode 15–30 lot names (PLTR, INTC, NVDA) became conviction beta.

### Error D — Location and MACD ignored when the story was loud

TPO rubric: never short the bottom of value. Rulebook: short only at
range tops. Adaptive-MACD: do not continue a run past the 70th
percentile / 75% of the prior impulse peak. The expensive F call knives
and B put fades are exactly “short the hole” and “buy the climax.”

N puts (−$13.5k when F never printed) treated VIX higher-lows as a
directional short instead of cheap, timed convexity. That violates both
the N playbook and MACD counter-trend hard-exit (~day 9, and in this
book day 3–4 was already enough).

---

## 2. Session flow

```
1. Own the thesis          setup_process §1
2. Classify regime         G Y R H D N F B from QQQ + VIX
3. Direction permission    table below — if denied, stop
4. Location                TPO extreme; shorts at VAH / range top
5. Adaptive MACD clock     continuation only if Fresh/Developed
6. Express                 ≤30 DTE tactical; size from ATR + regime
7. Hold clock              table below — not “see what happens”
8. Exit stack              regime flip > MACD decel > structure > clock
9. Book hygiene            no same-name revenge, no overwork of a paid F/B
```

### Direction permission

| State | Calls | Puts | Size |
| --- | --- | --- | --- |
| G | Yes — pullbacks, hold ≥4d | No | Full allowed |
| Y | No new. Wait, then attack | No new | Flat event risk |
| R | No | Yes — stay with red MACD | Trend size |
| H | Yes 3–7d | Yes 3–7d | 1/3, no 10+ lot conviction |
| D | Leaders only | Weak names only | Short duration |
| N | No | Convexity only | Small; cut if no F by day 4 |
| F | No | Yes if structure intact; no 0DTE chase after a ≥5% 3-day dump | Manage existing |
| B | Yes — the relever | No — cover | Build toward G |

### Hold clock (from this book)

| State | Put clock | Call clock |
| --- | --- | --- |
| F | 0–3d. Cover on B print. Hard stop >7d | Do not enter |
| B | Do not enter | **4–14d**. This is the call edge |
| G | Do not enter | **≥4d**. Same-day G is a leak |
| H | 1–7d. No 0d lotteries, no 8d+ | 4–7d only |
| N | 1–4d convexity. Dead if no F | Do not enter |
| R | While red MACD; hard exit ~day 9 or B | Do not enter |
| Y | Do not enter | After resolution only, 2–7d |
| D | 4–7d on weak names | 4–7d on leaders |

### Adaptive MACD overlay (existing manager + distribution framework)

Use the weekly/3D adaptive MACD already in `levered_trend_following_rules.md`
and the run-length rules in `rulebook.md` §VIII.

**Continuation (with color)**

- Fresh (<50% of prior completed MACD peak): allow. Tolerate 3 decelerating bars.
- Developed (50–75%): allow. Tolerate 2 bars. This is the late-OK window.
- Mature (75–100%): no new continuation. Delever on 1 confirmed deceleration.
- Extreme (≥100%): latch. No pyramids. This is the “do not bet on outlier
  run length / >70th percentile” rule.

**Counter-trend (against color)**

- Only legal in H (two-way) or as N convexity.
- Expect 1–4d. Look for flip days 4–8. Hard exit by median ~day 9.
- Never use counter-trend MACD as permission to put in G or call in R/F.

**Regime × MACD authority**

- G / B calls: weekly MACD+signal > 0 (C3 inheritance) is the hold license.
  3D histogram cooling does not exit a weekly inherited trend
  (`composite_trend` C3–C4). Same-day scratches violate this.
- F / R puts: daily/3D red MACD is the stay-with-move license. Weekly
  still green is why you do not size these as crash-of-civilization.
- C5 weekly structure break: flatten the long book regardless of VIX story.

### Exit stack (first true wins)

1. **Regime flip:** F→B cover puts, start calls. B→F cover calls. G→N/R
   delever longs. N→F you may add only if already in the put.
2. **MACD deceleration** per extension table. Removes sleeve, not the
   thesis, unless emergency ATR or C5.
3. **Structure:** weekly lower-high then break of intervening swing low.
4. **Hold clock / DTE.** H >7d is an automatic out. 0–2 DTE is event
   risk, not a swing.
5. **2–5× premium:** scale. Re-enter only with house money, only if
   permission is still yes.

### Book hygiene

From `trade_failure_modes.md`, now with a regime trigger:

- After a paid F week, the next state is usually B. That is a **side
  flip**, not “keep putting the same names.”
- One loss in a name that day ends that name.
- Weekend + ≤7 DTE is a reduced-size event ticket or a flat.

---

## 3. How this would have changed the teaching tapes

- **Apr 1–7 2025:** F + red MACD → puts only, 0–3d. No USO/BABA/GLD calls.
- **Apr 8–30:** B print → cover puts, relever calls, hold 4–14d.
- **May 2025:** G → no puts. Hold existing B/G calls instead of 44 new
  G-state shorts.
- **N that never became F:** cut by day 4. Do not treat VIX blips as
  directional shorts.
- **G call scratches:** illegal. Minimum 4d or a 2× scale, not a same-day
  fade of your own entry.
