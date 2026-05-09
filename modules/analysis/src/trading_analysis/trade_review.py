from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

import plotly.graph_objects as go

from .display_common import describe_contract, extract_underlying_symbol

if TYPE_CHECKING:
    from .parse_orders import RealizedTrade


DEFAULT_BACKEND_BASE_URL = os.getenv("TRADING_BACKTESTER_BACKEND_URL", "http://127.0.0.1:5001")
DEFAULT_TIMEFRAME = "1d"
DEFAULT_BUFFER_DAYS = 10
POLYGON_API_BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


def analyze_trade(
    trade: RealizedTrade,
    *,
    backend_base_url: str = DEFAULT_BACKEND_BASE_URL,
    timeframe: str = DEFAULT_TIMEFRAME,
    buffer_days: int = DEFAULT_BUFFER_DAYS,
) -> Path:
    underlying_symbol = extract_underlying_symbol(trade.symbol)
    start_date = trade.open_date - timedelta(days=buffer_days)
    end_date = trade.trade_date + timedelta(days=buffer_days)
    bars = fetch_trade_bars(
        underlying_symbol,
        start_date,
        end_date,
        backend_base_url=backend_base_url,
        timeframe=timeframe,
    )
    output_path = build_trade_review_chart(
        trade,
        bars,
        underlying_symbol=underlying_symbol,
        timeframe=timeframe,
    )
    webbrowser.open(output_path.resolve().as_uri())
    return output_path


def fetch_trade_bars(
    ticker: str,
    start_date: date,
    end_date: date,
    *,
    backend_base_url: str,
    timeframe: str,
) -> list[dict[str, object]]:
    backend_error: RuntimeError | None = None
    try:
        return _fetch_trade_bars_from_backend(
            ticker,
            start_date,
            end_date,
            backend_base_url=backend_base_url,
            timeframe=timeframe,
        )
    except RuntimeError as exc:
        backend_error = exc

    try:
        return _fetch_trade_bars_from_polygon(
            ticker,
            start_date,
            end_date,
            timeframe=timeframe,
        )
    except RuntimeError as exc:
        if backend_error is None:
            raise
        raise RuntimeError(f"{backend_error}\nFallback Polygon request also failed: {exc}") from exc


def _fetch_trade_bars_from_backend(
    ticker: str,
    start_date: date,
    end_date: date,
    *,
    backend_base_url: str,
    timeframe: str,
) -> list[dict[str, object]]:
    base_url = backend_base_url.rstrip("/")
    path = f"/stock/{ticker}/{start_date.isoformat()}/{end_date.isoformat()}"
    query = urllib.parse.urlencode({"timeframe": timeframe})
    url = f"{base_url}{path}?{query}"

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Trade analysis request failed ({exc.code}) for {url}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach backend market-data endpoint at {url}. "
            "Make sure the backend is running."
        ) from exc

    data = payload.get("data")
    if not isinstance(data, dict):
        error = payload.get("error") or "missing data payload"
        raise RuntimeError(f"Trade analysis response for {ticker} was invalid: {error}")

    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError(
            f"No ticker data returned for {ticker} between {start_date.isoformat()} and {end_date.isoformat()}."
        )
    return results


def _fetch_trade_bars_from_polygon(
    ticker: str,
    start_date: date,
    end_date: date,
    *,
    timeframe: str,
) -> list[dict[str, object]]:
    api_key = _get_polygon_api_key()
    if not api_key:
        raise RuntimeError(
            f"POLYGON_API_KEY is not set for direct Polygon fallback. "
            f"Expected it in the environment or {DEFAULT_ENV_PATH}."
        )

    multiplier, timespan = _timeframe_to_polygon_range(timeframe)
    query = urllib.parse.urlencode({"apiKey": api_key, "limit": 50000})
    url = (
        f"{POLYGON_API_BASE_URL}/{ticker}/range/{multiplier}/{timespan}/"
        f"{start_date.isoformat()}/{end_date.isoformat()}?{query}"
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Direct Polygon request failed ({exc.code}) for {url}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Polygon for trade analysis: {url}") from exc

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        error = payload.get("error") or payload.get("message") or "no results"
        raise RuntimeError(
            f"Polygon returned no data for {ticker} between {start_date.isoformat()} and "
            f"{end_date.isoformat()}: {error}"
        )
    return results


def build_trade_review_chart(
    trade: RealizedTrade,
    bars: Sequence[dict[str, object]],
    *,
    underlying_symbol: str,
    timeframe: str,
) -> Path:
    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []

    for bar in bars:
        timestamps.append(_parse_bar_timestamp(bar.get("t")))
        opens.append(float(bar["o"]))
        highs.append(float(bar["h"]))
        lows.append(float(bar["l"]))
        closes.append(float(bar["c"]))

    entry_marker = _build_trade_marker(trade.open_date, timestamps, closes, "Entry", "#2ca02c")
    exit_marker = _build_trade_marker(trade.trade_date, timestamps, closes, "Exit", "#d62728")

    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name=underlying_symbol,
        )
    )
    figure.add_trace(entry_marker)
    figure.add_trace(exit_marker)
    figure.update_layout(
        title=(
            f"{underlying_symbol} Trade Analysis: {describe_contract(trade.symbol)}"
            f" ({trade.open_date.isoformat()} to {trade.trade_date.isoformat()})"
        ),
        xaxis_title="Date",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        template="plotly_white",
    )

    output_dir = Path(tempfile.gettempdir()) / "trading-analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (
        f"{_sanitize_symbol(underlying_symbol)}-"
        f"{trade.open_date.isoformat()}-{trade.trade_date.isoformat()}-{timeframe}.html"
    )
    figure.write_html(output_path, auto_open=False, include_plotlyjs="cdn")
    return output_path


def _build_trade_marker(
    trade_date: date,
    timestamps: Sequence[datetime],
    closes: Sequence[float],
    label: str,
    color: str,
) -> go.Scatter:
    marker_index = _nearest_timestamp_index(trade_date, timestamps)
    marker_timestamp = timestamps[marker_index]
    marker_close = closes[marker_index]
    return go.Scatter(
        x=[marker_timestamp],
        y=[marker_close],
        mode="markers+text",
        marker={"size": 14, "color": color, "symbol": "diamond"},
        text=[label],
        textposition="top center",
        name=label,
        hovertemplate=f"{label}<br>%{{x|%Y-%m-%d}}<br>Close: %{{y:.2f}}<extra></extra>",
    )


def _nearest_timestamp_index(target_date: date, timestamps: Sequence[datetime]) -> int:
    target_datetime = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    return min(
        range(len(timestamps)),
        key=lambda index: abs(timestamps[index] - target_datetime),
    )


def _parse_bar_timestamp(raw_timestamp: object) -> datetime:
    if isinstance(raw_timestamp, (int, float)):
        return datetime.fromtimestamp(raw_timestamp / 1000, tz=timezone.utc)
    raise ValueError(f"Unsupported bar timestamp: {raw_timestamp!r}")


def _sanitize_symbol(symbol: str) -> str:
    return symbol.replace(":", "_").replace("/", "-")


def _timeframe_to_polygon_range(timeframe: str) -> tuple[int, str]:
    if timeframe == "1d":
        return 1, "day"
    if timeframe == "1h":
        return 1, "hour"
    if timeframe == "1wk":
        return 1, "week"
    if timeframe.endswith("m") and timeframe[:-1].isdigit():
        return int(timeframe[:-1]), "minute"
    raise RuntimeError(f"Unsupported timeframe for trade analysis: {timeframe}")


def _get_polygon_api_key() -> str | None:
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key:
        return api_key
    return _load_env_value(DEFAULT_ENV_PATH, "POLYGON_API_KEY")


def _load_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        cleaned = value.strip().strip('"').strip("'")
        if cleaned:
            os.environ[key] = cleaned
            return cleaned
    return None
