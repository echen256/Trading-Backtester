"""Quick local visualization for archived OHLCV CSV files."""
from __future__ import annotations

import argparse
import csv
import json
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
    red_markers = []
    green_markers = []
    for index, row in enumerate(rows):
        bar_range = max(row["high"] - row["low"], max(row["close"] * 0.01, 0.01))
        timestamp = int(row["timestamp"].timestamp())
        if (index + 1) % 10 == 0:
            red_markers.append(
                {
                    "time": timestamp,
                    "price": round(row["high"] + bar_range * 0.18, 6),
                }
            )
        if (index + 1) % 7 == 0:
            green_markers.append(
                {
                    "time": timestamp,
                    "price": round(max(row["low"] - bar_range * 0.18, 0.000001), 6),
                }
            )

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
  <script src="https://s3.tradingview.com/tv.js"></script>
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
    #tv-widget {{
      width: 100%;
      height: calc(100vh - 220px);
      min-height: 720px;
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
    @media (max-width: 1080px) {{
      #tv-widget {{
        height: calc(100vh - 260px);
        min-height: 520px;
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
      <div class="subtitle">TradingView market widget sized as the primary full-screen chart.</div>
    </div>
    <div class="panel">
      <div class="stats">
        {"".join(f'<div class="stat"><div class="label">{key}</div><div class="value">{value}</div></div>' for key, value in summary.items())}
      </div>
      <div class="note">This viewer still resolves the local CSV for ticker and timeframe selection, but the on-screen chart below is the TradingView market widget for <code>{_tradingview_symbol(ticker)}</code>.</div>
      <div class="controls">
        <button class="control-button" data-feature="fisher">Fisher 50</button>
        <button class="control-button" data-feature="macd">MACD</button>
        <button class="control-button" data-feature="redMarkers">Red triangles / 10 bars</button>
        <button class="control-button" data-feature="greenMarkers">Green triangles / 7 bars</button>
      </div>
      <div id="feature-status" class="status-panel"></div>
      <div class="note">Fisher and MACD are applied by rebuilding the hosted TradingView widget with the selected studies. The public hosted widget does not expose the drawing API needed for per-bar custom triangles.</div>
    </div>
    <section class="panel">
      <div id="tv-widget"></div>
      <div class="note">TradingView data may differ from the local archive if the archive is stale or adjusted differently.</div>
    </section>
  </div>
  <script>
    const state = {json.dumps(initial_state)};
    const redMarkers = {json.dumps(red_markers)};
    const greenMarkers = {json.dumps(green_markers)};

    function setButtonState(feature) {{
      const button = document.querySelector(`[data-feature="${{feature}}"]`);
      if (!button) return;
      button.classList.toggle("active", Boolean(state[feature]));
    }}

    function setAllButtonStates() {{
      Object.keys(state).forEach(setButtonState);
    }}

    function studiesForState() {{
      const studies = [];
      if (state.fisher) {{
        studies.push("Fisher Transform");
      }}
      if (state.macd) {{
        studies.push("MACD");
      }}
      return studies;
    }}

    function updateStatus() {{
      const lines = [
        `Studies active: ${{studiesForState().join(", ") || "none"}}`,
        `Red triangle overlay requested: ${{state.redMarkers ? "on" : "off"}}`,
        `Green triangle overlay requested: ${{state.greenMarkers ? "on" : "off"}}`,
        `Red marker candidates from local CSV: ${{redMarkers.length}}`,
        `Green marker candidates from local CSV: ${{greenMarkers.length}}`,
        "Hosted TradingView widget limitation: custom per-bar triangle drawings are not exposed through this embed API."
      ];
      document.getElementById("feature-status").textContent = lines.join("\\n");
    }}

    function renderWidget() {{
      const container = document.getElementById("tv-widget");
      if (!container) return;
      container.innerHTML = "";
      if (!window.TradingView) {{
        container.innerHTML =
          "<div class='note'>TradingView script did not load, so the debug toggles are unavailable in this browser session.</div>";
        return;
      }}
      new window.TradingView.widget({{
        autosize: true,
        symbol: "{_tradingview_symbol(ticker)}",
        interval: "{_tradingview_interval(timeframe_minutes)}",
        timezone: "Etc/UTC",
        theme: "dark",
        style: "1",
        locale: "en",
        withdateranges: true,
        hide_side_toolbar: false,
        allow_symbol_change: true,
        studies: studiesForState(),
        container_id: "tv-widget"
      }});
    }}

    function bindControls() {{
      document.querySelectorAll(".control-button").forEach((button) => {{
        button.addEventListener("click", () => {{
          const feature = button.dataset.feature;
          state[feature] = !state[feature];
          setButtonState(feature);
          updateStatus();
          if (feature === "fisher" || feature === "macd") {{
            try {{
              renderWidget();
            }} catch (error) {{
              console.error(`Failed to rerender widget for ${{feature}}`, error);
            }}
          }}
        }});
      }});
      setAllButtonStates();
      updateStatus();
    }}

    bindControls();
    renderWidget();
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
