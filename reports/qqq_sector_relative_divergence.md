# QQQ sector relative-divergence study

Study period: 2021-08-17 through 2026-08-14. The chart uses the most recent two years; all statistics use the full period.

Method: each sector's close is divided by QQQ, rebased to 100, and passed through the repository's Fisher adaptive-MACD configuration (50-bar Fisher; adaptive MACD 10/20/9; 20-bar R²). The histogram is standardized by a past-only 252-session rolling z-score. Positive divergence means accelerating sector outperformance versus QQQ.

## Sector-relative forward returns by divergence band

| Histogram z-score | N | Avg next 10d relative return | Relative win rate | Avg next 20d relative return | Relative win rate |
|---|---:|---:|---:|---:|---:|
| ≤−2 | 248 | +0.85% | 62.9% | +0.84% | 58.1% |
| −2 to −1 | 1780 | -0.20% | 47.7% | -0.36% | 45.9% |
| −1 to +1 | 9000 | -0.14% | 46.4% | -0.38% | 44.8% |
| +1 to +2 | 1684 | -0.50% | 46.2% | -0.42% | 47.4% |
| ≥+2 | 368 | -0.02% | 49.2% | -0.01% | 47.3% |

## QQQ forward returns by average sector divergence breadth

| Breadth z-score | N | Avg next 10d QQQ return | QQQ win rate | Avg next 20d QQQ return | QQQ win rate |
|---|---:|---:|---:|---:|---:|
| ≤−2 | 0 | — | — | — | — |
| −2 to −1 | 17 | -1.38% | 41.2% | -1.86% | 23.5% |
| −1 to +1 | 1027 | +0.86% | 61.2% | +1.67% | 66.0% |
| +1 to +2 | 46 | -1.62% | 41.3% | -2.33% | 41.3% |
| ≥+2 | 0 | — | — | — | — |

## Interpretation guardrails

- A sector z-score is a relative-strength signal, not a QQQ directional signal by itself.
- Treat a band as economically meaningful only if it has at least 100 observations, a sign-consistent 10d/20d result, and a material improvement over the neutral band.
- The bands are descriptive and overlap in time; they are not independent trades. Revalidate out of sample before using them as execution thresholds.
