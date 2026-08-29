"""Measure sector/QQQ relative-strength divergence with Fisher adaptive MACD.

The script retrieves daily bars from the configured Polygon feed, computes each
sector ETF's price ratio to QQQ, passes that synthetic relative-strength series
through the project's adaptive-MACD implementation, and writes a chart plus a
markdown summary.  It is deliberately descriptive: thresholds are selected
from fixed z-score bands, not optimized after viewing future returns.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from trading_analysis.dashboard import StudyArtifactWriter

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "modules" / "data-pipeline" / "src"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from trading_data_pipeline.downloader import PolygonDownloader  # noqa: E402
from trading_data_pipeline.strategies.fisher_adaptive_macd import (  # noqa: E402
    StrategyConfig,
    compute_fisher_adaptive_macd_strategy,
)


START = datetime(2021, 8, 1)
END = datetime(2026, 8, 15)
SECTORS = {
    "XLB": "Materials",
    "XLC": "Communication",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Technology",
    "XLP": "Staples",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLY": "Discretionary",
    "SMH": "Semiconductors",
}
REPORTS_DIR = REPO_ROOT / "reports"
CHART_PATH = REPORTS_DIR / "qqq_sector_relative_divergence.png"
REPORT_PATH = REPORTS_DIR / "qqq_sector_relative_divergence.md"
CSV_PATH = REPORTS_DIR / "qqq_sector_relative_divergence_bands.csv"
DASHBOARD_PATH = REPORTS_DIR / "qqq_sector_relative_dashboard.html"


def fetch_daily(downloader: PolygonDownloader, symbol: str) -> tuple[str, pd.DataFrame]:
    frame = downloader.fetch_bars(symbol, START, END, 1440).copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York").date
    return symbol, frame[["open", "high", "low", "close"]]


def adaptive_histogram(relative: pd.Series) -> pd.Series:
    """Apply the repository's exact Fisher adaptive-MACD configuration."""

    rows = [
        {
            "timestamp": pd.Timestamp(day).tz_localize("America/New_York").to_pydatetime(),
            "open": float(value),
            "high": float(value),
            "low": float(value),
            "close": float(value),
            "volume": None,
        }
        for day, value in relative.dropna().items()
    ]
    result = compute_fisher_adaptive_macd_strategy(
        rows,
        ticker="RELATIVE",
        config=StrategyConfig(ft_len=50, r2_period=20, macd_fast=10, macd_slow=20, macd_signal=9, htf_tf="D"),
    )
    return pd.Series(result.series["histogram"], index=relative.dropna().index, dtype=float)


def format_pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:+.2f}%"


def format_rate(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.1f}%"


def _series_values(series: pd.Series) -> list[float | None]:
    return [None if pd.isna(value) else round(float(value), 5) for value in series]


def write_dashboard(
    *,
    dates: pd.Index,
    normalized: pd.DataFrame,
    correlations: pd.DataFrame,
    divergence: pd.DataFrame,
    current_rows: list[dict[str, object]],
) -> None:
    """Write a no-server-needed Canvas dashboard with sector toggles."""

    colors = [
        "#1565c0", "#ef6c00", "#2e7d32", "#c62828", "#6a1b9a", "#00838f",
        "#ad1457", "#455a64", "#9e9d24", "#00897b", "#5d4037", "#43a047",
    ]
    payload = {
        "dates": [str(date) for date in dates],
        "names": SECTORS,
        "colors": {symbol: colors[index] for index, symbol in enumerate(SECTORS)},
        "normalized": {symbol: _series_values(normalized[symbol]) for symbol in normalized},
        "correlations": {symbol: _series_values(correlations[symbol]) for symbol in correlations},
        "divergence": {symbol: _series_values(divergence[symbol]) for symbol in divergence},
        "current": current_rows,
    }
    data = json.dumps(payload, separators=(",", ":"))
    dashboard = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>QQQ Sector Relative Dashboard</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; background: #f6f8fb; color: #172033; }}
    main {{ max-width: 1500px; margin: auto; padding: 24px; }}
    h1 {{ margin: 0 0 4px; font-size: 24px; }}
    .sub {{ margin: 0 0 18px; color: #526078; }}
    .controls, .card {{ background: white; border: 1px solid #dde3ee; border-radius: 10px; padding: 14px; box-shadow: 0 1px 2px #1720330d; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin-bottom: 16px; }}
    .controls button {{ border: 1px solid #c9d2e1; background: #f8fafc; border-radius: 6px; padding: 5px 9px; cursor: pointer; }}
    label {{ font-size: 13px; white-space: nowrap; }} input {{ vertical-align: middle; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }}
    .card h2 {{ font-size: 15px; margin: 0 0 10px; }}
    .metric {{ font-size: 21px; font-weight: 650; }} .small {{ color: #61708a; font-size: 12px; margin-top: 4px; }}
    .charts {{ display: grid; gap: 16px; }}
    canvas {{ width: 100%; height: 310px; display: block; }}
    #tooltip {{ position: fixed; display: none; z-index: 10; width: 220px; max-height: 280px; overflow: auto; padding: 9px 10px; background: #172033ed; border: 1px solid #334155; border-radius: 7px; color: #f8fafc; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; pointer-events: none; box-shadow: 0 6px 18px #17203340; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }} th,td {{ padding: 7px; border-bottom: 1px solid #e5eaf2; text-align: right; }} th:first-child,td:first-child {{ text-align: left; }}
    @media(max-width: 900px) {{ main {{ padding: 14px; }} .grid {{ grid-template-columns: 1fr; }} canvas {{ height: 260px; }} }}
  </style>
</head>
<body><div id=\"tooltip\"></div><main>
  <h1>QQQ Sector Relative Dashboard</h1>
  <p class=\"sub\">Daily data through {dates[-1]}. Toggle sectors to compare normalized prices, 60-session correlation, and relative adaptive-MACD divergence.</p>
  <div class=\"controls\" id=\"controls\"><strong>Visible sectors</strong><button id=\"all\">All</button><button id=\"none\">None</button></div>
  <section class=\"grid\" id=\"snapshot\"></section>
  <section class=\"charts\">
    <div class=\"card\"><h2>Normalized price (100 = first displayed day)</h2><canvas id=\"normalized\"></canvas></div>
    <div class=\"card\"><h2>60-session daily-return correlation to QQQ</h2><canvas id=\"correlation\"></canvas></div>
    <div class=\"card\"><h2>Adaptive-MACD relative divergence z-score</h2><canvas id=\"divergence\"></canvas></div>
  </section>
  <section class=\"card\" style=\"margin-top:16px\"><h2>Latest sector-relative readings</h2><table id=\"table\"></table></section>
</main>
<script>
const data={data};
const active=new Set(Object.keys(data.names));
const hover={{}};
const fmt=(n,d=2)=>n==null?'—':`${{n>=0?'+':''}}${{n.toFixed(d)}}`;
function controls() {{
  const root=document.getElementById('controls');
  Object.entries(data.names).forEach(([symbol,name])=>{{
    const label=document.createElement('label'); const box=document.createElement('input'); box.type='checkbox'; box.checked=true;
    box.onchange=()=>{{ box.checked?active.add(symbol):active.delete(symbol); drawAll(); }};
    label.append(box,document.createTextNode(' '+symbol+' · '+name)); label.style.color=data.colors[symbol]; root.append(label);
  }});
  document.getElementById('all').onclick=()=>{{Object.keys(data.names).forEach(x=>active.add(x));document.querySelectorAll('input[type=checkbox]').forEach(x=>x.checked=true);drawAll();}};
  document.getElementById('none').onclick=()=>{{active.clear();document.querySelectorAll('input[type=checkbox]').forEach(x=>x.checked=false);drawAll();}};
}}
function chart(id, series, includeQQQ, title) {{
  const canvas=document.getElementById(id), rect=canvas.getBoundingClientRect(), dpr=devicePixelRatio||1;
  canvas.width=Math.max(1,rect.width*dpr); canvas.height=Math.max(1,rect.height*dpr); const c=canvas.getContext('2d'); c.scale(dpr,dpr);
  const w=rect.width,h=rect.height,p={{l:52,r:16,t:12,b:27}}; const names=[...(includeQQQ?['QQQ']:[]),...active];
  const values=names.flatMap(s=>series[s].filter(v=>v!=null)); if(!values.length){{c.fillText('Select a sector',20,30);return;}}
  let lo=Math.min(...values),hi=Math.max(...values); const pad=(hi-lo||1)*.08;lo-=pad;hi+=pad;
  const X=i=>p.l+i*(w-p.l-p.r)/(data.dates.length-1),Y=v=>p.t+(hi-v)*(h-p.t-p.b)/(hi-lo);
  c.strokeStyle='#dbe3ef';c.lineWidth=1; c.font='11px system-ui';c.fillStyle='#61708a';
  for(let k=0;k<5;k++){{const y=p.t+k*(h-p.t-p.b)/4,v=hi-k*(hi-lo)/4;c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke();c.fillText(v.toFixed(id==='correlation'||id==='divergence'?1:0),4,y+4);}}
  for(let k=0;k<9;k++){{const i=Math.round(k*(data.dates.length-1)/8),x=X(i);c.fillText(data.dates[i].slice(0,7),x-18,h-7);}}
  if(id==='divergence'||id==='correlation'){{const y=Y(0);c.strokeStyle='#172033';c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke();}}
  names.forEach(s=>{{const a=series[s];c.strokeStyle=s==='QQQ'?'#111827':data.colors[s];c.lineWidth=s==='QQQ'?2.2:1.35;c.beginPath();let started=false;a.forEach((v,i)=>{{if(v==null){{started=false;return;}};if(!started){{c.moveTo(X(i),Y(v));started=true;}}else c.lineTo(X(i),Y(v));}});c.stroke();}});
  if(hover[id]!=null){{const i=hover[id];const hx=X(i);c.save();c.strokeStyle='#172033aa';c.setLineDash([4,4]);c.beginPath();c.moveTo(hx,p.t);c.lineTo(hx,h-p.b);c.stroke();c.restore();names.forEach(s=>{{const v=series[s][i];if(v==null)return;c.fillStyle=s==='QQQ'?'#111827':data.colors[s];c.beginPath();c.arc(hx,Y(v),3,0,Math.PI*2);c.fill();}});}}
  canvas.onmousemove=(event)=>{{const mx=event.clientX-rect.left;const i=Math.max(0,Math.min(data.dates.length-1,Math.round((mx-p.l)*(data.dates.length-1)/(rect.width-p.l-p.r))));hover[id]=i;showTooltip(event,series,includeQQQ);drawAll();}};
  canvas.onmouseleave=()=>{{delete hover[id];document.getElementById('tooltip').style.display='none';drawAll();}};
}}
function showTooltip(event,series,includeQQQ) {{
  const i=hover[event.currentTarget.id], names=[...(includeQQQ?['QQQ']:[]),...active], tip=document.getElementById('tooltip');
  let html=`<strong>${{data.dates[i]}}</strong><br>`;names.forEach(s=>{{const v=series[s][i];if(v!=null)html+=`<span style=\"color:${{s==='QQQ'?'#ffffff':data.colors[s]}}\">●</span> ${{s}}: ${{v.toFixed(2)}}<br>`;}});tip.innerHTML=html;
  tip.style.display='block';tip.style.left=Math.min(event.clientX+16,window.innerWidth-238)+'px';tip.style.top=Math.min(event.clientY+12,window.innerHeight-290)+'px';
}}
function drawAll() {{chart('normalized',data.normalized,true);chart('correlation',data.correlations,false);chart('divergence',data.divergence,false);}}
function snapshot() {{
  const e=data.current.find(x=>x.symbol==='XLE'); document.getElementById('snapshot').innerHTML=`<div class=\"card\"><h2>Energy vs QQQ</h2><div class=\"metric\">${{fmt(e.relative_63d)}}%</div><div class=\"small\">XLE relative return versus QQQ, trailing 63 sessions</div></div><div class=\"card\"><h2>Energy divergence</h2><div class=\"metric\">${{fmt(e.divergence_z)}} z</div><div class=\"small\">Adaptive-MACD relative histogram z-score</div></div><div class=\"card\"><h2>Energy correlation</h2><div class=\"metric\">${{e.correlation_60d==null?'—':e.correlation_60d.toFixed(2)}}</div><div class=\"small\">60-session correlation of daily returns to QQQ</div></div>`;
  let html='<tr><th>Sector</th><th>21d vs QQQ</th><th>63d vs QQQ</th><th>252d vs QQQ</th><th>Divergence z</th><th>60d corr.</th></tr>';
  data.current.forEach(x=>html+=`<tr><td><span style=\"color:${{data.colors[x.symbol]}}\">●</span> ${{x.symbol}} · ${{x.name}}</td><td>${{fmt(x.relative_21d)}}%</td><td>${{fmt(x.relative_63d)}}%</td><td>${{fmt(x.relative_252d)}}%</td><td>${{fmt(x.divergence_z)}}</td><td>${{x.correlation_60d==null?'—':x.correlation_60d.toFixed(2)}}</td></tr>`);document.getElementById('table').innerHTML=html;
}}
controls();snapshot();drawAll();addEventListener('resize',drawAll);
</script></body></html>"""
    DASHBOARD_PATH.write_text(dashboard, encoding="utf-8")


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    downloader = PolygonDownloader()
    symbols = ["QQQ", *SECTORS]
    bars: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_daily, downloader, symbol) for symbol in symbols]
        for future in as_completed(futures):
            symbol, frame = future.result()
            bars[symbol] = frame

    close = pd.concat({symbol: frame["close"] for symbol, frame in bars.items()}, axis=1).dropna()
    normalized = close.div(close.iloc[0]).mul(100)
    daily_returns = close.pct_change()
    rolling_corr = daily_returns.rolling(60).corr(daily_returns["QQQ"])

    relative = close.drop(columns="QQQ").div(close["QQQ"], axis=0).mul(100)
    histogram = pd.DataFrame({symbol: adaptive_histogram(relative[symbol]) for symbol in relative})
    # Past-only rolling normalization makes amplitudes comparable across sectors.
    zscore = histogram.sub(histogram.rolling(252, min_periods=126).mean()).div(
        histogram.rolling(252, min_periods=126).std()
    )
    relative_rebased = relative.div(relative.iloc[0]).mul(100)
    qqq_fwd_10 = close["QQQ"].shift(-10).div(close["QQQ"]).sub(1)
    qqq_fwd_20 = close["QQQ"].shift(-20).div(close["QQQ"]).sub(1)
    rel_fwd_10 = relative.shift(-10).div(relative).sub(1)
    rel_fwd_20 = relative.shift(-20).div(relative).sub(1)

    labels = ["≤−2", "−2 to −1", "−1 to +1", "+1 to +2", "≥+2"]
    bins = [-np.inf, -2, -1, 1, 2, np.inf]
    pooled = pd.DataFrame(
        {
            "z": zscore.stack(),
            "relative_10d": rel_fwd_10.stack(),
            "relative_20d": rel_fwd_20.stack(),
        }
    ).dropna()
    pooled["band"] = pd.cut(pooled["z"], bins=bins, labels=labels, include_lowest=True)
    band_summary = (
        pooled.groupby("band", observed=False)
        .agg(
            observations=("z", "size"),
            avg_relative_10d=("relative_10d", "mean"),
            win_relative_10d=("relative_10d", lambda x: (x > 0).mean()),
            avg_relative_20d=("relative_20d", "mean"),
            win_relative_20d=("relative_20d", lambda x: (x > 0).mean()),
        )
        .reindex(labels)
    )
    band_summary[["avg_relative_10d", "win_relative_10d", "avg_relative_20d", "win_relative_20d"]] *= 100
    band_summary.to_csv(CSV_PATH)

    # Cross-sector breadth: can the aggregate divergence forecast QQQ itself?
    breadth = zscore.mean(axis=1).rename("breadth_z")
    breadth_frame = pd.concat([breadth, qqq_fwd_10.rename("qqq_10d"), qqq_fwd_20.rename("qqq_20d")], axis=1).dropna()
    breadth_frame["band"] = pd.cut(breadth_frame["breadth_z"], bins=bins, labels=labels, include_lowest=True)
    breadth_summary = (
        breadth_frame.groupby("band", observed=False)
        .agg(
            observations=("breadth_z", "size"),
            avg_qqq_10d=("qqq_10d", "mean"),
            win_qqq_10d=("qqq_10d", lambda x: (x > 0).mean()),
            avg_qqq_20d=("qqq_20d", "mean"),
            win_qqq_20d=("qqq_20d", lambda x: (x > 0).mean()),
        )
        .reindex(labels)
    )
    breadth_summary[["avg_qqq_10d", "win_qqq_10d", "avg_qqq_20d", "win_qqq_20d"]] *= 100

    # Chart recent history to keep the comparison legible; calculations use full history.
    recent_start = normalized.index[-504]
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(3, 1, figsize=(16, 15), sharex=True, constrained_layout=True)
    normalized.loc[recent_start:].plot(ax=axes[0], linewidth=1.25)
    axes[0].set_title("Sector ETFs normalized to 100 — last two years")
    axes[0].set_ylabel("Rebased price")
    axes[0].legend(ncol=4, fontsize=8, loc="upper left")

    corr_frame = pd.DataFrame({symbol: rolling_corr.loc[:, symbol] for symbol in SECTORS})
    corr_frame.loc[recent_start:].plot(ax=axes[1], linewidth=1.1)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("60-session daily-return correlation to QQQ")
    axes[1].set_ylabel("Correlation")
    axes[1].legend(ncol=4, fontsize=8, loc="upper left")

    zscore.loc[recent_start:].plot(ax=axes[2], linewidth=1.0)
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].axhline(1, color="#2e7d32", linestyle="--", linewidth=0.8)
    axes[2].axhline(-1, color="#c62828", linestyle="--", linewidth=0.8)
    axes[2].axhline(2, color="#2e7d32", linestyle=":", linewidth=0.8)
    axes[2].axhline(-2, color="#c62828", linestyle=":", linewidth=0.8)
    axes[2].set_title("Adaptive-MACD divergence: sector / QQQ histogram z-score")
    axes[2].set_ylabel("252-session z-score")
    axes[2].legend(ncol=4, fontsize=8, loc="upper left")
    fig.savefig(CHART_PATH, dpi=180)
    plt.close(fig)

    current_rows = []
    for symbol, name in SECTORS.items():
        current_rows.append(
            {
                "symbol": symbol,
                "name": name,
                "relative_21d": float(relative[symbol].iloc[-1] / relative[symbol].iloc[-22] - 1) * 100,
                "relative_63d": float(relative[symbol].iloc[-1] / relative[symbol].iloc[-64] - 1) * 100,
                "relative_252d": float(relative[symbol].iloc[-1] / relative[symbol].iloc[-253] - 1) * 100,
                "relative_rebased": float(relative_rebased[symbol].iloc[-1]),
                "divergence_z": float(zscore[symbol].iloc[-1]),
                "correlation_60d": float(rolling_corr.loc[rolling_corr.index[-1], symbol]),
            }
        )
    dashboard_dates = normalized.loc[recent_start:].index
    write_dashboard(
        dates=dashboard_dates,
        normalized=normalized.loc[recent_start:],
        correlations=corr_frame.loc[recent_start:],
        divergence=zscore.loc[recent_start:],
        current_rows=current_rows,
    )

    lines = [
        "# QQQ sector relative-divergence study",
        "",
        f"Study period: {close.index.min()} through {close.index.max()}. The chart uses the most recent two years; all statistics use the full period.",
        "",
        "Method: each sector's close is divided by QQQ, rebased to 100, and passed through the repository's Fisher adaptive-MACD configuration (50-bar Fisher; adaptive MACD 10/20/9; 20-bar R²). The histogram is standardized by a past-only 252-session rolling z-score. Positive divergence means accelerating sector outperformance versus QQQ.",
        "",
        "## Sector-relative forward returns by divergence band",
        "",
        "| Histogram z-score | N | Avg next 10d relative return | Relative win rate | Avg next 20d relative return | Relative win rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for band, row in band_summary.iterrows():
        lines.append(
            f"| {band} | {int(row.observations)} | {format_pct(row.avg_relative_10d)} | {format_rate(row.win_relative_10d)} | {format_pct(row.avg_relative_20d)} | {format_rate(row.win_relative_20d)} |"
        )
    lines.extend(
        [
            "",
            "## QQQ forward returns by average sector divergence breadth",
            "",
            "| Breadth z-score | N | Avg next 10d QQQ return | QQQ win rate | Avg next 20d QQQ return | QQQ win rate |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for band, row in breadth_summary.iterrows():
        lines.append(
            f"| {band} | {int(row.observations)} | {format_pct(row.avg_qqq_10d)} | {format_rate(row.win_qqq_10d)} | {format_pct(row.avg_qqq_20d)} | {format_rate(row.win_qqq_20d)} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- A sector z-score is a relative-strength signal, not a QQQ directional signal by itself.",
            "- Treat a band as economically meaningful only if it has at least 100 observations, a sign-consistent 10d/20d result, and a material improvement over the neutral band.",
            "- The bands are descriptive and overlap in time; they are not independent trades. Revalidate out of sample before using them as execution thresholds.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    dashboard_output = StudyArtifactWriter().publish_report_study(
        study_id="qqq-sector-relative-divergence",
        study_name="QQQ Sector Relative Divergence",
        version="1.0",
        generator="modules/analysis/scripts/analyze_sector_relative_divergence.py",
        files={"report": REPORT_PATH, "bands": CSV_PATH, "chart": CHART_PATH, "legacy_dashboard": DASHBOARD_PATH},
    )
    print(f"Wrote {CHART_PATH}")
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {CSV_PATH}")
    print(f"Wrote {DASHBOARD_PATH}")
    print(f"Published dashboard study {dashboard_output}")
    energy = next(row for row in current_rows if row["symbol"] == "XLE")
    print(
        "XLE snapshot: "
        f"21d={energy['relative_21d']:+.2f}% vs QQQ, "
        f"63d={energy['relative_63d']:+.2f}%, "
        f"252d={energy['relative_252d']:+.2f}%, "
        f"divergence_z={energy['divergence_z']:+.2f}, corr60={energy['correlation_60d']:.2f}"
    )
    xle_extremes = zscore["XLE"].dropna()
    xle_negative_extremes = xle_extremes[xle_extremes <= -2]
    latest_extremes = ", ".join(
        f"{date} ({value:+.2f})" for date, value in xle_negative_extremes.tail(3).items()
    )
    print(
        f"XLE negative divergence extremes: count={len(xle_negative_extremes)}, "
        f"minimum={xle_extremes.min():+.2f} on {xle_extremes.idxmin()}, latest={latest_extremes or 'none'}"
    )


if __name__ == "__main__":
    main()
