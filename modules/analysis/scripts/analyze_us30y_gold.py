"""Compare US 30-year Treasury yield (^TYX) and gold (GC=F).

Outputs a static three-panel chart and a standalone HTML dashboard matching the
sector study's normalized-price, rolling-correlation, and adaptive-divergence
views.  ^TYX is a yield, not a total-return Treasury index; normalized levels
therefore show changes in the yield itself rather than bond-investor returns.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "modules" / "data-pipeline" / "src"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from trading_data_pipeline.strategies.fisher_adaptive_macd import (  # noqa: E402
    StrategyConfig,
    compute_fisher_adaptive_macd_strategy,
)


START = pd.Timestamp("2010-01-01")
END = pd.Timestamp("2026-08-16")
REPORTS = REPO_ROOT / "reports"
PNG_PATH = REPORTS / "us30y_gold_comparison.png"
HTML_PATH = REPORTS / "us30y_gold_dashboard.html"


def fetch_close(symbol: str) -> pd.Series:
    params = urlencode(
        {
            "period1": int(START.timestamp()),
            "period2": int((END + pd.Timedelta(days=2)).timestamp()),
            "interval": "1d",
            "events": "history",
        }
    )
    request = Request(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS endpoint
        result = json.load(response)["chart"]["result"][0]
    dates = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    close = result["indicators"].get("adjclose", [{}])[0].get("adjclose") or result["indicators"]["quote"][0]["close"]
    series = pd.Series(close, index=dates, dtype=float, name=symbol)
    return series[~series.index.duplicated()].dropna()


def adaptive_histogram(series: pd.Series) -> pd.Series:
    rows = [
        {
            "timestamp": pd.Timestamp(day).tz_localize("America/New_York").to_pydatetime(),
            "open": float(value), "high": float(value), "low": float(value), "close": float(value), "volume": None,
        }
        for day, value in series.dropna().items()
    ]
    result = compute_fisher_adaptive_macd_strategy(
        rows,
        ticker="GOLD_US30Y_RELATIVE",
        config=StrategyConfig(ft_len=50, r2_period=20, macd_fast=10, macd_slow=20, macd_signal=9, htf_tf="D"),
    )
    return pd.Series(result.series["histogram"], index=series.dropna().index, dtype=float)


def values(series: pd.Series, digits: int = 4) -> list[float | None]:
    return [None if pd.isna(value) else round(float(value), digits) for value in series]


def write_dashboard(frame: pd.DataFrame, normalized: pd.DataFrame, correlation: pd.Series, divergence: pd.Series) -> None:
    payload = json.dumps(
        {
            "dates": [str(date) for date in frame.index],
            "gold": values(normalized["Gold"], 3),
            "yield": values(normalized["US30Y"], 3),
            "corr": values(correlation, 4),
            "div": values(divergence, 4),
            "latest": {
                "gold": float(frame.Gold.iloc[-1]), "yield": float(frame.US30Y.iloc[-1]),
                "corr": None if pd.isna(correlation.iloc[-1]) else float(correlation.iloc[-1]),
                "div": None if pd.isna(divergence.iloc[-1]) else float(divergence.iloc[-1]),
                "gold_63": float(frame.Gold.iloc[-1] / frame.Gold.iloc[-64] - 1),
                "yield_63": float(frame.US30Y.iloc[-1] / frame.US30Y.iloc[-64] - 1),
            },
        },
        separators=(",", ":"),
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>US30Y vs Gold</title><style>
body{{margin:0;background:#f6f8fb;color:#172033;font:14px Inter,system-ui,sans-serif}}main{{max-width:1420px;margin:auto;padding:24px}}h1{{margin:0 0 5px}}.sub{{color:#60708a;margin:0 0 16px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card{{background:#fff;border:1px solid #dce4ef;border-radius:10px;padding:13px;box-shadow:0 1px 2px #1720330c}}.metric{{font-size:21px;font-weight:650;margin-top:4px}}.small{{font-size:12px;color:#62718a}}canvas{{display:block;width:100%;height:310px}}.chart{{margin-top:15px}}h2{{font-size:15px;margin:0 0 8px}}#tip{{display:none;position:fixed;z-index:10;background:#172033ed;color:#fff;padding:9px 10px;border-radius:7px;font:12px/1.45 ui-monospace,monospace;pointer-events:none;box-shadow:0 5px 16px #17203355}}@media(max-width:800px){{main{{padding:14px}}.grid{{grid-template-columns:1fr 1fr}}canvas{{height:260px}}}}</style></head>
<body><div id="tip"></div><main><h1>US 30-Year Yield vs Gold</h1><p class="sub">Daily data through {frame.index[-1]}. ^TYX is the 30-year yield; Gold is COMEX gold futures. Yield levels are normalized directly, not converted to bond returns.</p>
<section class="grid" id="cards"></section><section class="card chart"><h2>Normalized levels (100 = first date)</h2><canvas id="norm"></canvas></section><section class="card chart"><h2>60-session daily-return correlation</h2><canvas id="corr"></canvas></section><section class="card chart"><h2>Gold / US30Y relative adaptive-MACD divergence z-score</h2><canvas id="div"></canvas></section></main>
<script>const d={payload},tip=document.getElementById('tip'),hover={{}};const f=(x,n=2)=>x==null?'—':(x>=0?'+':'')+x.toFixed(n);const pct=x=>f(x*100)+'%';
const L=d.latest;document.getElementById('cards').innerHTML=`<div class="card"><div class="small">Gold futures</div><div class="metric">${{L.gold.toFixed(1)}}</div></div><div class="card"><div class="small">US 30Y yield</div><div class="metric">${{L.yield.toFixed(2)}}%</div></div><div class="card"><div class="small">60d correlation</div><div class="metric">${{f(L.corr)}}</div></div><div class="card"><div class="small">63d change: Gold / Yield</div><div class="metric">${{pct(L.gold_63)}} / ${{pct(L.yield_63)}}</div></div>`;
function draw(id,series,labels,colors,zero=false){{const c=document.getElementById(id),r=c.getBoundingClientRect(),q=devicePixelRatio||1;c.width=r.width*q;c.height=r.height*q;const x=c.getContext('2d');x.scale(q,q);const p={{l:55,r:16,t:12,b:26}},w=r.width,h=r.height;const a=series.flat().filter(v=>v!=null);let lo=Math.min(...a),hi=Math.max(...a),pad=(hi-lo||1)*.08;lo-=pad;hi+=pad;const X=i=>p.l+i*(w-p.l-p.r)/(d.dates.length-1),Y=v=>p.t+(hi-v)*(h-p.t-p.b)/(hi-lo);x.font='11px system-ui';x.fillStyle='#60708a';x.strokeStyle='#dbe3ef';for(let k=0;k<5;k++){{let y=p.t+k*(h-p.t-p.b)/4,v=hi-k*(hi-lo)/4;x.beginPath();x.moveTo(p.l,y);x.lineTo(w-p.r,y);x.stroke();x.fillText(v.toFixed(id==='norm'?0:1),3,y+4)}}for(let k=0;k<8;k++){{let i=Math.round(k*(d.dates.length-1)/7);x.fillText(d.dates[i].slice(0,7),X(i)-18,h-7)}}if(zero){{x.strokeStyle='#334155';x.beginPath();x.moveTo(p.l,Y(0));x.lineTo(w-p.r,Y(0));x.stroke()}}series.forEach((s,j)=>{{x.strokeStyle=colors[j];x.lineWidth=1.55;x.beginPath();let on=false;s.forEach((v,i)=>{{if(v==null){{on=false;return}}if(!on){{x.moveTo(X(i),Y(v));on=true}}else x.lineTo(X(i),Y(v))}});x.stroke()}});if(hover[id]!=null){{let i=hover[id],xx=X(i);x.setLineDash([4,4]);x.strokeStyle='#172033aa';x.beginPath();x.moveTo(xx,p.t);x.lineTo(xx,h-p.b);x.stroke();x.setLineDash([])}}c.onmousemove=e=>{{let i=Math.max(0,Math.min(d.dates.length-1,Math.round((e.clientX-r.left-p.l)*(d.dates.length-1)/(r.width-p.l-p.r))));hover[id]=i;let rows=labels.map((z,j)=>series[j][i]==null?'':`${{z}}: ${{series[j][i].toFixed(2)}}`).filter(Boolean).join('<br>');tip.innerHTML='<b>'+d.dates[i]+'</b><br>'+rows;tip.style.display='block';tip.style.left=Math.min(e.clientX+14,innerWidth-230)+'px';tip.style.top=Math.min(e.clientY+12,innerHeight-180)+'px';drawAll()}};c.onmouseleave=()=>{{delete hover[id];tip.style.display='none';drawAll()}}}}
function drawAll(){{draw('norm',[d.gold,d.yield],['Gold','US30Y'],['#d97706','#2563eb']);draw('corr',[d.corr],['Correlation'],['#7c3aed'],true);draw('div',[d.div],['Divergence z'],['#dc2626'],true)}}drawAll();addEventListener('resize',drawAll);</script></body></html>"""
    HTML_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    close = pd.concat({"US30Y": fetch_close("%5ETYX"), "Gold": fetch_close("GC%3DF")}, axis=1).dropna()
    normalized = close.div(close.iloc[0]).mul(100)
    correlation = close.pct_change().US30Y.rolling(60).corr(close.pct_change().Gold)
    relative = close.Gold.div(close.US30Y).mul(100)
    hist = adaptive_histogram(relative)
    divergence = hist.sub(hist.rolling(252, min_periods=126).mean()).div(hist.rolling(252, min_periods=126).std())
    REPORTS.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True, layout="constrained")
    axes[0].plot(normalized.index, normalized.Gold, color="#d97706", label="Gold futures")
    axes[0].plot(normalized.index, normalized.US30Y, color="#2563eb", label="US 30Y yield")
    axes[0].set_title("US 30-Year Treasury Yield vs Gold", loc="left", fontweight="bold")
    axes[0].set_ylabel("Normalized level")
    axes[0].legend(frameon=False)
    axes[1].plot(correlation.index, correlation, color="#7c3aed")
    axes[1].axhline(0, color="#475569", linewidth=.8)
    axes[1].set_ylabel("60d correlation")
    axes[2].plot(divergence.index, divergence, color="#dc2626")
    axes[2].axhline(0, color="#475569", linewidth=.8)
    axes[2].axhline(2, color="#94a3b8", linewidth=.7, linestyle="--")
    axes[2].axhline(-2, color="#94a3b8", linewidth=.7, linestyle="--")
    axes[2].set_ylabel("Relative adaptive-MACD z")
    for axis in axes:
        axis.grid(axis="y", alpha=.22)
    axes[2].set_xlabel("Date")
    fig.savefig(PNG_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)
    write_dashboard(close, normalized, correlation, divergence)
    print(f"Data: {close.index.min():%Y-%m-%d} to {close.index.max():%Y-%m-%d}")
    print(f"Latest: Gold {close.Gold.iloc[-1]:.1f}; US30Y {close.US30Y.iloc[-1]:.2f}%; 60d corr {correlation.iloc[-1]:.2f}; divergence z {divergence.iloc[-1]:.2f}")
    print(f"Wrote {PNG_PATH}\nWrote {HTML_PATH}")


if __name__ == "__main__":
    main()
