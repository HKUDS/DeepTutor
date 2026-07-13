"""Resolve which connected Obsidian vault (if any) the current turn targets.

The binding is derived once per turn from the user's selected knowledge bases:
the first selection whose KB metadata is ``type == obsidian`` wins, and its
``vault_path`` becomes the live vault the Obsidian tools operate on. The result
is cached on ``context.metadata`` so ``is_active`` / ``augment_kwargs`` /
``system_block`` share a single filesystem lookup. Pure read — no audit
side-effects (unlike ``resolve_for_rag``), and access errors resolve to "no
vault" rather than raising.
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import OBSIDIAN_KB_TYPE

# Cached on context.metadata: a {"name", "path"} dict, or "" once we've looked
# and found none. Absence of the key means "not resolved yet".
_CACHE_KEY = "_obsidian_vault"


def vault_for_turn(context: UnifiedContext) -> dict[str, str] | None:
    """Return ``{"name", "path"}`` of the selected Obsidian vault, or ``None``."""
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
        if not meta or meta.get("type") != OBSIDIAN_KB_TYPE:
            continue
        path = str(meta.get("vault_path") or "").strip()
        if path:
            return {"name": str(meta.get("name") or ref), "path": path}
    return None


_UNSET = object()

__all__ = ["vault_for_turn"]
