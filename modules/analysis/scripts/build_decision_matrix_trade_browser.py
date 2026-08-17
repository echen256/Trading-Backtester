"""Build a local HTML app that cycles through scored put/call trades."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_puts_decision_matrix import (
    ORDER_DIR,
    classify_state,
    fetch_underlying_daily_bars,
    get_polygon_api_key,
    load_vix,
    parse_bars,
)
from trading_analysis.parse_orders import OPTION_CONTRACT_RE

OUT_HTML = ORDER_DIR / "decision-matrix-trade-browser.html"
PUT_JSON = ORDER_DIR / "put-decision-matrix-review.json"
CALL_JSON = ORDER_DIR / "call-decision-matrix-review.json"


def compact_series(rows: list[dict]) -> dict:
    return {
        "t": [r["date"].isoformat() if isinstance(r["date"], date) else str(r["date"])[:10] for r in rows],
        "o": [round(r["o"], 4) for r in rows],
        "h": [round(r["h"], 4) for r in rows],
        "l": [round(r["l"], 4) for r in rows],
        "c": [round(r["c"], 4) for r in rows],
    }


def strike_from_symbol(symbol: str) -> float | None:
    match = OPTION_CONTRACT_RE.fullmatch(symbol)
    if not match:
        return None
    return int(match.group(4)) / 1000.0


def load_scored_trades() -> list[dict]:
    trades: list[dict] = []
    for path, side in ((PUT_JSON, "PUT"), (CALL_JSON, "CALL")):
        if not path.exists():
            raise SystemExit(f"Missing {path}. Run the put/call matrix scripts first.")
        payload = json.loads(path.read_text())
        for row in payload["trades"]:
            trades.append(
                {
                    "side": side,
                    "symbol": row["symbol"],
                    "und": row["underlying"],
                    "open": row["open_date"],
                    "close": row["close_date"],
                    "qty": row["quantity"],
                    "pnl": row["pnl"],
                    "hold": row["hold_days"],
                    "dte": row.get("dte_at_entry"),
                    "e": row["entry_state"],
                    "x": row["exit_state"],
                    "v": row["verdict"],
                    "why": row.get("why") or "",
                    "trend": row.get("name_trend") or "",
                    "strike": strike_from_symbol(row["symbol"]),
                }
            )
    trades.sort(key=lambda r: (r["open"], r["und"], r["symbol"], r["side"]))
    return trades


def main() -> None:
    if not get_polygon_api_key():
        raise SystemExit("POLYGON_API_KEY missing")

    trades = load_scored_trades()
    names = sorted({row["und"] for row in trades} | {"QQQ"})
    start = date.fromisoformat(min(row["open"] for row in trades)) - timedelta(days=90)
    end = date.fromisoformat(max(row["close"] for row in trades)) + timedelta(days=20)

    series: dict[str, dict] = {}
    missing: list[str] = []
    for i, name in enumerate(names):
        try:
            rows = parse_bars(
                fetch_underlying_daily_bars(name, start_date=start, end_date=end, throttle_seconds=0.08)
            )
            if rows:
                series[name] = compact_series(rows)
            else:
                missing.append(name)
        except Exception:
            missing.append(name)
        if (i + 1) % 25 == 0:
            print(f"underlyings {i+1}/{len(names)}")

    vix_rows, vix_src = load_vix(start, end)
    series["VIX"] = compact_series(vix_rows)

    qqq = parse_bars(
        fetch_underlying_daily_bars("QQQ", start_date=start, end_date=end, throttle_seconds=0.0)
    )
    regimes: dict[str, str] = {}
    for row in qqq:
        regimes[row["date"].isoformat()] = classify_state(qqq, vix_rows, row["date"])["state"]

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "vix_source": vix_src,
        "missing": missing,
        "regimes": regimes,
        "series": series,
        "trades": trades,
    }
    html = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload).replace("</", "<\\/"))
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"wrote {OUT_HTML} trades={len(trades)} series={len(series)} missing={len(missing)}")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Decision-matrix trade browser</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      --bg: #10151f;
      --panel: #151c28;
      --line: #263244;
      --text: #e9eef6;
      --muted: #9fb0c7;
      --chip: #192334;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text); font: 13px/1.4 system-ui, sans-serif; }
    header {
      display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      padding: 10px 14px; border-bottom: 1px solid var(--line); background: var(--bg);
      position: sticky; top: 0; z-index: 4;
    }
    header strong { font-size: 14px; margin-right: 6px; }
    select, input, button {
      background: var(--chip); color: var(--text); border: 1px solid #34435a;
      border-radius: 5px; padding: 7px 8px;
    }
    button { cursor: pointer; }
    button:hover { border-color: #5b7ea6; }
    #count { color: var(--muted); min-width: 90px; }
    main { display: grid; grid-template-columns: 320px 1fr; height: calc(100vh - 54px); }
    #list { overflow: auto; border-right: 1px solid var(--line); background: #121926; }
    .row {
      display: block; padding: 8px 10px; border-bottom: 1px solid #202b3b;
      color: inherit; text-decoration: none; cursor: pointer;
    }
    .row:hover, .row.active { background: #233651; }
    .row .meta { color: var(--muted); font-size: 11px; margin-top: 2px; }
    .pnl-pos { color: #7dcea0; }
    .pnl-neg { color: #f1948a; }
    #stage { display: flex; flex-direction: column; min-width: 0; }
    #meta {
      padding: 10px 14px 6px; border-bottom: 1px solid var(--line);
      display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: baseline;
    }
    #meta .pos { font-size: 16px; font-weight: 650; }
    #meta .why { color: var(--muted); max-width: 920px; }
    #chart { flex: 1; min-height: 0; }
    .legend { display: flex; flex-wrap: wrap; gap: 8px; padding: 6px 14px 10px; color: var(--muted); }
    .swatch { display: inline-flex; align-items: center; gap: 5px; }
    .swatch i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  </style>
</head>
<body>
<header>
  <strong>Decision-matrix trade browser</strong>
  <select id="side">
    <option value="ALL">Puts + calls</option>
    <option value="PUT">Puts</option>
    <option value="CALL">Calls</option>
  </select>
  <select id="state">
    <option value="ALL">All entry states</option>
    <option>G</option><option>Y</option><option>R</option><option>H</option>
    <option>D</option><option>N</option><option>F</option><option>B</option>
  </select>
  <select id="verdict">
    <option value="ALL">All verdicts</option>
    <option value="good_swing">good swing</option>
    <option value="outstayed">outstayed</option>
    <option value="too_early">too early</option>
    <option value="chase_nonexistent">chase nonexistent</option>
    <option value="chase_extension">chase extension</option>
  </select>
  <input id="search" placeholder="Filter ticker, symbol, date">
  <button id="prev" type="button">← Prev</button>
  <button id="next" type="button">Next →</button>
  <span id="count"></span>
</header>
<main>
  <nav id="list"></nav>
  <section id="stage">
    <div id="meta"></div>
    <div id="chart"></div>
    <div class="legend" id="legend"></div>
  </section>
</main>
<script type="application/json" id="payload">__PAYLOAD__</script>
<script>
const REGIME = {
  G: {fill:"rgba(46,204,113,0.28)", faint:"rgba(46,204,113,0.08)", line:"#2ecc71", name:"G Clean Risk-On"},
  Y: {fill:"rgba(241,196,15,0.30)", faint:"rgba(241,196,15,0.09)", line:"#f1c40f", name:"Y Event Divergence"},
  R: {fill:"rgba(231,76,60,0.28)", faint:"rgba(231,76,60,0.08)", line:"#e74c3c", name:"R Clean Correction"},
  H: {fill:"rgba(149,165,166,0.30)", faint:"rgba(149,165,166,0.10)", line:"#95a5a6", name:"H Hard Mode"},
  D: {fill:"rgba(155,89,182,0.28)", faint:"rgba(155,89,182,0.09)", line:"#9b59b6", name:"D Low-Vol Delever"},
  N: {fill:"rgba(230,126,34,0.30)", faint:"rgba(230,126,34,0.10)", line:"#e67e22", name:"N Denial / Latent"},
  F: {fill:"rgba(192,57,43,0.32)", faint:"rgba(192,57,43,0.10)", line:"#c0392b", name:"F Forced Recognition"},
  B: {fill:"rgba(26,188,156,0.30)", faint:"rgba(26,188,156,0.10)", line:"#1abc9c", name:"B Exhaustion / Repair"},
};
const data = JSON.parse(document.getElementById("payload").textContent);
const trades = data.trades;
const series = data.series;
const regimes = data.regimes;
let visible = trades.slice();
let current = 0;

document.getElementById("legend").innerHTML = Object.entries(REGIME).map(([k,v]) =>
  `<span class="swatch"><i style="background:${v.line}"></i>${k} ${v.name.slice(2)}</span>`
).join("");

function money(n) {
  const sign = n < 0 ? "−" : n > 0 ? "+" : "";
  return sign + "$" + Math.abs(n).toLocaleString(undefined, {maximumFractionDigits: 0});
}
function addDays(iso, n) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function sliceSeries(name, start, end) {
  const s = series[name];
  if (!s) return null;
  const out = {t:[], o:[], h:[], l:[], c:[]};
  for (let i = 0; i < s.t.length; i++) {
    if (s.t[i] < start || s.t[i] > end) continue;
    out.t.push(s.t[i]); out.o.push(s.o[i]); out.h.push(s.h[i]); out.l.push(s.l[i]); out.c.push(s.c[i]);
  }
  return out.t.length ? out : null;
}
function closeOn(s, day) {
  if (!s) return null;
  let last = null;
  for (let i = 0; i < s.t.length; i++) {
    if (s.t[i] <= day) last = s.c[i];
    if (s.t[i] === day) return s.c[i];
  }
  return last;
}
function regimeRuns(start, end) {
  const days = Object.keys(regimes).filter(d => d >= start && d <= end).sort();
  const runs = [];
  for (const day of days) {
    const st = regimes[day];
    if (!runs.length || runs[runs.length-1].state !== st) runs.push({state: st, start: day, end: day});
    else runs[runs.length-1].end = day;
  }
  return runs;
}
function applyFilter() {
  const side = document.getElementById("side").value;
  const state = document.getElementById("state").value;
  const verdict = document.getElementById("verdict").value;
  const q = document.getElementById("search").value.trim().toLowerCase();
  visible = trades.filter(t => {
    if (side !== "ALL" && t.side !== side) return false;
    if (state !== "ALL" && t.e !== state) return false;
    if (verdict !== "ALL" && t.v !== verdict) return false;
    if (q && !(`${t.und} ${t.symbol} ${t.open} ${t.close} ${t.v} ${t.e}`.toLowerCase().includes(q))) return false;
    return true;
  });
  if (current >= visible.length) current = 0;
  renderList();
  draw();
}
function renderList() {
  const list = document.getElementById("list");
  document.getElementById("count").textContent = visible.length ? `${current+1} / ${visible.length}` : "0 / 0";
  list.innerHTML = visible.map((t, i) => {
    const cls = t.pnl >= 0 ? "pnl-pos" : "pnl-neg";
    return `<a class="row ${i===current?"active":""}" data-i="${i}">
      <strong>${t.side} ${t.und}</strong> <span class="${cls}">${money(t.pnl)}</span>
      <div class="meta">${t.open} → ${t.close} · ${t.e}→${t.x} · ${t.v}</div>
    </a>`;
  }).join("");
  list.querySelectorAll(".row").forEach(el => el.onclick = () => { current = Number(el.dataset.i); draw(); renderList(); scrollActive(); });
  scrollActive();
}
function scrollActive() {
  document.querySelector(".row.active")?.scrollIntoView({block: "nearest"});
}
function draw() {
  const t = visible[current];
  const meta = document.getElementById("meta");
  if (!t) {
    meta.innerHTML = "<div class='why'>No trades match the filter.</div>";
    Plotly.purge("chart");
    return;
  }
  document.getElementById("count").textContent = `${current+1} / ${visible.length}`;
  const strike = t.strike != null ? t.strike.toString() : "";
  const pos = `${t.side} ${t.und} ${strike}${t.side==="PUT"?"p":"c"} × ${t.qty}`;
  const regime = `${t.e} → ${t.x}`;
  meta.innerHTML = `
    <div class="pos">${pos}</div>
    <div>${t.open} → ${t.close} · ${t.hold}d hold · ${t.dte ?? "?"} DTE</div>
    <div>Regime <strong>${regime}</strong> · ${t.v} · <span class="${t.pnl>=0?"pnl-pos":"pnl-neg"}">${money(t.pnl)}</span></div>
    <div class="why">${t.why}</div>`;

  const viewStart = addDays(t.open, -35);
  const viewEnd = addDays(t.close, 18);
  const px = sliceSeries(t.und, viewStart, viewEnd) || sliceSeries("QQQ", viewStart, viewEnd);
  const vx = sliceSeries("VIX", viewStart, viewEnd);
  const usingQqq = !series[t.und] && t.und !== "QQQ";
  const reg = REGIME[t.e] || REGIME.H;
  const shapes = [];
  for (const run of regimeRuns(viewStart, viewEnd)) {
    const style = REGIME[run.state];
    if (!style) continue;
    shapes.push({
      type: "rect", xref: "x", yref: "paper",
      x0: run.start, x1: addDays(run.end, 1), y0: 0, y1: 1,
      fillcolor: style.faint, line: {width: 0}, layer: "below",
    });
  }
  shapes.push({
    type: "rect", xref: "x", yref: "paper",
    x0: t.open, x1: addDays(t.close, 1),
    y0: 0, y1: 1,
    fillcolor: reg.fill, line: {width: 0}, layer: "below",
  });

  const entryY = closeOn(px, t.open);
  const exitY = closeOn(px, t.close);
  const traces = [];
  if (px) {
    traces.push({
      type: "candlestick",
      x: px.t, open: px.o, high: px.h, low: px.l, close: px.c,
      name: usingQqq ? `QQQ (no ${t.und} bars)` : t.und,
      increasing: {line: {color: "#7dcea0"}},
      decreasing: {line: {color: "#f1948a"}},
      xaxis: "x", yaxis: "y",
    });
    if (entryY != null) {
      traces.push({
        type: "scatter", mode: "markers+text",
        x: [t.open], y: [entryY],
        text: ["entry"], textposition: "top center",
        marker: {size: 11, color: "#e9eef6", symbol: "triangle-up"},
        name: "Entry", xaxis: "x", yaxis: "y",
      });
    }
    if (exitY != null) {
      traces.push({
        type: "scatter", mode: "markers+text",
        x: [t.close], y: [exitY],
        text: ["exit"], textposition: "bottom center",
        marker: {size: 11, color: "#e9eef6", symbol: "triangle-down"},
        name: "Exit", xaxis: "x", yaxis: "y",
      });
    }
    if (t.strike != null && t.strike > 0) {
      traces.push({
        type: "scatter", mode: "lines",
        x: [px.t[0], px.t[px.t.length-1]], y: [t.strike, t.strike],
        line: {color: "#f7dc6f", width: 1, dash: "dot"},
        name: "Strike", xaxis: "x", yaxis: "y",
      });
    }
  }
  if (vx) {
    traces.push({
      type: "scatter", mode: "lines",
      x: vx.t, y: vx.c,
      line: {color: "#5dade2", width: 2},
      name: "VIX", xaxis: "x", yaxis: "y2",
    });
  }

  const mid = t.open;
  const layout = {
    paper_bgcolor: "#10151f",
    plot_bgcolor: "#151c28",
    font: {color: "#e9eef6", size: 12},
    margin: {l: 56, r: 24, t: 36, b: 40},
    hovermode: "x unified",
    showlegend: false,
    xaxis: {anchor: "y2", type: "date", gridcolor: "#263244", tickfont: {color: "#9fb0c7"}},
    yaxis: {
      domain: [0.38, 1.0],
      title: {text: usingQqq ? "QQQ fallback" : t.und, font: {size: 12}},
      gridcolor: "#263244",
    },
    yaxis2: {
      domain: [0.0, 0.30],
      title: {text: "VIX", font: {size: 12}},
      gridcolor: "#263244",
    },
    shapes,
    annotations: [{
      x: mid, xref: "x", y: 1.0, yref: "paper", yanchor: "bottom",
      text: `${pos}   ·   ${t.e} → ${t.x}   ·   ${t.v}   ·   ${money(t.pnl)}`,
      showarrow: false, align: "left",
      bgcolor: "rgba(21,28,40,0.92)", bordercolor: reg.line, borderwidth: 1,
      font: {size: 12, color: "#e9eef6"},
    }],
  };
  Plotly.react("chart", traces, layout, {responsive: true, displaylogo: false});
}

document.getElementById("side").onchange = applyFilter;
document.getElementById("state").onchange = applyFilter;
document.getElementById("verdict").onchange = applyFilter;
document.getElementById("search").oninput = applyFilter;
document.getElementById("prev").onclick = () => { if (!visible.length) return; current = (current - 1 + visible.length) % visible.length; renderList(); draw(); };
document.getElementById("next").onclick = () => { if (!visible.length) return; current = (current + 1) % visible.length; renderList(); draw(); };
document.addEventListener("keydown", (ev) => {
  if (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT") return;
  if (ev.key === "ArrowLeft") document.getElementById("prev").click();
  if (ev.key === "ArrowRight") document.getElementById("next").click();
});
applyFilter();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
