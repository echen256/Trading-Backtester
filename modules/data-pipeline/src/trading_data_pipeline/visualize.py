"""Quick local visualization for archived OHLCV CSV files."""
from __future__ import annotations

import argparse
import csv
import json
import math
import tempfile
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"


def _parse_timeframe(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.endswith("m"):
        normalized = normalized[:-1]
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


def _build_html(rows: list[dict[str, object]], *, ticker: str, timeframe_minutes: int, csv_path: Path) -> str:
    latest = rows[-1]
    summary = {
        "Ticker": ticker.upper(),
        "Timeframe": f"{timeframe_minutes}m",
        "Rows": f"{len(rows):,}",
        "Start": str(rows[0]["timestamp"]),
        "End": str(latest["timestamp"]),
        "Last Close": f"{latest['close']:.2f}",
    }
    times = [row["time"] for row in rows]
    open_values = [row["open"] for row in rows]
    high_values = [row["high"] for row in rows]
    low_values = [row["low"] for row in rows]
    close_values = [row["close"] for row in rows]
    fisher_values = _fisher_transform(rows, length=50)
    macd_line, signal_line, macd_histogram = _macd(close_values)
    red_marker_times = []
    red_marker_prices = []
    green_marker_times = []
    green_marker_prices = []
    for index, row in enumerate(rows):
        bar_range = max(row["high"] - row["low"], max(row["close"] * 0.01, 0.01))
        if (index + 1) % 10 == 0:
            red_marker_times.append(row["time"])
            red_marker_prices.append(round(row["high"] + bar_range * 0.18, 6))
        if (index + 1) % 7 == 0:
            green_marker_times.append(row["time"])
            green_marker_prices.append(round(max(row["low"] - bar_range * 0.18, 0.000001), 6))

    initial_state = {
        "fisher": False,
        "macd": False,
        "redMarkers": False,
        "greenMarkers": False,
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{ticker.upper()} {timeframe_minutes}m</title>
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
    .note {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 12px;
      line-height: 1.5;
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
        <h1 class="title">{ticker.upper()} local archive</h1>
        <div class="subtitle">Source: <code>{csv_path}</code></div>
      </div>
      <div class="subtitle">Local interactive chart with deterministic debug overlays.</div>
    </div>
    <div class="panel">
      <div class="stats">
        {"".join(f'<div class="stat"><div class="label">{key}</div><div class="value">{value}</div></div>' for key, value in summary.items())}
      </div>
      <div class="note">This viewer now renders the archived CSV directly so the debug controls can reliably change the chart in-place.</div>
      <div class="controls">
        <button class="control-button" data-feature="fisher">Fisher 50</button>
        <button class="control-button" data-feature="macd">MACD</button>
        <button class="control-button" data-feature="redMarkers">Red triangles / 10 bars</button>
        <button class="control-button" data-feature="greenMarkers">Green triangles / 7 bars</button>
      </div>
      <div id="feature-status" class="status-panel"></div>
      <div class="links">
        <a class="link-button" href="https://www.tradingview.com/chart/?symbol={_tradingview_symbol(ticker).replace(':', '%3A')}" target="_blank" rel="noopener noreferrer">Open Symbol In TradingView</a>
      </div>
    </div>
    <section class="panel">
      <div id="chart"></div>
      <div id="fisher-chart" class="hidden"></div>
      <div id="macd-chart" class="hidden"></div>
      <div class="note">The chart uses local OHLCV data from the archive. Mouse wheel zoom, drag pan, box zoom, and reset controls are enabled through the Plotly toolbar.</div>
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
      const lines = [
        `Fisher pane: ${{state.fisher ? "on" : "off"}}`,
        `MACD pane: ${{state.macd ? "on" : "off"}}`,
        `Red triangle overlay: ${{state.redMarkers ? "on" : "off"}} (${{redMarkerTimes.length}} markers)`,
        `Green triangle overlay: ${{state.greenMarkers ? "on" : "off"}} (${{greenMarkerTimes.length}} markers)`
      ];
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
          type: "date"
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

    function plotConfig() {{
      return {{
        responsive: true,
        displaylogo: false,
        scrollZoom: true,
        doubleClick: "reset",
        modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toImage"],
        modeBarButtonsToAdd: ["zoomIn2d", "zoomOut2d", "resetScale2d"]
      }};
    }}

    function renderPriceChart() {{
      const traces = [
        {{
          type: "candlestick",
          x: times,
          open: openValues,
          high: highValues,
          low: lowValues,
          close: closeValues,
          name: "{ticker.upper()}",
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
      const layout = baseLayout(null);
      layout.yaxis.zeroline = false;
      Plotly.react("chart", traces, layout, plotConfig());
    }}

    function renderFisherChart() {{
      const container = document.getElementById("fisher-chart");
      container.classList.toggle("hidden", !state.fisher);
      if (!state.fisher) return;
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
        baseLayout(240),
        plotConfig()
      );
    }}

    function renderMacdChart() {{
      const container = document.getElementById("macd-chart");
      container.classList.toggle("hidden", !state.macd);
      if (!state.macd) return;
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
        baseLayout(240),
        plotConfig()
      );
    }}

    function renderChart() {{
      if (!window.Plotly) {{
        updateStatus();
        return;
      }}
      renderPriceChart();
      renderFisherChart();
      renderMacdChart();
    }}

    function bindControls() {{
      document.querySelectorAll(".control-button").forEach((button) => {{
        button.addEventListener("click", () => {{
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
    renderChart();
  </script>
</body>
</html>
"""


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
