#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import html
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}
FILE_FILL = "#f4f1ea"
DIR_FILL = "#d9e6f2"
ACTIVE_STROKE = "#1f4b73"

IMPORT_RE = re.compile(
    r"""(?mx)
    ^\s*import\s+[^'"]*?from\s+['"](?P<from>[^'"]+)['"] |
    ^\s*import\s+['"](?P<side>[^'"]+)['"] |
    ^\s*export\s+[^'"]*?from\s+['"](?P<export>[^'"]+)['"] |
    require\(\s*['"](?P<require>[^'"]+)['"]\s*\)
    """
)


@dataclass(slots=True)
class FileNode:
    rel_path: str
    abs_path: Path
    is_dir: bool
    parent: str | None
    children: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SymbolRef:
    kind: str
    target: str


@dataclass(slots=True)
class FunctionInfo:
    id: str
    file_rel: str
    name: str
    display_name: str
    class_name: str | None
    lineno: int
    end_lineno: int
    call_refs: list[str] = field(default_factory=list)


class PythonFunctionCollector(ast.NodeVisitor):
    def __init__(
        self,
        module_rel: str,
        import_aliases: dict[str, SymbolRef],
        seed_aliases: dict[str, str] | None = None,
    ) -> None:
        self.module_rel = module_rel
        self.import_aliases = import_aliases
        self.functions: dict[str, FunctionInfo] = {}
        self.local_aliases: dict[str, str] = dict(seed_aliases or {})
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Import(self, node: ast.Import) -> None:
        if self.function_stack:
            self.generic_visit(node)
            return
        for alias in node.names:
            bound_name = alias.asname or alias.name.split(".")[0]
            ref = self.import_aliases.get(bound_name)
            if ref:
                self.local_aliases[bound_name] = ref.target

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.function_stack:
            self.generic_visit(node)
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            bound_name = alias.asname or alias.name
            ref = self.import_aliases.get(bound_name)
            if ref:
                self.local_aliases[bound_name] = ref.target

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        class_name = self.class_stack[-1] if self.class_stack else None
        local_name = node.name
        display_name = f"{class_name}.{local_name}" if class_name else local_name
        function_id = f"{self.module_rel}::{display_name}"
        end_lineno = getattr(node, "end_lineno", node.lineno)
        info = FunctionInfo(
            id=function_id,
            file_rel=self.module_rel,
            name=local_name,
            display_name=display_name,
            class_name=class_name,
            lineno=node.lineno,
            end_lineno=end_lineno,
        )
        self.functions[function_id] = info
        previous = self.local_aliases.copy()
        self.function_stack.append(function_id)
        if class_name:
            self.local_aliases["self"] = class_name
            self.local_aliases["cls"] = class_name
        self.local_aliases[local_name] = function_id
        self.generic_visit(node)
        self.function_stack.pop()
        self.local_aliases = previous

    def visit_Call(self, node: ast.Call) -> None:
        if self.function_stack:
            target = self._resolve_call(node.func)
            if target:
                self.functions[self.function_stack[-1]].call_refs.append(target)
        self.generic_visit(node)

    def _resolve_call(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return self.local_aliases.get(func.id)
        if isinstance(func, ast.Attribute):
            owner = self._resolve_call(func.value)
            if owner:
                if owner.startswith(f"{self.module_rel}::"):
                    return f"{owner.rsplit('::', 1)[0]}::{func.attr}"
                if "::" not in owner and "/" in owner:
                    return f"{owner}::{func.attr}"
                if owner in self.class_stack:
                    return f"{self.module_rel}::{owner}.{func.attr}"
            if isinstance(func.value, ast.Name):
                instance_ref = self.local_aliases.get(func.value.id)
                if instance_ref in self.class_stack:
                    return f"{self.module_rel}::{instance_ref}.{func.attr}"
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a self-contained HTML architecture diagram for a module. "
            "The report includes nested, collapsible graphs so you can inspect "
            "subpackages without rendering the full dependency graph at once."
        )
    )
    parser.add_argument(
        "module",
        help="Module or directory to analyze, relative to the repo root or absolute.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to scan for internal imports. Defaults to current directory.",
    )
    parser.add_argument(
        "--output",
        help="Output HTML file. Defaults to <module-name>-architecture.html in the module directory.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=400,
        help="Skip report generation if the selected module exceeds this many source files.",
    )
    return parser.parse_args()


def normalize_rel(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return "." if rel == "" else rel


def discover_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") and part not in {".", ".."} for part in path.relative_to(root).parts):
            continue
        if "__pycache__" in path.parts or "node_modules" in path.parts or "dist" in path.parts or "build" in path.parts:
            continue
        if path.suffix in SUPPORTED_EXTENSIONS:
            files.append(path)
    return sorted(files)


def build_file_index(repo_root: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for file_path in discover_source_files(repo_root):
        rel = file_path.relative_to(repo_root).with_suffix("").as_posix()
        mapping[rel] = file_path
    return mapping


def parse_python_imports(path: Path, module_rel_no_suffix: str) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(
                    build_python_import_target(module_rel_no_suffix, node.level, module, alias.name)
                )
    return imports


def build_python_import_target(
    module_rel_no_suffix: str, level: int, module: str, imported_name: str
) -> str:
    current_parts = Path(module_rel_no_suffix).parts
    base_parts = list(current_parts[:-1])
    if level > 0:
        trim = max(len(base_parts) - level + 1, 0)
        base_parts = base_parts[:trim]
    target = ".".join(part for part in base_parts if part)
    if module:
        pieces = [piece for piece in [target, module] if piece]
    elif imported_name != "*":
        pieces = [piece for piece in [target, imported_name] if piece]
    else:
        pieces = [piece for piece in [target] if piece]
    return ".".join(pieces)


def parse_js_imports(path: Path) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    imports: list[str] = []
    for match in IMPORT_RE.finditer(content):
        for group in ("from", "side", "export", "require"):
            value = match.group(group)
            if value:
                imports.append(value)
                break
    return imports


def parse_python_import_aliases(
    path: Path,
    module_rel_no_suffix: str,
    repo_root: Path,
    file_index: dict[str, Path],
) -> dict[str, SymbolRef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}

    aliases: dict[str, SymbolRef] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve_internal_import(path, alias.name, repo_root, file_index)
                if not target:
                    continue
                bound_name = alias.asname or alias.name.split(".")[0]
                aliases[bound_name] = SymbolRef(kind="module", target=target)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            raw_base = build_python_import_target(module_rel_no_suffix, node.level, module, "*")
            target_file = resolve_internal_import(path, raw_base, repo_root, file_index)
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound_name = alias.asname or alias.name
                if target_file:
                    aliases[bound_name] = SymbolRef(
                        kind="symbol",
                        target=f"{target_file}::{alias.name}",
                    )
    return aliases


def scan_python_local_aliases(tree: ast.AST, module_rel: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            aliases[node.name] = f"{module_rel}::{node.name}"
        elif isinstance(node, ast.ClassDef):
            aliases[node.name] = node.name
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    aliases[child.name] = f"{module_rel}::{node.name}.{child.name}"
    return aliases


def resolve_internal_import(
    importer: Path,
    raw_import: str,
    repo_root: Path,
    file_index: dict[str, Path],
) -> str | None:
    if raw_import.startswith("."):
        base = (importer.parent / raw_import).resolve()
        candidates = module_candidates(base, repo_root)
        for candidate in candidates:
            rel = candidate.relative_to(repo_root).with_suffix("").as_posix()
            if rel in file_index:
                return rel
        return None

    dotted = raw_import.replace(".", "/")
    for candidate in (repo_root / dotted, repo_root / "src" / dotted):
        for path in module_candidates(candidate, repo_root):
            rel = path.relative_to(repo_root).with_suffix("").as_posix()
            if rel in file_index:
                return rel

    suffix_matches = [
        key
        for key in file_index
        if key == dotted
        or key.endswith(f"/{dotted}")
        or key.endswith(f"/{dotted}/__init__")
        or key.endswith(f"/{dotted}/index")
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return None


def module_candidates(base: Path, repo_root: Path) -> Iterable[Path]:
    suffixes = [".py", ".ts", ".tsx", ".js", ".jsx"]
    for suffix in suffixes:
        candidate = Path(f"{base}{suffix}")
        if candidate.is_file() and is_within(candidate, repo_root):
            yield candidate
    for suffix in suffixes:
        candidate = base / f"index{suffix}"
        if candidate.is_file() and is_within(candidate, repo_root):
            yield candidate
    for suffix in suffixes:
        candidate = base / f"__init__{suffix}"
        if candidate.is_file() and is_within(candidate, repo_root):
            yield candidate


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def build_dependency_graph(
    module_root: Path,
    repo_root: Path,
    file_index: dict[str, Path],
) -> tuple[list[Path], dict[str, set[str]]]:
    files = [
        path
        for path in discover_source_files(module_root)
        if path.suffix in SUPPORTED_EXTENSIONS
    ]
    graph: dict[str, set[str]] = defaultdict(set)
    selected_paths = {
        path.relative_to(repo_root).with_suffix("").as_posix(): path.relative_to(module_root).with_suffix("").as_posix()
        for path in files
    }

    for path in files:
        repo_rel = path.relative_to(repo_root).with_suffix("").as_posix()
        module_rel = path.relative_to(module_root).with_suffix("").as_posix()
        raw_imports = (
            parse_python_imports(path, module_rel)
            if path.suffix == ".py"
            else parse_js_imports(path)
        )
        for raw_import in raw_imports:
            target = resolve_internal_import(path, raw_import, repo_root, file_index)
            if target and target in selected_paths and target != repo_rel:
                graph[module_rel].add(selected_paths[target])

    for rel in selected_paths.values():
        graph.setdefault(rel, set())
    return files, graph


def build_function_graph(
    module_root: Path,
    repo_root: Path,
    files: list[Path],
    file_index: dict[str, Path],
) -> tuple[dict[str, FunctionInfo], dict[str, set[str]], dict[str, list[str]]]:
    functions: dict[str, FunctionInfo] = {}
    functions_by_file: dict[str, list[str]] = defaultdict(list)
    pending_calls: dict[str, list[str]] = {}

    for path in files:
        if path.suffix != ".py":
            continue
        module_rel = path.relative_to(module_root).with_suffix("").as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        import_aliases = parse_python_import_aliases(path, module_rel, repo_root, file_index)
        seed_aliases = scan_python_local_aliases(tree, module_rel)
        collector = PythonFunctionCollector(module_rel, import_aliases, seed_aliases=seed_aliases)
        collector.visit(tree)
        functions.update(collector.functions)
        pending_calls.update({function_id: info.call_refs[:] for function_id, info in collector.functions.items()})
        for function_id in collector.functions:
            functions_by_file[module_rel].append(function_id)

    graph: dict[str, set[str]] = defaultdict(set)
    simple_name_index: dict[tuple[str, str], list[str]] = defaultdict(list)
    method_name_index: dict[tuple[str, str, str], str] = {}
    for function_id, info in functions.items():
        simple_name_index[(info.file_rel, info.name)].append(function_id)
        if info.class_name:
            method_name_index[(info.file_rel, info.class_name, info.name)] = function_id

    for function_id, refs in pending_calls.items():
        source = functions[function_id]
        for ref in refs:
            target_id = resolve_function_ref(ref, source, functions, simple_name_index, method_name_index)
            if target_id and target_id != function_id:
                graph[function_id].add(target_id)
        graph.setdefault(function_id, set())

    for file_rel in functions_by_file:
        functions_by_file[file_rel].sort(key=lambda function_id: (functions[function_id].lineno, functions[function_id].display_name))
    return functions, graph, functions_by_file


def resolve_function_ref(
    ref: str,
    source: FunctionInfo,
    functions: dict[str, FunctionInfo],
    simple_name_index: dict[tuple[str, str], list[str]],
    method_name_index: dict[tuple[str, str, str], str],
) -> str | None:
    if ref in functions:
        return ref

    if "::" not in ref:
        return None

    file_rel, raw_name = ref.split("::", 1)
    if "." in raw_name:
        class_name, method_name = raw_name.split(".", 1)
        return method_name_index.get((file_rel, class_name, method_name))

    same_file_candidates = simple_name_index.get((file_rel, raw_name), [])
    if len(same_file_candidates) == 1:
        return same_file_candidates[0]

    if file_rel == source.file_rel and source.class_name:
        method_id = method_name_index.get((file_rel, source.class_name, raw_name))
        if method_id:
            return method_id

    return None


def build_tree(module_root: Path) -> dict[str, FileNode]:
    nodes: dict[str, FileNode] = {}
    root_rel = "."
    nodes[root_rel] = FileNode(rel_path=root_rel, abs_path=module_root, is_dir=True, parent=None)

    for path in sorted(module_root.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(module_root).parts):
            continue
        if "__pycache__" in path.parts or "node_modules" in path.parts or "dist" in path.parts or "build" in path.parts:
            continue
        if path.is_file() and path.suffix not in SUPPORTED_EXTENSIONS:
            continue

        rel = normalize_rel(path, module_root)
        parent = normalize_rel(path.parent, module_root)
        nodes[rel] = FileNode(rel_path=rel, abs_path=path, is_dir=path.is_dir(), parent=parent)
        if parent in nodes:
            nodes[parent].children.append(rel)

    for node in nodes.values():
        node.children.sort()
    return nodes


def descendants(scope: str, nodes: dict[str, FileNode]) -> list[str]:
    result: list[str] = []
    stack = [scope]
    while stack:
        current = stack.pop()
        node = nodes[current]
        if not node.is_dir:
            result.append(current)
            continue
        for child in reversed(node.children):
            stack.append(child)
    return result


def immediate_bucket(scope: str, target: str) -> str:
    if scope == ".":
        return target.split("/", 1)[0]
    prefix = f"{scope}/"
    if not target.startswith(prefix):
        return target
    remainder = target[len(prefix) :]
    head = remainder.split("/", 1)[0]
    return f"{scope}/{head}"


def aggregate_scope_edges(
    scope: str,
    nodes: dict[str, FileNode],
    graph: dict[str, set[str]],
) -> tuple[list[str], dict[tuple[str, str], int]]:
    node = nodes[scope]
    visible_children = [child for child in node.children if child in nodes]
    edges: dict[tuple[str, str], int] = defaultdict(int)
    if not node.is_dir:
        for target in graph.get(scope, set()):
            edges[(scope, target)] += 1
        return visible_children, edges

    scoped_files = descendants(scope, nodes)
    scoped_set = set(scoped_files)
    for source in scoped_files:
        for target in graph.get(source, set()):
            if target not in scoped_set:
                continue
            src_bucket = immediate_bucket(scope, source)
            dst_bucket = immediate_bucket(scope, target)
            if src_bucket != dst_bucket:
                edges[(src_bucket, dst_bucket)] += 1
    return visible_children, edges


def svg_for_scope(scope: str, nodes: dict[str, FileNode], graph: dict[str, set[str]]) -> str:
    children, edges = aggregate_scope_edges(scope, nodes, graph)
    if not children:
        return "<p class='empty'>No supported source files below this scope.</p>"

    card_width = 220
    card_height = 64
    gap_x = 48
    gap_y = 48
    cols = max(1, min(3, math.ceil(math.sqrt(len(children)))))
    rows = math.ceil(len(children) / cols)
    width = 40 + cols * card_width + (cols - 1) * gap_x + 40
    height = 40 + rows * card_height + (rows - 1) * gap_y + 40

    positions: dict[str, tuple[int, int]] = {}
    for index, child in enumerate(children):
        row = index // cols
        col = index % cols
        x = 40 + col * (card_width + gap_x)
        y = 40 + row * (card_height + gap_y)
        positions[child] = (x, y)

    lines = [
        f"<svg viewBox='0 0 {width} {height}' class='graph' role='img' aria-label='{html.escape(scope)} dependency graph'>",
        "<defs>",
        "<marker id='arrow' markerWidth='10' markerHeight='10' refX='8' refY='3' orient='auto'>",
        "<path d='M0,0 L0,6 L9,3 z' fill='#5d6d7e'></path>",
        "</marker>",
        "</defs>",
    ]

    for (src, dst), weight in sorted(edges.items()):
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        start_x = x1 + card_width / 2
        start_y = y1 + card_height / 2
        end_x = x2 + card_width / 2
        end_y = y2 + card_height / 2
        dx = max(abs(end_x - start_x) / 2, 40)
        control_1 = start_x + dx if end_x >= start_x else start_x - dx
        control_2 = end_x - dx if end_x >= start_x else end_x + dx
        label_x = (start_x + end_x) / 2
        label_y = (start_y + end_y) / 2 - 8
        lines.append(
            "<path "
            f"d='M {start_x:.1f} {start_y:.1f} C {control_1:.1f} {start_y:.1f}, {control_2:.1f} {end_y:.1f}, {end_x:.1f} {end_y:.1f}' "
            "stroke='#85929e' stroke-width='2' fill='none' marker-end='url(#arrow)'></path>"
        )
        if weight > 1:
            lines.append(
                f"<text x='{label_x:.1f}' y='{label_y:.1f}' class='edge-label'>{weight}</text>"
            )

    for child in children:
        node = nodes[child]
        x, y = positions[child]
        fill = DIR_FILL if node.is_dir else FILE_FILL
        label = child.split("/")[-1]
        subtitle = "directory" if node.is_dir else node.abs_path.suffix.lstrip(".")
        lines.append(
            f"<rect x='{x}' y='{y}' width='{card_width}' height='{card_height}' rx='12' "
            f"fill='{fill}' stroke='{ACTIVE_STROKE}' stroke-width='2'></rect>"
        )
        lines.append(f"<text x='{x + 14}' y='{y + 28}' class='node-label'>{html.escape(label)}</text>")
        lines.append(f"<text x='{x + 14}' y='{y + 48}' class='node-subtitle'>{html.escape(subtitle)}</text>")

    lines.append("</svg>")
    return "".join(lines)


def svg_for_function_file(
    file_rel: str,
    functions: dict[str, FunctionInfo],
    function_graph: dict[str, set[str]],
    functions_by_file: dict[str, list[str]],
) -> str:
    function_ids = functions_by_file.get(file_rel, [])
    if not function_ids:
        return "<p class='empty'>Function mapping is currently available for Python files only.</p>"

    nodes_in_graph = function_ids[:24]
    if not nodes_in_graph:
        return "<p class='empty'>No functions or methods detected.</p>"

    card_width = 260
    card_height = 70
    gap_x = 36
    gap_y = 36
    cols = max(1, min(2, math.ceil(math.sqrt(len(nodes_in_graph)))))
    rows = math.ceil(len(nodes_in_graph) / cols)
    width = 40 + cols * card_width + (cols - 1) * gap_x + 40
    height = 40 + rows * card_height + (rows - 1) * gap_y + 40

    positions: dict[str, tuple[int, int]] = {}
    for index, function_id in enumerate(nodes_in_graph):
        row = index // cols
        col = index % cols
        positions[function_id] = (
            40 + col * (card_width + gap_x),
            40 + row * (card_height + gap_y),
        )

    lines = [
        f"<svg viewBox='0 0 {width} {height}' class='graph function-graph' role='img' aria-label='{html.escape(file_rel)} function graph'>",
        "<defs>",
        "<marker id='function-arrow' markerWidth='10' markerHeight='10' refX='8' refY='3' orient='auto'>",
        "<path d='M0,0 L0,6 L9,3 z' fill='#8a5b24'></path>",
        "</marker>",
        "</defs>",
    ]

    visible = set(nodes_in_graph)
    for source_id in nodes_in_graph:
        for target_id in sorted(function_graph.get(source_id, set())):
            if target_id not in visible:
                continue
            x1, y1 = positions[source_id]
            x2, y2 = positions[target_id]
            start_x = x1 + card_width / 2
            start_y = y1 + card_height / 2
            end_x = x2 + card_width / 2
            end_y = y2 + card_height / 2
            dx = max(abs(end_x - start_x) / 2, 40)
            control_1 = start_x + dx if end_x >= start_x else start_x - dx
            control_2 = end_x - dx if end_x >= start_x else end_x + dx
            lines.append(
                "<path "
                f"d='M {start_x:.1f} {start_y:.1f} C {control_1:.1f} {start_y:.1f}, {control_2:.1f} {end_y:.1f}, {end_x:.1f} {end_y:.1f}' "
                "stroke='#c08a4a' stroke-width='2' fill='none' marker-end='url(#function-arrow)'></path>"
            )

    for function_id in nodes_in_graph:
        info = functions[function_id]
        x, y = positions[function_id]
        lines.append(
            f"<rect x='{x}' y='{y}' width='{card_width}' height='{card_height}' rx='12' "
            "fill='#fff7eb' stroke='#8a5b24' stroke-width='2'></rect>"
        )
        lines.append(f"<text x='{x + 14}' y='{y + 28}' class='node-label'>{html.escape(info.display_name)}</text>")
        lines.append(
            f"<text x='{x + 14}' y='{y + 50}' class='node-subtitle'>lines {info.lineno}-{info.end_lineno}</text>"
        )

    lines.append("</svg>")
    if len(function_ids) > len(nodes_in_graph):
        lines.append(
            f"<p class='empty'>Showing first {len(nodes_in_graph)} functions by source order; "
            f"{len(function_ids) - len(nodes_in_graph)} additional functions omitted from the graph.</p>"
        )
    return "".join(lines)


def render_function_relationships(
    file_rel: str,
    functions: dict[str, FunctionInfo],
    function_graph: dict[str, set[str]],
    functions_by_file: dict[str, list[str]],
) -> str:
    function_ids = functions_by_file.get(file_rel, [])
    svg = svg_for_function_file(file_rel, functions, function_graph, functions_by_file)
    if not function_ids:
        return (
            "<div class='file-list'><strong>Function relationships</strong>"
            f"{svg}</div>"
        )

    items: list[str] = []
    for function_id in function_ids:
        info = functions[function_id]
        callees = sorted(function_graph.get(function_id, set()), key=lambda item: functions[item].display_name)
        if callees:
            mapped = ", ".join(
                html.escape(
                    f"{functions[target].file_rel}::{functions[target].display_name}"
                    if functions[target].file_rel != file_rel
                    else functions[target].display_name
                )
                for target in callees
            )
        else:
            mapped = "no resolved internal calls"
        items.append(
            f"<li><code>{html.escape(info.display_name)}</code> -> {mapped}</li>"
        )
    return (
        "<div class='file-list'><strong>Function relationships</strong>"
        f"{svg}<ul>{''.join(items)}</ul></div>"
    )


def scope_title(scope: str) -> str:
    return "Module root" if scope == "." else scope


def render_scope(
    scope: str,
    nodes: dict[str, FileNode],
    graph: dict[str, set[str]],
    functions: dict[str, FunctionInfo],
    function_graph: dict[str, set[str]],
    functions_by_file: dict[str, list[str]],
) -> str:
    node = nodes[scope]
    summary = html.escape(scope_title(scope))
    details_open = " open" if scope == "." else ""

    if node.is_dir:
        sections = [
            render_scope(child, nodes, graph, functions, function_graph, functions_by_file)
            for child in node.children
            if nodes[child].is_dir
        ]
        file_items = [
            f"<li><code>{html.escape(child)}</code></li>"
            for child in node.children
            if not nodes[child].is_dir
        ]
        files_html = (
            "<div class='file-list'><strong>Files in this scope</strong><ul>"
            + "".join(file_items)
            + "</ul></div>"
            if file_items
            else ""
        )
        nested_html = "".join(sections)
        svg = svg_for_scope(scope, nodes, graph)
        return (
            f"<details class='scope'{details_open}>"
            f"<summary>{summary}</summary>"
            "<div class='scope-body'>"
            f"{svg}"
            f"{files_html}"
            f"{nested_html}"
            "</div>"
            "</details>"
        )

    direct_imports = sorted(graph.get(scope, set()))
    imports_html = (
        "<ul>" + "".join(f"<li><code>{html.escape(dep)}</code></li>" for dep in direct_imports) + "</ul>"
        if direct_imports
        else "<p class='empty'>No internal imports detected.</p>"
    )
    function_html = render_function_relationships(scope, functions, function_graph, functions_by_file)
    return (
        f"<details class='scope'>"
        f"<summary>{summary}</summary>"
        "<div class='scope-body'>"
        "<div class='file-list'><strong>Direct internal imports</strong>"
        f"{imports_html}</div>"
        f"{function_html}"
        "</div>"
        "</details>"
    )


def render_tree(scope: str, nodes: dict[str, FileNode]) -> str:
    node = nodes[scope]
    label = html.escape(scope_title(scope) if scope == "." else scope.split("/")[-1])
    if not node.is_dir:
        return f"<li><code>{label}</code></li>"
    children = "".join(render_tree(child, nodes) for child in node.children)
    open_attr = " open" if scope == "." else ""
    return (
        f"<li><details{open_attr}><summary>{label}</summary>"
        f"<ul>{children}</ul>"
        "</details></li>"
    )


def build_report(
    module_root: Path,
    repo_root: Path,
    files: list[Path],
    graph: dict[str, set[str]],
    nodes: dict[str, FileNode],
    functions: dict[str, FunctionInfo],
    function_graph: dict[str, set[str]],
    functions_by_file: dict[str, list[str]],
) -> str:
    module_rel = module_root.relative_to(repo_root).as_posix()
    edge_count = sum(len(targets) for targets in graph.values())
    function_count = len(functions)
    function_edge_count = sum(len(targets) for targets in function_graph.values())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Architecture Diagram: {html.escape(module_rel)}</title>
  <style>
    :root {{
      --bg: #fcfaf6;
      --panel: #fffdf8;
      --ink: #182026;
      --muted: #5c6975;
      --accent: #1f4b73;
      --line: #d8d2c7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #f5efe5 0%, var(--bg) 120px);
      color: var(--ink);
    }}
    main {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 2rem;
    }}
    .meta {{
      color: var(--muted);
      margin-bottom: 24px;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 24px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(24, 32, 38, 0.06);
    }}
    ul {{
      margin: 8px 0 0;
      padding-left: 20px;
    }}
    details {{
      margin-bottom: 12px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 600;
    }}
    .scope {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .scope-body {{
      margin-top: 12px;
    }}
    .graph {{
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      margin-bottom: 12px;
    }}
    .function-graph {{
      background: #fffaf1;
    }}
    .node-label {{
      font-size: 14px;
      font-weight: 700;
      fill: var(--ink);
    }}
    .node-subtitle {{
      font-size: 12px;
      fill: var(--muted);
    }}
    .edge-label {{
      font-size: 12px;
      text-anchor: middle;
      fill: var(--muted);
    }}
    .empty {{
      color: var(--muted);
      font-style: italic;
    }}
    .file-list {{
      margin-bottom: 16px;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.92em;
    }}
    @media (max-width: 980px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Architecture Diagram</h1>
    <div class="meta">
      <div><strong>Module:</strong> <code>{html.escape(module_rel)}</code></div>
      <div><strong>Source files:</strong> {len(files)} | <strong>Internal edges:</strong> {edge_count}</div>
      <div><strong>Functions mapped:</strong> {function_count} | <strong>Function-call edges:</strong> {function_edge_count}</div>
      <div><strong>How to use:</strong> expand a scope to see only that level's child graph, then keep drilling down.</div>
    </div>
    <div class="layout">
      <aside class="panel">
        <h2>Tree</h2>
        <ul>{render_tree(".", nodes)}</ul>
      </aside>
      <section class="panel">
        <h2>Nested Graphs</h2>
        {render_scope(".", nodes, graph, functions, function_graph, functions_by_file)}
      </section>
    </div>
    <script type="application/json" id="graph-summary">{html.escape(json.dumps({
        "module": module_rel,
        "files": len(files),
        "edges": edge_count,
        "functions": function_count,
        "function_edges": function_edge_count,
    }))}</script>
  </main>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    module_root = Path(args.module)
    if not module_root.is_absolute():
        module_root = (repo_root / module_root).resolve()

    if not module_root.exists() or not module_root.is_dir():
        raise SystemExit(f"Module directory not found: {module_root}")
    if not is_within(module_root, repo_root):
        raise SystemExit(f"Module must be within repo root: {module_root}")

    file_index = build_file_index(repo_root)
    files, graph = build_dependency_graph(module_root, repo_root, file_index)
    functions, function_graph, functions_by_file = build_function_graph(module_root, repo_root, files, file_index)
    if len(files) > args.max_files:
        raise SystemExit(
            f"Refusing to render {len(files)} files under {module_root}. "
            f"Increase --max-files if you want the full report."
        )

    nodes = build_tree(module_root)
    report = build_report(
        module_root,
        repo_root,
        files,
        graph,
        nodes,
        functions,
        function_graph,
        functions_by_file,
    )

    output_path = Path(args.output) if args.output else module_root / f"{module_root.name}-architecture.html"
    if not output_path.is_absolute():
        output_path = (repo_root / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"Wrote architecture report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
