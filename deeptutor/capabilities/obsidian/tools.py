"""Obsidian tools — the seam between the chat loop and a connected vault.

Nine tools auto-mounted only when an Obsidian vault is the selected KB (via
:class:`~deeptutor.capabilities.obsidian.capability.ObsidianCapability`, which
runs the turn exclusively on these tools). Six read the vault (navigate links,
search, read notes, list tags) and three write it additively (create / append /
set a property). Every tool is a thin wrapper over the pure
:mod:`deeptutor.capabilities.obsidian.vault` operations.

The vault root is injected server-side as ``_vault_path`` by the capability's
``augment_kwargs`` (resolved from the selected KB's ``vault_path``); the model
never supplies or sees it, so it cannot read or write outside the vault.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.capabilities.obsidian import vault as vault_ops
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

# Tool names mounted together when an Obsidian turn is active. Single source of
# truth so the mount policy and the registration list can't disagree.
OBSIDIAN_TOOL_NAMES: tuple[str, ...] = (
    "obsidian_search",
    "obsidian_read",
    "obsidian_list",
    "obsidian_backlinks",
    "obsidian_links",
    "obsidian_tags",
    "obsidian_create_note",
    "obsidian_append",
    "obsidian_set_property",
)


def _vault_root(kwargs: dict[str, Any]) -> Path | None:
    raw = str(kwargs.get("_vault_path") or "").strip()
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


def _no_vault_result() -> ToolResult:
    return ToolResult(
        content="No Obsidian vault is connected on this turn; Obsidian tools are unavailable.",
        success=False,
    )


def _ok(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, ensure_ascii=False), success=True)


def _err(message: str) -> ToolResult:
    return ToolResult(content=message, success=False)


class _ObsidianTool(BaseTool):
    """Shared vault-root resolution + uniform error handling for Obsidian tools."""

    async def execute(self, **kwargs: Any) -> ToolResult:
        root = _vault_root(kwargs)
        if root is None:
            return _no_vault_result()
        try:
            return await self._run(root, kwargs)
        except vault_ops.VaultError as exc:
            return _err(str(exc))

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:  # pragma: no cover
        raise NotImplementedError


class ObsidianSearchTool(_ObsidianTool):
    """Full-text search across the vault's notes."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_search",
            description=(
                "Search the user's Obsidian vault for notes whose title or body "
                "contains the query (case-insensitive). Returns matching note "
                "paths with a short snippet. Use this first to find where "
                "something lives, then obsidian_read the promising notes."
            ),
            parameters=[
                ToolParameter(name="query", type="string", description="Text to search for."),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max results (default 20).",
                    required=False,
                ),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return _err("obsidian_search needs a non-empty 'query'.")
        limit = _as_int(kwargs.get("limit"), default=20, lo=1, hi=100)
        hits = vault_ops.search_notes(root, query, limit=limit)
        return _ok({"query": query, "count": len(hits), "results": hits})


class ObsidianReadTool(_ObsidianTool):
    """Read a note's frontmatter and body."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_read",
            description=(
                "Read a note from the vault. Accepts a bare note name (resolved "
                "like a [[wikilink]]) or a vault-relative path. Returns the "
                "note's frontmatter properties and Markdown body."
            ),
            parameters=[
                ToolParameter(
                    name="note",
                    type="string",
                    description="Note name (e.g. 'Project Plan') or path (e.g. 'work/Plan.md').",
                ),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        ref = str(kwargs.get("note") or "").strip()
        if not ref:
            return _err("obsidian_read needs a 'note' name or path.")
        return _ok(vault_ops.read_note(root, ref))


class ObsidianListTool(_ObsidianTool):
    """List notes in the vault or a folder."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_list",
            description=(
                "List note paths in the vault, optionally restricted to a folder. "
                "Use to discover structure when you don't have a search term."
            ),
            parameters=[
                ToolParameter(
                    name="folder",
                    type="string",
                    description="Vault-relative folder to list (empty = whole vault).",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max paths (default 200).",
                    required=False,
                ),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        folder = str(kwargs.get("folder") or "").strip()
        limit = _as_int(kwargs.get("limit"), default=200, lo=1, hi=1000)
        paths = vault_ops.list_notes(root, folder=folder, limit=limit)
        return _ok({"folder": folder, "count": len(paths), "notes": paths})


class ObsidianBacklinksTool(_ObsidianTool):
    """Find notes that link to a given note."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_backlinks",
            description=(
                "Find notes that link TO the given note via [[wikilink]]. The "
                "backbone of vault navigation — follow backlinks to discover how "
                "ideas connect."
            ),
            parameters=[
                ToolParameter(name="note", type="string", description="Note name or path."),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        ref = str(kwargs.get("note") or "").strip()
        if not ref:
            return _err("obsidian_backlinks needs a 'note' name or path.")
        links = vault_ops.backlinks(root, ref)
        return _ok({"note": ref, "count": len(links), "backlinks": links})


class ObsidianLinksTool(_ObsidianTool):
    """List the outgoing wikilinks of a note."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_links",
            description=(
                "List the notes a given note links OUT to via [[wikilink]], in "
                "order. Pair with obsidian_backlinks to traverse the graph both ways."
            ),
            parameters=[
                ToolParameter(name="note", type="string", description="Note name or path."),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        ref = str(kwargs.get("note") or "").strip()
        if not ref:
            return _err("obsidian_links needs a 'note' name or path.")
        links = vault_ops.outgoing_links(root, ref)
        return _ok({"note": ref, "count": len(links), "links": links})


class ObsidianTagsTool(_ObsidianTool):
    """List the vault's tags by frequency."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_tags",
            description=(
                "List all tags used across the vault (inline #tags and frontmatter "
                "tags), ranked by how many notes use each. Use to map the vault's "
                "topics before drilling in."
            ),
            parameters=[
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max tags (default 200).",
                    required=False,
                ),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        limit = _as_int(kwargs.get("limit"), default=200, lo=1, hi=1000)
        tags = vault_ops.collect_tags(root, limit=limit)
        return _ok({"count": len(tags), "tags": tags})


class ObsidianCreateNoteTool(_ObsidianTool):
    """Create a new note (never overwrites)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_create_note",
            description=(
                "Create a NEW note in the vault. Fails if the path already exists "
                "(use obsidian_append for existing notes). Write valid Obsidian "
                "Flavored Markdown: [[wikilinks]] for vault notes, > [!note] "
                "callouts, ![[embeds]]. Pass structured metadata as 'properties' "
                "(frontmatter), not inline."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Vault-relative path, e.g. 'Summaries/Photosynthesis.md'.",
                ),
                ToolParameter(name="content", type="string", description="Markdown body."),
                ToolParameter(
                    name="properties",
                    type="object",
                    description="Optional frontmatter properties (tags, aliases, …).",
                    required=False,
                ),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        path = str(kwargs.get("path") or "").strip()
        if not path:
            return _err("obsidian_create_note needs a 'path'.")
        properties = kwargs.get("properties")
        frontmatter = properties if isinstance(properties, dict) else None
        created = vault_ops.create_note(
            root, path, str(kwargs.get("content") or ""), frontmatter=frontmatter
        )
        return _ok({"status": "created", "path": created})


class ObsidianAppendTool(_ObsidianTool):
    """Append to an existing note."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_append",
            description=(
                "Append Markdown to the end of an existing note. Use for adding to "
                "a daily note, log, or running document without rewriting it."
            ),
            parameters=[
                ToolParameter(name="note", type="string", description="Note name or path."),
                ToolParameter(name="content", type="string", description="Markdown to append."),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        ref = str(kwargs.get("note") or "").strip()
        if not ref:
            return _err("obsidian_append needs a 'note' name or path.")
        updated = vault_ops.append_note(root, ref, str(kwargs.get("content") or ""))
        return _ok({"status": "appended", "path": updated})


class ObsidianSetPropertyTool(_ObsidianTool):
    """Set a frontmatter property on an existing note."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="obsidian_set_property",
            description=(
                "Set a single frontmatter property (key/value) on an existing "
                "note, e.g. status, due date, or a tag list. Creates the "
                "frontmatter block if absent; leaves the body untouched."
            ),
            parameters=[
                ToolParameter(name="note", type="string", description="Note name or path."),
                ToolParameter(name="key", type="string", description="Property name."),
                ToolParameter(
                    name="value",
                    type="string",
                    description="Property value (string, or a comma-free scalar).",
                ),
            ],
        )

    async def _run(self, root: Path, kwargs: dict[str, Any]) -> ToolResult:
        ref = str(kwargs.get("note") or "").strip()
        key = str(kwargs.get("key") or "").strip()
        if not ref or not key:
            return _err("obsidian_set_property needs 'note' and 'key'.")
        updated = vault_ops.set_property(root, ref, key, kwargs.get("value"))
        return _ok({"status": "updated", "path": updated, "key": key})


def _as_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, out))


OBSIDIAN_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    ObsidianSearchTool,
    ObsidianReadTool,
    ObsidianListTool,
    ObsidianBacklinksTool,
    ObsidianLinksTool,
    ObsidianTagsTool,
    ObsidianCreateNoteTool,
    ObsidianAppendTool,
    ObsidianSetPropertyTool,
)


__all__ = ["OBSIDIAN_TOOL_NAMES", "OBSIDIAN_TOOL_TYPES"]
