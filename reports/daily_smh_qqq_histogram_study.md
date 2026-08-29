# Daily SMH / QQQ adaptive-MACD histogram study

## Scope and causal definitions

Fisher adaptive-MACD on daily bars (Fisher 50; adaptive MACD 10/20/9; R² 20), the same configuration as the weekly/3-day histogram-shape pilot. Prices are Polygon adjusted daily OHLC. Entry is the event-day close; forward returns are close-to-close. Short events are signed so that a profitable short is positive.

Histogram colors match the local charts: **light blue** = positive and rising; **dark blue** = positive and falling; **light red** = negative and becoming more negative; **dark red** = negative and rising toward zero.

- **Light→dark in blue:** first falling positive bar after a rising positive bar. This is the color-transition itself: histogram still above zero, momentum just rolled over. A long here is an early bet that the blue run continues.
- **Dark→light in blue:** already in a positive histogram for at least two bars, the last bar decelerated, then the current bar re-accelerates. This is buying the color-shift back to light blue, not a zero-line flip.
- **Histogram flip red→blue:** first positive histogram bar after a non-positive bar.
- **Early rising-blue:** third consecutive strictly increasing positive bar; one observation per impulse. This is the weekly/3-day checkpoint, included for comparison.
- **Dark→light-red / flip blue→red:** the short-side analogues.
- A color-shift **fails the 1-day clock** when the next session’s signed return is ≤ 0. Holding on means keeping that ticket; waiting for the crossover means scratching and taking the next zero-line flip as a new trade.

Sample after MACD warmup: SMH 2021-09-16–2026-08-18 (1235 sessions); QQQ 2021-09-16–2026-08-18 (1235 sessions).

## All-session baseline

| Ticker | Horizon | All-session mean | Median | Positive |
|---|---:|---:|---:|---:|
| SMH | 1 | +0.15% | +0.19% | 54.1% |
| SMH | 2 | +0.29% | +0.50% | 56.1% |
| SMH | 3 | +0.44% | +0.57% | 56.0% |
| SMH | 5 | +0.72% | +0.72% | 56.3% |
| SMH | 10 | +1.41% | +1.47% | 58.5% |
| QQQ | 1 | +0.06% | +0.11% | 54.3% |
| QQQ | 2 | +0.13% | +0.25% | 55.7% |
| QQQ | 3 | +0.19% | +0.37% | 56.4% |
| QQQ | 5 | +0.32% | +0.53% | 57.6% |
| QQQ | 10 | +0.62% | +0.95% | 58.8% |

## Light→dark in blue (first fade, still above zero)

Events: **126** (SMH 58, QQQ 68). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 125 | +0.77% | +1.07% | 58.4% | 16.7% | +3.13% | +2.54% |
| SMH 5d | 57 | +0.92% | +1.29% | 61.4% | 10.3% | +3.81% | +3.28% |
| QQQ 5d | 68 | +0.64% | +0.92% | 55.9% | 22.1% | +2.56% | +1.92% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | +0.18% / 55.6% | +0.13% / 51.7% | +0.22% / 58.8% |
| 2d | +0.34% / 53.2% | +0.05% / 41.4% | +0.59% / 63.2% |
| 3d | +0.51% / 58.7% | +0.34% / 51.7% | +0.65% / 64.7% |
| 5d | +0.77% / 57.9% | +0.92% / 60.3% | +0.64% / 55.9% |
| 10d | +0.99% / 60.3% | +1.56% / 62.1% | +0.50% / 58.8% |

## Dark→light in blue (re-acceleration long)

Events: **29** (SMH 12, QQQ 17). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 29 | +0.21% | +0.23% | 51.7% | 3.4% | +2.82% | +2.43% |
| SMH 5d | 12 | -0.76% | -0.95% | 41.7% | 0.0% | +2.97% | +3.42% |
| QQQ 5d | 17 | +0.90% | +1.96% | 58.8% | 5.9% | +2.71% | +1.73% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | -0.11% / 37.9% | -0.28% / 33.3% | +0.01% / 41.2% |
| 2d | +0.20% / 51.7% | +0.20% / 58.3% | +0.20% / 47.1% |
| 3d | +0.59% / 65.5% | +0.36% / 66.7% | +0.76% / 64.7% |
| 5d | +0.21% / 51.7% | -0.76% / 41.7% | +0.90% / 58.8% |
| 10d | -0.33% / 48.3% | +0.49% / 66.7% | -0.92% / 35.3% |

## Histogram flip red→blue

Events: **103** (SMH 52, QQQ 51). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 103 | +0.60% | +0.41% | 56.3% | 4.9% | +3.04% | +2.60% |
| SMH 5d | 52 | +1.29% | +1.60% | 61.5% | 9.6% | +4.26% | +2.85% |
| QQQ 5d | 51 | -0.11% | +0.07% | 51.0% | 0.0% | +1.80% | +2.33% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | +0.15% / 58.3% | +0.31% / 59.6% | -0.03% / 56.9% |
| 2d | +0.32% / 55.3% | +0.81% / 63.5% | -0.19% / 47.1% |
| 3d | +0.49% / 55.3% | +1.17% / 63.5% | -0.21% / 47.1% |
| 5d | +0.60% / 56.3% | +1.29% / 61.5% | -0.11% / 51.0% |
| 10d | +1.36% / 55.3% | +1.79% / 55.8% | +0.91% / 54.9% |

## Early rising-blue (3rd increasing bar)

Events: **91** (SMH 44, QQQ 47). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 91 | +0.99% | +1.00% | 62.6% | 3.3% | +3.19% | +2.34% |
| SMH 5d | 44 | +1.04% | +1.40% | 61.4% | 0.0% | +4.19% | +2.75% |
| QQQ 5d | 47 | +0.95% | +0.91% | 63.8% | 6.4% | +2.26% | +1.97% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | +0.16% / 58.2% | +0.40% / 63.6% | -0.05% / 53.2% |
| 2d | +0.13% / 58.2% | +0.27% / 63.6% | -0.01% / 53.2% |
| 3d | +0.40% / 57.1% | +0.71% / 63.6% | +0.11% / 51.1% |
| 5d | +0.99% / 62.6% | +1.04% / 61.4% | +0.95% / 63.8% |
| 10d | +1.19% / 53.8% | +0.97% / 52.3% | +1.40% / 55.3% |

## Light→dark-red in red (first fade toward zero)

Events: **142** (SMH 71, QQQ 71). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 142 | +0.02% | -0.34% | 46.5% | 12.0% | +3.19% | +2.68% |
| SMH 5d | 71 | +0.12% | +0.08% | 50.7% | 7.0% | +4.19% | +3.23% |
| QQQ 5d | 71 | -0.07% | -0.68% | 42.3% | 16.9% | +2.18% | +2.13% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | +0.19% / 44.4% | +0.36% / 52.1% | +0.02% / 36.6% |
| 2d | +0.10% / 48.6% | +0.28% / 52.1% | -0.09% / 45.1% |
| 3d | +0.02% / 46.5% | +0.22% / 46.5% | -0.19% / 46.5% |
| 5d | +0.02% / 46.5% | +0.12% / 50.7% | -0.07% / 42.3% |
| 10d | -0.89% / 39.4% | -1.09% / 40.8% | -0.69% / 38.0% |

## Dark→light-red in red (re-acceleration short)

Events: **43** (SMH 23, QQQ 20). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 43 | -1.18% | -0.43% | 44.2% | 0.0% | +2.88% | +3.38% |
| SMH 5d | 23 | -0.76% | +0.45% | 52.2% | 0.0% | +3.84% | +3.55% |
| QQQ 5d | 20 | -1.65% | -1.24% | 35.0% | 0.0% | +1.77% | +3.18% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | -0.15% / 41.9% | +0.08% / 43.5% | -0.41% / 40.0% |
| 2d | +0.04% / 46.5% | +0.60% / 52.2% | -0.60% / 40.0% |
| 3d | -0.63% / 41.9% | -0.41% / 47.8% | -0.89% / 35.0% |
| 5d | -1.18% / 44.2% | -0.76% / 52.2% | -1.65% / 35.0% |
| 10d | -2.29% / 30.2% | -2.52% / 34.8% | -2.02% / 25.0% |

## Histogram flip blue→red

Events: **103** (SMH 52, QQQ 51). Primary window: **5 sessions**.

| Slice | N | Mean | Median | Hit | Two-bar flip/fail | MFE | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pooled 5d | 103 | -0.70% | -0.79% | 39.8% | 3.9% | +2.73% | +3.02% |
| SMH 5d | 52 | -0.89% | -1.46% | 40.4% | 7.7% | +3.13% | +3.93% |
| QQQ 5d | 51 | -0.50% | -0.54% | 39.2% | 0.0% | +2.33% | +2.09% |

| Horizon | Pooled mean / hit | SMH mean / hit | QQQ mean / hit |
|---|---:|---:|---:|
| 1d | -0.13% / 39.8% | -0.53% / 32.7% | +0.29% / 47.1% |
| 2d | -0.32% / 36.9% | -0.91% / 30.8% | +0.29% / 43.1% |
| 3d | -0.24% / 41.7% | -0.58% / 44.2% | +0.11% / 39.2% |
| 5d | -0.70% / 39.8% | -0.89% / 40.4% | -0.50% / 39.2% |
| 10d | -1.04% / 41.7% | -2.01% / 36.5% | -0.05% / 47.1% |

## One-session clock on color-shifts

### Light→dark blue (longs at first fade)

- Events with 1d and 5d outcomes: **125**. 1d losers: **56** (44.8%).
- 1d winners held 5d: mean +1.60%, hit 66.7% (N=69).
- 1d losers held 5d: mean -0.26%, hit 48.2% (N=56).
- 1d losers held 2d: mean -0.75%, still red 66.1%.
- Hold every color-shift 5d: mean +0.77%, hit 58.4%.
- Scratch losers at day 1, hold winners 5d: mean +0.27%, hit 36.8%.

- After a 1d-failed color-shift, median sessions to the next zero-line flip: **15** (mean 17.3, N=56).
- If you **hold the dead color-shift until that flip**: mean -0.65%, hit 50.0%.
- If you **scratch and take the new flip for 5d**: mean -0.18%, hit 53.6%.

### Dark→light blue (longs)

- Events with 1d and 5d outcomes: **29**. 1d losers: **18** (62.1%).
- 1d winners held 5d: mean +1.62%, hit 72.7% (N=11).
- 1d losers held 5d: mean -0.64%, hit 38.9% (N=18).
- 1d losers held 2d: mean -0.85%, still red 72.2%.
- Hold every color-shift 5d: mean +0.21%, hit 51.7%.
- Scratch losers at day 1, hold winners 5d: mean -0.17%, hit 27.6%.

- After a 1d-failed color-shift, median sessions to the next zero-line flip: **22** (mean 23.5, N=18).
- If you **hold the dead color-shift until that flip**: mean -1.96%, hit 38.9%.
- If you **scratch and take the new flip for 5d**: mean -1.89%, hit 44.4%.

### Dark→light-red (shorts)

- Events with 1d and 5d outcomes: **43**. 1d losers: **25** (58.1%).
- 1d winners held 5d: mean -0.94%, hit 44.4% (N=18).
- 1d losers held 5d: mean -1.35%, hit 44.0% (N=25).
- 1d losers held 2d: mean -0.59%, still red 60.0%.
- Hold every color-shift 5d: mean -1.18%, hit 44.2%.
- Scratch losers at day 1, hold winners 5d: mean -1.20%, hit 18.6%.

- After a 1d-failed color-shift, median sessions to the next zero-line flip: **21** (mean 23.4, N=24).
- If you **hold the dead color-shift until that flip**: mean -0.92%, hit 41.7%.
- If you **scratch and take the new flip for 5d**: mean -2.71%, hit 12.5%.

## Head-to-head: color-shift vs flip vs early-blue

Signed 1-day and 5-day close-to-close. Long events want price up; short events want price down.

| Event | Side | N | 1d mean / hit | 5d mean / hit | 5d vs SMH/QQQ baseline | 1d losers → 5d if held |
|---|---|---:|---:|---:|---:|---:|
| Light→dark in blue (first fade, still above zero) | long | 126 | +0.18% / 55.6% | +0.77% / 57.9% | SMH +0.21%; QQQ +0.33% | -0.26% / 48.2% |
| Dark→light in blue (re-acceleration long) | long | 29 | -0.11% / 37.9% | +0.21% / 51.7% | SMH -1.47%; QQQ +0.58% | -0.64% / 38.9% |
| Histogram flip red→blue | long | 103 | +0.15% / 58.3% | +0.60% / 56.3% | SMH +0.58%; QQQ -0.43% | -0.14% / 48.8% |
| Early rising-blue (3rd increasing bar) | long | 91 | +0.16% / 58.2% | +0.99% / 62.6% | SMH +0.32%; QQQ +0.63% | -0.79% / 47.4% |
| Light→dark-red in red (first fade toward zero) | short | 142 | +0.19% / 44.4% | +0.02% / 46.5% | SMH -0.60%; QQQ -0.39% | -1.19% / 35.4% |
| Dark→light-red in red (re-acceleration short) | short | 43 | -0.15% / 41.9% | -1.18% / 44.2% | SMH -1.48%; QQQ -1.97% | -1.35% / 44.0% |
| Histogram flip blue→red | short | 103 | -0.13% / 39.8% | -0.70% / 39.8% | SMH -1.60%; QQQ -0.82% | -1.75% / 24.2% |

## Conclusion

- The best daily **long** on this sample is the **third rising light-blue bar**, not the color-shift: 5d +0.99% / 62.6% hit (N=91).
- **Red→blue flips** are +EV on SMH (+1.29% 5d, 61.5% hit) and flat-to-negative on QQQ (-0.11% 5d). Pooled 1d is +0.15% / 58.3% hit.
- **Light→dark** (first fade, still above zero) 1d +0.17% / 55.2% hit. **Dark→light re-acceleration** 1d -0.11% / 37.9% hit. Both underperform a coin flip on day one.
- If a color-shift long is red after one session, holding does not salvage it: light→dark losers 5d -0.26%; dark→light losers 5d -0.64%.
- **Do not short the daily blue→red flip** on these two names: signed 5d -0.70% (price usually keeps rising). Color-shift shorts are worse (-1.18% 5d).
- Size: color-transition = probe and 1-session clock, or skip. SMH red→blue or 3rd light-blue bar = full daily swing. QQQ daily flip is not a full-size long on this sample.

## Limitations

- Polygon plan only returns ~5 years of daily bars, so the sample is 2021-08-19 through 2026-08-18, not 2010.
- Two liquid ETFs, not a market-wide universe. Events overlap across names on the same dates.
- Close-to-close, no gap-at-open slippage, no option premium path. A 30–45 DTE option will not match these underlying percentages one-for-one.
- Color-shift and early-rising-blue can fire on nearby bars of the same impulse; they are not mutually exclusive samples.
- Quartile slope filters from the weekly/3-day pilot are omitted here because the hypothesis under test is event type plus a 1-day timeout, not slope.
