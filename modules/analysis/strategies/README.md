# Strategies

This folder holds strategy specifications and reproducible run artifacts. Code
lives in `src/trading_analysis/strategies/` so it can be imported and run via
the analysis package.

`levered_trend_following_rules.md` is the local implementation rulebook for
the weekly levered trend manager. It is intentionally separate from entry
selection: callers supply entry dates, then inspect the emitted decision log,
trade ledger, equity curve, exposure, turnover, drawdown, and tail-return
metrics.

`composite_trend.py` is the experimental 3D ignition → weekly-inheritance
detector. It emits state and timeframe authority separately, letting its 3D
entry + weekly-handoff hypothesis be tested against the weekly-only baseline.

The adjacent `*.default.json` files are versioned, non-optimized starting
parameters. Pass a copied/edited file with `--config` to retain an exact
parameter record with each experiment.
