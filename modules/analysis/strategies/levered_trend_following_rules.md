# Levered Trend-Following Position Management Rules

## Scope

Selection and initial entry are external inputs. The strategy manages a long
position from an invariant 1.00x core through at most 2.00x exposure; it does not claim
to generate entry alpha.

## Implemented hierarchy

1. Emergency ATR thesis invalidation exits all exposure.
2. A causal weekly lower-high followed by a break of its intervening swing low
   exits the remaining core.
3. Adaptive-MACD and histogram deceleration reduces leverage with increasing
   sensitivity as current MACD approaches the last completed positive impulse
   peak.
4. Non-extreme MACD/histogram reacceleration and constructive price action can
   restore leverage.
5. Favorable ATR continuation can pyramid in 0.25x increments.

## Momentum-extension regimes

| Extension to prior completed major MACD peak | Regime | Management |
| --- | --- | --- |
| <50% | Fresh | Tolerate 3 decelerating bars; up to 2.00x |
| 50–75% | Developed | Tolerate 2 decelerating bars; up to 2.00x |
| 75–100% | Mature | De-lever on 1 confirmed deceleration; cap at 1.50x |
| >=100% | Extreme | Latch state, prohibit aggressive pyramids, cap re-leverage at 1.25x |

An extreme is remembered for the life of the trade; a pullback does not reset
the state to fresh. In every regime, ordinary momentum management removes only
the earned trend sleeve: it never reduces the original 1.00x spot core. The
emergency/thesis-invalidation and structural-exit paths can still close it.

## Output contract

Each run emits `levered-trend-following/v1` JSON with:

- Bar-level adaptive MACD, signal, histogram, RSI(14), ATR(14), extension,
  target exposure, and equity.
- Explicit `ENTER`, `PYRAMID`, `DELEVER`, `RELEVER`, and `EXIT` decisions.
- Closed-trade ledger and aggregate return, drawdown, turnover, exposure, and
  tail-return statistics.

Run it with `trading-levered-trend-following run --help`. The experimental 3D
ignition / weekly-inheritance detector is implemented separately in
`trading_analysis.strategies.composite_trend`. It follows C0 consolidation,
C1 ignition, C2 transition, C3 weekly inheritance, C4 weekly deceleration,
and C5 structural failure. It uses 3D breakout behavior only until weekly MACD
and signal are both positive; isolated 3D histogram normalization cannot exit
an inherited weekly trend. Compare it with the weekly-only manager rather than
silently folding it into baseline results.
