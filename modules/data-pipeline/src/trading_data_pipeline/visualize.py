"""Quick local visualization for archived OHLCV CSV files."""
from __future__ import annotations

import argparse
import csv
import importlib
import inspect
import json
import math
import tempfile
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"
STRATEGIES_DIR = Path(__file__).resolve().parent / "strategies"


@dataclass(slots=True)
class ChartPayload:
    ticker: str
    timeframe_minutes: int
    rows: list[dict[str, object]]
    source_label: str | None = None
    overlays: dict[str, Any] = field(default_factory=dict)


def _parse_timeframe(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.endswith("m"):
        normalized = normalized[:-1]
    elif normalized.endswith("h"):
        return 60
    elif normalized in {"d", "1d", "day", "daily"}:
        return 1440
    elif normalized in {"w", "1w", "week", "weekly"}:
        return 10080

    try:
        minutes = int(normalized)
    except ValueError as exc:  # pragma: no cover - argparse exercises this
        raise argparse.ArgumentTypeError(f"Unsupported timeframe: {value}") from exc

    if minutes <= 0:
        raise argparse.ArgumentTypeError("timeframe must be a positive integer")
    return minutes


def _sanitize_symbol(symbol: str) -> str:
    return symbol.upper().replace(":", "_").replace("/", "-")


def _find_data_file(data_dir: Path, ticker: str, timeframe_minutes: int) -> Path:
    sanitized = _sanitize_symbol(ticker)
    direct_match = data_dir / str(timeframe_minutes) / f"{sanitized}-{timeframe_minutes}M.csv"
    if direct_match.exists():
        return direct_match

    matches = sorted(
        path
        for path in data_dir.rglob(f"{sanitized}-{timeframe_minutes}M.csv")
        if path.is_file()
    )
    if matches:
        return matches[0]

    available = sorted(path.name for path in data_dir.rglob(f"{sanitized}-*.csv") if path.is_file())
    if available:
        raise FileNotFoundError(
            f"No data found for timeframe {timeframe_minutes} minutes. "
            f"Available files for {ticker.upper()}: {', '.join(available)}"
        )

    raise FileNotFoundError(f"No archived CSV found for {ticker.upper()} under {data_dir}")


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_rows(csv_path: Path) -> list[dict[str, object]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        required = {"timestamp", "open", "high", "low", "close"}
        missing = required.difference(fieldnames)
        if missing:
            raise ValueError(f"{csv_path} is missing required columns: {', '.join(sorted(missing))}")

        rows: list[dict[str, object]] = []
        for row in reader:
            if not row.get("timestamp"):
                continue
            parsed_timestamp = _parse_timestamp(row["timestamp"])
            try:
                open_price = float(row["open"])
                high_price = float(row["high"])
                low_price = float(row["low"])
                close_price = float(row["close"])
            except (TypeError, ValueError):
                continue

            volume = None
            raw_volume = row.get("volume")
            if raw_volume not in {None, ""}:
                try:
                    volume = float(raw_volume)
                except ValueError:
                    volume = None

            rows.append(
                {
                    "timestamp": parsed_timestamp,
                    "time": parsed_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume,
                }
            )

    rows.sort(key=lambda row: row["timestamp"])
    return rows


def normalize_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row in rows:
        raw_timestamp = row.get("timestamp")
        if isinstance(raw_timestamp, datetime):
            parsed_timestamp = (
                raw_timestamp.astimezone(timezone.utc)
                if raw_timestamp.tzinfo is not None
                else raw_timestamp.replace(tzinfo=timezone.utc)
            )
        elif isinstance(raw_timestamp, str):
            parsed_timestamp = _parse_timestamp(raw_timestamp)
        else:
            raw_time = row.get("time")
            if isinstance(raw_time, str):
                parsed_timestamp = _parse_timestamp(raw_time)
            else:
                raise ValueError("Each row must include a 'timestamp' datetime/string or a 'time' string.")

        try:
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Each row must include numeric open/high/low/close values.") from exc

        volume = row.get("volume")
        if volume not in {None, ""}:
            try:
                volume = float(volume)
            except (TypeError, ValueError):
                volume = None

        normalized.append(
            {
                "timestamp": parsed_timestamp,
                "time": parsed_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            }
        )

    normalized.sort(key=lambda row: row["timestamp"])
    return normalized


def _tradingview_interval(timeframe_minutes: int) -> str:
    if timeframe_minutes == 1440:
        return "D"
    if timeframe_minutes == 10080:
        return "W"
    return str(timeframe_minutes)


def _tradingview_symbol(symbol: str) -> str:
    if ":" in symbol:
        return symbol.upper()
    return f"NASDAQ:{symbol.upper()}"


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    result: list[float] = []
    ema_value: float | None = None
    for value in values:
        ema_value = value if ema_value is None else (value * alpha) + (ema_value * (1 - alpha))
        result.append(ema_value)
    return result


def _macd(close_values: list[float]) -> tuple[list[float], list[float], list[float]]:
    ema_fast = _ema(close_values, 12)
    ema_slow = _ema(close_values, 26)
    macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, 9)
    histogram = [macd - signal for macd, signal in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def _fisher_transform(rows: list[dict[str, object]], length: int = 50) -> list[float | None]:
    medians = [(row["high"] + row["low"]) / 2 for row in rows]
    values: list[float | None] = []
    previous_value = 0.0
    previous_fisher = 0.0
    for index, median in enumerate(medians):
        start = max(0, index - length + 1)
        window = medians[start : index + 1]
        highest = max(window)
        lowest = min(window)
        if highest == lowest:
            normalized = 0.0
        else:
            normalized = 2 * ((median - lowest) / (highest - lowest) - 0.5)
        value = 0.33 * normalized + 0.67 * previous_value
        value = max(min(value, 0.999), -0.999)
        fisher = 0.5 * math.log((1 + value) / (1 - value)) + 0.5 * previous_fisher
        values.append(fisher if index >= length - 1 else None)
        previous_value = value
        previous_fisher = fisher
    return values


def _default_debug_markers(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    red_markers: list[dict[str, object]] = []
    green_markers: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        bar_range = max(row["high"] - row["low"], max(row["close"] * 0.01, 0.01))
        if (index + 1) % 10 == 0:
            red_markers.append(
                {
                    "time": row["time"],
                    "price": round(row["high"] + bar_range * 0.18, 6),
                }
            )
        if (index + 1) % 7 == 0:
            green_markers.append(
                {
                    "time": row["time"],
                    "price": round(max(row["low"] - bar_range * 0.18, 0.000001), 6),
                }
            )
    return {
        "red_markers": red_markers,
        "green_markers": green_markers,
    }


def _normalize_marker_points(points: list[dict[str, object]] | None) -> tuple[list[str], list[float]]:
    times: list[str] = []
    prices: list[float] = []
    for point in points or []:
        raw_time = point.get("time") or point.get("timestamp")
        if isinstance(raw_time, datetime):
            parsed_time = raw_time.astimezone(timezone.utc) if raw_time.tzinfo else raw_time.replace(tzinfo=timezone.utc)
            time_value = parsed_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(raw_time, str):
            time_value = _parse_timestamp(raw_time).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            raise ValueError("Marker points must include a datetime/string 'time' or 'timestamp'.")
        try:
            price_value = float(point["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Marker points must include a numeric 'price'.") from exc
        times.append(time_value)
        prices.append(price_value)
    return times, prices


def _strategy_display_name(slug: str) -> str:
    return slug.replace("_", " ").strip().title()


def _discover_strategy_modules() -> list[tuple[str, object]]:
    discovered: list[tuple[str, object]] = []
    if not STRATEGIES_DIR.exists():
        return discovered

    for path in sorted(STRATEGIES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"{__package__}.strategies.{path.stem}" if __package__ else f"strategies.{path.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        discovered.append((path.stem, module))
    return discovered


def _select_strategy_callable(module: object) -> object | None:
    for name in ("compute_strategy", "run_strategy"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate

    compute_candidates: list[tuple[str, object]] = []
    for name in dir(module):
        if not (name.startswith("compute_") and name.endswith("_strategy")):
            continue
        candidate = getattr(module, name, None)
        if callable(candidate):
            compute_candidates.append((name, candidate))
    if len(compute_candidates) == 1:
        return compute_candidates[0][1]
    return None


def _call_strategy(
    strategy_callable: object,
    rows: list[dict[str, object]],
    *,
    ticker: str,
    timeframe_minutes: int,
) -> object:
    signature = inspect.signature(strategy_callable)
    kwargs: dict[str, object] = {}
    if "rows" in signature.parameters:
        kwargs["rows"] = rows
    if "ticker" in signature.parameters:
        kwargs["ticker"] = ticker
    if "timeframe_minutes" in signature.parameters:
        kwargs["timeframe_minutes"] = timeframe_minutes
    if not kwargs and any(
        parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in signature.parameters.values()
    ):
        return strategy_callable(rows)
    return strategy_callable(**kwargs)


def _coerce_event_points(points: list[dict[str, object]] | None) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for point in points or []:
        raw_time = point.get("time") or point.get("timestamp")
        raw_price = point.get("price")
        if raw_time is None or raw_price is None:
            continue
        if isinstance(raw_time, datetime):
            timestamp_value = raw_time.astimezone(timezone.utc) if raw_time.tzinfo else raw_time.replace(tzinfo=timezone.utc)
            time_value = timestamp_value.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(raw_time, str):
            time_value = _parse_timestamp(raw_time).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            continue
        try:
            price_value = float(raw_price)
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "time": time_value,
                "price": round(price_value, 6),
                "label": str(point.get("reason") or point.get("label") or ""),
            }
        )
    return normalized


def _extract_strategy_payload(slug: str, module: object, result: object) -> dict[str, object] | None:
    payload: dict[str, object] | None = None
    build_payload = getattr(module, "build_chart_payload", None)
    if callable(build_payload):
        try:
            maybe_payload = build_payload(result)
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
        except Exception:
            payload = None

    if payload is None and isinstance(result, dict):
        payload = result

    if payload is None and hasattr(result, "events"):
        payload = {
            "events": getattr(result, "events", {}),
            "summary": getattr(result, "summary", {}),
        }

    if payload is None:
        return None

    events = payload.get("events")
    if not isinstance(events, dict):
        return None

    entries: list[dict[str, object]] = []
    exits: list[dict[str, object]] = []
    for event_name, event_points in events.items():
        if not isinstance(event_name, str):
            continue
        coerced = _coerce_event_points(event_points if isinstance(event_points, list) else None)
        if event_name.endswith("_entries") or event_name == "entries":
            entries.extend(coerced)
        elif event_name.endswith("_exits") or event_name == "exits":
            exits.extend(coerced)

    if not entries and not exits:
        return None

    summary = payload.get("summary")
    statistics = payload.get("statistics")
    return {
        "slug": slug,
        "name": _strategy_display_name(slug),
        "summary": summary if isinstance(summary, dict) else {},
        "statistics": statistics if isinstance(statistics, dict) else {},
        "entries": entries,
        "exits": exits,
    }


def _compute_strategy_overlays(
    rows: list[dict[str, object]],
    *,
    ticker: str,
    timeframe_minutes: int,
) -> list[dict[str, object]]:
    overlays: list[dict[str, object]] = []
    for slug, module in _discover_strategy_modules():
        strategy_callable = _select_strategy_callable(module)
        if strategy_callable is None:
            continue
        try:
            result = _call_strategy(strategy_callable, rows, ticker=ticker, timeframe_minutes=timeframe_minutes)
            payload = _extract_strategy_payload(slug, module, result)
        except Exception:
            continue
        if payload is not None:
            overlays.append(payload)
    return overlays


def make_chart_payload(
    *,
    ticker: str,
    timeframe_minutes: int,
    rows: list[dict[str, object]],
    source_label: str | None = None,
    overlays: dict[str, Any] | None = None,
) -> ChartPayload:
    normalized_rows = normalize_rows(rows)
    resolved_overlays = dict(overlays or {})
    defaults = _default_debug_markers(normalized_rows)
    resolved_overlays.setdefault("red_markers", defaults["red_markers"])
    resolved_overlays.setdefault("green_markers", defaults["green_markers"])
    return ChartPayload(
        ticker=ticker,
        timeframe_minutes=timeframe_minutes,
        rows=normalized_rows,
        source_label=source_label,
        overlays=resolved_overlays,
    )


def make_chart_payload_from_csv(csv_path: Path, *, ticker: str, timeframe_minutes: int) -> ChartPayload:
    return make_chart_payload(
        ticker=ticker,
        timeframe_minutes=timeframe_minutes,
        rows=_load_rows(csv_path),
        source_label=str(csv_path),
    )


def render_chart_html(payload: ChartPayload) -> str:
    rows = payload.rows
    latest = rows[-1]
    strategy_payloads = _compute_strategy_overlays(
        rows,
        ticker=payload.ticker,
        timeframe_minutes=payload.timeframe_minutes,
    )
    summary = {
        "Ticker": payload.ticker.upper(),
        "Timeframe": f"{payload.timeframe_minutes}m",
        "Rows": f"{len(rows):,}",
        "Start": str(rows[0]["timestamp"]),
        "End": str(latest["timestamp"]),
        "Last Close": f"{latest['close']:.2f}",
        "Strategies": str(len(strategy_payloads)),
    }
    times = [row["time"] for row in rows]
    open_values = [row["open"] for row in rows]
    high_values = [row["high"] for row in rows]
    low_values = [row["low"] for row in rows]
    close_values = [row["close"] for row in rows]
    fisher_values = _fisher_transform(rows, length=50)
    macd_line, signal_line, macd_histogram = _macd(close_values)
    red_marker_times, red_marker_prices = _normalize_marker_points(payload.overlays.get("red_markers"))
    green_marker_times, green_marker_prices = _normalize_marker_points(payload.overlays.get("green_markers"))

    initial_state = {
        "fisher": False,
        "macd": False,
        "redMarkers": False,
        "greenMarkers": False,
        "sessionGaps": True,
    }
    strategy_options_html = "".join(
        [
            '<option value="">None</option>',
            *[
                f'<option value="{strategy["slug"]}">{strategy["name"]}</option>'
                for strategy in strategy_payloads
            ],
        ]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{payload.ticker.upper()} {payload.timeframe_minutes}m</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0e1726;
      --panel: #152238;
      --text: #e5eefc;
      --muted: #9db0cc;
      --accent: #56b6c2;
      --grid: #22324d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Menlo, Monaco, Consolas, monospace;
      background:
        radial-gradient(circle at top left, rgba(86, 182, 194, 0.18), transparent 30%),
        linear-gradient(180deg, #122034 0%, var(--bg) 60%);
      color: var(--text);
    }}
    .page {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }}
    .title {{
      margin: 0;
      font-size: 28px;
    }}
    .subtitle {{
      color: var(--muted);
      margin-top: 8px;
    }}
    .panel {{
      background: rgba(21, 34, 56, 0.88);
      border: 1px solid rgba(157, 176, 204, 0.16);
      border-radius: 16px;
      padding: 16px;
      backdrop-filter: blur(10px);
      box-shadow: 0 16px 50px rgba(0, 0, 0, 0.25);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .control-button {{
      appearance: none;
      border: 1px solid rgba(157, 176, 204, 0.28);
      background: rgba(8, 14, 24, 0.45);
      color: var(--text);
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      font: inherit;
      transition: transform 140ms ease, background 140ms ease, border-color 140ms ease;
    }}
    .control-button:hover {{
      transform: translateY(-1px);
      border-color: rgba(86, 182, 194, 0.7);
    }}
    .control-button.active {{
      background: rgba(86, 182, 194, 0.18);
      border-color: rgba(86, 182, 194, 0.9);
      color: #eefcff;
    }}
    .control-select {{
      appearance: none;
      border: 1px solid rgba(157, 176, 204, 0.28);
      background: rgba(8, 14, 24, 0.72);
      color: var(--text);
      border-radius: 999px;
      padding: 10px 14px;
      font: inherit;
      min-width: 240px;
    }}
    .control-group {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(157, 176, 204, 0.18);
      background: rgba(8, 14, 24, 0.28);
      flex-wrap: wrap;
    }}
    .control-field {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .control-input {{
      width: 92px;
      border: 1px solid rgba(157, 176, 204, 0.28);
      background: rgba(8, 14, 24, 0.72);
      color: var(--text);
      border-radius: 999px;
      padding: 8px 10px;
      font: inherit;
    }}
    .stat {{
      background: rgba(8, 14, 24, 0.35);
      border-radius: 12px;
      padding: 12px;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .value {{
      font-size: 15px;
    }}
    .status-panel {{
      margin-top: 14px;
      padding: 12px;
      border-radius: 12px;
      background: rgba(8, 14, 24, 0.35);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-line;
    }}
    #chart {{
      width: 100%;
      height: calc(100vh - 220px);
      min-height: 720px;
    }}
    #fisher-chart,
    #macd-chart {{
      width: 100%;
      height: 240px;
      min-height: 240px;
      margin-top: 14px;
    }}
    .hidden {{
      display: none;
    }}
    #chart .draglayer .nsdrag,
    #chart .draglayer .ewdrag {{
      fill: rgba(86, 182, 194, 0.001);
      stroke: rgba(86, 182, 194, 0.55);
      stroke-width: 1.5px;
      transition: fill 120ms ease, stroke 120ms ease, opacity 120ms ease;
    }}
    #chart .draglayer .ewdrag {{
      cursor: ew-resize;
    }}
    #chart .draglayer .nsdrag:hover,
    #chart .draglayer .nsdrag.is-hovering,
    #chart .draglayer .nsdrag.is-dragging,
    #chart .draglayer .ewdrag:hover,
    #chart .draglayer .ewdrag.is-hovering,
    #chart .draglayer .ewdrag.is-dragging {{
      fill: rgba(86, 182, 194, 0.18);
      stroke: rgba(86, 182, 194, 0.95);
      stroke-width: 2px;
    }}
    #chart .draglayer .nsdrag.is-dragging,
    #chart .draglayer .ewdrag.is-dragging {{
      fill: rgba(86, 182, 194, 0.26);
    }}
    .note {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 12px;
      line-height: 1.5;
    }}
    .strategy-stats-panel {{
      margin-top: 14px;
    }}
    .strategy-stats-panel.hidden {{
      display: none;
    }}
    .strategy-stats-header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}
    .strategy-stats-title {{
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .strategy-stats-subtitle {{
      font-size: 12px;
      color: var(--muted);
    }}
    .strategy-stats-table {{
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      border-radius: 12px;
      background: rgba(8, 14, 24, 0.42);
    }}
    .strategy-stats-table th,
    .strategy-stats-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid rgba(157, 176, 204, 0.12);
      text-align: left;
      font-size: 13px;
    }}
    .strategy-stats-table th {{
      width: 42%;
      color: var(--muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .strategy-stats-table tr:last-child th,
    .strategy-stats-table tr:last-child td {{
      border-bottom: 0;
    }}
    code {{
      color: var(--accent);
    }}
    .links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .link-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(86, 182, 194, 0.4);
      border-radius: 999px;
      color: var(--text);
      text-decoration: none;
      padding: 10px 14px;
      background: rgba(86, 182, 194, 0.1);
    }}
    @media (max-width: 1080px) {{
      #chart {{
        height: calc(100vh - 260px);
        min-height: 520px;
      }}
      #fisher-chart,
      #macd-chart {{
        height: 220px;
        min-height: 220px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="header">
      <div>
        <h1 class="title">{payload.ticker.upper()} local archive</h1>
        <div class="subtitle">Source: <code>{payload.source_label or "custom payload"}</code></div>
      </div>
      <div class="subtitle">Local interactive chart with deterministic debug overlays.</div>
    </div>
    <div class="panel">
      <div class="stats">
        {"".join(f'<div class="stat"><div class="label">{key}</div><div class="value">{value}</div></div>' for key, value in summary.items())}
      </div>
      <div class="note">This viewer now renders the archived CSV directly so the debug controls can reliably change the chart in-place.</div>
      <div class="controls">
        <select id="strategy-select" class="control-select" aria-label="Strategy overlay">
          {strategy_options_html}
        </select>
        <button class="control-button" data-feature="fisher">Fisher 50</button>
        <button class="control-button" data-feature="macd">MACD</button>
        <button class="control-button" data-feature="sessionGaps">Session Gaps</button>
        <button class="control-button" data-feature="redMarkers">Red triangles / 10 bars</button>
        <button class="control-button" data-feature="greenMarkers">Green triangles / 7 bars</button>
        <div class="control-group" aria-label="Gap calibration settings">
          <label class="control-field" for="gap-min-pct">
            Gap % >=
            <input id="gap-min-pct" class="control-input" type="number" min="0" step="0.1" value="0.5" />
          </label>
          <label class="control-field" for="gap-min-abs">
            Gap $ >=
            <input id="gap-min-abs" class="control-input" type="number" min="0" step="0.01" value="0" />
          </label>
        </div>
        <button class="control-button" data-action="scale-x-in">X Scale In</button>
        <button class="control-button" data-action="scale-x-out">X Scale Out</button>
        <button class="control-button" data-action="scale-x-reset">X Scale Reset</button>
        <button class="control-button" data-action="scale-y-in">Y Scale In</button>
        <button class="control-button" data-action="scale-y-out">Y Scale Out</button>
        <button class="control-button" data-action="scale-y-reset">Y Scale Reset</button>
      </div>
      <div id="feature-status" class="status-panel"></div>
      <div class="links">
        <a class="link-button" href="https://www.tradingview.com/chart/?symbol={_tradingview_symbol(payload.ticker).replace(':', '%3A')}" target="_blank" rel="noopener noreferrer">Open Symbol In TradingView</a>
      </div>
    </div>
    <section class="panel">
      <div id="chart" data-plot-pane="true"></div>
      <div id="fisher-chart" class="hidden" data-plot-pane="true"></div>
      <div id="macd-chart" class="hidden" data-plot-pane="true"></div>
      <div id="strategy-stats-panel" class="strategy-stats-panel hidden">
        <div class="strategy-stats-header">
          <div class="strategy-stats-title">Strategy Statistics</div>
          <div id="strategy-stats-subtitle" class="strategy-stats-subtitle"></div>
        </div>
        <table class="strategy-stats-table">
          <tbody id="strategy-stats-body"></tbody>
        </table>
      </div>
      <div class="note">The chart uses local OHLCV data from the archive. Mouse wheel zoom, drag pan, box zoom, reset controls, keyboard x/y-scaling, and visible x/y-axis drag handles are enabled.</div>
    </section>
  </div>
  <script>
    const state = {json.dumps(initial_state)};
    const times = {json.dumps(times)};
    const openValues = {json.dumps(open_values)};
    const highValues = {json.dumps(high_values)};
    const lowValues = {json.dumps(low_values)};
    const closeValues = {json.dumps(close_values)};
    const fisherValues = {json.dumps(fisher_values)};
    const macdLine = {json.dumps(macd_line)};
    const signalLine = {json.dumps(signal_line)};
    const macdHistogram = {json.dumps(macd_histogram)};
    const redMarkerTimes = {json.dumps(red_marker_times)};
    const redMarkerPrices = {json.dumps(red_marker_prices)};
    const greenMarkerTimes = {json.dumps(green_marker_times)};
    const greenMarkerPrices = {json.dumps(green_marker_prices)};
    const strategyPayloads = {json.dumps(strategy_payloads)};
    const strategyPayloadBySlug = Object.fromEntries(strategyPayloads.map((strategy) => [strategy.slug, strategy]));
    const timeframeMinutes = {json.dumps(payload.timeframe_minutes)};
    const defaultPriceRange = [Math.min(...lowValues), Math.max(...highValues)];
    const fullTimeRange = [times[0], times[times.length - 1]];
    const sixMonthWindowMs = 183 * 24 * 60 * 60 * 1000;
    let axisDragCleanup = null;
    let wheelPanCleanup = null;
    let xSyncCleanup = null;
    let syncingTimeRange = false;
    let activePaneId = "chart";

    function getSelectedStrategy() {{
      const select = document.getElementById("strategy-select");
      if (!select || !select.value) return null;
      return strategyPayloadBySlug[select.value] || null;
    }}

    function strategySummaryLines(strategy) {{
      if (!strategy || !strategy.summary || typeof strategy.summary !== "object") return [];
      return Object.entries(strategy.summary).map(([key, value]) => `${{key}}: ${{value}}`);
    }}

    function formatStatisticLabel(key) {{
      return key
        .replace(/_/g, " ")
        .replace(/\\b\\w/g, (char) => char.toUpperCase());
    }}

    function formatStatisticValue(key, value) {{
      if (value === null || value === undefined || value === "") return "N/A";
      if (typeof value === "boolean") return value ? "Yes" : "No";
      if (typeof value === "number") {{
        if (key.endsWith("_pct")) return `${{value.toFixed(2)}}%`;
        if (key.includes("profit_factor")) return value.toFixed(2);
        if (key.includes("bars")) return value.toFixed(2);
        return value.toFixed(4).replace(/\\.0+$/, "").replace(/(\\.\\d*?)0+$/, "$1");
      }}
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }}

    function statisticRows(strategy) {{
      if (!strategy || !strategy.statistics || typeof strategy.statistics !== "object") return [];
      return Object.entries(strategy.statistics)
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([key, value]) => {{
          if (value && typeof value === "object" && !Array.isArray(value)) {{
            return [formatStatisticLabel(key), Object.entries(value).map(([nestedKey, nestedValue]) => `${{formatStatisticLabel(nestedKey)}}: ${{formatStatisticValue(nestedKey, nestedValue)}}`).join(" | ")];
          }}
          return [formatStatisticLabel(key), formatStatisticValue(key, value)];
        }});
    }}

    function renderStrategyStatsTable() {{
      const panel = document.getElementById("strategy-stats-panel");
      const body = document.getElementById("strategy-stats-body");
      const subtitle = document.getElementById("strategy-stats-subtitle");
      const strategy = getSelectedStrategy();
      if (!panel || !body || !subtitle) return;

      const rows = statisticRows(strategy);
      if (!strategy || rows.length === 0) {{
        panel.classList.add("hidden");
        body.innerHTML = "";
        subtitle.textContent = "";
        return;
      }}

      subtitle.textContent = strategy.name;
      body.innerHTML = rows.map(([label, value]) => `<tr><th scope="row">${{label}}</th><td>${{value}}</td></tr>`).join("");
      panel.classList.remove("hidden");
    }}

    function setButtonState(feature) {{
      const button = document.querySelector(`[data-feature="${{feature}}"]`);
      if (!button) return;
      button.classList.toggle("active", Boolean(state[feature]));
    }}

    function setAllButtonStates() {{
      Object.keys(state).forEach(setButtonState);
    }}

    function buildDomains() {{
      const panes = [];
      if (state.fisher) panes.push("fisher");
      if (state.macd) panes.push("macd");
      if (panes.length === 0) {{
        return {{
          yaxis: [0, 1],
          yaxis2: null,
          yaxis3: null
        }};
      }}
      if (panes.length === 1) {{
        return {{
          yaxis: [0.30, 1],
          yaxis2: panes[0] === "fisher" ? [0, 0.20] : null,
          yaxis3: panes[0] === "macd" ? [0, 0.20] : null
        }};
      }}
      return {{
        yaxis: [0.48, 1],
        yaxis2: [0.24, 0.42],
        yaxis3: [0, 0.18]
      }};
    }}

    function updateStatus() {{
      const selectedStrategy = getSelectedStrategy();
      const sessionGaps = computeSessionGaps();
      const gapSettings = getGapSettings();
      const lines = [
        `Fisher pane: ${{state.fisher ? "on" : "off"}}`,
        `MACD pane: ${{state.macd ? "on" : "off"}}`,
        `Session gap overlay: ${{state.sessionGaps ? "on" : "off"}} (${{sessionGaps.length}} gaps, min % ${{gapSettings.minPercent.toFixed(2)}}, min $ ${{gapSettings.minAbsolute.toFixed(2)}})`,
        `Red triangle overlay: ${{state.redMarkers ? "on" : "off"}} (${{redMarkerTimes.length}} markers)`,
        `Green triangle overlay: ${{state.greenMarkers ? "on" : "off"}} (${{greenMarkerTimes.length}} markers)`,
        `Strategy overlay: ${{selectedStrategy ? selectedStrategy.name : "none"}}`
      ];
      if (sessionGaps.length) {{
        const largestGap = sessionGaps.reduce((best, gap) => (gap.absolutePoints > best.absolutePoints ? gap : best), sessionGaps[0]);
        lines.push(`Largest gap: ${{largestGap.direction}} ${{largestGap.absolutePoints.toFixed(2)}} pts (${{largestGap.percent.toFixed(2)}}%) on ${{largestGap.currentTime.slice(0, 10)}}`);
      }}
      if (selectedStrategy) {{
        lines.push(`Strategy entries: ${{selectedStrategy.entries.length}}`);
        lines.push(`Strategy exits: ${{selectedStrategy.exits.length}}`);
        lines.push(...strategySummaryLines(selectedStrategy));
      }}
      if (!window.Plotly) {{
        lines.push("Plotly failed to load, so charts cannot render.");
      }}
      document.getElementById("feature-status").textContent = lines.join("\\n");
    }}

    function baseLayout(height) {{
      return {{
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "#152238",
        dragmode: "pan",
        margin: {{ l: 52, r: 28, t: 12, b: 36 }},
        font: {{ color: "#d7e3f8", family: "Menlo, Monaco, Consolas, monospace" }},
        showlegend: true,
        legend: {{ orientation: "h", x: 0, y: 1.08 }},
        height,
        xaxis: {{
          rangeslider: {{ visible: false }},
          showgrid: true,
          gridcolor: "#22324d",
          zeroline: false,
          type: "date",
          rangebreaks: [{{ bounds: ["sat", "mon"] }}]
        }},
        yaxis: {{
          side: "right",
          showgrid: true,
          gridcolor: "#22324d",
          zeroline: true,
          zerolinecolor: "#314562",
          fixedrange: false
        }}
      }};
    }}

    function getGapSettings() {{
      const percentInput = document.getElementById("gap-min-pct");
      const absoluteInput = document.getElementById("gap-min-abs");
      const minPercent = Math.max(0, Number.parseFloat(percentInput?.value ?? "0") || 0);
      const minAbsolute = Math.max(0, Number.parseFloat(absoluteInput?.value ?? "0") || 0);
      return {{ minPercent, minAbsolute }};
    }}

    function isSessionBoundary(index) {{
      if (index <= 0) return false;
      if (timeframeMinutes >= 1440) return true;

      const previousTime = new Date(times[index - 1]);
      const currentTime = new Date(times[index]);
      const previousMs = previousTime.getTime();
      const currentMs = currentTime.getTime();
      if (!Number.isFinite(previousMs) || !Number.isFinite(currentMs)) return false;

      const expectedBarMs = Math.max(timeframeMinutes, 1) * 60 * 1000;
      const dateChanged = previousTime.toISOString().slice(0, 10) !== currentTime.toISOString().slice(0, 10);
      const hasLargeTimeJump = currentMs - previousMs > expectedBarMs * 1.5;
      return dateChanged || hasLargeTimeJump;
    }}

    function computeSessionGaps() {{
      const {{ minPercent, minAbsolute }} = getGapSettings();
      const gaps = [];

      for (let index = 1; index < times.length; index += 1) {{
        if (!isSessionBoundary(index)) continue;

        const previousClose = Number(closeValues[index - 1]);
        const currentOpen = Number(openValues[index]);
        if (!Number.isFinite(previousClose) || !Number.isFinite(currentOpen)) continue;

        const gapPoints = currentOpen - previousClose;
        const absolutePoints = Math.abs(gapPoints);
        if (absolutePoints <= 0) continue;

        const percent = absolutePoints / Math.max(Math.abs(previousClose), 0.000001) * 100;
        if (minAbsolute > 0 && absolutePoints < minAbsolute) continue;
        if (minPercent > 0 && percent < minPercent) continue;

        const previousTime = times[index - 1];
        const currentTime = times[index];
        const previousMs = new Date(previousTime).getTime();
        const currentMs = new Date(currentTime).getTime();
        const midpointTime = Number.isFinite(previousMs) && Number.isFinite(currentMs)
          ? new Date((previousMs + currentMs) / 2).toISOString()
          : currentTime;

        gaps.push({{
          previousTime,
          currentTime,
          midpointTime,
          lower: Math.min(previousClose, currentOpen),
          upper: Math.max(previousClose, currentOpen),
          midpointPrice: (previousClose + currentOpen) / 2,
          direction: gapPoints > 0 ? "up" : "down",
          points: gapPoints,
          absolutePoints,
          percent,
        }});
      }}

      return gaps;
    }}

    function buildGapShapes(sessionGaps) {{
      return sessionGaps.map((gap) => {{
        const stroke = gap.direction === "up" ? "rgba(38, 166, 154, 0.95)" : "rgba(239, 83, 80, 0.95)";
        const fill = gap.direction === "up" ? "rgba(38, 166, 154, 0.22)" : "rgba(239, 83, 80, 0.22)";
        return {{
          type: "rect",
          xref: "x",
          yref: "y",
          x0: gap.previousTime,
          x1: gap.currentTime,
          y0: gap.lower,
          y1: gap.upper,
          line: {{ color: stroke, width: 1.5 }},
          fillcolor: fill,
          layer: "above"
        }};
      }});
    }}

    function getPlotPanes() {{
      return Array.from(document.querySelectorAll('[data-plot-pane="true"]'));
    }}

    function getVisiblePaneIds() {{
      return getPlotPanes()
        .filter((pane) => !pane.classList.contains("hidden"))
        .map((pane) => pane.id)
        .filter(Boolean);
    }}

    function getPrimaryPaneId() {{
      const visiblePaneIds = getVisiblePaneIds();
      if (visiblePaneIds.includes(activePaneId)) return activePaneId;
      return visiblePaneIds[0] || "chart";
    }}

    function setActivePane(paneId) {{
      activePaneId = paneId;
    }}

    function plotConfig() {{
      return {{
        responsive: true,
        displaylogo: false,
        scrollZoom: false,
        doubleClick: "reset",
        modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toImage"],
        modeBarButtonsToAdd: ["zoomIn2d", "zoomOut2d", "resetScale2d"]
      }};
    }}

    function defaultVisibleTimeRange() {{
      const startMs = new Date(fullTimeRange[0]).getTime();
      const endMs = new Date(fullTimeRange[1]).getTime();
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {{
        return [...fullTimeRange];
      }}
      const windowMs = Math.min(sixMonthWindowMs, endMs - startMs);
      return [
        new Date(endMs - windowMs).toISOString(),
        new Date(endMs).toISOString()
      ];
    }}

    function clampTimeRange(startMs, endMs) {{
      const minMs = new Date(fullTimeRange[0]).getTime();
      const maxMs = new Date(fullTimeRange[1]).getTime();
      if (!Number.isFinite(minMs) || !Number.isFinite(maxMs) || maxMs <= minMs) {{
        return [startMs, endMs];
      }}
      const span = endMs - startMs;
      if (span >= maxMs - minMs) {{
        return [minMs, maxMs];
      }}
      if (startMs < minMs) {{
        return [minMs, minMs + span];
      }}
      if (endMs > maxMs) {{
        return [maxMs - span, maxMs];
      }}
      return [startMs, endMs];
    }}

    function getCurrentPriceRange(chartId = getPrimaryPaneId()) {{
      const chart = document.getElementById(chartId);
      const layout = chart && chart._fullLayout;
      const current = layout && layout.yaxis && layout.yaxis.range;
      if (Array.isArray(current) && current.length === 2) {{
        return [Number(current[0]), Number(current[1])];
      }}
      return [...defaultPriceRange];
    }}

    function scalePriceAxis(factor, chartId = getPrimaryPaneId()) {{
      if (!window.Plotly) return;
      const [minValue, maxValue] = getCurrentPriceRange(chartId);
      const midpoint = (minValue + maxValue) / 2;
      const halfRange = ((maxValue - minValue) / 2) * factor;
      Plotly.relayout(chartId, {{
        "yaxis.range": [midpoint - halfRange, midpoint + halfRange]
      }});
    }}

    function resetPriceAxis(chartId = getPrimaryPaneId()) {{
      if (!window.Plotly) return;
      Plotly.relayout(chartId, {{
        "yaxis.autorange": true
      }});
    }}

    function getCurrentTimeRange() {{
      const chart = document.getElementById(getPrimaryPaneId());
      const layout = chart && chart._fullLayout;
      const current = layout && layout.xaxis && layout.xaxis.range;
      if (Array.isArray(current) && current.length === 2) {{
        return [String(current[0]), String(current[1])];
      }}
      return defaultVisibleTimeRange();
    }}

    function applyTimeRange(startIso, endIso) {{
      if (!window.Plotly) return;
      const paneIds = getVisiblePaneIds();
      if (!paneIds.length) return;
      syncingTimeRange = true;
      const update = {{
        "xaxis.range": [startIso, endIso]
      }};
      Promise.allSettled(paneIds.map((paneId) => Plotly.relayout(paneId, update))).finally(() => {{
        syncingTimeRange = false;
      }});
    }}

    function scaleTimeAxis(factor) {{
      if (!window.Plotly) return;
      const [startValue, endValue] = getCurrentTimeRange();
      const startMs = new Date(startValue).getTime();
      const endMs = new Date(endValue).getTime();
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return;
      const midpoint = (startMs + endMs) / 2;
      const halfRange = ((endMs - startMs) / 2) * factor;
      const [clampedStart, clampedEnd] = clampTimeRange(midpoint - halfRange, midpoint + halfRange);
      applyTimeRange(
        new Date(clampedStart).toISOString(),
        new Date(clampedEnd).toISOString(),
      );
    }}

    function resetTimeAxis() {{
      if (!window.Plotly) return;
      const [defaultStart, defaultEnd] = defaultVisibleTimeRange();
      applyTimeRange(defaultStart, defaultEnd);
    }}

    function bindAxisDragHandles() {{
      if (axisDragCleanup) {{
        axisDragCleanup();
        axisDragCleanup = null;
      }}
      const listeners = [];

      for (const chart of getPlotPanes()) {{
        const chartId = chart.id;
        if (!chartId || chart.classList.contains("hidden")) continue;

        const onPaneEnter = () => setActivePane(chartId);
        chart.addEventListener("mouseenter", onPaneEnter);
        listeners.push(() => chart.removeEventListener("mouseenter", onPaneEnter));

        const handles = Array.from(chart.querySelectorAll(".draglayer .nsdrag"));
        for (const handle of handles) {{
          const onMouseEnter = () => {{
            setActivePane(chartId);
            handle.classList.add("is-hovering");
          }};
          const onMouseLeave = () => handle.classList.remove("is-hovering");
          handle.addEventListener("mouseenter", onMouseEnter);
          handle.addEventListener("mouseleave", onMouseLeave);
          listeners.push(() => handle.removeEventListener("mouseenter", onMouseEnter));
          listeners.push(() => handle.removeEventListener("mouseleave", onMouseLeave));

          const onMouseDown = (event) => {{
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            setActivePane(chartId);
            handle.classList.add("is-dragging");

            const startY = event.clientY;
            const [startMin, startMax] = getCurrentPriceRange(chartId);
            const startMid = (startMin + startMax) / 2;
            const startHalfRange = (startMax - startMin) / 2;

            const onMouseMove = (moveEvent) => {{
              const dy = moveEvent.clientY - startY;
              const factor = Math.max(0.15, 1 + dy * 0.006);
              Plotly.relayout(chartId, {{
                "yaxis.range": [startMid - startHalfRange * factor, startMid + startHalfRange * factor]
              }});
            }};

            const onMouseUp = () => {{
              handle.classList.remove("is-dragging");
              window.removeEventListener("mousemove", onMouseMove);
              window.removeEventListener("mouseup", onMouseUp);
            }};

            window.addEventListener("mousemove", onMouseMove);
            window.addEventListener("mouseup", onMouseUp);
          }};

          handle.addEventListener("mousedown", onMouseDown);
          listeners.push(() => handle.removeEventListener("mousedown", onMouseDown));
        }}

        const xHandles = Array.from(chart.querySelectorAll(".draglayer .ewdrag"));
        for (const handle of xHandles) {{
          const onMouseEnter = () => {{
            setActivePane(chartId);
            handle.classList.add("is-hovering");
          }};
          const onMouseLeave = () => handle.classList.remove("is-hovering");
          handle.addEventListener("mouseenter", onMouseEnter);
          handle.addEventListener("mouseleave", onMouseLeave);
          listeners.push(() => handle.removeEventListener("mouseenter", onMouseEnter));
          listeners.push(() => handle.removeEventListener("mouseleave", onMouseLeave));

          const onMouseDown = (event) => {{
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            setActivePane(chartId);
            handle.classList.add("is-dragging");

            const startX = event.clientX;
            const [startFrom, startTo] = getCurrentTimeRange();
            const startFromMs = new Date(startFrom).getTime();
            const startToMs = new Date(startTo).getTime();
            const startMid = (startFromMs + startToMs) / 2;
            const startHalfRange = (startToMs - startFromMs) / 2;

            const onMouseMove = (moveEvent) => {{
              const dx = moveEvent.clientX - startX;
              const factor = Math.max(0.08, 1 + dx * 0.006);
              const [clampedStart, clampedEnd] = clampTimeRange(
                startMid - startHalfRange * factor,
                startMid + startHalfRange * factor,
              );
              applyTimeRange(
                new Date(clampedStart).toISOString(),
                new Date(clampedEnd).toISOString(),
              );
            }};

            const onMouseUp = () => {{
              handle.classList.remove("is-dragging");
              window.removeEventListener("mousemove", onMouseMove);
              window.removeEventListener("mouseup", onMouseUp);
            }};

            window.addEventListener("mousemove", onMouseMove);
            window.addEventListener("mouseup", onMouseUp);
          }};

          handle.addEventListener("mousedown", onMouseDown);
          listeners.push(() => handle.removeEventListener("mousedown", onMouseDown));
        }}
      }}

      axisDragCleanup = () => {{
        for (const cleanup of listeners) cleanup();
      }};
    }}

    function bindWheelPan() {{
      if (wheelPanCleanup) {{
        wheelPanCleanup();
        wheelPanCleanup = null;
      }}
      const cleanups = [];
      for (const chart of getPlotPanes()) {{
        const chartId = chart.id;
        if (!chartId || chart.classList.contains("hidden")) continue;

        const onWheel = (event) => {{
          if (!window.Plotly) return;
          const target = event.target;
          if (!(target instanceof Element) || !target.closest(".plotly, [data-plot-pane='true']")) return;
          setActivePane(chartId);
          const [startValue, endValue] = getCurrentTimeRange();
          const startMs = new Date(startValue).getTime();
          const endMs = new Date(endValue).getTime();
          if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return;

          const dominantDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
          if (!dominantDelta) return;

          event.preventDefault();
          const span = endMs - startMs;
          const width = Math.max(chart.clientWidth, 300);
          const shiftMs = dominantDelta * (span / width);
          const [clampedStart, clampedEnd] = clampTimeRange(startMs + shiftMs, endMs + shiftMs);

          applyTimeRange(
            new Date(clampedStart).toISOString(),
            new Date(clampedEnd).toISOString(),
          );
        }};

        chart.addEventListener("wheel", onWheel, {{ passive: false }});
        cleanups.push(() => chart.removeEventListener("wheel", onWheel));
      }}

      wheelPanCleanup = () => {{
        for (const cleanup of cleanups) cleanup();
      }};
    }}

    function bindTimeRangeSync() {{
      if (xSyncCleanup) {{
        xSyncCleanup();
        xSyncCleanup = null;
      }}

      const cleanups = [];
      for (const chart of getPlotPanes()) {{
        const chartId = chart.id;
        if (!chartId || chart.classList.contains("hidden")) continue;

        const syncHandler = (eventData) => {{
          if (syncingTimeRange || !eventData) return;
          const start = eventData["xaxis.range[0]"];
          const end = eventData["xaxis.range[1]"];
          if (!start || !end) return;
          setActivePane(chartId);
          applyTimeRange(String(start), String(end));
        }};

        chart.on?.("plotly_relayout", syncHandler);
        cleanups.push(() => chart.removeListener?.("plotly_relayout", syncHandler));
      }}

      xSyncCleanup = () => {{
        for (const cleanup of cleanups) cleanup();
      }};
    }}

    function bindKeyboardShortcuts() {{
      window.addEventListener("keydown", (event) => {{
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const tag = document.activeElement && document.activeElement.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || document.activeElement?.isContentEditable) return;

        if (event.key === "=" || event.key === "+") {{
          event.preventDefault();
          scalePriceAxis(0.85);
        }} else if (event.key === "-" || event.key === "_") {{
          event.preventDefault();
          scalePriceAxis(1.15);
        }} else if (event.key === "]") {{
          event.preventDefault();
          scaleTimeAxis(0.85);
        }} else if (event.key === "[") {{
          event.preventDefault();
          scaleTimeAxis(1.15);
        }} else if (event.key === "0") {{
          event.preventDefault();
          resetTimeAxis();
          resetPriceAxis();
        }}
      }});
    }}

    function renderPriceChart() {{
      const selectedStrategy = getSelectedStrategy();
      const sessionGaps = computeSessionGaps();
      const traces = [
        {{
          type: "candlestick",
          x: times,
          open: openValues,
          high: highValues,
          low: lowValues,
          close: closeValues,
          name: "{payload.ticker.upper()}",
          increasing: {{ line: {{ color: "#26a69a" }}, fillcolor: "#26a69a" }},
          decreasing: {{ line: {{ color: "#ef5350" }}, fillcolor: "#ef5350" }},
          whiskerwidth: 0.4
        }},
        {{
          type: "scatter",
          mode: "markers",
          x: redMarkerTimes,
          y: redMarkerPrices,
          name: "Red Triangles",
          marker: {{ color: "#ef5350", size: 11, symbol: "triangle-down" }},
          visible: state.redMarkers
        }},
        {{
          type: "scatter",
          mode: "markers",
          x: greenMarkerTimes,
          y: greenMarkerPrices,
          name: "Green Triangles",
          marker: {{ color: "#26a69a", size: 11, symbol: "triangle-up" }},
          visible: state.greenMarkers
        }}
      ];
      if (selectedStrategy) {{
        if (selectedStrategy.entries.length) {{
          traces.push({{
            type: "scatter",
            mode: "markers",
            x: selectedStrategy.entries.map((point) => point.time),
            y: selectedStrategy.entries.map((point) => point.price),
            text: selectedStrategy.entries.map((point) => point.label || selectedStrategy.name),
            hovertemplate: "%{{x}}<br>Entry: %{{y:.2f}}<br>%{{text}}<extra></extra>",
            name: `${{selectedStrategy.name}} Entries`,
            marker: {{ color: "#00e676", size: 12, symbol: "triangle-up" }}
          }});
        }}
        if (selectedStrategy.exits.length) {{
          traces.push({{
            type: "scatter",
            mode: "markers",
            x: selectedStrategy.exits.map((point) => point.time),
            y: selectedStrategy.exits.map((point) => point.price),
            text: selectedStrategy.exits.map((point) => point.label || selectedStrategy.name),
            hovertemplate: "%{{x}}<br>Exit: %{{y:.2f}}<br>%{{text}}<extra></extra>",
            name: `${{selectedStrategy.name}} Exits`,
            marker: {{ color: "#ff5252", size: 12, symbol: "triangle-down" }}
          }});
        }}
      }}
      const layout = baseLayout(null);
      layout.xaxis.range = getCurrentTimeRange();
      layout.yaxis.zeroline = false;
      layout.shapes = state.sessionGaps ? buildGapShapes(sessionGaps) : [];
      Plotly.react("chart", traces, layout, plotConfig()).then(() => {{
        bindAxisDragHandles();
        bindWheelPan();
        bindTimeRangeSync();
      }});
    }}

    function renderFisherChart() {{
      const container = document.getElementById("fisher-chart");
      container.classList.toggle("hidden", !state.fisher);
      if (!state.fisher) return;
      const layout = baseLayout(240);
      layout.xaxis.range = getCurrentTimeRange();
      Plotly.react(
        "fisher-chart",
        [{{
          type: "scatter",
          mode: "lines",
          x: times,
          y: fisherValues,
          name: "Fisher 50",
          line: {{ color: "#56b6c2", width: 2 }}
        }}],
        layout,
        plotConfig()
      ).then(() => {{
        bindAxisDragHandles();
        bindWheelPan();
        bindTimeRangeSync();
      }});
    }}

    function renderMacdChart() {{
      const container = document.getElementById("macd-chart");
      container.classList.toggle("hidden", !state.macd);
      if (!state.macd) return;
      const layout = baseLayout(240);
      layout.xaxis.range = getCurrentTimeRange();
      Plotly.react(
        "macd-chart",
        [
          {{
            type: "bar",
            x: times,
            y: macdHistogram,
            name: "MACD Histogram",
            marker: {{
              color: macdHistogram.map((value) => value >= 0 ? "rgba(38,166,154,0.75)" : "rgba(239,83,80,0.75)")
            }}
          }},
          {{
            type: "scatter",
            mode: "lines",
            x: times,
            y: macdLine,
            name: "MACD",
            line: {{ color: "#56b6c2", width: 2 }}
          }},
          {{
            type: "scatter",
            mode: "lines",
            x: times,
            y: signalLine,
            name: "Signal",
            line: {{ color: "#f6c85f", width: 2 }}
          }}
        ],
        layout,
        plotConfig()
      ).then(() => {{
        bindAxisDragHandles();
        bindWheelPan();
        bindTimeRangeSync();
      }});
    }}

    function renderChart() {{
      if (!window.Plotly) {{
        updateStatus();
        renderStrategyStatsTable();
        return;
      }}
      renderPriceChart();
      renderFisherChart();
      renderMacdChart();
      renderStrategyStatsTable();
    }}

    function bindControls() {{
      const strategySelect = document.getElementById("strategy-select");
      if (strategySelect) {{
        strategySelect.addEventListener("change", () => {{
          updateStatus();
          renderChart();
        }});
      }}
      ["gap-min-pct", "gap-min-abs"].forEach((inputId) => {{
        const input = document.getElementById(inputId);
        if (!input) return;
        input.addEventListener("input", () => {{
          if (Number.parseFloat(input.value) < 0) {{
            input.value = "0";
          }}
          updateStatus();
          renderChart();
        }});
      }});
      document.querySelectorAll(".control-button").forEach((button) => {{
        button.addEventListener("click", () => {{
          const action = button.dataset.action;
          if (action === "scale-x-in") {{
            scaleTimeAxis(0.85);
            return;
          }}
          if (action === "scale-x-out") {{
            scaleTimeAxis(1.15);
            return;
          }}
          if (action === "scale-x-reset") {{
            resetTimeAxis();
            return;
          }}
          if (action === "scale-y-in") {{
            scalePriceAxis(0.85);
            return;
          }}
          if (action === "scale-y-out") {{
            scalePriceAxis(1.15);
            return;
          }}
          if (action === "scale-y-reset") {{
            resetPriceAxis();
            return;
          }}
          const feature = button.dataset.feature;
          state[feature] = !state[feature];
          setButtonState(feature);
          updateStatus();
          renderChart();
        }});
      }});
      setAllButtonStates();
      updateStatus();
    }}

    bindControls();
    bindKeyboardShortcuts();
    renderChart();
  </script>
</body>
</html>
"""


def _build_html(rows: list[dict[str, object]], *, ticker: str, timeframe_minutes: int, csv_path: Path) -> str:
    payload = make_chart_payload(
        ticker=ticker,
        timeframe_minutes=timeframe_minutes,
        rows=rows,
        source_label=str(csv_path),
    )
    return render_chart_html(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visualize a local archived time series in the browser")
    parser.add_argument("ticker", help="Ticker symbol, for example AAPL or NASDAQ:AAPL")
    parser.add_argument("timeframe", type=_parse_timeframe, help="Timeframe in minutes, or D/1D/W")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Root data directory to search (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional HTML output path. Defaults to a temporary file.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Generate the HTML but do not open the browser automatically.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    csv_path = _find_data_file(args.data_dir, args.ticker, args.timeframe)
    rows = _load_rows(csv_path)
    if not rows:
        raise ValueError(f"{csv_path} does not contain any valid OHLC rows")
    html = _build_html(rows, ticker=args.ticker, timeframe_minutes=args.timeframe, csv_path=csv_path)

    if args.output:
        output_path = args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir = Path(tempfile.gettempdir())
        output_path = temp_dir / f"{_sanitize_symbol(args.ticker)}-{args.timeframe}M-view.html"

    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote viewer to {output_path}")

    if not args.no_open:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":  # pragma: no cover
    main()
