# DVOL embedded-MACD 0.5 cross: BTCUSD event study

Source: `/Users/ericchen/Downloads/DERIBIT_DVOL, 1D.csv` (TradingView-exported `MACD` line) and Yahoo Finance daily `BTC-USD` closes.
Sample: 2021-04-12 to 2026-08-16.

## Signal definition

An event is the first daily close where the exported MACD line moves from ≤0.5 to >0.5. An episode ends only at a down-cross whose current day and next four sessions all remain below 0.5. BTC returns are close-to-close from the event-day BTC close; they are calendar-day horizons because BTC trades every day.

## Threshold persistence

- 0.5 upside-cross events: **54**
- Confirmed exits below 0.5 for five sessions: **54**
- Reached MACD ≥1.0 before confirmed exit: **36 (66.7%)**
- Reached MACD ≥2.0 before confirmed exit: **19 (35.2%)**

### BTCUSD returns after a 0.5 upside cross

| Horizon | N | Mean BTC return | Median | Win rate |
|---:|---:|---:|---:|---:|
| 1 calendar days | 54 | -0.71% | -0.26% | 48.1% |
| 3 calendar days | 54 | +0.60% | +1.15% | 61.1% |
| 5 calendar days | 54 | +0.32% | +0.51% | 53.7% |
| 10 calendar days | 54 | +1.58% | +2.14% | 59.3% |
| 20 calendar days | 54 | +3.13% | +1.80% | 59.3% |
| 30 calendar days | 54 | +2.69% | +0.28% | 51.9% |

### BTCUSD all-day baseline (context only)

| Horizon | N | Mean BTC return | Median | Win rate |
|---:|---:|---:|---:|---:|
| 1 calendar days | 1952 | +0.04% | -0.03% | 49.3% |
| 3 calendar days | 1950 | +0.12% | +0.13% | 51.6% |
| 5 calendar days | 1948 | +0.20% | +0.10% | 50.8% |
| 10 calendar days | 1943 | +0.44% | +0.17% | 51.6% |
| 20 calendar days | 1933 | +0.98% | +0.03% | 50.0% |
| 30 calendar days | 1923 | +1.52% | +0.23% | 50.8% |

## Regime split

Regimes are assigned by the 0.5-cross date. The all-day reference uses every BTC starting day in the same window; it is context, not an independent statistical test.

### 2022 bear-market window

- Independent 0.5-cross episodes: **14**
- Reached MACD ≥1.0: **8 (57.1%)**
- Reached MACD ≥2.0: **4 (28.6%)**

| Horizon | Cross return | Win rate | Same-window all-day return | All-day win rate |
|---:|---:|---:|---:|---:|
| 1 calendar days | -1.83% (N=14) | 57.1% | -0.23% | 46.6% |
| 3 calendar days | -0.67% (N=14) | 64.3% | -0.69% | 47.9% |
| 5 calendar days | -2.02% (N=14) | 50.0% | -1.11% | 46.6% |
| 10 calendar days | -2.36% (N=14) | 42.9% | -2.10% | 46.3% |
| 20 calendar days | -3.24% (N=14) | 50.0% | -3.58% | 42.7% |
| 30 calendar days | -2.68% (N=14) | 42.9% | -4.41% | 40.3% |

### October 2025–present window

- Independent 0.5-cross episodes: **9**
- Reached MACD ≥1.0: **6 (66.7%)**
- Reached MACD ≥2.0: **4 (44.4%)**

| Horizon | Cross return | Win rate | Same-window all-day return | All-day win rate |
|---:|---:|---:|---:|---:|
| 1 calendar days | -0.63% (N=9) | 33.3% | -0.17% | 47.3% |
| 3 calendar days | -1.07% (N=9) | 33.3% | -0.54% | 47.9% |
| 5 calendar days | -3.73% (N=9) | 33.3% | -0.92% | 43.5% |
| 10 calendar days | -2.42% (N=9) | 44.4% | -1.81% | 43.2% |
| 20 calendar days | -1.87% (N=9) | 44.4% | -3.40% | 37.0% |
| 30 calendar days | -2.55% (N=9) | 44.4% | -5.01% | 41.4% |

## General principle: price-led volatility expansion

Volatility expansion is direction-neutral; it is an amplifier of the market's active price-discovery regime. It is constructive when a prolonged compression is resolved by accepted upside price discovery, and destructive when price is breaking down or repeatedly failing to hold a breakout.

Treat a rising DVOL / positive DVOL-MACD as a continuation tailwind only when all three conditions are present:

1. **Compression:** realised and/or implied volatility has been subdued relative to its own recent history.
2. **Price leadership:** spot closes through a multi-week range high and holds it, rather than merely wicking above it.
3. **Trend acceptance:** the higher-timeframe price trend remains constructive (for example, rising medium-term trend and higher highs).

The volatility expansion then represents new participation and a repricing of upside risk. Without price leadership and trend acceptance, the same vol signal more often represents deleveraging, hedging demand, or a bear-market rally that can fail. Use the price breakout/hold as the entry trigger; use the volatility signal as a sizing and regime filter, not as a directional trigger by itself.

## Pre-DVOL check: price-confirmed realized-volatility expansion

Deribit returns no DVOL observations before 2021-03-24. For the 2020 portion, this uses a BTC-only proxy: 20-day realised volatility must be in the bottom 35% of its trailing 252-day distribution; 5-day realised volatility must then be at least 1.25× the 20-day reading; and the BTC close must break its prior 20-day high. Every input is known at that day's close.

### 2020–early-2021 bull window

- Price-confirmed compression-to-expansion signals: **7**

| Horizon | Signal return | Signal win rate | Same-window all-day return | All-day win rate |
|---:|---:|---:|---:|---:|
| 1 calendar days | +0.77% (N=7) | 57.1% | +0.65% | 57.4% |
| 3 calendar days | +1.82% (N=7) | 71.4% | +1.96% | 61.7% |
| 5 calendar days | +3.24% (N=7) | 100.0% | +3.28% | 65.7% |
| 10 calendar days | +6.13% (N=7) | 100.0% | +6.48% | 68.4% |
| 20 calendar days | +13.11% (N=7) | 100.0% | +13.20% | 72.1% |
| 30 calendar days | +20.65% (N=7) | 100.0% | +19.94% | 75.3% |

### 2023 early-bull window

- Price-confirmed compression-to-expansion signals: **3**

| Horizon | Signal return | Signal win rate | Same-window all-day return | All-day win rate |
|---:|---:|---:|---:|---:|
| 1 calendar days | +1.42% (N=3) | 33.3% | +0.37% | 50.3% |
| 3 calendar days | +2.39% (N=3) | 33.3% | +1.13% | 53.6% |
| 5 calendar days | +5.59% (N=3) | 66.7% | +1.90% | 54.1% |
| 10 calendar days | +7.67% (N=3) | 66.7% | +3.75% | 60.2% |
| 20 calendar days | +9.52% (N=3) | 66.7% | +6.25% | 60.8% |
| 30 calendar days | +13.33% (N=3) | 100.0% | +7.78% | 63.5% |

## Event-level detail

| Cross date | Entry MACD | Confirmed exit | Peak MACD before exit | Hit ≥1 | Hit ≥2 | BTC 5d | BTC 10d | BTC 20d |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| 2021-04-13 | 0.640 | 2021-04-15 | 0.640 | No | No | -11.48% | -19.54% | -9.93% |
| 2021-04-22 | 0.689 | 2021-04-27 | 2.361 | Yes | Yes | +6.32% | +9.41% | -5.05% |
| 2021-05-06 | 0.699 | 2021-05-31 | 11.497 | Yes | Yes | +0.55% | -17.63% | -30.33% |
| 2021-06-22 | 1.149 | 2021-06-29 | 1.868 | Yes | No | +6.60% | +4.28% | +2.00% |
| 2021-07-28 | 1.158 | 2021-08-16 | 2.069 | Yes | Yes | -1.99% | +11.40% | +11.75% |
| 2021-09-28 | 0.682 | 2021-10-01 | 0.878 | No | No | +17.46% | +31.52% | +51.16% |
| 2021-10-12 | 0.527 | 2021-10-16 | 1.466 | Yes | No | +9.84% | +8.30% | +8.86% |
| 2021-11-18 | 0.546 | 2021-11-19 | 0.546 | No | No | +1.10% | +0.54% | -11.31% |
| 2021-12-06 | 0.571 | 2021-12-16 | 0.965 | No | No | -2.41% | -5.77% | +0.45% |
| 2022-01-22 | 1.611 | 2022-01-30 | 2.979 | Yes | Yes | +6.02% | +10.60% | +21.06% |
| 2022-02-13 | 0.560 | 2022-02-16 | 0.699 | No | No | -5.13% | -11.61% | -6.63% |
| 2022-02-21 | 0.629 | 2022-03-02 | 1.249 | Yes | No | +5.47% | +14.50% | +2.09% |
| 2022-03-07 | 0.509 | 2022-03-16 | 0.751 | No | No | +2.21% | +7.59% | +23.01% |
| 2022-04-12 | 0.673 | 2022-04-15 | 0.763 | No | No | -1.02% | -0.96% | -3.98% |
| 2022-04-27 | 0.560 | 2022-04-28 | 0.560 | No | No | -1.81% | -9.53% | -22.46% |
| 2022-05-08 | 0.564 | 2022-05-21 | 8.384 | Yes | Yes | -14.02% | -15.68% | -15.40% |
| 2022-06-12 | 1.248 | 2022-06-24 | 7.596 | Yes | Yes | -23.51% | -25.32% | -28.10% |
| 2022-07-19 | 0.587 | 2022-07-23 | 0.847 | No | No | -3.34% | +1.78% | +1.80% |
| 2022-08-19 | 0.961 | 2022-08-25 | 1.684 | Yes | No | +2.48% | -2.78% | -7.41% |
| 2022-09-06 | 0.856 | 2022-09-08 | 0.856 | No | No | +15.56% | +4.96% | +2.04% |
| 2022-09-26 | 0.621 | 2022-10-01 | 1.098 | Yes | No | +0.47% | +3.81% | +0.24% |
| 2022-11-08 | 1.508 | 2022-11-18 | 9.733 | Yes | Yes | -11.80% | -9.94% | -12.53% |
| 2022-12-17 | 0.549 | 2022-12-22 | 1.301 | Yes | No | +0.21% | -0.46% | +0.93% |
| 2023-01-13 | 1.133 | 2023-01-24 | 4.624 | Yes | Yes | +3.91% | +15.19% | +17.89% |
| 2023-02-17 | 1.022 | 2023-02-24 | 1.974 | Yes | No | -1.53% | -4.24% | -17.11% |
| 2023-03-09 | 0.583 | 2023-03-26 | 3.109 | Yes | Yes | +21.52% | +37.69% | +39.22% |
| 2023-06-13 | 0.689 | 2023-06-27 | 1.519 | Yes | No | +1.61% | +18.43% | +20.21% |
| 2023-08-17 | 1.614 | 2023-08-25 | 2.058 | Yes | Yes | -2.37% | -2.16% | -3.42% |
| 2023-09-06 | 0.749 | 2023-09-15 | 1.104 | Yes | No | -2.29% | +3.16% | +1.80% |
| 2023-10-17 | 0.703 | 2023-11-10 | 3.520 | Yes | Yes | +5.55% | +19.33% | +23.30% |
| 2023-12-20 | 0.525 | 2024-01-11 | 2.314 | Yes | Yes | -0.09% | -3.43% | +5.70% |
| 2024-02-10 | 0.839 | 2024-03-19 | 3.315 | Yes | Yes | +8.72% | +9.45% | +30.71% |
| 2024-05-15 | 0.538 | 2024-05-23 | 0.950 | No | No | +7.82% | +4.52% | +6.49% |
| 2024-07-07 | 0.786 | 2024-07-28 | 3.188 | Yes | Yes | +3.67% | +14.81% | +21.42% |
| 2024-08-06 | 1.132 | 2024-08-13 | 1.709 | Yes | No | +4.79% | +5.10% | +12.22% |
| 2024-09-05 | 0.647 | 2024-09-11 | 1.241 | Yes | No | +2.65% | +5.38% | +12.43% |
| 2024-09-30 | 0.604 | 2024-10-09 | 1.152 | Yes | No | -1.96% | -4.82% | +8.96% |
| 2024-10-29 | 0.528 | 2024-11-07 | 1.207 | Yes | No | -5.47% | +5.26% | +24.51% |
| 2024-11-16 | 0.574 | 2024-11-26 | 0.862 | No | No | +8.77% | +1.58% | +10.34% |
| 2024-12-09 | 0.661 | 2024-12-14 | 0.799 | No | No | +4.04% | +0.06% | -4.01% |
| 2025-01-16 | 0.629 | 2025-01-22 | 1.205 | Yes | No | +6.40% | +2.93% | -3.15% |
| 2025-03-02 | 0.700 | 2025-03-13 | 2.143 | Yes | Yes | -7.96% | -11.17% | -11.05% |
| 2025-04-02 | 0.630 | 2025-04-13 | 1.631 | Yes | No | -3.94% | +3.40% | +13.28% |
| 2025-05-22 | 0.742 | 2025-05-27 | 0.828 | No | No | -2.40% | -5.39% | -2.67% |
| 2025-08-30 | 0.505 | 2025-09-03 | 0.631 | No | No | +1.76% | +2.50% | +6.32% |
| 2025-10-09 | 0.541 | 2025-10-25 | 2.033 | Yes | Yes | -7.06% | -10.71% | -9.57% |
| 2025-11-05 | 0.549 | 2025-11-08 | 0.701 | No | No | +2.03% | -8.03% | -15.93% |
| 2025-11-16 | 0.582 | 2025-11-27 | 2.090 | Yes | Yes | -9.65% | -3.88% | -5.21% |
| 2026-01-31 | 0.891 | 2026-02-12 | 5.206 | Yes | Yes | -20.25% | -12.50% | -13.50% |
| 2026-02-24 | 1.094 | 2026-03-02 | 1.125 | Yes | No | +2.59% | +6.33% | +16.82% |
| 2026-03-08 | 0.570 | 2026-03-09 | 0.570 | No | No | +7.58% | +8.00% | +0.53% |
| 2026-03-22 | 0.639 | 2026-03-24 | 0.639 | No | No | -2.22% | +0.34% | +7.68% |
| 2026-06-02 | 0.619 | 2026-06-12 | 2.592 | Yes | Yes | -5.19% | -4.74% | -4.13% |
| 2026-06-24 | 0.735 | 2026-07-01 | 1.404 | Yes | No | -1.40% | +3.43% | +6.49% |
