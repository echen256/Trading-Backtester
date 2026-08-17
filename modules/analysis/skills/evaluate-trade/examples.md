# Evaluate-trade examples

These are teaching cases from the week of 2026-08-10 and the hold study, not forecasts.

## CRCL Friday 8/7 — oversized 10-DTE call (actual)

```bash
trading-evaluate-trade CRCL 2026-08-07 10d long --regime H --location mid
```

Expected:

- Permission yes (H allows small 3–7d calls)
- Rating **2 / Probe only** (Friday + ≤14D event ticket; mid location; H caps conviction)
- Size **$500** sit-through (not $2,487 / 10 lots)
- Duration **7–14 DTE**
- Why: the 72-calls were a valid swing that 2×’d by Tuesday and ~2.15× by Thursday close. The error was size, then the Monday puke and put flip.

A $500 / 2-lot hold was sit-through size through Monday’s $1.40 low.

## CRCL Friday if treated as a G pullback with 30 DTE

```bash
trading-evaluate-trade CRCL 2026-08-07 30d long --regime G --location extreme_with --macd fresh
```

Expected:

- Rating **5 / Double up** only if location and MACD actually qualify
- Size **$800 first ticket**, double after 2× — still not a $2.5k opener
- Duration **21–30 DTE** so the 4–14d G clock is holdable across the weekend

## QQQ 0DTE call in G

```bash
trading-evaluate-trade QQQ 2026-08-10 0dte long --regime G --location mid
```

Expected:

- Rating **1 / No go**
- Size **$0**
- Why: same-day G calls are a leak. Recommend 21–30 DTE or skip.

## F put, structure intact, extreme_with, fresh

```bash
trading-evaluate-trade QQQ 2025-04-03 3d short --regime F --location extreme_with --macd fresh
```

Expected:

- Rating **5 / Double up**
- Size **$800** first, double after 2×
- Duration **3–10 DTE**, hold 0–3d, cover on B
- Not 0DTE chase after a ≥5% 3-day dump

## G put

```bash
trading-evaluate-trade SPY 2026-08-10 7d short --regime G --location extreme_with
```

Expected:

- Rating **1 / No go**
- Puts in G invent a threat that is not there
