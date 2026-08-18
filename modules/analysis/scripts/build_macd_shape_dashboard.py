"""Build an interactive annotated atlas for the MACD histogram-shape events."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = REPO_ROOT / "modules" / "analysis" / "strategies" / "runs"
EVENTS_CSV = REPO_ROOT / "reports" / "macd_histogram_shape_events.csv"
OUTPUT = REPO_ROOT / "reports" / "macd_histogram_shape_dashboard.html"
SOURCES = {
    "Weekly": RUN_ROOT / "scanner-weekly-fixed-core" / "runs",
    "3-day": RUN_ROOT / "scanner-3d-fixed-core" / "runs",
}
MAIN_HORIZON = {"Weekly": 4, "3-day": 5}


def choose_longest_runs(root: Path) -> dict[str, dict[str, object]]:
    chosen: dict[str, tuple[tuple[int, str], dict[str, object]]] = {}
    for path in root.glob("*/*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars = payload.get("bars") or []
        if not bars:
            continue
        ticker = str(payload.get("ticker") or path.parent.name).upper()
        key = (len(bars), str(bars[-1].get("time") or ""))
        if ticker not in chosen or key > chosen[ticker][0]:
            chosen[ticker] = (key, payload)
    return {ticker: payload for ticker, (_, payload) in chosen.items()}


def clean_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def build_payload() -> dict[str, object]:
    events = pd.read_csv(EVENTS_CSV)
    payload: dict[str, object] = {}
    for timeframe, root in SOURCES.items():
        horizon = MAIN_HORIZON[timeframe]
        datasets: dict[str, object] = {}
        for ticker, run in sorted(choose_longest_runs(root).items()):
            bars = run["bars"]
            dates = [str(bar["time"]) for bar in bars]
            index_by_date = {date: index for index, date in enumerate(dates)}
            selected = events[(events.timeframe == timeframe) & (events.ticker == ticker)]
            annotations: list[dict[str, object]] = []
            for _, event in selected.iterrows():
                date = str(event.date)
                index = index_by_date.get(date)
                if index is None:
                    continue
                end_index = index + horizon
                annotations.append(
                    {
                        "date": date,
                        "event": str(event.event),
                        "quartile": str(event.slope_quartile),
                        "slope": clean_number(event.slope_norm),
                        "shape": str(event.line_shape),
                        "aboveZero": bool(event.both_above_zero),
                        "price": clean_number(bars[index]["close"]),
                        "macd": clean_number(bars[index]["adaptive_macd"]),
                        "forwardBars": horizon,
                        "forwardReturn": clean_number(event.get(f"return_{horizon}")),
                        "endDate": dates[end_index] if end_index < len(dates) else None,
                        "endPrice": clean_number(bars[end_index]["close"]) if end_index < len(bars) else None,
                    }
                )
            datasets[ticker] = {
                "date": dates,
                "open": [clean_number(bar.get("open")) for bar in bars],
                "high": [clean_number(bar.get("high")) for bar in bars],
                "low": [clean_number(bar.get("low")) for bar in bars],
                "close": [clean_number(bar.get("close")) for bar in bars],
                "macd": [clean_number(bar.get("adaptive_macd")) for bar in bars],
                "signal": [clean_number(bar.get("signal")) for bar in bars],
                "histogram": [clean_number(bar.get("histogram")) for bar in bars],
                "events": annotations,
            }
        payload[timeframe] = datasets
    return payload


def render_html(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Adaptive-MACD shape event atlas</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root{{--bg:#0b1220;--panel:#121d30;--line:#263956;--text:#e8eef9;--muted:#9fb0c9;--cyan:#4dc3ff;--gold:#f7c948}}
    *{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(160deg,#101d31,var(--bg) 48%);color:var(--text);font:14px ui-monospace,SFMono-Regular,Menlo,monospace}}
    .page{{max-width:1600px;margin:auto;padding:20px}} h1{{font:700 26px system-ui;margin:0 0 6px}} .sub{{color:var(--muted);margin-bottom:16px}}
    .toolbar{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);padding:12px 14px;border-radius:10px}}
    label{{color:var(--muted)}} select,button{{margin-left:6px;background:#0d1727;color:var(--text);border:1px solid #345075;border-radius:6px;padding:7px 9px}}
    .check{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .check label{{color:var(--text)}}
    #chart{{height:850px;margin-top:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px}}
    .legend{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;margin-top:12px}}
    .card{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;color:var(--muted)}} .card b{{color:var(--text)}}
  </style>
</head>
<body><div class="page">
  <h1>Adaptive-MACD histogram-shape event atlas</h1>
  <div class="sub">Exact Fisher adaptive-MACD used by the pilot · hover markers for slope, line shape, regime, and forward outcome</div>
  <div class="toolbar">
    <label>Timeframe<select id="timeframe"><option>3-day</option><option>Weekly</option></select></label>
    <label>Symbol<select id="ticker"></select></label>
    <div class="check">
      <label><input id="early" type="checkbox" checked> Early rising-blue</label>
      <label><input id="q1" type="checkbox" checked> Bear cross Q1 weak</label>
      <label><input id="mid" type="checkbox"> Bear cross Q2–Q3</label>
      <label><input id="q4" type="checkbox" checked> Bear cross Q4 steep</label>
      <label><input id="paths" type="checkbox"> Forward evaluation paths</label>
    </div>
    <button id="recent">Latest 2 years</button><button id="all">Fit all</button>
  </div>
  <div id="chart"></div>
  <div class="legend">
    <div class="card"><b>Cyan circles</b><br>Third consecutive positive and increasing histogram bar; this is the causal early checkpoint.</div>
    <div class="card"><b>Red ▼ / violet ▼</b><br>Bearish histogram crossover after weak-Q1 / steep-Q4 completed positive impulse.</div>
    <div class="card"><b>Small diamonds</b><br>The same events located directly on the adaptive MACD line.</div>
    <div class="card"><b>Evaluation paths</b><br>Dotted observation-to-forward-window paths. They are research endpoints, not executed trades.</div>
  </div>
</div>
<script>
const DATA={encoded};
const tf=document.getElementById('timeframe'), ticker=document.getElementById('ticker');
const checks=['early','q1','mid','q4','paths'].map(id=>document.getElementById(id));
let rangeMode='recent';
function symbols(){{return Object.keys(DATA[tf.value]).sort()}}
function refreshSymbols(){{const prior=ticker.value; ticker.innerHTML=symbols().map(s=>`<option>${{s}}</option>`).join(''); ticker.value=symbols().includes(prior)?prior:(symbols().includes('MU')?'MU':symbols()[0]); render()}}
function enabled(e){{if(e.event==='early_rising_blue')return document.getElementById('early').checked;if(e.quartile==='Q1 weak')return document.getElementById('q1').checked;if(e.quartile==='Q4 steep')return document.getElementById('q4').checked;return document.getElementById('mid').checked}}
function eventStyle(e){{if(e.event==='early_rising_blue')return {{color:'#43d5ff',symbol:'circle',label:'Early blue'}};if(e.quartile==='Q1 weak')return {{color:'#ff5f6d',symbol:'triangle-down',label:'Bear Q1 weak'}};if(e.quartile==='Q4 steep')return {{color:'#b68cff',symbol:'triangle-down',label:'Bear Q4 steep'}};return {{color:'#f7c948',symbol:'triangle-down',label:`Bear ${{e.quartile}}`}}}}
function hover(e){{const ret=e.forwardReturn==null?'—':(e.forwardReturn*100).toFixed(2)+'%';const slope=e.slope==null?'—':e.slope.toFixed(2);return `${{e.event==='early_rising_blue'?'Early rising-blue checkpoint':'Bearish histogram crossover'}}<br>${{e.date}}<br>Slope: ${{slope}} (${{e.quartile}})<br>Lines: ${{e.shape}}<br>MACD + signal above zero: ${{e.aboveZero?'yes':'no'}}<br>${{e.forwardBars}}-bar return: ${{ret}}`}}
function markerTraces(events,axis){{const groups={{}};events.filter(enabled).forEach(e=>{{const st=eventStyle(e),key=st.label;if(!groups[key])groups[key]={{style:st,events:[]}};groups[key].events.push(e)}});return Object.values(groups).map(g=>({{type:'scatter',mode:'markers',name:g.style.label+(axis==='y'?' · price':' · MACD'),x:g.events.map(e=>e.date),y:g.events.map(e=>axis==='y'?e.price:e.macd),text:g.events.map(hover),hovertemplate:'%{{text}}<extra></extra>',marker:{{color:g.style.color,symbol:axis==='y'?g.style.symbol:'diamond',size:axis==='y'?12:8,line:{{color:'#0b1220',width:1}}}},yaxis:axis,showlegend:axis==='y'}}))}}
function render(){{const d=DATA[tf.value][ticker.value];const ev=d.events;const histColors=d.histogram.map((v,i)=>v==null?'#52627a':v>=0?(i&&d.histogram[i-1]!=null&&v>d.histogram[i-1]?'#42c7ef':'#256f8d'):(i&&d.histogram[i-1]!=null&&v<d.histogram[i-1]?'#ff6574':'#8e3540'));
 const traces=[{{type:'candlestick',x:d.date,open:d.open,high:d.high,low:d.low,close:d.close,name:ticker.value,increasing:{{line:{{color:'#2ec4a6'}}}},decreasing:{{line:{{color:'#ef5966'}}}},yaxis:'y'}},{{type:'bar',x:d.date,y:d.histogram,name:'Histogram',marker:{{color:histColors}},yaxis:'y2'}},{{type:'scatter',mode:'lines',x:d.date,y:d.macd,name:'Adaptive MACD',line:{{color:'#4dc3ff',width:2}},yaxis:'y2'}},{{type:'scatter',mode:'lines',x:d.date,y:d.signal,name:'Signal',line:{{color:'#f7c948',width:2}},yaxis:'y2'}},...markerTraces(ev,'y'),...markerTraces(ev,'y2')];
 if(document.getElementById('paths').checked){{const selected=ev.filter(e=>enabled(e)&&e.endDate&&e.event==='bearish_crossover');for(const sign of [1,-1]){{const subset=selected.filter(e=>Math.sign(e.forwardReturn||0)===sign),x=[],y=[];subset.forEach(e=>{{x.push(e.date,e.endDate,null);y.push(e.price,e.endPrice,null)}});traces.push({{type:'scatter',mode:'lines+markers',x,y,yaxis:'y',name:sign>0?'Forward price rise':'Forward price fall',line:{{color:sign>0?'rgba(46,196,166,.55)':'rgba(239,89,102,.55)',dash:'dot',width:1}},marker:{{size:5}},hoverinfo:'skip'}})}}}}
 const start=rangeMode==='recent'?d.date[Math.max(0,d.date.length-(tf.value==='Weekly'?104:244))]:d.date[0];
 const layout={{paper_bgcolor:'#121d30',plot_bgcolor:'#121d30',font:{{color:'#dfe8f6'}},height:850,margin:{{l:65,r:30,t:55,b:45}},title:{{text:`${{ticker.value}} · ${{tf.value}} adaptive-MACD shape events`,x:.02}},hovermode:'x unified',dragmode:'pan',legend:{{orientation:'h',y:1.04}},xaxis:{{domain:[0,1],range:[start,d.date[d.date.length-1]],rangeslider:{{visible:false}},gridcolor:'#263956',showspikes:true,spikemode:'across'}},yaxis:{{domain:[.39,1],title:'Price',gridcolor:'#263956'}},yaxis2:{{domain:[0,.31],title:'Adaptive MACD',gridcolor:'#263956',zeroline:true,zerolinecolor:'#7f8da3'}},bargap:.12}};
 Plotly.react('chart',traces,layout,{{responsive:true,scrollZoom:true,displaylogo:false}})}}
tf.addEventListener('change',refreshSymbols);ticker.addEventListener('change',render);checks.forEach(x=>x.addEventListener('change',render));document.getElementById('recent').onclick=()=>{{rangeMode='recent';render()}};document.getElementById('all').onclick=()=>{{rangeMode='all';render()}};refreshSymbols();
</script></body></html>"""


def main() -> None:
    payload = build_payload()
    OUTPUT.write_text(render_html(payload), encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
