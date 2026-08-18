# Adaptive-MACD histogram shape study — local pilot

## Scope and causal definitions

This pilot uses the Fisher adaptive-MACD already embedded in the local scanner runs (Fisher 50; adaptive MACD 10/20/9; R² 20). One longest bar history is retained per ticker so multiple entry-date runs do not duplicate events.

- **Early rising-blue checkpoint:** the third consecutive positive and strictly increasing histogram bar. The feature is the average MACD-line slope across those three bars.
- **Bearish crossover:** the first negative histogram bar after a positive impulse. The feature is the average MACD-line change on only the bars where the positive histogram was expanding.
- Slopes are divided by the past-only 52-bar median absolute MACD change. Quartiles are formed separately by timeframe and event type.
- A bearish cross is called a two-bar whipsaw when the histogram returns positive within the next two bars. At the early checkpoint, failure means it turns negative within two bars.

This is a selected 27-symbol scanner universe, not a survivorship-free market universe. Results are hypothesis-screening evidence, not final production thresholds.

## Weekly

Universe: **27 symbols**; embedded histories span 2021-03-19 through 2026-08-07.

### Early rising-blue checkpoint

Events: **211**. Primary forward window: **4 bars (~4 weeks)**.

| Normalized MACD slope | N | Mean forward return | Median | Price positive | Two-bar noise | Short MFE | Short MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 weak | 52 | -3.95% | -6.09% | 38.5% | 7.7% | +15.67% | +16.99% |
| Q2 | 51 | +3.64% | +0.06% | 51.0% | 0.0% | +13.32% | +20.18% |
| Q3 | 52 | +0.89% | -2.08% | 46.2% | 1.9% | +13.00% | +19.33% |
| Q4 steep | 53 | -2.18% | -0.49% | 49.1% | 0.0% | +14.83% | +20.71% |

- Spearman slope/forward-return relationship: **+0.048**.
- Steep-minus-weak mean-return spread: **+1.77%**; ticker-clustered 95% interval **-4.70% to +8.89%**.

| MACD/signal shape at observation | N | Mean forward return | Price positive | Two-bar noise |
|---|---:|---:|---:|---:|
| MACD leads signal | 205 | -0.39% | 45.9% | 2.4% |
| MACD and signal aligned | 3 | -3.14% | 66.7% | 0.0% |

| Zero-line regime | Slope group | N | Mean forward return | Median | Directional hit |
|---|---|---:|---:|---:|---:|
| MACD + signal above zero | Q1 weak | 14 | -1.79% | -6.22% | 35.7% |
| MACD + signal above zero | Q4 steep | 8 | -2.12% | -4.12% | 50.0% |
| Not both above zero | Q1 weak | 38 | -4.74% | -6.09% | 39.5% |
| Not both above zero | Q4 steep | 45 | -2.19% | -0.49% | 48.9% |

| Forward horizon | Weak-slope mean / positive | Steep-slope mean / positive |
|---|---:|---:|
| 1 bars | +0.69% / 39.6% | +0.43% / 49.1% |
| 2 bars | -1.86% / 34.0% | +2.05% / 49.1% |
| 4 bars | -3.95% / 38.5% | -2.18% / 49.1% |
| 8 bars | +5.90% / 45.1% | +1.61% / 40.0% |

### Bearish histogram crossover

Events: **220**. Primary forward window: **4 bars (~4 weeks)**.

| Normalized MACD slope | N | Mean forward return | Median | Price positive | Two-bar noise | Short MFE | Short MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 weak | 55 | +4.01% | -3.75% | 43.6% | 3.6% | +14.20% | +19.80% |
| Q2 | 53 | +0.22% | -0.45% | 45.3% | 0.0% | +11.56% | +16.35% |
| Q3 | 53 | +11.01% | +5.35% | 60.4% | 3.8% | +12.53% | +24.74% |
| Q4 steep | 54 | +3.88% | +5.26% | 63.0% | 1.9% | +11.81% | +19.67% |

- Spearman slope/forward-return relationship: **+0.100**.
- Steep-minus-weak mean-return spread: **-0.13%**; ticker-clustered 95% interval **-12.22% to +9.75%**.

| MACD/signal shape at observation | N | Mean forward return | Price positive | Two-bar noise |
|---|---:|---:|---:|---:|
| MACD and signal aligned | 55 | +5.10% | 61.8% | 1.8% |
| MACD leads signal | 160 | +4.66% | 50.0% | 2.5% |

| Zero-line regime | Slope group | N | Mean forward return | Median | Directional hit |
|---|---|---:|---:|---:|---:|
| MACD + signal above zero | Q1 weak | 28 | +3.84% | -6.14% | 60.7% |
| MACD + signal above zero | Q4 steep | 47 | +4.01% | +5.00% | 36.2% |
| Not both above zero | Q1 weak | 27 | +4.19% | -2.72% | 51.9% |
| Not both above zero | Q4 steep | 7 | +3.00% | +5.51% | 42.9% |

| Forward horizon | Weak-slope mean / positive | Steep-slope mean / positive |
|---|---:|---:|
| 1 bars | +1.55% / 52.7% | +2.67% / 64.8% |
| 2 bars | +2.62% / 47.3% | +4.52% / 66.7% |
| 4 bars | +4.01% / 43.6% | +3.88% / 63.0% |
| 8 bars | +10.38% / 43.4% | +7.85% / 51.9% |

## 3-day

Universe: **27 symbols**; embedded histories span 2021-03-18 through 2026-08-06.

### Early rising-blue checkpoint

Events: **492**. Primary forward window: **5 bars (~15 calendar days)**.

| Normalized MACD slope | N | Mean forward return | Median | Price positive | Two-bar noise | Short MFE | Short MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 weak | 121 | +1.43% | -0.24% | 48.8% | 7.4% | +9.19% | +11.22% |
| Q2 | 122 | +0.48% | -0.44% | 48.4% | 0.0% | +9.84% | +11.40% |
| Q3 | 123 | +5.42% | +1.08% | 53.7% | 0.0% | +7.38% | +15.67% |
| Q4 steep | 123 | +3.84% | -0.97% | 48.0% | 0.0% | +9.20% | +15.94% |

- Spearman slope/forward-return relationship: **+0.070**.
- Steep-minus-weak mean-return spread: **+2.41%**; ticker-clustered 95% interval **-3.26% to +7.80%**.

| MACD/signal shape at observation | N | Mean forward return | Price positive | Two-bar noise |
|---|---:|---:|---:|---:|
| MACD leads signal | 480 | +2.58% | 49.6% | 1.7% |
| MACD and signal aligned | 9 | +14.56% | 55.6% | 11.1% |

| Zero-line regime | Slope group | N | Mean forward return | Median | Directional hit |
|---|---|---:|---:|---:|---:|
| MACD + signal above zero | Q1 weak | 32 | +0.02% | -3.27% | 40.6% |
| MACD + signal above zero | Q4 steep | 13 | -3.79% | -9.40% | 23.1% |
| Not both above zero | Q1 weak | 89 | +1.94% | +0.12% | 51.7% |
| Not both above zero | Q4 steep | 110 | +4.74% | +0.23% | 50.9% |

| Forward horizon | Weak-slope mean / positive | Steep-slope mean / positive |
|---|---:|---:|
| 1 bars | -0.65% / 46.7% | +0.41% / 48.8% |
| 3 bars | -0.05% / 50.0% | +2.20% / 54.5% |
| 5 bars | +1.43% / 48.8% | +3.84% / 48.0% |
| 10 bars | +6.50% / 48.3% | +6.50% / 54.5% |

### Bearish histogram crossover

Events: **536**. Primary forward window: **5 bars (~15 calendar days)**.

| Normalized MACD slope | N | Mean forward return | Median | Price positive | Two-bar noise | Short MFE | Short MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 weak | 133 | +3.68% | +2.46% | 57.1% | 4.5% | +8.23% | +14.98% |
| Q2 | 131 | +4.71% | +1.18% | 56.5% | 6.1% | +6.94% | +16.07% |
| Q3 | 133 | +2.09% | +0.67% | 52.6% | 0.8% | +8.77% | +12.07% |
| Q4 steep | 132 | -1.67% | -1.96% | 39.4% | 1.5% | +12.48% | +10.45% |

- Spearman slope/forward-return relationship: **-0.122**.
- Steep-minus-weak mean-return spread: **-5.35%**; ticker-clustered 95% interval **-9.13% to -1.68%**.

| MACD/signal shape at observation | N | Mean forward return | Price positive | Two-bar noise |
|---|---:|---:|---:|---:|
| MACD leads signal | 351 | +2.54% | 53.3% | 4.0% |
| MACD and signal aligned | 178 | +1.54% | 47.8% | 1.7% |

| Zero-line regime | Slope group | N | Mean forward return | Median | Directional hit |
|---|---|---:|---:|---:|---:|
| MACD + signal above zero | Q1 weak | 71 | +4.74% | +1.06% | 45.1% |
| MACD + signal above zero | Q4 steep | 126 | -1.54% | -1.89% | 58.7% |
| Not both above zero | Q1 weak | 62 | +2.47% | +2.46% | 40.3% |
| Not both above zero | Q4 steep | 6 | -4.37% | -7.60% | 66.7% |

| Forward horizon | Weak-slope mean / positive | Steep-slope mean / positive |
|---|---:|---:|
| 1 bars | +0.73% / 50.0% | -1.04% / 40.3% |
| 3 bars | +2.54% / 48.9% | -2.64% / 41.8% |
| 5 bars | +3.68% / 57.1% | -1.67% / 39.4% |
| 10 bars | +4.36% / 52.6% | -1.49% / 45.0% |

## Pilot conclusion

- **Slope did not create a clean continuation signal at the early rising-blue checkpoint.** Neither timeframe was monotonic across quartiles, and both ticker-clustered Q4−Q1 intervals included zero.
- **At weekly bearish crossovers, steep prior impulses behaved more like pullbacks than shorts:** 63.0% of steep events were positive four weeks later versus 43.6% for weak events. The mean spread was not statistically resolved because weak events had a positively skewed tail.
- **At 3-day bearish crossovers, the relationship reversed:** steep impulses returned -1.67% over the next five bars with only 39.4% positive, versus +3.68% and 57.1% positive for weak impulses. The ticker-clustered steep-minus-weak interval excluded zero.
- The useful feature is therefore not ‘high slope always means continuation.’ It is an interaction between slope, timeframe, and crossover state: weekly steep-impulse crossovers often reset and continue, while 3-day steep-impulse crossovers look like shorter-term exhaustion.

## Interpretation rules

- The hypothesis is supported only when returns improve monotonically from weak to steep slope, the continuous Spearman relationship has the same sign, and the clustered interval for the Q4−Q1 spread excludes zero.
- For bearish crossovers, a low-slope short filter should produce lower underlying returns, higher short MFE, and fewer positive recrosses. A steep prior impulse should do the reverse if the crossover is merely a pullback.
- Line geometry is useful only if it improves on the raw histogram event. A slope filter that changes returns but not whipsaw or adverse excursion may not reduce execution noise.

## Limitations

- The scanner universe is selected from previously traded/entered assets and is concentrated in volatile growth names.
- Events share market regimes and some forward windows overlap. The bootstrap clusters by ticker but not simultaneously by calendar date.
- Quartile boundaries are descriptive and use the full pilot sample. Production thresholds require a broader universe and walk-forward validation.
- Returns exclude costs, borrow constraints, dividends, and options implied volatility.
