"""Resolve which connected subagent (if any) the current turn targets.

Mirrors :mod:`deeptutor.capabilities.obsidian.binding`: the binding is derived
once per turn from the user's selected knowledge bases — the first selection
whose KB metadata is ``type == subagent`` wins, and its ``agent_kind`` plus its
target (``cwd`` for a local CLI, ``partner_id`` for a partner) become the live
connection the consult tool drives. Cached on ``context.metadata`` so
``is_active`` / ``augment_kwargs`` / ``system_block`` share one lookup. Pure
read; access errors resolve to "no connection".
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import SUBAGENT_KB_TYPE

# Cached on context.metadata: a {"name", "kind", "cwd", "partner_id"} dict, or ""
# once we've looked and found none. Absence of the key means "not resolved yet".
_CACHE_KEY = "_subagent_connection"
_UNSET = object()


def connection_for_turn(context: UnifiedContext) -> dict[str, str] | None:
    """Return ``{"name", "kind", "cwd", "partner_id"}`` of the selected subagent, or ``None``."""
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
        if not meta or meta.get("type") != SUBAGENT_KB_TYPE:
            continue
        kind = str(meta.get("agent_kind") or "").strip()
        if not kind:
            continue
        return {
            "name": str(meta.get("name") or ref),
            "kind": kind,
            "cwd": str(meta.get("cwd") or "").strip(),
            "partner_id": str(meta.get("partner_id") or "").strip(),
        }
    return None


__all__ = ["connection_for_turn"]
