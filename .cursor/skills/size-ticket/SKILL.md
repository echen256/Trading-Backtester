---
name: size-ticket
description: >-
  Fetches the live price of a ticker, sizes the position from a stop using
  2% account risk (options debit cap 4%), and runs the swing sanity checklist
  including MACD histogram top/bottom. Use when the user asks to size a
  ticket, size a position, calculate lots/shares, get current price and size,
  or sanity-check a setup against the H2 charter.
---

# Size ticket

Run the sizer. Do not invent a last price or a lot count.

```bash
venv/bin/python -m trading_analysis.position_sizer \
  QQQ --stop 560 --side long --equity 20000
```

From `Trading-Backtester`. Options (premium stop, e.g. 50% of debit):

```bash
venv/bin/python -m trading_analysis.position_sizer QQQ --instrument option --entry 4.80 --stop 2.40 --side long --equity 20000
```

Crypto aliases: `BTC`, `ETH` → Polygon `X:BTCUSD` / `X:ETHUSD`.

## Required inputs

Ask if missing: **symbol**, **stop**, **side** (`long`/`short`). Optional: `--entry`, `--instrument stock|option`, `--equity` (else `TRADING_EQUITY` or `$20,000`), `--risk-pct` (default `0.02`).

Manual charter gates:

```bash
--check hurry=pass --check concurrent_names=pass --check revenge=pass --check harvest_flat=pass
```

`--json` for structured output.

## What it does

1. Polygon last trade.
2. `qty = floor((equity × 2%) / (|entry−stop| × multiplier))`. Options ×100; debit capped at 4% of equity.
3. Checklist `src/trading_analysis/position_sizer/checklists/swing.json`. Add checks there; evaluators in `checklist.py`.
4. Auto MACD on daily 12/26/9 histogram. Fail a long at the top of the histogram; fail a short at the bottom.

If `BLOCKED` or qty 0, do not suggest sending. Pending manuals are not a pass.
