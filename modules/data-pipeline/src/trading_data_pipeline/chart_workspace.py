"""Multi-symbol, multi-timeframe, multi-study workspace for chart HTML views."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from html import escape


SCHEMA_VERSION = "trading-chart-workspace/v1"


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    id: str
    ticker: str
    timeframe: str
    study_id: str
    study_label: str
    html: str
    label: str = ""

    def as_payload(self) -> dict[str, str]:
        return {
            "id": self.id,
            "ticker": self.ticker.upper(),
            "timeframe": self.timeframe,
            "studyId": self.study_id,
            "studyLabel": self.study_label,
            "label": self.label or f"{self.ticker.upper()} · {self.timeframe} · {self.study_label}",
            "htmlBase64": base64.b64encode(self.html.encode("utf-8")).decode("ascii"),
        }


def render_chart_workspace_html(views: list[WorkspaceView], *, title: str = "Trading research workspace") -> str:
    if not views:
        raise ValueError("A chart workspace requires at least one view")
    ids = [view.id for view in views]
    if len(ids) != len(set(ids)):
        raise ValueError("Chart workspace view ids must be unique")
    combinations = [(view.ticker.upper(), view.timeframe, view.study_id) for view in views]
    if len(combinations) != len(set(combinations)):
        raise ValueError("Chart workspace symbol/timeframe/study combinations must be unique")
    encoded = json.dumps([view.as_payload() for view in views], separators=(",", ":")).replace("<", "\\u003c")
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#09111e; --panel:#132138; --line:#29415f; --text:#e8f0fc; --muted:#9eb1cc; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:linear-gradient(145deg,#12233b,var(--bg) 52%); color:var(--text); font:14px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .shell {{ height:100vh; display:grid; grid-template-rows:auto 1fr; gap:10px; padding:12px; }}
    .toolbar {{ display:flex; gap:12px; align-items:end; flex-wrap:wrap; padding:12px 14px; background:rgba(19,33,56,.94); border:1px solid var(--line); border-radius:12px; }}
    .brand {{ margin-right:auto; min-width:260px; }} .brand h1 {{ font:700 20px system-ui; margin:0 0 4px; }} .brand div,.status {{ color:var(--muted); font-size:12px; }}
    label {{ color:var(--muted); font-size:12px; }} select,button {{ display:block; margin-top:5px; min-width:150px; padding:8px 10px; color:var(--text); background:#0b1728; border:1px solid #365777; border-radius:7px; font:inherit; }}
    button {{ min-width:auto; cursor:pointer; }} button:hover {{ border-color:#59bdd4; }}
    .nav {{ display:flex; gap:6px; }}
    .frame-wrap {{ min-height:0; overflow:hidden; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
    iframe {{ width:100%; height:100%; border:0; background:#0e1726; }}
    @media(max-width:800px) {{ .shell{{height:auto;min-height:100vh}} .frame-wrap{{height:900px}} .brand{{width:100%}} }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="toolbar">
      <div class="brand"><h1>{safe_title}</h1><div>Switch symbols, timeframes, and studies without leaving the visualizer.</div></div>
      <label>Symbol<select id="symbol"></select></label>
      <label>Timeframe<select id="timeframe"></select></label>
      <label>Study<select id="study"></select></label>
      <div class="nav"><button id="previous" title="Previous view">←</button><button id="next" title="Next view">→</button></div>
      <div id="status" class="status"></div>
    </header>
    <main class="frame-wrap"><iframe id="viewer" title="Selected trading chart"></iframe></main>
  </div>
  <script>
    const views = {encoded};
    const symbol = document.getElementById("symbol");
    const timeframe = document.getElementById("timeframe");
    const study = document.getElementById("study");
    const frame = document.getElementById("viewer");
    const status = document.getElementById("status");
    const unique = (values) => [...new Set(values)];
    let selectedId = views[0].id;

    function replaceOptions(select, values, labels, preferred) {{
      const prior = preferred || select.value;
      select.replaceChildren();
      values.forEach((value, index) => {{
        const option = document.createElement("option");
        option.value = value;
        option.textContent = labels ? labels[index] : value;
        select.appendChild(option);
      }});
      select.value = values.includes(prior) ? prior : values[0];
    }}

    function refreshSymbolOptions() {{
      replaceOptions(symbol, unique(views.map((view) => view.ticker)));
      refreshTimeframeOptions();
    }}

    function refreshTimeframeOptions() {{
      const candidates = views.filter((view) => view.ticker === symbol.value);
      replaceOptions(timeframe, unique(candidates.map((view) => view.timeframe)));
      refreshStudyOptions();
    }}

    function refreshStudyOptions() {{
      const candidates = views.filter((view) => view.ticker === symbol.value && view.timeframe === timeframe.value);
      const studies = unique(candidates.map((view) => view.studyId));
      const labels = studies.map((id) => candidates.find((view) => view.studyId === id).studyLabel);
      replaceOptions(study, studies, labels);
      loadSelected();
    }}

    function selectedView() {{
      return views.find((view) => view.ticker === symbol.value && view.timeframe === timeframe.value && view.studyId === study.value) || views[0];
    }}

    function decodeHtml(encodedHtml) {{
      const bytes = Uint8Array.from(atob(encodedHtml), (character) => character.charCodeAt(0));
      return new TextDecoder().decode(bytes);
    }}

    function loadSelected() {{
      const view = selectedView();
      selectedId = view.id;
      frame.srcdoc = decodeHtml(view.htmlBase64);
      status.textContent = `${{views.indexOf(view)+1}}/${{views.length}} · ${{view.label}}`;
    }}

    function move(offset) {{
      const index = views.findIndex((view) => view.id === selectedId);
      const target = views[(index + offset + views.length) % views.length];
      symbol.value = target.ticker;
      const timeframes = unique(views.filter((view) => view.ticker === symbol.value).map((view) => view.timeframe));
      replaceOptions(timeframe, timeframes, null, target.timeframe);
      timeframe.value = target.timeframe;
      const candidates = views.filter((view) => view.ticker === symbol.value && view.timeframe === timeframe.value);
      const studies = unique(candidates.map((view) => view.studyId));
      replaceOptions(study, studies, studies.map((id) => candidates.find((view) => view.studyId === id).studyLabel), target.studyId);
      study.value = target.studyId;
      loadSelected();
    }}

    symbol.addEventListener("change", refreshTimeframeOptions);
    timeframe.addEventListener("change", refreshStudyOptions);
    study.addEventListener("change", loadSelected);
    document.getElementById("previous").addEventListener("click", () => move(-1));
    document.getElementById("next").addEventListener("click", () => move(1));
    window.addEventListener("keydown", (event) => {{
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "ArrowLeft") move(-1);
      if (event.key === "ArrowRight") move(1);
    }});
    refreshSymbolOptions();
  </script>
</body>
</html>"""


__all__ = ["SCHEMA_VERSION", "WorkspaceView", "render_chart_workspace_html"]
