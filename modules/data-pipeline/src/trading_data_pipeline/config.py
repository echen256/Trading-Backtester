"""Configuration helpers for the data pipeline module."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "download.json"
DEFAULT_WATCHLIST_PATH = PACKAGE_ROOT / "config" / "watchlists" / "NASDAQ.csv"


@dataclass(slots=True)
class DownloadConfig:
    minimum_market_cap: int = 0
    limit: int | None = None


def load_download_config(path: Path | None = None) -> DownloadConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return DownloadConfig()
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    minimum_cap = int(payload.get("minimum_market_cap", 0))
    limit_value = payload.get("limit")
    return DownloadConfig(
        minimum_market_cap=minimum_cap,
        limit=int(limit_value) if limit_value is not None else None,
    )


def read_watchlist(path: Path | None = None) -> list[str]:
    watchlist_path = Path(path) if path else DEFAULT_WATCHLIST_PATH
    if not watchlist_path.exists():
        raise FileNotFoundError(f"Watchlist not found: {watchlist_path}")
    symbols: list[str] = []
    with watchlist_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            token = line.strip()
            if not token:
                continue
            if token.lower() == "symbol" and not symbols:
                continue
            symbols.append(token)
    return symbols


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_WATCHLIST_PATH",
    "DownloadConfig",
    "load_download_config",
    "read_watchlist",
]
