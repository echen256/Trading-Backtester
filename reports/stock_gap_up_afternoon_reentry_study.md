# Huge gap-up → first-hour runner → afternoon re-entry study

Source: Polygon adjusted one-minute aggregates, RTH only. Cohort: **128** ≥10% gap-ups from **2024-07-29 through 2026-08-11** across 31 selected liquid/high-beta stocks.

## Answer

Under the primary straight-up definition, **8 of 12 (66.7%, 95% Wilson CI 39.1–86.2%)** made a fresh high of day after 13:00.
A ≥1% pullback occurred before that afternoon high in **6 of 12 (50.0%)** primary runners.
The mechanical afternoon 50%-recovery reclaim appeared in **8 of 12 (66.7%)**. Conditional on a signal, **6 of 8 (75.0%, CI 40.9–92.9%)** subsequently cleared the pre-afternoon HOD by at least 10 bps.

## Operational definitions

- **Huge gap:** open ≥10% above the adjusted prior close, prior close ≥$5, session volume ≥1M.
- **First hour:** 09:30–10:29 ET. Primary ‘straight up’ requires return ≥3%, close in the top 25% of the first-hour range, and maximum close-to-running-peak drawdown ≤3%. Minute-path directional efficiency is retained in the event file for further filtering but is not used in the primary rule.
- **Afternoon new HOD:** a 13:00–15:59 bar trades at least 10 bps above the full high-of-day already known at 13:00—not merely above the first-hour high.
- **Pullback chance:** after that pre-afternoon HOD and before the new HOD, price trades at least 1% below the known high. Deeper thresholds are shown separately.
- **Reclaim entry proxy:** from 13:00 through 15:30, after an observed ≥1% pullback, the first close at or above the halfway recovery from the running low to the HOD known at 13:00. The signal uses no future bars; success requires a later bar to clear that HOD by 10 bps.

## Sensitivity

| Runner filter | N | Afternoon new HOD | Pullback then HOD | Reclaim offered | HOD after reclaim | Median entry→close |
|---|---:|---:|---:|---:|---:|---:|
| Loose | 30 | 46.7% (14/30) | 36.7% | 53.3% | 75.0% | +0.6% |
| Primary | 12 | 66.7% (8/12) | 50.0% | 66.7% | 75.0% | +0.5% |
| Strict | 4 | 50.0% (2/4) | 0.0% | 50.0% | 0.0% | -2.0% |

### Pullback depth before the afternoon HOD (primary runners)

| Minimum pullback | Share of all primary runners | Share of afternoon-HOD winners |
|---|---:|---:|
| ≥0.5% | 7/12 (58.3%) | 7/8 (87.5%) |
| ≥1% | 6/12 (50.0%) | 6/8 (75.0%) |
| ≥1.5% | 5/12 (41.7%) | 5/8 (62.5%) |
| ≥2% | 3/12 (25.0%) | 3/8 (37.5%) |
| ≥3% | 2/12 (16.7%) | 2/8 (25.0%) |

For comparison, non-primary gap-ups made an afternoon new HOD **26.7%** of the time (31/116). The primary cohort’s median afternoon HOD time was **13:45 ET**; its median reclaim time was **13:17 ET**.
Of the 8 primary afternoon-HOD events, **5** first broke out from 13:00–13:59, **3** from 14:00–14:59, and **0** after 15:00.

## Entry-path characteristics

Among primary reclaim signals, entry-to-close return averaged **+0.3%** and had a **62.5%** positive-close rate. Median post-entry MFE was **+1.5%** and median MAE was **-0.7%**.
The session closed above the pre-afternoon HOD in **16.7%** of primary cases and within 2% of HOD in **50.0%**.

## Strongest successful reclaim examples

| Ticker | Date | Gap | Signal | Entry→close |
|---|---|---:|---:|---:|
| IREN | 2024-11-11 | 10.6% | 13:44 ET | +2.6% |
| SNDK | 2026-07-30 | 11.7% | 13:00 ET | +2.3% |
| COIN | 2025-05-13 | 11.8% | 13:29 ET | +1.2% |
| PLTR | 2024-11-05 | 15.6% | 13:46 ET | +0.8% |
| CIFR | 2026-07-30 | 11.6% | 13:00 ET | +0.1% |
| MRVL | 2024-12-04 | 17.1% | 13:00 ET | -0.2% |

## Weakest / failed reclaim examples

| Ticker | Date | Gap | Signal | Entry→close |
|---|---|---:|---:|---:|
| MRVL | 2026-03-06 | 11.9% | 14:15 ET | -2.3% |
| NBIS | 2026-05-21 | 10.4% | 13:06 ET | -1.7% |

## Interpretation and limitations

This is an opportunity-frequency study, not a fill-level backtest. The reclaim close omits spread, slippage, halts, and liquidity constraints. The 31-stock universe is selected, and the 12 primary observations represent only 10 tickers and 11 dates; ticker/date clustering makes the nominal Wilson intervals too optimistic. The operational thresholds were selected after an initial feasibility pass showed that a literal straight-line rule left only two events. The results are therefore descriptive rather than confirmatory; the loose/primary/strict tiers expose sensitivity, but an out-of-sample universe is still required.

The practical distinction is important: ‘made a new afternoon HOD’ is not itself an entry rule. The separate reclaim statistic asks whether a known-at-the-time pullback/recovery setup appeared before the later high.
