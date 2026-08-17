"""Run the weekly manager for every unique entry date in a scanner report."""
from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .levered_weekly_trend import LeveredTrendConfig, run_levered_weekly_trend, write_strategy_report


def scanner_entry_events(report: Path) -> list[tuple[str, str]]:
    """Read unique (ticker, entry-date) pairs from the scanner's Markdown tables."""
    events: set[tuple[str, str]] = set()
    for line in report.read_text(encoding="utf-8").splitlines():
        cells = [item.strip() for item in line.strip().split("|")[1:-1]]
        if len(cells) < 7 or cells[0] in {"Asset", "---"} or not re.fullmatch(r"[A-Z0-9._-]+", cells[0]):
            continue
        for entry_date in re.findall(r"\d{4}-\d{2}-\d{2}", cells[-2]):
            events.add((cells[0], entry_date))
    return sorted(events)


def load_scanner_weekly_rows(chart: Path) -> list[dict[str, object]]:
    """Load source weekly OHLC embedded in the scanner's self-contained chart."""
    text = chart.read_text(encoding="utf-8")
    match = re.search(r"<script>const p=(\{.*?\});", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Could not locate embedded chart payload in {chart}")
    payload = json.loads(match.group(1))
    fields = ("times", "open", "high", "low", "close")
    if not all(field in payload for field in fields):
        raise ValueError(f"Chart payload in {chart} does not contain weekly OHLC")
    return [
        {
            "timestamp": datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
            "open": float(open_),
            "high": float(high),
            "low": float(low),
            "close": float(close),
        }
        for day, open_, high, low, close in zip(payload["times"], payload["open"], payload["high"], payload["low"], payload["close"], strict=True)
    ]


def _summary(records: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(item["total_return_pct"]) for item in records]
    drawdowns = [float(item["max_drawdown_pct"]) for item in records]
    closed = [item for item in records if item["status"] == "closed"]
    return {
        "event_count": len(records),
        "closed_event_count": len(closed),
        "open_event_count": len(records) - len(closed),
        "mean_return_pct": round(statistics.fmean(returns), 4) if returns else None,
        "median_return_pct": round(statistics.median(returns), 4) if returns else None,
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "mean_max_drawdown_pct": round(statistics.fmean(drawdowns), 4) if drawdowns else None,
        "median_max_drawdown_pct": round(statistics.median(drawdowns), 4) if drawdowns else None,
    }


def _write_readme(path: Path, summary: dict[str, object], records: list[dict[str, object]], *, timeframe_days: int) -> None:
    lines = [
        f"# {timeframe_days}D fixed-core manager — scanner-entry batch",
        "",
        "Each row is an independent replay beginning from one unique ticker/date entry reported by the weekly scanner. This is an event study, not an investable portfolio: entries can overlap and no cross-asset capital allocation is modeled.",
        "",
        f"- Events: {summary['event_count']} ({summary['closed_event_count']} closed, {summary['open_event_count']} open at the scanner data cutoff)",
        f"- Mean / median return: {summary['mean_return_pct']:.2f}% / {summary['median_return_pct']:.2f}%",
        f"- Win rate: {summary['win_rate_pct']:.2f}%",
        f"- Mean / median max drawdown: {summary['mean_max_drawdown_pct']:.2f}% / {summary['median_max_drawdown_pct']:.2f}%",
        "",
        "## Event results",
        "",
        "| Ticker | Scanner entry | Status | Return | Max DD | Chart |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for item in records:
        chart = f"runs/{item['ticker']}/{item['entry_date']}.html"
        lines.append(
            f"| {item['ticker']} | {item['entry_date']} | {item['status']} | {item['total_return_pct']:.2f}% | {item['max_drawdown_pct']:.2f}% | [view]({chart}) |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_scanner_batch(
    scanner_report: Path,
    scanner_chart_dir: Path,
    output_dir: Path,
    *,
    config: LeveredTrendConfig | None = None,
    timeframe_days: int = 7,
    limit: int | None = None,
) -> dict[str, object]:
    """Generate independent fixed-core studies for every scanner entry event."""
    cfg = config or LeveredTrendConfig()
    records: list[dict[str, object]] = []
    row_cache: dict[str, list[dict[str, object]]] = {}
    events = scanner_entry_events(scanner_report)
    if limit is not None:
        events = events[:limit]
    for ticker, entry_date in events:
        if ticker not in row_cache:
            row_cache[ticker] = load_scanner_weekly_rows(scanner_chart_dir / f"{ticker}.html")
        run = run_levered_weekly_trend(ticker, row_cache[ticker], [entry_date], timeframe_days=timeframe_days, config=cfg)
        run_dir = output_dir / "runs" / ticker
        json_path = run_dir / f"{entry_date}.json"
        run_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
        write_strategy_report(run, run_dir / f"{entry_date}.html")
        closed_trade = run.closed_trades[-1] if run.closed_trades else None
        records.append(
            {
                "ticker": ticker,
                "entry_date": entry_date,
                "status": "closed" if closed_trade else "open",
                "exit_date": closed_trade.exit_time if closed_trade else None,
                "total_return_pct": float(run.statistics["total_return_pct"]),
                "max_drawdown_pct": float(run.statistics["max_drawdown_pct"]),
                "final_exposure": float(run.bars[-1]["target_exposure"]),
                "decisions": len(run.decisions),
            }
        )
    records.sort(key=lambda item: (str(item["ticker"]), str(item["entry_date"])))
    summary = _summary(records)
    payload = {
        "schema_version": "scanner-weekly-manager-batch/v1",
        "source_report": str(scanner_report),
        "data_source": f"{timeframe_days}D OHLC embedded in scanner charts",
        "timeframe_days": timeframe_days,
        "config": cfg.__dict__ if hasattr(cfg, "__dict__") else {name: getattr(cfg, name) for name in cfg.__dataclass_fields__},
        "summary": summary,
        "records": records,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_readme(output_dir / "README.md", summary, records, timeframe_days=timeframe_days)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner-report", type=Path, required=True)
    parser.add_argument("--scanner-chart-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeframe-days", type=int, choices=(3, 7), default=7)
    parser.add_argument("--limit", type=int, help="Run only the first N sorted scanner events")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    payload = run_scanner_batch(
        args.scanner_report,
        args.scanner_chart_dir,
        args.output_dir,
        timeframe_days=args.timeframe_days,
        limit=args.limit,
    )
    print(f"Wrote {args.output_dir} ({payload['summary']['event_count']} scanner entry events)")


if __name__ == "__main__":  # pragma: no cover
    main()
