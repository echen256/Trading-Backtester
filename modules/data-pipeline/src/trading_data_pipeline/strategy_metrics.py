"""Helpers for computing strategy profitability and performance statistics."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class StrategyTrade:
    """Normalized completed trade used for strategy-level performance metrics."""

    side: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    bars_held: int
    pnl_points: float
    pnl_pct: float
    exit_reason: str = ""


def _coerce_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _trade_return_pct(side: str, entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    normalized_side = side.lower().strip()
    if normalized_side == "short":
        return ((entry_price - exit_price) / entry_price) * 100.0
    return ((exit_price - entry_price) / entry_price) * 100.0


def build_trade(
    *,
    side: str,
    entry_time: str,
    entry_price: float,
    exit_time: str,
    exit_price: float,
    bars_held: int,
    exit_reason: str = "",
) -> StrategyTrade:
    entry_value = float(entry_price)
    exit_value = float(exit_price)
    pnl_pct = _trade_return_pct(side, entry_value, exit_value)
    pnl_points = exit_value - entry_value if side.lower().strip() != "short" else entry_value - exit_value
    return StrategyTrade(
        side=side.lower().strip() or "long",
        entry_time=entry_time,
        entry_price=entry_value,
        exit_time=exit_time,
        exit_price=exit_value,
        bars_held=int(bars_held),
        pnl_points=pnl_points,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
    )


def serialize_trades(trades: list[StrategyTrade]) -> list[dict[str, Any]]:
    return [asdict(trade) for trade in trades]


def compute_strategy_statistics(
    trades: list[StrategyTrade],
    *,
    open_trade: dict[str, object] | None = None,
    latest_close: float | None = None,
) -> dict[str, object]:
    """Compute profitability and risk statistics from completed trades."""

    trade_count = len(trades)
    wins = [trade for trade in trades if trade.pnl_pct > 0]
    losses = [trade for trade in trades if trade.pnl_pct < 0]

    net_profit_points = sum(trade.pnl_points for trade in trades)
    avg_trade_return_pct = sum(trade.pnl_pct for trade in trades) / trade_count if trade_count else 0.0
    avg_bars_held = sum(trade.bars_held for trade in trades) / trade_count if trade_count else 0.0
    avg_win_return_pct = sum(trade.pnl_pct for trade in wins) / len(wins) if wins else 0.0
    avg_loss_return_pct = sum(trade.pnl_pct for trade in losses) / len(losses) if losses else 0.0
    gross_profit_pct = sum(trade.pnl_pct for trade in wins)
    gross_loss_pct = abs(sum(trade.pnl_pct for trade in losses))
    profit_factor = None if gross_loss_pct == 0 else gross_profit_pct / gross_loss_pct

    equity_curve = [1.0]
    max_equity = 1.0
    max_drawdown_pct = 0.0
    for trade in trades:
        equity_curve.append(equity_curve[-1] * (1.0 + trade.pnl_pct / 100.0))
        max_equity = max(max_equity, equity_curve[-1])
        if max_equity > 0:
            drawdown = ((equity_curve[-1] / max_equity) - 1.0) * 100.0
            max_drawdown_pct = min(max_drawdown_pct, drawdown)

    open_trade_return_pct = None
    open_trade_payload = dict(open_trade) if isinstance(open_trade, dict) else None
    if open_trade_payload and latest_close is not None:
        side = str(open_trade_payload.get("side") or "long")
        entry_price = _coerce_float(open_trade_payload.get("entry_price"))
        if entry_price is not None and entry_price > 0:
            open_trade_return_pct = _trade_return_pct(side, entry_price, latest_close)
            open_trade_payload["unrealized_return_pct"] = round(open_trade_return_pct, 4)
            open_trade_payload["latest_close"] = round(latest_close, 6)

    expectancy_pct = ((len(wins) / trade_count) * avg_win_return_pct + (len(losses) / trade_count) * avg_loss_return_pct) if trade_count else 0.0

    return {
        "closed_trades": trade_count,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round((len(wins) / trade_count) * 100.0, 2) if trade_count else 0.0,
        "net_profit_points": round(net_profit_points, 4),
        "cumulative_return_pct": round((equity_curve[-1] - 1.0) * 100.0, 4),
        "avg_trade_return_pct": round(avg_trade_return_pct, 4),
        "avg_win_return_pct": round(avg_win_return_pct, 4),
        "avg_loss_return_pct": round(avg_loss_return_pct, 4),
        "profit_factor": None if profit_factor is None else round(profit_factor, 4),
        "expectancy_pct": round(expectancy_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "avg_bars_held": round(avg_bars_held, 2),
        "open_trade": open_trade_payload,
        "open_trade_return_pct": None if open_trade_return_pct is None else round(open_trade_return_pct, 4),
    }


__all__ = [
    "StrategyTrade",
    "build_trade",
    "compute_strategy_statistics",
    "serialize_trades",
]
