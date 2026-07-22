"""Pure filesystem operations over a connected Obsidian vault.

This module is the *only* place that knows Obsidian's on-disk conventions:

* notes are ``.md`` files anywhere under the vault root;
* metadata is YAML frontmatter fenced by ``---`` at the top of a note;
* links are ``[[wikilinks]]`` (optionally ``[[Note#heading|alias]]``);
* ``.obsidian`` / ``.trash`` / ``.git`` are vault internals to ignore.

Every function takes the vault root explicitly and returns plain data — no
dependency on the chat loop, tools, or capability machinery, so it is trivial
to unit-test and reuse. Writes are additive only (create / append / set a
property); nothing here edits-in-place or deletes existing prose.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml

# Vault-internal folders that hold app state, not user notes.
IGNORED_DIRS: frozenset[str] = frozenset({".obsidian", ".trash", ".git"})

# Target of a wikilink, up to the first of ``#`` (heading), ``^`` (block), or
# ``|`` (display alias). ``![[...]]`` embeds share the same target syntax.
_WIKILINK_RE = re.compile(r"!?\[\[([^\]\n|#^]+)")
# Inline ``#tag`` (allowing nested ``#a/b``), not a Markdown heading (``# h``):
# requires a non-space immediately after ``#`` and not at line start after space.
_INLINE_TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z0-9_][A-Za-z0-9_/-]*)")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class VaultError(Exception):
    """A vault operation could not be completed (missing note, bad path, …)."""


# --- internals --------------------------------------------------------------


def _is_ignored(rel: Path) -> bool:
    return any(part in IGNORED_DIRS for part in rel.parts)


def _iter_markdown(root: Path):
    """Yield every user-facing ``.md`` file under ``root`` (ignored dirs skipped)."""
    for path in sorted(root.rglob("*.md")):
        if _is_ignored(path.relative_to(root)):
            continue
        yield path


def _safe_join(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root``, refusing anything that escapes the vault."""
    root_resolved = root.resolve()
    candidate = (root_resolved / rel.lstrip("/")).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise VaultError(f"Path {rel!r} escapes the vault.")
    return candidate


def _with_md_suffix(rel: str) -> str:
    return rel if rel.lower().endswith(".md") else f"{rel}.md"


def resolve_note(root: Path, ref: str) -> Path | None:
    """Resolve a note reference to a file path the way Obsidian links do.

    ``ref`` may be a vault-relative path (``folder/Note.md``) or a bare note
    name (``Note``) matched by basename anywhere in the vault. Returns ``None``
    when nothing matches.
    """
    ref = (ref or "").strip().split("#", 1)[0].split("|", 1)[0].strip()
    if not ref:
        return None
    # Explicit path (has a separator or .md suffix) → resolve directly.
    if "/" in ref or ref.lower().endswith(".md"):
        candidate = _safe_join(root, _with_md_suffix(ref))
        return candidate if candidate.is_file() else None
    # Bare name → first .md whose stem matches (case-insensitive fallback).
    wanted = ref.lower()
    fallback: Path | None = None
    for path in _iter_markdown(root):
        if path.stem == ref:
            return path
        if fallback is None and path.stem.lower() == wanted:
            fallback = path
    return fallback


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a note into (frontmatter dict, body). Tolerates malformed YAML."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[match.end() :]


def _compose_note(frontmatter: dict[str, Any], body: str) -> str:
    if not frontmatter:
        return body
    fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n{body}"


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _snippet(body: str, query: str, width: int = 160) -> str:
    lowered = body.lower()
    idx = lowered.find(query.lower())
    if idx < 0:
        return body[:width].strip().replace("\n", " ")
    start = max(0, idx - width // 3)
    return ("…" if start else "") + body[start : start + width].strip().replace("\n", " ") + "…"


# --- read operations --------------------------------------------------------


def read_note(root: Path, ref: str) -> dict[str, Any]:
    """Return ``{path, frontmatter, body}`` for a note, or raise ``VaultError``."""
    path = resolve_note(root, ref)
    if path is None:
        raise VaultError(f"Note {ref!r} not found in the vault.")
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    return {"path": _rel(root, path), "frontmatter": frontmatter, "body": body}


def search_notes(root: Path, query: str, limit: int = 20) -> list[dict[str, str]]:
    """Case-insensitive substring search over note titles and bodies."""
    query = (query or "").strip()
    if not query:
        return []
    needle = query.lower()
    hits: list[dict[str, str]] = []
    for path in _iter_markdown(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if needle in path.stem.lower() or needle in text.lower():
            hits.append({"path": _rel(root, path), "snippet": _snippet(text, query)})
            if len(hits) >= limit:
                break
    return hits


def list_notes(root: Path, folder: str = "", limit: int = 200) -> list[str]:
    """List note paths (vault-relative), optionally under ``folder``."""
    base = _safe_join(root, folder) if folder.strip() else root.resolve()
    if not base.exists():
        return []
    out: list[str] = []
    for path in _iter_markdown(base if base.is_dir() else root):
        out.append(_rel(root, path))
        if len(out) >= limit:
            break
    return out


def outgoing_links(root: Path, ref: str) -> list[str]:
    """The wikilink targets a note points to, in order, de-duplicated."""
    note = read_note(root, ref)
    seen: dict[str, None] = {}
    for target in _WIKILINK_RE.findall(note["body"]):
        name = target.strip()
        if name:
            seen.setdefault(name, None)
    return list(seen)


def backlinks(root: Path, ref: str, limit: int = 50) -> list[dict[str, str]]:
    """Notes that link to ``ref`` via ``[[name]]`` (matched by basename)."""
    target = resolve_note(root, ref)
    if target is None:
        raise VaultError(f"Note {ref!r} not found in the vault.")
    stem = target.stem.lower()
    out: list[dict[str, str]] = []
    for path in _iter_markdown(root):
        if path == target:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(t.strip().lower() == stem for t in _WIKILINK_RE.findall(text)):
            out.append({"path": _rel(root, path), "snippet": _snippet(text, target.stem)})
            if len(out) >= limit:
                break
    return out


def collect_tags(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    """All tags across the vault (inline ``#tag`` + frontmatter ``tags``), by count."""
    counts: dict[str, int] = {}

    def bump(tag: str) -> None:
        tag = tag.strip().lstrip("#")
        if tag:
            counts[tag] = counts.get(tag, 0) + 1

    for path in _iter_markdown(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = split_frontmatter(text)
        fm_tags = frontmatter.get("tags")
        if isinstance(fm_tags, str):
            fm_tags = [fm_tags]
        if isinstance(fm_tags, list):
            for tag in fm_tags:
                bump(str(tag))
        for tag in _INLINE_TAG_RE.findall(body):
            bump(tag)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tag": tag, "count": count} for tag, count in ranked[:limit]]


# --- write operations (additive only) ---------------------------------------


def create_note(
    root: Path,
    rel_path: str,
    content: str,
    frontmatter: dict[str, Any] | None = None,
) -> str:
    """Create a new ``.md`` note. Refuses to overwrite an existing file."""
    rel_path = (rel_path or "").strip()
    if not rel_path:
        raise VaultError("create_note needs a non-empty path.")
    path = _safe_join(root, _with_md_suffix(rel_path))
    if path.exists():
        raise VaultError(f"Note {_with_md_suffix(rel_path)!r} already exists; use append instead.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_compose_note(frontmatter or {}, content or ""), encoding="utf-8")
    return _rel(root, path)


def append_note(root: Path, ref: str, content: str) -> str:
    """Append text to the end of an existing note."""
    path = resolve_note(root, ref)
    if path is None:
        raise VaultError(f"Note {ref!r} not found; create it first.")
    existing = path.read_text(encoding="utf-8")
    separator = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(existing + separator + (content or ""), encoding="utf-8")
    return _rel(root, path)


def set_property(root: Path, ref: str, key: str, value: Any) -> str:
    """Set a single frontmatter property on an existing note."""
    key = (key or "").strip()
    if not key:
        raise VaultError("set_property needs a non-empty key.")
    path = resolve_note(root, ref)
    if path is None:
        raise VaultError(f"Note {ref!r} not found; create it first.")
    frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    frontmatter[key] = value
    path.write_text(_compose_note(frontmatter, body), encoding="utf-8")
    return _rel(root, path)


__all__ = [
    "VaultError",
    "IGNORED_DIRS",
    "resolve_note",
    "read_note",
    "search_notes",
    "list_notes",
    "outgoing_links",
    "backlinks",
    "collect_tags",
    "create_note",
    "append_note",
    "set_property",
    "split_frontmatter",
]
