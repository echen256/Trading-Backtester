"""Create one searchable, keyboard-navigable hub for strategy chart artifacts."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Sequence


def build_chart_hub(summaries: Sequence[tuple[str, Path]], output: Path) -> Path:
    """Build a local iframe hub from one or more scanner-batch summary files."""
    events: list[dict[str, object]] = []
    for label, summary_path in summaries:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        for record in payload["records"]:
            chart = summary_path.parent / "runs" / str(record["ticker"]) / f"{record['entry_date']}.html"
            events.append({**record, "timeframe": label, "href": os.path.relpath(chart, output.parent)})
    events.sort(key=lambda item: (str(item["timeframe"]), str(item["ticker"]), str(item["entry_date"])))
    serialized = json.dumps(events).replace("</", "<\\/")
    labels = sorted({str(item["timeframe"]) for item in events})
    options = "".join(f'<option value="{html.escape(label)}">{html.escape(label)}</option>' for label in labels)
    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Scanner strategy chart hub</title>
<style>
body{margin:0;background:#10151f;color:#e9eef6;font:14px system-ui,sans-serif} header{padding:12px 16px;border-bottom:1px solid #263244;display:flex;gap:10px;align-items:center;position:sticky;top:0;background:#10151f;z-index:3} select,input,button,a{background:#192334;color:#e9eef6;border:1px solid #34435a;border-radius:5px;padding:8px} input{min-width:220px} button{cursor:pointer} #count{color:#9fb0c7} main{display:grid;grid-template-columns:310px 1fr;height:calc(100vh - 62px)} #list{overflow:auto;border-right:1px solid #263244} .event{display:block;color:inherit;text-decoration:none;padding:10px 12px;border-bottom:1px solid #202b3b} .event:hover,.event.active{background:#233651} .meta{color:#aab8ca;font-size:12px;margin-top:3px} iframe{border:0;width:100%;height:100%;background:#fff}
</style></head><body>
<header><strong>Scanner strategy chart hub</strong><select id="timeframe"><option value="all">All timeframes</option>__OPTIONS__</select><input id="search" placeholder="Filter ticker or entry date"><button id="previous">← Prev</button><button id="next">Next →</button><span id="count"></span><a id="open" target="_blank" rel="noopener">Open chart</a></header>
<main><nav id="list"></nav><iframe id="chart" title="Selected strategy chart"></iframe></main>
<script>const events=__EVENTS__;let visible=[],current=0;const list=document.querySelector('#list'),frame=document.querySelector('#chart'),openLink=document.querySelector('#open'),count=document.querySelector('#count');
function redraw(selectFirst=true){const q=document.querySelector('#search').value.trim().toLowerCase(),f=document.querySelector('#timeframe').value;visible=events.filter(x=>(f==='all'||x.timeframe===f)&&(`${x.ticker} ${x.entry_date} ${x.status}`.toLowerCase().includes(q)));if(selectFirst||current>=visible.length)current=0;count.textContent=`${visible.length} / ${events.length} charts`;list.innerHTML=visible.map((x,i)=>`<a class="event ${i===current?'active':''}" href="#" data-index="${i}"><strong>${x.timeframe} · ${x.ticker}</strong><div class="meta">${x.entry_date} · ${x.status} · ${Number(x.total_return_pct).toFixed(2)}%</div></a>`).join('');document.querySelectorAll('.event').forEach(a=>a.onclick=e=>{e.preventDefault();current=Number(a.dataset.index);show();});show();}
function show(){const x=visible[current];if(!x){frame.removeAttribute('src');openLink.removeAttribute('href');return;}frame.src=x.href;openLink.href=x.href;document.querySelectorAll('.event').forEach((a,i)=>a.classList.toggle('active',i===current));document.querySelector('.event.active')?.scrollIntoView({block:'nearest'});}
document.querySelector('#search').oninput=()=>redraw();document.querySelector('#timeframe').onchange=()=>redraw();document.querySelector('#previous').onclick=()=>{if(visible.length){current=(current-1+visible.length)%visible.length;show();}};document.querySelector('#next').onclick=()=>{if(visible.length){current=(current+1)%visible.length;show();}};document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;if(e.key==='ArrowLeft')document.querySelector('#previous').click();if(e.key==='ArrowRight')document.querySelector('#next').click();});redraw();
</script></body></html>""".replace("__OPTIONS__", options).replace("__EVENTS__", serialized)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", nargs=2, action="append", metavar=("LABEL", "PATH"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = build_chart_hub([(label, Path(path)) for label, path in args.summary], args.output)
    print(f"Wrote {result}")


if __name__ == "__main__":  # pragma: no cover
    main()
