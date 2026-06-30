# Trade Failure Modes

These labels are used for post-mortem tagging. They are behavioral patterns, not
mutually exclusive categories.

## Scattered Overtrading / Impulse Trades

Too many unrelated intraday trades, usually across several symbols or both
directions, where no single thesis explains the exposure. The common signature is
many small-to-medium losses that overwhelm the few winners.

## Weekend Hold Risk In Short-Dated Options

Short-dated option trades held over a weekend where theta, gap risk, or volatility
reset dominates the original setup. These trades need to be sized as event risk,
not normal intraday trades.

## Revenge / Re-Entry In Failed Symbols

Repeatedly returning to the same ticker after it has already failed that day or
week. The common signature is multiple losses in the same underlying, often after
one large loss should have ended trading in that name.

## Overworking A Previously Good Theme

Continuing to trade a theme after the clean edge has already paid. The common
signature is early wins followed by repeated re-entries that give back part or all
of the gain.

## 2026 Heuristic Trend Scan

The scan below uses realized trades from `webull_orders_2026.csv`. Labels are
heuristic and should be reviewed manually before being treated as final.

| Month | PnL | Scattered | Weekend Hold | Re-entry | Overwork |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jan | 5,079.00 | 0 | 3 | 2 | 0 |
| Feb | 13,995.85 | 3 | 6 | 2 | 0 |
| Mar | 21,355.57 | 1 | 7 | 7 | 2 |
| Apr | -14,242.08 | 4 | 8 | 8 | 3 |
| May | -90.49 | 6 | 3 | 9 | 2 |
| Jun | 8,702.80 | 6 | 3 | 8 | 3 |

Initial read:

- April is the regime break. It is the first month where all four failure modes
  cluster together and the flagged days account for most of the drawdown.
- Weekend hold risk appears throughout the year, but the worst losses cluster
  from March through May.
- Re-entry risk gets worse after March and stays elevated through June.
- Scattered overtrading becomes much more common in May and June, even though
  June finished positive.
- Overwork shows up mostly after the strategy has proven it can hit large
  winners, suggesting the issue is giving back good themes rather than lacking
  trade ideas.
