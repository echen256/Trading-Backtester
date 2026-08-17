# QQQ gap-day trading rule book

## Scope and definitions

This is an evidence-based intraday decision framework, not a standalone trading system or investment advice. Statistics use QQQ and selected Nasdaq-100 constituents from 2025-04-01 through 2026-08-14. Returns are unlevered, exclude trading costs, and should be revalidated as the market regime changes.

Definitions:

- **Gap up:** QQQ regular-session open is at least 0.5% above the prior close.
- **Strong green day:** QQQ close-to-close return is at least +1.0%.
- **True gap fill after a gap up:** QQQ trades below the prior close between 09:35 and 10:25 ET.
- **Opening retrace:** QQQ trades below the regular-session open between 09:35 and 10:25 ET.
- **Red-to-green:** QQQ opens below the prior close and closes above it.

Use regular-session prices only. Establish the prior close, opening price, and all trigger levels before the open.

## Regime 1 — QQQ gaps up at least 0.5%

### Base expectation

Across 88 qualifying sessions, QQQ averaged -0.07% from open to close. A positive gap therefore does **not** by itself justify chasing the open. MU averaged +0.09% open-to-close, while NBIS averaged -0.71%.

### First-hour decision tree

1. **Do not treat a dip below the open as a failed gap.** It occurred on 85.2% of qualifying sessions, most commonly by 09:35 ET.
2. **If QQQ remains above the prior close, favor continuation/reclaim setups.** After an opening retrace, QQQ subsequently made a new session high 66.7% of the time. A new high followed by a green close occurred 58.7% of the time.
3. **If QQQ trades below the prior close by 10:25 ET, classify it as a true gap failure.** This occurred on 17.0% of qualifying sessions. Reduce or avoid long exposure; do not average into the first breakdown.
4. **On a true gap fill, favor fades, failed reclaims, and capital preservation over dip-buying.** The true-gap-fill sample closed below the opening print 86.7% of the time and closed red versus the prior close 60.0% of the time. Only 20.0% later made a new session high.

### True gap-fill path

The average initial gap was +0.89%. After a true fill, QQQ averaged -0.65% from the open by 10:00, -1.01% by 10:30, about -1.04% at noon, and -0.77% at the close. The average bounce from the fill low to the close was only +0.17%; the median was -0.07%.

**Execution rule:** a new QQQ session high after the fill is the invalidation for a fade thesis. Until then, assume midday consolidation is a pause in a weak session rather than proof of recovery.

## Regime 2 — bullish QQQ close

### Relative-long hierarchy

On 65 strong-green QQQ days, the AI basket beat QQQ by an average 1.97 percentage points and outperformed on 92% of sessions. Hardware was second (+0.96 pp; 74%); software lagged (-0.46 pp; 32%).

Preferred strong-green relative-long list, ordered by average excess return:

| Tier | Names | Evidence on QQQ >= +1% days |
|---|---|---|
| 1 | SNDK, MU, AMD, ARM, MRVL | +2.73 to +4.04 pp average excess; 75% to 82% beat rate |
| 2 | WDC, MSTR, AVGO, STX, MCHP | +1.04 to +2.05 pp average excess; 63% to 72% beat rate |
| 3 | APP, PLTR, NVDA, CRWD | +0.51 to +1.03 pp average excess; 60% to 68% beat rate |

**Execution rule:** after QQQ confirms above the prior close and holds/reclaims the opening range, concentrate long watchlists in AI infrastructure/semis first, then storage hardware. Use QQQ loss of the prior close as a regime stop, not merely a stock-specific pullback.

### Relative-lag / avoid list on bullish QQQ days

Software is the lowest-priority long group. ADBE, INTU, ADSK, and WDAY had the weakest strong-green relative results, each lagging QQQ by at least 1.27 pp on average. They are candidates for avoidance or relative-value fades only when their own tape is weak; they are not automatic shorts solely because QQQ is green.

## Risk controls

- Size smaller on event/earnings days and when the selected stock has idiosyncratic news.
- Require a liquid entry and define the invalidation price before entry.
- Do not extrapolate the 15-observation true-gap-fill sample into certainty.
- Re-run these conditional statistics quarterly and after major changes to QQQ membership or market leadership.

## Regime 3 — QQQ gaps down at least 0.5%

### Base expectation

Across 69 qualifying sessions, the average QQQ opening gap was -1.18%. QQQ was essentially flat from open to close on average (+0.02%) and positive only 50.7% of the time. A gap-down open alone is therefore not a short signal and not a long signal.

MU and NBIS both showed modestly better open-to-close behavior than QQQ on these days: MU averaged +0.49% (+0.47 pp versus QQQ), while NBIS averaged +0.71% (+0.69 pp). These are tendencies, not high-conviction standalone signals; their QQQ beat rates were only 53.6% and 47.8%, respectively.

### First-hour decision tree

1. **Do not buy merely because QQQ trades above its opening print.** A bounce above the open occurred on 91.3% of gap-down sessions, usually by 09:35 ET. Yet 71.4% of those sessions later made a new session low, and only 20.6% closed green versus the prior close.
2. **Require a true recovery through the prior close before adopting a bullish reversal thesis.** QQQ traded above the prior close in the first 55 minutes on 14.5% of gap-down sessions.
3. **After a true downside-gap fill, favor pullback longs over breakout chasing.** The true-fill sample closed green 60.0% of the time and averaged +1.03% from open to close, but only 50% continued higher from the first fill high to the close. A failed hold above the prior close is the invalidation.
4. **If QQQ cannot reclaim the prior close, treat the early bounce as a likely short-covering/range event.** Keep directional exposure smaller and avoid assuming the first bounce is a durable reversal.

### True downside-gap-fill path

For the 10 true-fill observations, QQQ was positive from the open on 90% of sessions by 09:45 and 10:00, averaged +1.25% by 10:15, and finished +1.04% from the open. The median initial gap was about -1.0%. The post-fill path typically consolidated rather than trended cleanly: average return from the fill high to the close was -0.06%.

### Relative-long and avoid lists on a gap-down day

On all 69 gap-down sessions, AI (+0.32 pp) and hardware (+0.27 pp) outperformed QQQ from open to close; software was flat relative and MSTR lagged. The preferred relative-long watchlist after a confirmed QQQ reclaim is STX, WDC, AMD, MU, PLTR, MRVL, NVDA, and AVGO. WDC had the best combined consistency (+0.96% average from open to close, +0.93 pp relative, and a 68.1% QQQ-beat rate).

The lowest-priority long / relative-fade list on an unconfirmed bounce is MCHP, SNPS, INTU, CDNS, MSTR, WDAY, APP, and MSFT. This list is conditional on their own relative weakness; no name should be shorted solely because QQQ gaps down.

### Defined failed-reclaim short setup

**Signal:** QQQ opens at least 0.5% below its prior close and has not traded above that prior close by 10:25 ET. Enter the individual-stock short at 10:30 ET and cover at the 15:45 ET close. This occurred on 59 of 69 gap-down sessions. Reported returns below are gross short returns before borrow, spread, commissions, slippage, and stop losses.

| Tier | Names | 10:30-to-close evidence |
|---|---|---|
| Highest raw EV, high tail risk | SNDK | +0.96% average, +0.71% median, 55.9% wins; worst observed day -10.33% |
| Balanced short candidates | INTU, MU, ADSK, SNPS, CDNS | +0.18% to +0.39% average; 59.3% to 64.4% wins except MU at 57.6% |
| Secondary / smaller size | MCHP, MSTR | +0.31% to +0.34% average, but only 54.2% wins |
| Do-not-short / lowest EV | WDC, STX, NVDA, PANW, AMD | -0.17% to +0.00% average short return; WDC and STX were decisively negative expectancy |

APP is **not** a preferred short despite a positive mean (+0.12%): its median result was -0.31% and the win rate was only 44.1%, indicating a tail-driven and unreliable profile.

**Risk rule:** invalidate the failed-reclaim short thesis if QQQ later reclaims and holds the prior close. SNDK, MSTR, APP, and other high-volatility names require substantially smaller size or a defined hard stop; raw average return does not compensate for unconstrained gap/squeeze risk.
