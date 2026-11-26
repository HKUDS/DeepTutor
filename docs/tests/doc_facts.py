"""Readers for the facts the documentation asserts.

The CLI and API surface comes from ``docs/tests/docs_surface.json``, generated
from the live Typer CLI and FastAPI app by ``scripts/export_docs_surface.py``
and committed, so the light docs job needs no runtime dependencies.
``tests/api/test_docs_surface_export.py`` gates that artifact against
regeneration with the full install. Only the version constant is still read
from source.

Nothing here enforces policy. Each reader returns a plain set so the test can
decide what to compare and how to report it.
"""

from __future__ import annotations

import ast
from functools import cache
import json
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs" / "src" / "content" / "docs"
SURFACE_PATH = REPO_ROOT / "docs" / "tests" / "docs_surface.json"


@cache
def documentation_pages(locale: str = "all") -> list[Path]:
    """Every Markdown page, optionally restricted to one locale.

    ``"all"`` is the default on purpose. The site ships an English tree and a
    ``zh-cn/`` mirror, and a check that silently covered only one of them would
    have passed on 58 of 116 pages while reporting nothing.
    """
    pages = sorted(path for pattern in ("*.md", "*.mdx") for path in DOCS_ROOT.rglob(pattern))
    if locale == "all":
        return pages
    if locale == "zh":
        return [page for page in pages if "zh-cn" in page.relative_to(DOCS_ROOT).parts]
    return [page for page in pages if "zh-cn" not in page.relative_to(DOCS_ROOT).parts]


def page_body(page: Path) -> str:
    """Page source with frontmatter removed and fenced blocks kept.

    Commands and endpoints matter most inside examples — a code block is what a
    reader copies — so a check that cares about invocations reads this variant
    and decides for itself which fenced lines actually invoke something.

    Frontmatter is stripped because its ``description`` is a sentence for
    search engines, not a command reference: "Common deeptutor commands" would
    otherwise be read as a ``deeptutor commands`` invocation.
    """
    text = page.read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)


def page_text(page: Path) -> str:
    """Page source with frontmatter and fenced code blocks removed.

    A mention in prose is a claim that the thing exists; a mention in a fenced
    example may be conditional ("run this after enabling the module"). Checks
    that assert plain existence read prose only; checks that also police code
    samples start from :func:`page_body` and filter fenced lines themselves.
    """
    return re.sub(r"```.*?```", "", page_body(page), flags=re.DOTALL)


# ── CLI commands ────────────────────────────────────────────────────────────


@cache
def docs_surface() -> dict:
    """The committed surface artifact, loaded once.

    ``scripts/export_docs_surface.py`` writes it from the live CLI and app; the
    tests read it instead of importing either. A missing artifact would make
    every check vacuously pass, so fail loudly with the command that recreates
    it rather than returning an empty surface.
    """
    if not SURFACE_PATH.is_file():
        raise RuntimeError(
            f"{SURFACE_PATH} is missing; regenerate it with 'python scripts/export_docs_surface.py'"
        )
    return json.loads(SURFACE_PATH.read_text(encoding="utf-8"))


@cache
def cli_groups() -> set[str]:
    """Top-level ``deeptutor <group>`` names the CLI registers."""
    return set(docs_surface()["cli"]["groups"])


@cache
def cli_subcommands(group: str) -> set[str] | None:
    """Subcommands of ``group``, or ``None`` when there are none to check.

    ``None`` is not "no subcommands": the artifact records an entry only for
    groups that mount subcommands, so a bare command such as ``deeptutor
    doctor`` looks the same here as an unknown group. Callers skip rather than
    fail; ``cli_groups`` is what rejects an unknown group.
    """
    subcommands = docs_surface()["cli"]["subcommands"]
    if group not in subcommands:
        return None
    return set(subcommands[group])


# ── HTTP and WebSocket routes ──────────────────────────────────────────────


@cache
def api_paths() -> set[str]:
    """Every HTTP and WebSocket path the backend serves, prefixes included.

    Both are unioned because pages reference sockets in the same
    ``ws://.../api/...`` shape as HTTP calls; a WebSocket endpoint missing from
    this set would otherwise be reported as unserved.
    """
    surface = docs_surface()
    return set(surface["http"]) | set(surface["ws"])


def matches_api_path(documented: str, known: set[str]) -> bool:
    """Whether a path written in the docs could be served by one of ``known``.

    Path parameters in prose are placeholder text (``{kb_name}``, ``{id}``), and
    a documented path may name a sub-resource the router declares as a parameter
    (``/api/partners/{partner_id}/channels``). Match segment by segment, letting
    any ``{...}`` on either side absorb the other's segment.

    A right-hand placeholder may also absorb several segments at once: docs
    abbreviate a deeper resource as ``/api/plugins/{plugin_id}/{plugin_path}``
    for a router that mounts ``/api/plugins/{plugin_id}/pages/{extension_id}``.
    That is allowed only for the final documented segment, and only on the
    documented side — a real extra segment such as ``v1`` in ``/api/v1/...``
    never matches a shorter known path.

    A documented path that is a strict segment prefix of a known path also
    matches, because docs legitimately name a mounted prefix as the surface root
    ("the ``/api/reading`` surface").

    Known limit: a single-parameter route absorbs any literal in that slot, so a
    documented ``/api/books/nonexistent`` matches the served
    ``/api/books/{book_id}``. Distinguishing a wrong concrete id from a real one
    would need the route's value constraints, which the surface does not carry;
    this check answers "is there a route of this shape", not "is this id valid".
    """
    documented_segments = [segment for segment in documented.split("/") if segment]
    for candidate in known:
        known_segments = [segment for segment in candidate.split("/") if segment]
        if _path_matches(documented_segments, known_segments):
            return True
        # Docs may name a mounted prefix as the surface root ("the
        # ``/api/reading`` surface"). Accept it when every documented segment
        # matches the head of a served path; ``/api/v1`` has no known
        # descendants, so the mistake this test exists for still fails.
        if len(documented_segments) < len(known_segments) and all(
            _segment_matches(left, right)
            for left, right in zip(documented_segments, known_segments)
        ):
            return True
    return False


def _path_matches(documented: list[str], known: list[str]) -> bool:
    """Segment-by-segment match, where ``{...}`` absorbs exactly one segment.

    A placeholder normally stands for one path parameter. Documentation also
    abbreviates a deeper resource with a single placeholder
    (``/api/plugins/{plugin_id}/{plugin_path}`` for a router that mounts
    ``/api/plugins/{plugin_id}/pages/{extension_id}``); that is allowed only
    when the placeholder is the *final* documented segment, and only the
    documented side is abbreviated — a real extra segment such as ``v1`` in
    ``/api/v1/...`` never matches a shorter known path.
    """
    if len(documented) <= len(known):
        return len(documented) == len(known) and all(
            _segment_matches(left, right) for left, right in zip(documented, known)
        )
    # Documented is longer than any known path: only acceptable when its tail is
    # a single placeholder standing in for the remaining known segments.
    head = documented[: len(known)]
    if not all(_segment_matches(left, right) for left, right in zip(head, known)):
        return False
    tail = documented[len(known) :]
    return len(tail) == 1 and tail[0].startswith("{")


def _segment_matches(documented: str, known: str) -> bool:
    if documented == known:
        return True
    if documented.startswith("{") and documented.endswith("}"):
        return True
    if known.startswith("{") and known.endswith("}"):
        return True
    return False


# ── Versions ────────────────────────────────────────────────────────────────


@cache
def project_version() -> str:
    """``__version__`` from `deeptutor/__version__.py`."""
    module = REPO_ROOT / "deeptutor" / "__version__.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            if isinstance(node.value, ast.Constant):
                return str(node.value.value)
    raise RuntimeError("deeptutor/__version__.py does not define __version__")
