"""Resolve which connected MarginNote 4 library (if any) the current turn targets.

Mirrors the Obsidian binding pattern: the first selected KB whose metadata is
``type == marginnote4`` wins. The KB's ``db_path`` (or a computed default)
becomes the live store the MarginNote tools query. The result is cached on
``context.metadata`` so ``is_active`` / ``augment_kwargs`` / ``system_block``
share a single resolution.
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import MARGINNOTE4_KB_TYPE

_CACHE_KEY = "_marginnote4_binding"
_UNSET = object()


def marginnote_binding(context: UnifiedContext) -> dict[str, str] | None:
    """Return ``{"name", "db_path"}`` of the selected MN4 KB, or ``None``."""
    cached = context.metadata.get(_CACHE_KEY, _UNSET)
    if cached is not _UNSET:
        return cached or None
    resolved = _resolve(context)
    context.metadata[_CACHE_KEY] = resolved or ""
    return resolved


def _resolve(context: UnifiedContext) -> dict[str, str] | None:
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if not meta or meta.get("type") != MARGINNOTE4_KB_TYPE:
            continue
        from deeptutor.capabilities.marginnote4.store import resolve_db_path

        db_path = str(resolve_db_path(ref, metadata=meta))
        return {"name": str(meta.get("name") or ref), "db_path": db_path}
    return None


def marginnote_kb_refs(context: UnifiedContext) -> set[str]:
    """Return every selected KB ref that resolves to a connected MN4 library.

    All MN4 refs are reported so the chat pipeline can exclude them from the
    ``rag`` surface, exactly like Obsidian vault refs.
    """
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    refs: set[str] = set()
    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if meta and meta.get("type") == MARGINNOTE4_KB_TYPE:
            refs.add(ref)
    return refs


__all__ = ["marginnote_binding", "marginnote_kb_refs"]
