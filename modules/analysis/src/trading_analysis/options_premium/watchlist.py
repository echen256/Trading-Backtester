"""Txt watchlist loader for options-premium tools."""

from __future__ import annotations

from pathlib import Path

from trading_analysis.parse_orders import ORDER_DATA_DIR

DEFAULT_WATCHLIST_PATH = ORDER_DATA_DIR / "watchlist.txt"


def load_watchlist(path: Path | None = None) -> list[str]:
    """
    Load tickers from a text watchlist.

    Format: one symbol per line; blank lines and ``#`` comments ignored.
    """
    watchlist_path = Path(path) if path is not None else DEFAULT_WATCHLIST_PATH
    if not watchlist_path.exists():
        return []
    symbols: list[str] = []
    seen: set[str] = set()
    for raw in watchlist_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # allow "MU  # note" style
        token = line.split("#", 1)[0].strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        symbols.append(token)
    return symbols
