# Discretionary overlay simulation

Local copy of the 2026-08-18 project plan. The Cursor canvas is a view of this; this file is the source of record in the repo.

## Principle

Do not put the model inside the bar loop. A deterministic daily engine applies hard rules and emits decision points. The agent only sees data dated ≤ as-of, writes memory, and may veto / resize / hold. Algo-only is the control. Webull fills are the other control.

## Already in the repo

- FIFO fills: `parse_orders`, CSVs `webull_orders_2024h2.csv`, `2025`, `2026`
- Regime scorer: `evaluate_calls/puts_decision_matrix` + VIX
- Permission and sit-through size: `evaluate_trade`
- Hold clocks and 2–5× scale: `optimized_trading_flow`, `rulebook`
- Management given an entry: `levered_weekly_trend` (ENTER / DELEVER / EXIT JSON)
- Timeframe authority: `composite_trend` C0–C5
- Histogram events: flip vs color-shift, 1-day clock (`analyze_daily_smh_qqq_histogram.py`)
- Live snapshot + VaR: `compliance_monitor`, Webull bridge
- Option daily cache for contracts already traded

The weekly scanner is an event study, not a portfolio. Do not stretch it into a book.

## Three policies, same ledger

Ledger: $20k, gross dollar-delta, one primary theme.

| Run | Entries | Exits / size | Question |
| --- | --- | --- | --- |
| A · Actual book | Webull fills | Webull fills | Baseline path |
| B · Same entries, managed | Webull fills | Algo + optional agent | Would sitting / sizing have helped? |
| C · Autonomous | Signals + agent overlay | Algo + agent | Can the stack trade without clicks? |

A and B need no option-chain simulator. C starts as underlying exposure, then 30–45 DTE calls sized off dollar-delta.

## Decision-point protocol

The engine steps one RTH session. Hard rules fire automatically: denied side, 3× cap, 1-day color-shift scratch, expiration, C5 flatten, one-loss-ends-the-name.

The agent is invoked only when the algo proposes a new theme, a 2× scale, a regime change (F→B, G→N), or a conflict (weekly hold vs 3D dark-blue). Output is structured: `approve | veto | resize | hold` plus a memory patch dated that session.

## Memory

Append-only markdown/JSONL with an `as_of` stamp. Later sessions may read it; earlier ones may not.

- **Causal** — honest walk-forward
- **Hindsight** — today’s lessons applied to 2024 tape, explicitly labeled

Do not dump August 2026 lessons into January 2025 causal memory.

## How the agent is looped in

- **Backtest:** engine writes `sim/decisions/YYYY-MM-DD.json`. Skill `evaluate-sim` reads N points, updates `sim/memory/`, writes actions. Batch in chat, or a `cursor-sdk` agent over that folder.
- **Live:** same objects. `compliance_monitor` already snapshots. A `/loop` at 10:30 / 15:00 ET is the discretionary pass on today’s book.

## Build order

| Phase | Deliverable | Depends on |
| --- | --- | --- |
| 0 | Canonical session ledger + $20k cash, gross delta, one theme | `parse_orders` + daily QQQ/VIX/XLE |
| 1 | Run A vs B on 2024–now (your entries, rule exits/size) | Phase 0 + `evaluate_trade` + hold clocks |
| 2 | Memory store + decision JSONL + `evaluate-sim` skill | Phase 1 |
| 3 | Run C on QQQ, XLE, SMH, GLD daily | `composite_trend` + histogram events + 3× sizer |
| 4 | Live: same objects, compliance monitor + `/loop` | Phase 2–3 |

## Out of v1

0DTE chain replay, tick-level fills, LLM-on-every-bar.

## First milestone

Run B on 2026-08-07 through 2026-08-18 with frozen rules and no agent, then the same week with the agent on decision points only. If that ledger matches the reconstructed week, extend to 2024.
