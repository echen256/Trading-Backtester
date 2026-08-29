"""Adapt MACD-shape study events to the universal chart annotation contract."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SRC = REPO_ROOT / "modules" / "data-pipeline" / "src"
if str(PIPELINE_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SRC))

from trading_data_pipeline.chart_annotations import SCHEMA_VERSION, normalize_annotation_document  # noqa: E402
from trading_data_pipeline.chart_workspace import WorkspaceView, render_chart_workspace_html  # noqa: E402
from trading_data_pipeline.visualize import make_chart_payload, render_chart_html  # noqa: E402
from trading_analysis.dashboard import DatasetImporter, ImportOptions, StudyArtifactWriter  # noqa: E402


RUN_ROOT = REPO_ROOT / "modules" / "analysis" / "strategies" / "runs"
EVENTS_CSV = REPO_ROOT / "reports" / "macd_histogram_shape_events.csv"
SOURCE_DIRS = {
    "Weekly": RUN_ROOT / "scanner-weekly-fixed-core" / "runs",
    "3-day": RUN_ROOT / "scanner-3d-fixed-core" / "runs",
}
TIMEFRAME_MINUTES = {"Weekly": 10080, "3-day": 4320}
HORIZON = {"Weekly": 4, "3-day": 5}


def choose_run(ticker: str, timeframe: str) -> dict[str, object]:
    candidates: list[tuple[tuple[int, str], dict[str, object]]] = []
    for path in (SOURCE_DIRS[timeframe] / ticker.upper()).glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars = payload.get("bars") or []
        if bars:
            candidates.append(((len(bars), str(bars[-1].get("time") or "")), payload))
    if not candidates:
        raise FileNotFoundError(f"No {timeframe} scanner run found for {ticker.upper()}")
    return max(candidates, key=lambda item: item[0])[1]


def group_for(event: pd.Series) -> str:
    if event.event == "early_rising_blue":
        return "early"
    if event.slope_quartile == "Q1 weak":
        return "bear_q1"
    if event.slope_quartile == "Q4 steep":
        return "bear_q4"
    return "bear_mid"


def build_annotations(ticker: str, timeframe: str, bars: list[dict[str, object]]) -> dict[str, object]:
    events = pd.read_csv(EVENTS_CSV)
    events = events[(events.ticker == ticker.upper()) & (events.timeframe == timeframe)]
    horizon = HORIZON[timeframe]
    index_by_date = {str(bar["time"]): index for index, bar in enumerate(bars)}

    groups = [
        {"id": "early", "label": "Early rising-blue", "color": "#43d5ff", "visible": True},
        {"id": "bear_q1", "label": "Bear cross Q1 weak", "color": "#ff5f6d", "visible": True},
        {"id": "bear_mid", "label": "Bear cross Q2–Q3", "color": "#f7c948", "visible": False},
        {"id": "bear_q4", "label": "Bear cross Q4 steep", "color": "#b68cff", "visible": True},
    ]
    histogram_points: list[dict[str, object]] = []
    previous: float | None = None
    for bar in bars:
        value = bar.get("histogram")
        numeric = float(value) if value is not None else None
        if numeric is None:
            color = "#52627a"
        elif numeric >= 0:
            color = "#42c7ef" if previous is not None and numeric > previous else "#256f8d"
        else:
            color = "#ff6574" if previous is not None and numeric < previous else "#8e3540"
        histogram_points.append({"time": bar["time"], "value": numeric, "color": color})
        previous = numeric

    panels = [
        {
            "id": "adaptive_macd",
            "label": "Fisher adaptive-MACD 10/20/9",
            "height": 300,
            "visible": True,
            "zero_line": True,
            "series": [
                {"id": "histogram", "name": "Histogram", "type": "histogram", "points": histogram_points},
                {
                    "id": "macd",
                    "name": "Adaptive MACD",
                    "type": "line",
                    "color": "#4dc3ff",
                    "points": [{"time": bar["time"], "value": bar.get("adaptive_macd")} for bar in bars],
                },
                {
                    "id": "signal",
                    "name": "Signal",
                    "type": "line",
                    "color": "#f7c948",
                    "points": [{"time": bar["time"], "value": bar.get("signal")} for bar in bars],
                },
            ],
        }
    ]
    points: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    for row_index, event in events.iterrows():
        index = index_by_date.get(str(event.date))
        if index is None:
            continue
        group = group_for(event)
        is_early = event.event == "early_rising_blue"
        marker = "circle" if is_early else "triangle-down"
        label = "Blue 3" if is_early else str(event.slope_quartile)
        metadata = {
            "event": str(event.event),
            "normalized_slope": round(float(event.slope_norm), 4),
            "slope_quartile": str(event.slope_quartile),
            "line_shape": str(event.line_shape),
            "both_lines_above_zero": bool(event.both_above_zero),
            f"forward_{horizon}_bar_return_pct": round(float(event[f"return_{horizon}"]) * 100, 3)
            if pd.notna(event[f"return_{horizon}"])
            else None,
        }
        base_id = f"{ticker.lower()}-{timeframe.lower()}-{row_index}"
        points.extend([
            {
                "id": f"{base_id}-price",
                "group": group,
                "time": bars[index]["time"],
                "pane": "price",
                "value": bars[index]["close"],
                "label": label,
                "role": "checkpoint" if is_early else "crossover",
                "marker": marker,
                "metadata": metadata,
            },
            {
                "id": f"{base_id}-macd",
                "group": group,
                "time": bars[index]["time"],
                "pane": "adaptive_macd",
                "value": bars[index]["adaptive_macd"],
                "label": "",
                "role": "checkpoint" if is_early else "crossover",
                "marker": "diamond",
                "size": 8,
                "metadata": metadata,
            },
        ])
        end_index = index + horizon
        if not is_early and end_index < len(bars):
            links.append({
                "id": f"{base_id}-outcome",
                "group": group,
                "pane": "price",
                "start_time": bars[index]["time"],
                "end_time": bars[end_index]["time"],
                "start_value": bars[index]["close"],
                "end_value": bars[end_index]["close"],
                "label": f"{horizon}-bar evaluation window",
                "metadata": metadata,
            })
    return normalize_annotation_document({
        "schema_version": SCHEMA_VERSION,
        "groups": groups,
        "panels": panels,
        "points": points,
        "links": links,
        "spans": [],
    })


def bars_as_rows(bars: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "timestamp": bar["time"],
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar.get("volume"),
        }
        for bar in bars
    ]


def study_presets(annotations: dict[str, object]) -> list[tuple[str, str, dict[str, object]]]:
    presets = [
        ("overview", "MACD shape overview", {"early", "bear_q1", "bear_q4"}),
        ("early_momentum", "Early rising momentum", {"early"}),
        ("bear_slope", "Bear crossover slope", {"bear_q1", "bear_mid", "bear_q4"}),
    ]
    documents: list[tuple[str, str, dict[str, object]]] = []
    for study_id, label, visible_groups in presets:
        document = copy.deepcopy(annotations)
        for group in document["groups"]:
            group["visible"] = group["id"] in visible_groups
        documents.append((study_id, label, document))
    return documents


def build_workspace(ticker: str) -> str:
    views: list[WorkspaceView] = []
    for timeframe in SOURCE_DIRS:
        bars = choose_run(ticker, timeframe)["bars"]
        rows = bars_as_rows(bars)
        annotations = build_annotations(ticker, timeframe, bars)
        for study_id, study_label, study_annotations in study_presets(annotations):
            payload = make_chart_payload(
                ticker=ticker,
                timeframe_minutes=TIMEFRAME_MINUTES[timeframe],
                rows=rows,
                source_label=f"local scanner run · {timeframe} · {study_label}",
                annotations=study_annotations,
            )
            views.append(
                WorkspaceView(
                    id=f"{ticker.lower()}-{timeframe.lower()}-{study_id}",
                    ticker=ticker,
                    timeframe=timeframe,
                    study_id=study_id,
                    study_label=study_label,
                    html=render_chart_html(payload),
                )
            )
    return render_chart_workspace_html(views, title=f"{ticker} · MACD shape research")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="MU")
    parser.add_argument("--timeframe", choices=tuple(SOURCE_DIRS), default="3-day")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--annotations-output", type=Path)
    parser.add_argument("--workspace-output", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ticker = args.ticker.upper()
    run = choose_run(ticker, args.timeframe)
    bars = run["bars"]
    annotations = build_annotations(ticker, args.timeframe, bars)
    rows = bars_as_rows(bars)
    payload = make_chart_payload(
        ticker=ticker,
        timeframe_minutes=TIMEFRAME_MINUTES[args.timeframe],
        rows=rows,
        source_label=f"local scanner run · {args.timeframe}",
        annotations=annotations,
    )
    output = args.output or REPO_ROOT / "reports" / f"{ticker.lower()}_{args.timeframe.lower()}_macd_shape_universal.html"
    annotation_output = args.annotations_output or REPO_ROOT / "reports" / f"{ticker.lower()}_{args.timeframe.lower()}_macd_shape_annotations.json"
    workspace_output = args.workspace_output or REPO_ROOT / "reports" / f"{ticker.lower()}_macd_shape_workspace.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    annotation_output.parent.mkdir(parents=True, exist_ok=True)
    workspace_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_chart_html(payload), encoding="utf-8")
    annotation_output.write_text(json.dumps(annotations, indent=2) + "\n", encoding="utf-8")
    workspace_output.write_text(build_workspace(ticker), encoding="utf-8")
    dataset = DatasetImporter().import_rows(
        rows,
        source_label=f"scanner-run://{ticker}/{args.timeframe}",
        options=ImportOptions(
            symbol=ticker,
            asset_class="stock",
            venue="scanner-archive",
            provider="scanner-run",
            interval_seconds=TIMEFRAME_MINUTES[args.timeframe] * 60,
            calendar="XNYS",
        ),
    )
    dashboard_manifest = StudyArtifactWriter().build_manifest(
        study_id="macd-histogram-shape",
        study_name="MACD Histogram Shape",
        version="2.0",
        description="Adaptive-MACD histogram shape checkpoints and forward evaluation windows.",
        generator="modules/analysis/scripts/export_macd_shape_universal_chart.py",
        parameters={"ticker": ticker, "timeframe": args.timeframe},
        views=[{
            "id": f"{ticker.lower()}-{args.timeframe.lower()}-overview",
            "label": f"{ticker} · {args.timeframe} overview",
            "dataset_id": dataset["id"],
            "chart": annotations,
        }],
        metrics=[
            {"label": "Chart events", "value": len(annotations["points"])},
            {"label": "Evaluation paths", "value": len(annotations["links"])},
        ],
        methodology=(
            "Events are computed by the MACD histogram-shape study. The dashboard artifact references "
            "the exact normalized scanner bars used by this run and preserves all v1 annotation metadata."
        ),
    )
    dashboard_output = StudyArtifactWriter().publish(dashboard_manifest)
    print(f"Wrote {output}")
    print(f"Wrote {annotation_output}")
    print(f"Wrote {workspace_output}")
    print(f"Published dashboard study {dashboard_output}")


if __name__ == "__main__":
    main()
