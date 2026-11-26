"""Contracts that keep the public docs aligned with the CLI surface."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = ROOT / "docs" / "src" / "content" / "docs"
SURFACE_ARTIFACT = ROOT / "docs" / "tests" / "docs_surface.json"
HANDBOOK_ROOT = ROOT / "docs-for-dev"
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "deeptutor_cli" / "README.md",
    ROOT / "SKILL.md",
    ROOT / "docs-for-dev" / "AGENT_SETUP.md",
)


def test_handbook_links_resolve_and_index_reaches_every_guide() -> None:
    """Moving guides/examples must retain a navigable, self-contained handbook."""
    index = HANDBOOK_ROOT / "README.md"
    assert index.is_file()
    assert (HANDBOOK_ROOT / "AGENT_SETUP.md").is_file()
    pages = {path.resolve() for path in HANDBOOK_ROOT.rglob("*.md")}
    graph: dict[Path, set[Path]] = {}
    for path in pages:
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        graph[path] = set()
        for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            url = urlsplit(href.strip().strip("<>"))
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.exists(), f"{path.relative_to(ROOT)}: broken link {href}"
            if target in pages:
                graph[path].add(target)
    visited: set[Path] = set()
    pending = [index.resolve()]
    while pending:
        page = pending.pop()
        if page not in visited:
            visited.add(page)
            pending.extend(graph[page] - visited)
    assert visited == pages, f"Guides unreachable from handbook index: {pages - visited}"


def _command_doc_paths() -> list[Path]:
    paths: list[Path] = []
    if DOCS_ROOT.exists():
        paths.extend(DOCS_ROOT.rglob("*.md"))
    paths.extend(path for path in PUBLIC_DOCS if path.exists())
    paths.extend(HANDBOOK_ROOT.rglob("*.md"))
    return list(dict.fromkeys(paths))


def _docs_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _command_doc_paths())


def _doc_ids() -> set[str]:
    ids: set[str] = set()
    for path in DOCS_ROOT.rglob("*.md"):
        slug = path.relative_to(DOCS_ROOT).with_suffix("").as_posix()
        ids.add(f"/{slug}")
        ids.add(f"/{slug}/")
        if slug.endswith("/index"):
            base = slug[: -len("/index")]
            ids.add(f"/{base}")
            ids.add(f"/{base}/")
    return ids


def _deeptutor_commands() -> list[str]:
    commands: list[str] = []
    pending = ""
    for path in _command_doc_paths():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not pending and not stripped.startswith("deeptutor "):
                continue
            continued = stripped.endswith("\\")
            line_part = stripped[:-1].strip() if continued else stripped
            pending = f"{pending} {line_part}".strip()
            if continued:
                continue
            commands.append(pending)
            pending = ""
    return commands


def _docs_surface() -> dict:
    """The committed CLI/API surface the docs are checked against."""
    if not SURFACE_ARTIFACT.is_file():
        pytest.skip("run scripts/export_docs_surface.py")
    return json.loads(SURFACE_ARTIFACT.read_text(encoding="utf-8"))


def test_public_docs_site_pages_are_scanned() -> None:
    """Guard the path itself: a missing site tree must not silently disable the checks."""
    assert DOCS_ROOT.is_dir(), f"public docs site not found at {DOCS_ROOT.relative_to(ROOT)}"
    pages = list(DOCS_ROOT.rglob("*.md"))
    assert len(pages) > 50, f"only found {len(pages)} pages under {DOCS_ROOT.relative_to(ROOT)}"


def test_internal_docs_links_point_to_existing_pages() -> None:
    ids = _doc_ids()
    missing: list[tuple[str, str]] = []

    for path in DOCS_ROOT.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\[[^\]]+\]\((/docs/[^)\s#]+)(?:#[^)]+)?\)", text):
            href = match.group(1)
            if href not in ids:
                missing.append((str(path.relative_to(ROOT)), href))

    assert missing == []


def test_documented_deeptutor_subcommands_exist() -> None:
    surface = _docs_surface()
    top_level = set(surface["cli"]["groups"])
    nested_subcommands = surface["cli"]["subcommands"]

    for command in _deeptutor_commands():
        first_segment = command.split("|", 1)[0].split("#", 1)[0].strip()
        if "<" in first_segment or "[" in first_segment:
            continue
        tokens = shlex.split(first_segment)
        if len(tokens) < 2:
            continue
        assert tokens[1] in top_level, command
        nested = nested_subcommands.get(tokens[1])
        if nested is not None and len(tokens) >= 3:
            assert tokens[2] in nested, command


def test_deep_research_examples_include_required_config() -> None:
    examples = [
        command for command in _deeptutor_commands() if "deeptutor run deep_research" in command
    ]

    assert examples, "docs should include at least one deep_research example"
    for command in examples:
        has_json_config = "--config-json" in command
        has_pair_config = "--config mode=" in command and "--config depth=" in command
        assert has_json_config or has_pair_config, command


def test_docs_do_not_advertise_removed_cli_forms() -> None:
    text = _docs_text()

    assert "deeptutor provider logout" not in text
    assert "deeptutor memory show summary" not in text
    assert "WS /api/turns" not in text
