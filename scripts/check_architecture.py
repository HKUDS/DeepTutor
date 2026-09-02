#!/usr/bin/env python3
"""AST-enforced dependency boundaries, including imports inside functions."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True, slots=True)
class ImportEdge:
    importer: str
    imported: str
    path: Path
    line: int

    @property
    def importer_root(self) -> str:
        parts = self.importer.split(".")
        return parts[1] if len(parts) > 1 else ""

    @property
    def imported_root(self) -> str:
        parts = self.imported.split(".")
        return parts[1] if len(parts) > 1 else ""


def _module_name(path: Path, project_root: Path) -> tuple[str, bool]:
    relative = path.relative_to(project_root).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _resolve_from_import(
    importer: str,
    *,
    is_package: bool,
    node: ast.ImportFrom,
) -> list[str]:
    if node.level == 0:
        return [str(node.module or "")]
    package = importer.split(".") if is_package else importer.split(".")[:-1]
    ascend = node.level - 1
    prefix = package[: max(0, len(package) - ascend)]
    if node.module:
        return [".".join([*prefix, node.module])]
    return [".".join([*prefix, alias.name]) for alias in node.names]


def collect_import_edges(project_root: Path) -> list[ImportEdge]:
    package_root = project_root / "deeptutor"
    edges: list[ImportEdge] = []
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        importer, is_package = _module_name(path, project_root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_names = _resolve_from_import(
                    importer,
                    is_package=is_package,
                    node=node,
                )
            for imported in imported_names:
                if imported == "deeptutor" or imported.startswith("deeptutor."):
                    edges.append(
                        ImportEdge(
                            importer=importer,
                            imported=imported,
                            path=path,
                            line=int(getattr(node, "lineno", 0)),
                        )
                    )
    return edges


def _layer(package_root: str) -> str:
    if package_root == "core":
        return "core"
    if package_root == "app":
        return "application"
    if package_root == "api":
        return "adapter"
    return "domain_runtime"


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, set()):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return components


def architecture_violations(project_root: Path) -> list[str]:
    edges = collect_import_edges(project_root)
    violations: list[str] = []
    seen: set[tuple[Path, int, str]] = set()

    def reject(edge: ImportEdge, reason: str) -> None:
        key = (edge.path, edge.line, reason)
        if key in seen:
            return
        seen.add(key)
        location = edge.path.relative_to(project_root)
        violations.append(f"{location}:{edge.line}: {reason}: {edge.imported}")

    for edge in edges:
        source = edge.importer_root
        target = edge.imported_root
        if source == "core" and target in {"app", "api", "runtime", "services"}:
            reject(edge, "core may contain values/protocols only")
        if source == "app" and target == "api":
            reject(edge, "application must not depend on API adapters")
        if source not in {"", "api", "app", "core"} and target == "api":
            reject(edge, "domain/runtime code must not depend on API adapters")
        if source not in {"", "api", "app"} and target == "app":
            reject(edge, "domain/runtime code must not depend on the application facade")

    graph: dict[str, set[str]] = {
        "core": set(),
        "domain_runtime": set(),
        "application": set(),
        "adapter": set(),
    }
    for edge in edges:
        source_layer = _layer(edge.importer_root)
        target_layer = _layer(edge.imported_root)
        if source_layer != target_layer:
            graph[source_layer].add(target_layer)
    for component in _strongly_connected_components(graph):
        violations.append(f"architecture layers form a dependency cycle: {' -> '.join(component)}")
    return sorted(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    args = parser.parse_args(argv)
    violations = architecture_violations(args.root.resolve())
    if violations:
        print("Architecture boundary violations:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print("Architecture boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
