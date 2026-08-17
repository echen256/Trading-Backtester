"""Compare weekly trend-management controls on identical scanner entry events.

The scanner artifacts only embed weekly OHLC, so the fixed-hold controls use
four and eight completed weekly bars as transparent approximations of 20 and
40 trading days.  It is an event study, not a capital-constrained portfolio.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, replace
from pathlib import Path
from typing import Sequence

from .levered_weekly_trend import LeveredTrendConfig, run_levered_weekly_trend
from .scanner_batch import load_scanner_weekly_rows, scanner_entry_events


VARIANTS: dict[str, LeveredTrendConfig] = {
    "core_structure": LeveredTrendConfig(
        max_exposure=1.0,
        allow_pyramiding=False,
        allow_delevering=False,
        allow_relevering=False,
        enable_emergency_exit=False,
    ),
    "sleeve_no_relever": LeveredTrendConfig(allow_relevering=False),
    "full_manager": LeveredTrendConfig(),
    "hold_4_weekly_bars": LeveredTrendConfig(
        max_exposure=1.0,
        allow_pyramiding=False,
        allow_delevering=False,
        allow_relevering=False,
        enable_emergency_exit=False,
        enable_structure_exit=False,
        fixed_hold_bars=4,
    ),
    "hold_8_weekly_bars": LeveredTrendConfig(
        max_exposure=1.0,
        allow_pyramiding=False,
        allow_delevering=False,
        allow_relevering=False,
        enable_emergency_exit=False,
        enable_structure_exit=False,
        fixed_hold_bars=8,
    ),
}


def _aggregate(records: list[dict[str, object]], variant: str) -> dict[str, object]:
    values = [float(item["variants"][variant]["return_pct"]) for item in records]
    drawdowns = [float(item["variants"][variant]["max_drawdown_pct"]) for item in records]
    statuses = [str(item["variants"][variant]["status"]) for item in records]
    return {
        "mean_return_pct": round(statistics.fmean(values), 4),
        "median_return_pct": round(statistics.median(values), 4),
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
        "mean_max_drawdown_pct": round(statistics.fmean(drawdowns), 4),
        "median_max_drawdown_pct": round(statistics.median(drawdowns), 4),
        "closed_event_count": statuses.count("closed"),
        "open_event_count": statuses.count("open"),
    }


def _write_readme(path: Path, aggregate: dict[str, dict[str, object]], records: list[dict[str, object]]) -> None:
    core = "core_structure"
    lines = [
        "# Weekly trend-manager control experiment",
        "",
        "All variants replay the same 202 scanner-selected entry events independently. These are overlapping event studies, not a portfolio simulation. Four and eight weekly completed bars approximate the requested 20/40 trading-day holds because this scanner archive embeds weekly—not daily—OHLC.",
        "",
        "| Model | Mean return | Median return | Win rate | Median max DD | Closed / open |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "core_structure": "1.0x core to weekly structure exit",
        "sleeve_no_relever": "Core + sleeve; no re-lever",
        "full_manager": "Full manager",
        "hold_4_weekly_bars": "1.0x fixed 4-week hold (~20d)",
        "hold_8_weekly_bars": "1.0x fixed 8-week hold (~40d)",
    }
    for key in VARIANTS:
        item = aggregate[key]
        lines.append(f"| {labels[key]} | {item['mean_return_pct']:.2f}% | {item['median_return_pct']:.2f}% | {item['win_rate_pct']:.2f}% | {item['median_max_drawdown_pct']:.2f}% | {item['closed_event_count']} / {item['open_event_count']} |")
    full_advantages = [
        float(item["variants"]["full_manager"]["return_pct"]) - float(item["variants"][core]["return_pct"])
        for item in records
    ]
    lines.extend([
        "",
        f"Full manager beat core-only in {sum(value > 0 for value in full_advantages)} / {len(full_advantages)} events ({sum(value > 0 for value in full_advantages) / len(full_advantages) * 100:.2f}%).",
        f"Median full-minus-core return difference: {statistics.median(full_advantages):.2f} percentage points.",
        "",
        "## Per-event comparison",
        "",
        "| Ticker | Entry | Core structure | Sleeve/no re-lever | Full | 4-week | 8-week |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for record in records:
        values = record["variants"]
        lines.append(
            f"| {record['ticker']} | {record['entry_date']} | {values['core_structure']['return_pct']:.2f}% | {values['sleeve_no_relever']['return_pct']:.2f}% | {values['full_manager']['return_pct']:.2f}% | {values['hold_4_weekly_bars']['return_pct']:.2f}% | {values['hold_8_weekly_bars']['return_pct']:.2f}% |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiment(scanner_report: Path, chart_dir: Path, output_dir: Path) -> dict[str, object]:
    records: list[dict[str, object]] = []
    cache: dict[str, list[dict[str, object]]] = {}
    for ticker, entry_date in scanner_entry_events(scanner_report):
        if ticker not in cache:
            cache[ticker] = load_scanner_weekly_rows(chart_dir / f"{ticker}.html")
        variants: dict[str, dict[str, object]] = {}
        for name, config in VARIANTS.items():
            run = run_levered_weekly_trend(ticker, cache[ticker], [entry_date], config=config)
            folder = output_dir / "runs" / ticker / entry_date
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{name}.json").write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
            trade = run.closed_trades[-1] if run.closed_trades else None
            variants[name] = {
                "return_pct": float(run.statistics["total_return_pct"]),
                "max_drawdown_pct": float(run.statistics["max_drawdown_pct"]),
                "status": "closed" if trade else "open",
                "exit_date": trade.exit_time if trade else None,
                "final_exposure": float(run.bars[-1]["target_exposure"]),
            }
        records.append({"ticker": ticker, "entry_date": entry_date, "variants": variants})
    aggregate = {name: _aggregate(records, name) for name in VARIANTS}
    payload = {
        "schema_version": "weekly-control-experiment/v1",
        "event_count": len(records),
        "source_report": str(scanner_report),
        "methodology": "Scanner-embedded weekly OHLC; independent overlapping event replays.",
        "variants": {name: asdict(config) for name, config in VARIANTS.items()},
        "aggregate": aggregate,
        "records": records,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_readme(output_dir / "README.md", aggregate, records)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner-report", type=Path, required=True)
    parser.add_argument("--scanner-chart-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    payload = run_experiment(args.scanner_report, args.scanner_chart_dir, args.output_dir)
    print(f"Wrote {args.output_dir} ({payload['event_count']} events × {len(VARIANTS)} variants)")


if __name__ == "__main__":  # pragma: no cover
    main()
