# QQQ gap-up → open retest → initial-low sweep study

Source: existing Polygon-adjusted QQQ RTH one-minute cache. Sample: **2024-07-31 through 2026-07-27**.

## Primary answer

Across the broader daily sample, a simple RTH gap-up (open above previous close) occurred in **286/499 (57.3%)** sessions. The stricter body-clearing ≥0.10% gap used for the intraday sequence occurred in **183/499 (36.7%)** sessions.

Of **183** QQQ body-clearing gap-ups, **91** opened with a bullish five-minute candle. **63 of 91 (69.2%)** then returned to the 09:30 open by 10:29. **56 of 183 (30.6%, 95% CI 24.4–37.6%)** completed the entire sequence by subsequently trading below the initial five-minute low.

Conditional on a bullish initial candle, the full-setup rate was **61.5%**. Conditional on the open retest already occurring, the low-sweep rate was **88.9%**. The sweep itself happened by 10:29 in **52/56 (92.9%)** cases. Median open retest: **09:38 ET**; median low sweep: **09:45 ET**.

### Literal version without requiring a bullish opening candle

If every gap-up is included regardless of how the initial five-minute candle closes, **141/183 (77.0%)** qualifies: 155 touch the open after 09:34 and 141 subsequently sweep the initial low. After those sweeps, 89 revisit the initial high and 91 retest the previous close.

That literal rate is inflated as a ‘retracement’ estimate because a bearish initial candle may already be trading below its open. The primary version requires the initial five-minute candle to close above the open, establishing an actual move away before the return.

## What happened after the sweep?

- Revisited the initial five-minute high later: **42/56 (75.0%)**.
- Retested the previous close on a later minute: **36/56 (64.3%)**.
- Reached both targets later: **25/56 (44.6%)**.

Because both targets can trade in one session, the cleaner competing-risk result is: previous close had already been reached by the sweep in **7** cases. Among the remaining **49**, the initial high traded first in **28 (57.1%)**, the previous close traded first in **18 (36.7%)**, and neither traded in **3 (6.1%)**.

## Operational sequence

1. **Gap-up:** the 09:30 open is at least 0.10% above the larger of the prior session’s open and close. This is the existing cache’s stricter body-clearing gap definition.
2. **Initial gap candle:** the 09:30–09:34 composite closes above the 09:30 open.
3. **Gap-level retracement:** after 09:34 and by 10:29, a one-minute low touches or crosses the 09:30 open.
4. **Low sweep:** on a strictly later minute, price trades below the 09:30–09:34 low.
5. **Resolution:** only later one-minute bars are used to decide whether the initial high or previous close trades first. Same-minute ordering is never inferred.

## Gap-size sensitivity

| Simple open/previous-close gap | Gap days | Bullish 5m | Full setup | Initial high first | Previous close first | Neither |
|---|---:|---:|---:|---:|---:|---:|
| ≥0.1% | 183 | 91 | 56 (30.6%) | 28 | 25 | 3 |
| ≥0.25% | 140 | 70 | 38 (27.1%) | 23 | 12 | 3 |
| ≥0.5% | 96 | 41 | 20 (20.8%) | 13 | 5 | 2 |
| ≥1% | 40 | 13 | 9 (22.5%) | 7 | 1 | 1 |

Larger gaps were less likely to reach the previous close before revisiting the opening high. This is the clearest conditioning variable in the sample.

## Initial-candle sensitivity

| Initial candle | Bullish candles | Full setup | Any later high revisit | Any later previous-close retest | High first | Previous close first |
|---|---:|---:|---:|---:|---:|---:|
| 1m | 90 | 67 (36.6% of gaps) | 80.6% | 65.7% | 40 | 24 |
| 5m | 91 | 56 (30.6% of gaps) | 75.0% | 64.3% | 28 | 25 |
| 10m | 87 | 45 (24.6% of gaps) | 57.8% | 68.9% | 15 | 26 |

The initial-candle definition materially changes the result: a ten-minute opening candle favors previous-close resolution, while the one- and five-minute definitions favor or roughly balance a high revisit.

## Limitations

The cache contains body-clearing gaps, not every open one cent above the previous close, so the estimate does not apply to tiny inside-body gaps. The study uses one-minute OHLC bars and therefore cannot order two levels touched within the same minute. Exact equality is treated as a touch; the low sweep requires a strict break. Results are descriptive and overlap across time, so the nominal Wilson interval does not address regime dependence.
