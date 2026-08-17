"""Experimental 3D-ignition / weekly-inheritance trend detector.

This layer answers *whether a trend is active and which timeframe has
authority*.  It deliberately does not size or exit the position; use
``levered_weekly_trend`` for the independent position-management study.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .levered_weekly_trend import (
    LeveredTrendConfig,
    _confirmed_lower_high_break,
    _float_or_none,
    aggregate_bars,
    build_weekly_features,
    load_ohlcv_csv,
)


@dataclass(frozen=True, slots=True)
class CompositeTrendConfig:
    """Coarse controls for the experimental stateful timeframe handoff."""

    breakout_lookback_3d: int = 8
    efficiency_lookback_3d: int = 5
    minimum_price_efficiency: float = 0.45


def _price_efficiency(features: list[dict[str, object]], index: int, lookback: int) -> float | None:
    if index < lookback:
        return None
    closes = [float(item["close"]) for item in features[index - lookback : index + 1]]
    path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    return (closes[-1] - closes[0]) / path if path else 0.0


def build_composite_trend_states(
    daily_rows: list[dict[str, object]],
    *,
    indicator_config: LeveredTrendConfig | None = None,
    config: CompositeTrendConfig | None = None,
) -> list[dict[str, object]]:
    """Return causal C0--C5 states without allowing 3D normalization to exit a weekly trend.

    ``C1``/``C2`` are governed by 3D breakout behavior.  Once the weekly
    adaptive MACD and signal are positive, the detector moves to ``C3`` and
    only weekly inputs can move it through ``C4`` or ``C5``.
    """
    cfg, indicator_cfg = config or CompositeTrendConfig(), indicator_config or LeveredTrendConfig()
    fast_rows = aggregate_bars(daily_rows, timeframe_days=3)
    weekly_rows = aggregate_bars(daily_rows, timeframe_days=7)
    fast, weekly = build_weekly_features(fast_rows, indicator_cfg), build_weekly_features(weekly_rows, indicator_cfg)
    weekly_breaks = _confirmed_lower_high_break(weekly_rows)
    weekly_index = -1
    state, breakout_level = "C0_CONSOLIDATION", None
    output: list[dict[str, object]] = []

    for index, feature in enumerate(fast):
        current_time = str(feature["time"])
        while weekly_index + 1 < len(weekly) and str(weekly[weekly_index + 1]["time"]) <= current_time:
            weekly_index += 1
        weekly_feature = weekly[weekly_index] if weekly_index >= 0 else None
        weekly_active = bool(
            weekly_feature
            and _float_or_none(weekly_feature["adaptive_macd"]) is not None
            and _float_or_none(weekly_feature["signal"]) is not None
            and float(weekly_feature["adaptive_macd"]) > 0
            and float(weekly_feature["signal"]) > 0
        )
        efficiency = _price_efficiency(fast, index, cfg.efficiency_lookback_3d)
        fast_macd, fast_hist = _float_or_none(feature["adaptive_macd"]), _float_or_none(feature["histogram"])
        prior_fast = fast[index - 1] if index else None
        prior_high = max((float(item["high"]) for item in fast[max(0, index - cfg.breakout_lookback_3d) : index]), default=None)
        ignition = bool(
            prior_high is not None
            and fast_macd is not None
            and fast_hist is not None
            and fast_macd > 0
            and fast_hist >= 0
            and float(feature["close"]) > prior_high
            and (efficiency is None or efficiency >= cfg.minimum_price_efficiency)
        )
        prior_hist = _float_or_none(prior_fast["histogram"]) if prior_fast else None
        prior_macd = _float_or_none(prior_fast["adaptive_macd"]) if prior_fast else None
        fast_normalizing = bool(fast_hist is not None and prior_hist is not None and fast_hist < prior_hist and fast_macd is not None and prior_macd is not None and fast_macd >= prior_macd)
        failed_handoff = bool(
            state in {"C1_IGNITION", "C2_TRANSITION"}
            and breakout_level is not None
            and (float(feature["close"]) < breakout_level or (fast_macd is not None and fast_macd < 0 and fast_hist is not None and fast_hist < 0))
        )
        weekly_decelerating = False
        weekly_structure_break = False
        if weekly_index > 0 and weekly_feature:
            prior_weekly = weekly[weekly_index - 1]
            weekly_decelerating = bool(
                _float_or_none(weekly_feature["histogram"]) is not None
                and _float_or_none(prior_weekly["histogram"]) is not None
                and _float_or_none(weekly_feature["adaptive_macd"]) is not None
                and _float_or_none(prior_weekly["adaptive_macd"]) is not None
                and float(weekly_feature["histogram"]) < float(prior_weekly["histogram"])
                and float(weekly_feature["adaptive_macd"]) <= float(prior_weekly["adaptive_macd"])
            )
            weekly_structure_break = weekly_breaks[weekly_index]

        if state == "C0_CONSOLIDATION" and ignition:
            state, breakout_level = "C1_IGNITION", float(feature["close"])
        elif state in {"C1_IGNITION", "C2_TRANSITION"}:
            if weekly_active:
                state = "C3_WEEKLY_INHERITANCE"
            elif failed_handoff:
                state, breakout_level = "C0_CONSOLIDATION", None
            elif fast_normalizing:
                state = "C2_TRANSITION"
        elif state in {"C3_WEEKLY_INHERITANCE", "C4_WEEKLY_DECELERATION"}:
            if weekly_structure_break:
                state, breakout_level = "C5_STRUCTURAL_FAILURE", None
            elif weekly_decelerating:
                state = "C4_WEEKLY_DECELERATION"
            else:
                state = "C3_WEEKLY_INHERITANCE"

        authority = "weekly" if state in {"C3_WEEKLY_INHERITANCE", "C4_WEEKLY_DECELERATION", "C5_STRUCTURAL_FAILURE"} else ("3D" if state in {"C1_IGNITION", "C2_TRANSITION"} else "none")
        output.append(
            {
                "time": current_time,
                "state": state,
                "authority": authority,
                "close": feature["close"],
                "price_efficiency": efficiency,
                "fast_macd": fast_macd,
                "fast_histogram": fast_hist,
                "weekly_macd": weekly_feature["adaptive_macd"] if weekly_feature else None,
                "weekly_histogram": weekly_feature["histogram"] if weekly_feature else None,
                "breakout_level": breakout_level,
            }
        )
        if state == "C5_STRUCTURAL_FAILURE":
            state = "C0_CONSOLIDATION"
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--ohlcv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="JSON overrides matching CompositeTrendConfig")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    values = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    if not isinstance(values, dict):
        raise ValueError("composite config must be a JSON object")
    config = CompositeTrendConfig(**values)
    states = build_composite_trend_states(load_ohlcv_csv(args.ohlcv), config=config)
    payload = {"schema_version": "composite-trend/v1", "ticker": args.ticker.upper(), "config": asdict(config), "states": states}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(states)} 3D state observations)")


if __name__ == "__main__":  # pragma: no cover
    main()
