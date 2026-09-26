"""Resolve which connected subagent (if any) the current turn targets.

Mirrors :mod:`deeptutor.capabilities.obsidian.binding`: the binding is derived
once per turn from the user's selected knowledge bases — the first selection
whose KB metadata is ``type == subagent`` wins, and its ``agent_kind`` plus its
target (``cwd`` for a local CLI, ``partner_id`` for a partner) become the live
connection the consult tool drives. Cached in the extension namespace so
``is_active`` / ``augment_kwargs`` / ``system_block`` share one lookup. Pure
read; access errors resolve to "no connection".
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import SUBAGENT_KB_TYPE

# Cached per extension: a {"name", "kind", "cwd", "partner_id"} dict, or ""
# once we've looked and found none. Absence of the key means "not resolved yet".
_CACHE_KEY = "_subagent_connection"
_UNSET = object()


def connection_for_turn(context: UnifiedContext) -> dict[str, str] | None:
    """Return ``{"name", "kind", "cwd", "partner_id"}`` of the selected subagent, or ``None``."""
    state = context.extension("subagent")
    cached = state.get(_CACHE_KEY, _UNSET)
    if cached is not _UNSET:
        return cached or None
    resolved = _resolve(context)
    state[_CACHE_KEY] = resolved or ""
    return resolved


def _resolve(context: UnifiedContext) -> dict[str, str] | None:
    group_id = str(context.runtime.partner_discussion_group_id or "").strip()
    if group_id:
        from deeptutor.services.partner_groups.manager import get_partner_group_manager

        group = get_partner_group_manager().get_group(group_id)
        # Keep an unavailable selection active so the consult reports the error;
        # never silently answer as though a requested discussion had happened.
        return {
            "name": group.name if group else group_id,
            "kind": "partner_group",
            "partner_id": group_id,
            "cwd": "",
        }

    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    partner_id = str(context.runtime.consult_partner_id or "").strip()
    if partner_id:
        from deeptutor.multi_user.partner_access import visible_partner_cards

        partner = next((p for p in visible_partner_cards() if p["partner_id"] == partner_id), None)
        return {
            "name": partner["name"] if partner else partner_id,
            "kind": "partner",
            "partner_id": partner_id,
            "cwd": "",
        }

    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if not meta or meta.get("type") != SUBAGENT_KB_TYPE:
            continue
        kind = str(meta.get("agent_kind") or "").strip()
        if not kind or kind == "partner":
            continue
        return {
            "name": str(meta.get("name") or ref),
            "kind": kind,
            "cwd": str(meta.get("cwd") or "").strip(),
            "partner_id": str(meta.get("partner_id") or "").strip(),
        }
    return None


def subagent_refs(context: UnifiedContext) -> set[str]:
    """Return every selected KB ref that resolves to a connected subagent.

    A subagent "KB" is a delegate consulted via ``consult_subagent``, not a rag
    index — exclude these refs from the rag surface so a co-selected real KB
    stays reachable (issue #650) and the agent ref never appears as a rag choice.
    """
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    refs: set[str] = set()
    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if (
            meta
            and meta.get("type") == SUBAGENT_KB_TYPE
            and str(meta.get("agent_kind") or "").strip()
        ):
            refs.add(ref)
    return refs


__all__ = ["connection_for_turn", "subagent_refs"]
