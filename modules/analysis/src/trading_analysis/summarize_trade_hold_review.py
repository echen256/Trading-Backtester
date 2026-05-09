from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_INPUT_PATH = (
    REPO_ROOT / "modules" / "analysis" / "order-data" / "trade-hold-review-2025-01-01-to-2026-04-29.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize trade hold review JSON.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to the trade hold review JSON file.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    profitable_trades = _as_list(payload.get("profitable_trades"))
    unprofitable_trades = _as_list(payload.get("unprofitable_trades"))

    profitable_summary = _summarize_bucket(profitable_trades)
    unprofitable_summary = _summarize_bucket(unprofitable_trades)

    total_trades = len(profitable_trades) + len(unprofitable_trades)
    print(f"Input: {args.input}")
    print(f"Total trades: {total_trades}")
    print("")
    _print_bucket("Profitable Trades", profitable_summary)
    print("")
    _print_bucket("Unprofitable Trades", unprofitable_summary)


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _summarize_bucket(trades: list[dict[str, Any]]) -> dict[str, int]:
    total = len(trades)
    had_later_data = sum(1 for trade in trades if trade.get("hold_longer_analysis_status") == "ok")
    no_later_data = total - had_later_data
    later_profitable = sum(1 for trade in trades if trade.get("would_have_been_profitable_if_held_longer") is True)
    later_not_profitable = sum(1 for trade in trades if trade.get("would_have_been_profitable_if_held_longer") is False)
    later_improved = sum(1 for trade in trades if trade.get("would_have_improved_pnl_if_held_longer") is True)
    later_not_improved = sum(1 for trade in trades if trade.get("would_have_improved_pnl_if_held_longer") is False)
    later_beat_pre_exit_peak = sum(
        1 for trade in trades if trade.get("would_have_beaten_pre_exit_peak_pnl_if_held_longer") is True
    )
    later_did_not_beat_pre_exit_peak = sum(
        1 for trade in trades if trade.get("would_have_beaten_pre_exit_peak_pnl_if_held_longer") is False
    )
    return {
        "total": total,
        "had_later_data": had_later_data,
        "no_later_data": no_later_data,
        "later_profitable": later_profitable,
        "later_not_profitable": later_not_profitable,
        "later_improved": later_improved,
        "later_not_improved": later_not_improved,
        "later_beat_pre_exit_peak": later_beat_pre_exit_peak,
        "later_did_not_beat_pre_exit_peak": later_did_not_beat_pre_exit_peak,
    }


def _print_bucket(title: str, summary: dict[str, int]) -> None:
    total = summary["total"] or 1
    print(title)
    print(f"  Total: {summary['total']}")
    print(f"  Had later option data: {summary['had_later_data']}")
    print(f"  No later option data: {summary['no_later_data']}")
    print(
        f"  Would have been profitable if held longer: "
        f"{summary['later_profitable']} ({summary['later_profitable'] / total:.2%})"
    )
    print(
        f"  Would not have been profitable if held longer: "
        f"{summary['later_not_profitable']} ({summary['later_not_profitable'] / total:.2%})"
    )
    print(
        f"  Would have improved PnL if held longer: "
        f"{summary['later_improved']} ({summary['later_improved'] / total:.2%})"
    )
    print(
        f"  Would not have improved PnL if held longer: "
        f"{summary['later_not_improved']} ({summary['later_not_improved'] / total:.2%})"
    )
    print(
        f"  Would have beaten pre-exit peak PnL if held longer: "
        f"{summary['later_beat_pre_exit_peak']} ({summary['later_beat_pre_exit_peak'] / total:.2%})"
    )
    print(
        f"  Would not have beaten pre-exit peak PnL if held longer: "
        f"{summary['later_did_not_beat_pre_exit_peak']} ({summary['later_did_not_beat_pre_exit_peak'] / total:.2%})"
    )


if __name__ == "__main__":
    main()
