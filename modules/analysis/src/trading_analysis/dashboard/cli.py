"""CLI for importing data, publishing studies, and serving the dashboard."""

from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path
from typing import Sequence

from .api import serve_dashboard
from .artifacts import StudyArtifactWriter
from .catalog import DatasetCatalog
from .config import DEFAULT_WEB_ROOT
from .ingestion import DatasetImporter, ImportOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, help="Override dashboard artifact/catalog directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Serve the dashboard API and built React app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--web-root", type=Path, default=DEFAULT_WEB_ROOT)
    serve.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")

    importer = subparsers.add_parser("import", help="Normalize and catalog one OHLCV file")
    importer.add_argument("path", type=Path)
    importer.add_argument("--symbol")
    importer.add_argument("--asset-class", choices=("stock", "crypto", "index", "option", "forex", "unknown"))
    importer.add_argument("--venue")
    importer.add_argument("--base-asset")
    importer.add_argument("--quote-asset")
    importer.add_argument("--provider")
    importer.add_argument("--interval-seconds", type=int)
    importer.add_argument("--timezone", default="UTC")
    importer.add_argument("--calendar")
    importer.add_argument("--adjustment")

    reindex = subparsers.add_parser("reindex", help="Rebuild the study catalog from artifact manifests")

    publish = subparsers.add_parser("publish-annotations", help="Publish a v1/v2 annotation file as a study")
    publish.add_argument("annotations", type=Path)
    publish.add_argument("--dataset-id", required=True)
    publish.add_argument("--study-id", required=True)
    publish.add_argument("--name", required=True)
    publish.add_argument("--version", default="1.0")
    publish.add_argument("--view-label", default="Overview")
    report = subparsers.add_parser("publish-report", help="Publish existing report files as a dashboard study")
    report.add_argument("--study-id", required=True)
    report.add_argument("--name", required=True)
    report.add_argument("--version", default="1.0")
    report.add_argument("--generator", default="manual")
    report.add_argument("--description", default="")
    report.add_argument("--file", nargs=2, action="append", metavar=("NAME", "PATH"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    catalog = DatasetCatalog(args.artifact_root)
    if args.command == "serve":
        if args.open:
            webbrowser.open(f"http://{args.host}:{args.port}")
        serve_dashboard(host=args.host, port=args.port, catalog=catalog, web_root=args.web_root)
        return
    if args.command == "import":
        options = ImportOptions(
            symbol=args.symbol,
            asset_class=args.asset_class,
            venue=args.venue,
            base_asset=args.base_asset,
            quote_asset=args.quote_asset,
            provider=args.provider,
            interval_seconds=args.interval_seconds,
            timezone=args.timezone,
            calendar=args.calendar,
            adjustment=args.adjustment,
        )
        metadata = DatasetImporter(catalog).import_file(args.path, options)
        print(json.dumps(metadata, indent=2))
        return
    if args.command == "reindex":
        print(f"Indexed {catalog.rebuild_study_index()} study runs")
        return
    if args.command == "publish-annotations":
        annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
        path = StudyArtifactWriter(catalog).publish_annotation_study(
            study_id=args.study_id,
            study_name=args.name,
            version=args.version,
            dataset_id=args.dataset_id,
            annotations=annotations,
            view_label=args.view_label,
            generator="trading-analysis-dashboard publish-annotations",
        )
        print(f"Published {path}")
        return
    if args.command == "publish-report":
        path = StudyArtifactWriter(catalog).publish_report_study(
            study_id=args.study_id,
            study_name=args.name,
            version=args.version,
            generator=args.generator,
            description=args.description,
            files={name: Path(value) for name, value in args.file},
        )
        print(f"Published {path}")
        return
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
