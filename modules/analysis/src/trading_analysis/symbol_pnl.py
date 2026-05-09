from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from statistics import StatisticsError
from typing import TYPE_CHECKING, List, Mapping, Sequence

try:
    from asciichart import asciichart as asciichart_module
except ModuleNotFoundError:
    asciichart_module = None

if TYPE_CHECKING:
    from .parse_orders import RealizedTrade


def analyze_symbols(contract_pnl: Mapping[str, float]) -> dict[str, float]:
    symbol_pnl: dict[str, float] = {}
    for contract_name, pnl in contract_pnl.items():
        symbol = re.split(r"\d+", contract_name)[0]
        if symbol_pnl.get(symbol) is None:
            symbol_pnl[symbol] = 0.0
        symbol_pnl[symbol] += pnl
    return symbol_pnl


def compute_symbol_avg_rr(trades: Sequence[RealizedTrade]) -> dict[str, float]:
    wins_by_symbol: dict[str, List[float]] = defaultdict(list)
    losses_by_symbol: dict[str, List[float]] = defaultdict(list)

    for trade in trades:
        symbol = re.split(r"\d+", trade.symbol)[0]
        if trade.pnl > 0:
            wins_by_symbol[symbol].append(trade.pnl)
        elif trade.pnl < 0:
            losses_by_symbol[symbol].append(trade.pnl)

    all_symbols = set(wins_by_symbol) | set(losses_by_symbol)
    rr: dict[str, float] = {}
    for symbol in all_symbols:
        wins = wins_by_symbol.get(symbol, [])
        losses = losses_by_symbol.get(symbol, [])
        avg_win = statistics.mean(wins) if wins else 0.0
        avg_loss = abs(statistics.mean(losses)) if losses else 0.0
        if avg_loss == 0:
            rr[symbol] = float("inf") if avg_win > 0 else 0.0
        else:
            rr[symbol] = avg_win / avg_loss
    return rr


def render_contract_pnl_chart(
    contract_pnl: Mapping[str, float],
    symbol_rr: Mapping[str, float] | None = None,
) -> str:
    if asciichart_module is None:
        raise RuntimeError("asciichart is required for rendering the ASCII PnL chart.")

    sorted_items = sorted(contract_pnl.items(), key=lambda kv: kv[1], reverse=True)

    def _rr_tag(symbol: str) -> str:
        if symbol_rr is None or symbol not in symbol_rr:
            return ""
        rr = symbol_rr[symbol]
        if math.isinf(rr):
            return " [R:R inf]"
        return f" [R:R {rr:.2f}]"

    labels = [
        f"{index + 1:03d}. {symbol} ({value:,.2f}){_rr_tag(symbol)}"
        for index, (symbol, value) in enumerate(sorted_items)
    ]
    magnitudes = [abs(value) for _, value in sorted_items]
    max_label_len = max(len(label) for label in labels)
    all_integer = all(float(magnitude).is_integer() for magnitude in magnitudes)
    min_value = min(magnitudes)
    max_value = max(magnitudes)
    if max_value == 0:
        return "".join(label.rjust(max_label_len) for label in labels)
    width = max(10, 80 - max_label_len - 1)
    lines = []
    for label, magnitude in zip(labels, magnitudes):
        bar = asciichart_module.draw_bar("=", magnitude, all_integer, min_value, max_value, width)
        lines.append(f"{label.rjust(max_label_len)} {bar}")

    pnl_list = list(contract_pnl.values())
    total = sum(pnl_list)
    average = total / len(pnl_list)
    median = statistics.median(pnl_list)
    try:
        mode_value = statistics.mode(pnl_list)
    except StatisticsError:
        mode_candidates = statistics.multimode(pnl_list)
        mode_value = mode_candidates[0] if mode_candidates else 0.0
    pnl_range = (min(pnl_list), max(pnl_list))
    stdev = statistics.stdev(pnl_list) if len(pnl_list) >= 2 else 0.0

    wins = sum(1 for value in pnl_list if value > 0)
    losses = sum(1 for value in pnl_list if value < 0)
    flats = len(pnl_list) - wins - losses
    denominator = len(pnl_list) or 1
    win_rate = (wins / denominator) * 100
    loss_rate = (losses / denominator) * 100

    avg_rr_text = "N/A"
    if symbol_rr:
        finite_rrs = [v for v in symbol_rr.values() if not math.isinf(v) and v > 0]
        if finite_rrs:
            avg_rr_text = f"{statistics.mean(finite_rrs):.2f}"

    lines.append("--------------------------------")
    lines.append(f"Total: {total:,.2f}")
    lines.append(f"Average: {average:,.2f}")
    lines.append(f"Median: {median:,.2f}")
    lines.append(f"Mode: {mode_value:,.2f}")
    lines.append(f"Range: {pnl_range[0]:,.2f} - {pnl_range[1]:,.2f}")
    lines.append(f"Standard Deviation: {stdev:,.2f}")
    lines.append(f"Win rate: {win_rate:5.2f}% ({wins}/{len(pnl_list)})")
    lines.append(f"Loss rate: {loss_rate:5.2f}% ({losses}/{len(pnl_list)})")
    lines.append(f"Flat positions: {flats}")
    lines.append(f"Avg R:R: {avg_rr_text}")

    kelly_text = "N/A"
    w = wins / denominator if denominator else 0.0
    if symbol_rr:
        finite_rrs = [v for v in symbol_rr.values() if not math.isinf(v) and v > 0]
        if finite_rrs:
            r = statistics.mean(finite_rrs)
            if r > 0:
                kelly = w - (1 - w) / r
                kelly_text = f"{kelly * 100:.2f}%"
    lines.append(f"Kelly Criterion: {kelly_text}")
    lines.append("--------------------------------")
    return "\n".join(lines)
