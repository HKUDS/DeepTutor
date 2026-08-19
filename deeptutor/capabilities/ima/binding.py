"""Resolve which connected Tencent IMA libraries the current turn can reach.

The binding is derived once per turn from the user's selected knowledge bases:
every selection whose KB metadata is ``type == ima`` becomes a library the IMA
tools may operate on. Unlike the Obsidian binding (one live vault per turn) all
selected IMA libraries are kept, because a turn can legitimately browse one and
read from another — the tools take an explicit ``kb_name`` when there is more
than one.

Credentials are deliberately *not* part of a binding. What a tool call carries is
the KB reference; the credential pair is loaded from ``kb_config.json`` at call
time by :func:`resolve_client`, which also re-runs the per-user access check. So
no secret is ever placed in tool kwargs (where a trace or a log could pick it up),
and a model cannot reach a library by naming one that was not selected.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import IMA_KB_TYPE

# Cached on context.metadata: a tuple of bindings, empty once we have looked and
# found none. Absence of the key means "not resolved yet".
_CACHE_KEY = "_ima_bindings"


@dataclass(frozen=True, slots=True)
class ImaBinding:
    """One selected knowledge base that points at a Tencent IMA library."""

    kb_ref: str
    """The reference as the user selected it (name or id) — what tools pass back."""

    name: str
    """Display name, used to match a model-supplied ``kb_name``."""

    knowledge_base_id: str
    """Which IMA library this KB reads. Not a secret (it is shown in the UI)."""


def ima_bindings(context: UnifiedContext) -> tuple[ImaBinding, ...]:
    """Every connected IMA library among this turn's selected knowledge bases."""
    cached = context.metadata.get(_CACHE_KEY)
    if cached is not None:
        return tuple(cached)
    resolved = _resolve(context)
    context.metadata[_CACHE_KEY] = resolved
    return resolved


def select_binding(
    bindings: tuple[ImaBinding, ...],
    kb_name: str | None = None,
) -> ImaBinding | None:
    """The binding a tool call targets, chosen from what the turn made available.

    With one selected library the argument is optional (and ignored when it does
    not match, since there is no ambiguity to resolve). With several, an
    unmatched name resolves to ``None`` so the tool can ask for a valid one
    instead of silently operating on the wrong library. A pure function over the
    turn's bindings — the model can only ever reach a library that was selected.
    """
    if not bindings:
        return None
    requested = str(kb_name or "").strip()
    if not requested:
        return bindings[0] if len(bindings) == 1 else None
    for binding in bindings:
        if requested in {binding.kb_ref, binding.name, binding.knowledge_base_id}:
            return binding
    return bindings[0] if len(bindings) == 1 else None


def resolve_client(kb_ref: str, *, for_write: bool = False):
    """An :class:`ImaClient` for *kb_ref*, after re-checking the user's access.

    Raises ``ImaNotConfiguredError`` when the KB (or the account settings) lacks
    a complete credential pair, and ``fastapi.HTTPException`` when the reference
    is not accessible to the current user — writes require write access, since
    they modify the user's own IMA library.
    """
    from deeptutor.multi_user.knowledge_access import resolve_kb
    from deeptutor.services.rag.pipelines.ima.client import ImaClient
    from deeptutor.services.rag.pipelines.ima.config import resolve_kb_config
    from deeptutor.services.rag.provider_binding import load_kb_config_entry

    resource = resolve_kb(str(kb_ref), require_write=for_write)
    entry = load_kb_config_entry(resource.base_dir, resource.name)
    return ImaClient(resolve_kb_config(entry))


def _resolve(context: UnifiedContext) -> tuple[ImaBinding, ...]:
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    bindings: list[ImaBinding] = []
    seen: set[str] = set()
    for raw in context.knowledge_bases or []:
        ref = str(raw).strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        meta = resolve_kb_metadata(ref)
        if not meta or meta.get("type") != IMA_KB_TYPE:
            continue
        bindings.append(
            ImaBinding(
                kb_ref=ref,
                name=str(meta.get("name") or ref),
                knowledge_base_id=str(meta.get("knowledge_base_id") or ""),
            )
        )
    return tuple(bindings)


__all__ = ["ImaBinding", "ima_bindings", "resolve_client", "select_binding"]
