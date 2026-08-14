"""MarginNote 4 tools -- the seam between the chat loop and the synced store.

Seven tools auto-mounted only when a MarginNote 4 library is the selected KB
(via :class:`~deeptutor.capabilities.marginnote4.capability.MarginNoteCapability`,
which runs the turn exclusively on these tools). Five read the synced data
(search, read, list, links, tags) and two provide structural navigation
(documents, mindmap). Every tool is a thin wrapper over the pure
:class:`~deeptutor.capabilities.marginnote4.store.MarginNoteStore` methods.

The store path is injected server-side as ``_db_path`` by the capability's
``augment_kwargs``; the model never supplies or sees it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.capabilities.marginnote4.models import ALL_TYPES
from deeptutor.capabilities.marginnote4.store import MarginNoteStore
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

MARGINNOTE_TOOL_NAMES: tuple[str, ...] = (
    "marginnote_search",
    "marginnote_read",
    "marginnote_list",
    "marginnote_documents",
    "marginnote_links",
    "marginnote_tags",
    "marginnote_cards",
)


def _store(kwargs: dict[str, Any]) -> MarginNoteStore | None:
    raw = str(kwargs.get("_db_path") or "").strip()
    if not raw:
        return None
    root = Path(raw)
    cached = _STORE_CACHE.get(raw)
    if cached is not None:
        return cached
    if not root.parent.exists():
        return None
    store = MarginNoteStore(root)
    _STORE_CACHE[raw] = store
    return store


_STORE_CACHE: dict[str, MarginNoteStore] = {}


def _clear_store_cache() -> None:
    """Drop cached stores (tests that swap db files under the same path)."""
    _STORE_CACHE.clear()


def _no_store_result() -> ToolResult:
    return ToolResult(
        content="No MarginNote 4 library is connected on this turn; "
        "MarginNote tools are unavailable.",
        success=False,
    )


def _ok(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, ensure_ascii=False), success=True)


def _err(message: str) -> ToolResult:
    return ToolResult(content=message, success=False)


def _as_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, out))


class _MN4Tool(BaseTool):
    """Shared store resolution + uniform error handling for MN4 tools."""

    async def execute(self, **kwargs: Any) -> ToolResult:
        store = _store(kwargs)
        if store is None:
            return _no_store_result()
        try:
            return await self._run(store, kwargs)
        except Exception as exc:
            return _err(str(exc))

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class MarginNoteSearchTool(_MN4Tool):
    """Full-text search across synced MN4 objects."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_search",
            description=(
                "Search the user's MarginNote 4 library for notes, excerpts, "
                "cards, or mindmap nodes whose title or content contains the "
                "query (case-insensitive). Returns matching objects with a "
                "short snippet. Use this first to find where something lives."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Text to search for.",
                ),
                ToolParameter(
                    name="object_type",
                    type="string",
                    description=(
                        "Filter by type: note, excerpt, card, mindmap_node, document, comment."
                    ),
                    required=False,
                    enum=sorted(ALL_TYPES),
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max results (default 20).",
                    required=False,
                ),
            ],
        )

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return _err("marginnote_search needs a non-empty 'query'.")
        obj_type = str(kwargs.get("object_type") or "").strip()
        limit = _as_int(kwargs.get("limit"), default=20, lo=1, hi=100)
        hits = store.search(query, object_type=obj_type, limit=limit)
        return _ok({"query": query, "count": len(hits), "results": hits})


class MarginNoteReadTool(_MN4Tool):
    """Read a single MN4 object in full."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_read",
            description=(
                "Read a single MarginNote 4 object by its ID. Returns the full "
                "object: title, content, excerpt, tags, links, source document, "
                "and timestamps. Use after marginnote_search or "
                "marginnote_list to drill into a specific item."
            ),
            parameters=[
                ToolParameter(
                    name="object_id",
                    type="string",
                    description="The MN4 object ID from a search or list result.",
                ),
            ],
        )

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        oid = str(kwargs.get("object_id") or "").strip()
        if not oid:
            return _err("marginnote_read needs an 'object_id'.")
        obj = store.get(oid)
        if obj is None:
            return _err(f"Object {oid!r} not found in the MarginNote library.")
        return _ok(obj.to_dict())


class MarginNoteListTool(_MN4Tool):
    """List objects, optionally filtered by type or source document."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_list",
            description=(
                "List MarginNote 4 objects, optionally filtered by type or "
                "source document. Use to discover structure when you lack a "
                "search term."
            ),
            parameters=[
                ToolParameter(
                    name="object_type",
                    type="string",
                    description="Filter: note, excerpt, card, mindmap_node.",
                    required=False,
                    enum=sorted(ALL_TYPES),
                ),
                ToolParameter(
                    name="document_id",
                    type="string",
                    description="Restrict to one source document.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max results (default 200).",
                    required=False,
                ),
            ],
        )

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        obj_type = str(kwargs.get("object_type") or "").strip()
        doc_id = str(kwargs.get("document_id") or "").strip()
        limit = _as_int(kwargs.get("limit"), default=200, lo=1, hi=1000)
        items = store.list_objects(object_type=obj_type, document_id=doc_id, limit=limit)
        return _ok({"count": len(items), "objects": items})


class MarginNoteDocumentsTool(_MN4Tool):
    """List source documents with their object counts."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_documents",
            description=(
                "List all source documents (PDFs, books) in the MarginNote "
                "library with a count of annotations, cards, and nodes each "
                "contains. Use to scope a search to one document."
            ),
            parameters=[],
        )

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        docs = store.list_documents()
        return _ok({"count": len(docs), "documents": docs})


class MarginNoteLinksTool(_MN4Tool):
    """Find objects linked to or from a given object."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_links",
            description=(
                "Find MarginNote objects linked TO or FROM the given object. "
                "Links include mindmap parent/child relationships and card "
                "links. Pair with marginnote_read to traverse the knowledge "
                "graph."
            ),
            parameters=[
                ToolParameter(
                    name="object_id",
                    type="string",
                    description="The MN4 object ID to find links for.",
                ),
            ],
        )

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        oid = str(kwargs.get("object_id") or "").strip()
        if not oid:
            return _err("marginnote_links needs an 'object_id'.")
        links = store.linked_objects(oid)
        return _ok({"object_id": oid, "count": len(links), "links": links})


class MarginNoteTagsTool(_MN4Tool):
    """List all tags ranked by frequency."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_tags",
            description=(
                "List all tags used across the MarginNote library, ranked by "
                "how many objects use each. Use to map topics before drilling in."
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

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        limit = _as_int(kwargs.get("limit"), default=200, lo=1, hi=1000)
        tags = store.collect_tags(limit=limit)
        return _ok({"count": len(tags), "tags": tags})


class MarginNoteCardsTool(_MN4Tool):
    """List flashcards for review-scope queries."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_cards",
            description=(
                "List flashcards in the MarginNote library. Returns card "
                "front/back content, tags, and source document. Use when the "
                "user asks about their review material or wants to study."
            ),
            parameters=[
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max cards (default 100).",
                    required=False,
                ),
            ],
        )

    async def _run(self, store: MarginNoteStore, kwargs: dict[str, Any]) -> ToolResult:
        limit = _as_int(kwargs.get("limit"), default=100, lo=1, hi=500)
        cards = store.list_objects(object_type="card", limit=limit)
        return _ok({"count": len(cards), "cards": cards})


MARGINNOTE_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MarginNoteSearchTool,
    MarginNoteReadTool,
    MarginNoteListTool,
    MarginNoteDocumentsTool,
    MarginNoteLinksTool,
    MarginNoteTagsTool,
    MarginNoteCardsTool,
)


__all__ = ["MARGINNOTE_TOOL_NAMES", "MARGINNOTE_TOOL_TYPES"]
