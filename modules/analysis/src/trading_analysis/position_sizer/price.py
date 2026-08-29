"""Last usable price: live trade if entitled, else previous close / daily bar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from trading_analysis.market_data.polygon import (
    PolygonHttpError,
    fetch_last_trade,
    fetch_prev_close,
)
from trading_analysis.market_data.underlying_dailies import fetch_underlying_daily_bars

CRYPTO_ALIASES = {
    "BTC": "X:BTCUSD",
    "BTCUSD": "X:BTCUSD",
    "BTC-USD": "X:BTCUSD",
    "ETH": "X:ETHUSD",
    "ETHUSD": "X:ETHUSD",
    "ETH-USD": "X:ETHUSD",
}

PriceSource = Literal["last_trade", "prev_close", "daily_close"]


@dataclass(frozen=True, slots=True)
class LastPrice:
    requested: str
    polygon_ticker: str
    price: float
    source: PriceSource
    size: float | None
    exchange: int | None
    timestamp_ns: int | None
    as_of_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "polygon_ticker": self.polygon_ticker,
            "price": self.price,
            "source": self.source,
            "size": self.size,
            "exchange": self.exchange,
            "timestamp_ns": self.timestamp_ns,
            "as_of_utc": self.as_of_utc,
        }


def resolve_polygon_ticker(symbol: str) -> str:
    raw = symbol.strip().upper()
    return CRYPTO_ALIASES.get(raw, raw)


def _from_trade(symbol: str, ticker: str, trade: dict[str, Any]) -> LastPrice:
    ts = trade.get("t")
    as_of = None
    if isinstance(ts, (int, float)):
        as_of = datetime.fromtimestamp(ts / 1e9, tz=timezone.utc).isoformat()
    return LastPrice(
        requested=symbol.strip().upper(),
        polygon_ticker=ticker,
        price=float(trade["p"]),
        source="last_trade",
        size=float(trade["s"]) if trade.get("s") is not None else None,
        exchange=int(trade["x"]) if trade.get("x") is not None else None,
        timestamp_ns=int(ts) if isinstance(ts, (int, float)) else None,
        as_of_utc=as_of,
    )


def _from_bar(symbol: str, ticker: str, bar: dict[str, Any], source: PriceSource) -> LastPrice:
    ts = bar.get("t")
    as_of = None
    if isinstance(ts, (int, float)):
        as_of = datetime.fromtimestamp(ts / 1e3, tz=timezone.utc).isoformat()
    return LastPrice(
        requested=symbol.strip().upper(),
        polygon_ticker=ticker,
        price=float(bar["c"]),
        source=source,
        size=None,
        exchange=None,
        timestamp_ns=int(ts) * 1_000_000 if isinstance(ts, (int, float)) else None,
        as_of_utc=as_of,
    )


def fetch_last_price(symbol: str) -> LastPrice:
    ticker = resolve_polygon_ticker(symbol)
    try:
        return _from_trade(symbol, ticker, fetch_last_trade(ticker))
    except PolygonHttpError:
        pass
    try:
        return _from_bar(symbol, ticker, fetch_prev_close(ticker), "prev_close")
    except PolygonHttpError:
        pass
    end = date.today()
    start = end - timedelta(days=14)
    bars = fetch_underlying_daily_bars(ticker, start_date=start, end_date=end)
    if not bars:
        raise RuntimeError(f"No price available for {ticker}")
    return _from_bar(symbol, ticker, bars[-1], "daily_close")  # type: ignore[arg-type]
