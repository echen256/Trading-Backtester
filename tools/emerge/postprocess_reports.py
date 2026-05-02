#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys


def patch_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text

    updated = re.sub(
        r"(\s*currentGraph = JSON\.parse\(JSON\.stringify\(graphData\[graphType\]\['graph'\]\)\)\n)(?!\s*if \(currentGraph\.links === undefined && currentGraph\.edges !== undefined\))",
        (
            r"\1"
            "    if (currentGraph.links === undefined && currentGraph.edges !== undefined) {\n"
            "        currentGraph.links = currentGraph.edges\n"
            "    }\n"
        ),
        updated,
        count=1,
    )

    updated = updated.replace(
        "    currentGraph.links.forEach(function(d) {\n",
        "    (currentGraph.links || []).forEach(function(d) {\n",
    )
    updated = updated.replace(
        "    currentGraph.links.forEach((d) => {\n",
        "    (currentGraph.links || []).forEach((d) => {\n",
    )
    updated = updated.replace(
        "    .links(currentGraph.links);",
        "    .links(currentGraph.links || []);",
    )

    if updated == text:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: postprocess_reports.py <reports-emerge-dir>", file=sys.stderr)
        return 1

    root = Path(sys.argv[1])
    if not root.exists():
        print(f"Missing directory: {root}", file=sys.stderr)
        return 1

    targets = sorted(root.glob("*/html/resources/js/emerge_*.js"))
    patched = 0
    for path in targets:
        if patch_file(path):
            patched += 1

    print(f"Patched {patched} generated Emerge JS file(s) under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
