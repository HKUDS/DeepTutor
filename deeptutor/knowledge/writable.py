"""Reusable writable local-KB policy for knowledge-card publication (KB-03).

The API router's ``_assert_kb_writable_or_409`` guard covers incremental
uploads; knowledge-card publication needs the same guard plus a few stronger
checks. This module is the shared, read-only policy so both paths fail closed
identically and no product code embeds the rule set again.

A KB is writable for publication iff all of the following hold (§7.9.2
requirement 4):

* it is a registered, existing ordinary local indexed KB — never a connected /
  external pointer (Obsidian, linked, subagent, LightRAG server, IMA);
* it is ``ready`` (status ``ready``, no ``needs_reindex``);
* it has a local raw document set (``<kb>/raw`` exists as a directory);
* it has a ready provider index for the bound RAG provider.

The policy never mutates anything — it returns the KB entry on success and
raises :class:`KbNotWritableError` otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.knowledge.kb_types import is_connected_kb
from deeptutor.services.rag.factory import has_ready_provider_index
from deeptutor.services.rag.provider_binding import resolve_bound_provider


class KbNotWritableError(Exception):
    """Raised when a knowledge base cannot accept publication writes.

    ``error_code`` is the stable, secret-free code surfaced by the API
    (``kb_not_writable``). ``reason`` is a short human-readable cause.
    """

    error_code = "kb_not_writable"

    def __init__(self, kb_name: str, reason: str) -> None:
        self.kb_name = kb_name
        self.reason = reason
        super().__init__(f"Knowledge base '{kb_name}' is not writable for publication: {reason}")


def kb_has_local_raw_doc_set(kb_dir: str | Path) -> bool:
    """True when ``kb_dir`` has an existing local ``raw/`` directory."""
    return Path(kb_dir, "raw").is_dir()


def assert_kb_writable(manager: Any, kb_name: str) -> dict[str, Any]:
    """Return the KB entry when *kb_name* is a writable local indexed KB.

    Equivalent to the API's ``_assert_kb_writable_or_409`` guard, extended with
    the publication requirements. Raises :class:`KbNotWritableError` without
    mutating anything when any check fails.
    """
    entry = manager.get_kb_entry(kb_name)
    if not isinstance(entry, dict):
        raise KbNotWritableError(kb_name, "not registered")
    if is_connected_kb(entry):
        raise KbNotWritableError(kb_name, "connected/external knowledge bases are read-only")
    if bool(entry.get("needs_reindex", False)):
        raise KbNotWritableError(kb_name, "needs reindex before accepting writes")
    status = str(entry.get("status") or "unknown")
    if status != "ready":
        raise KbNotWritableError(kb_name, f"status is {status!r}, expected 'ready'")
    try:
        kb_dir = manager.get_knowledge_base_path(kb_name)
    except Exception as exc:
        raise KbNotWritableError(
            kb_name, f"knowledge base directory is missing ({type(exc).__name__})"
        ) from exc
    if not kb_dir.is_dir():
        raise KbNotWritableError(kb_name, "knowledge base directory is missing")
    if not kb_has_local_raw_doc_set(kb_dir):
        raise KbNotWritableError(kb_name, "has no local raw document set")
    provider = resolve_bound_provider(str(manager.base_dir), kb_name)
    if not has_ready_provider_index(kb_dir, provider):
        raise KbNotWritableError(kb_name, "has no ready provider index")
    return entry


def kb_is_ready(manager: Any, kb_name: str, kb_dir: str | Path | None = None) -> bool:
    """Read-only check that *kb_name* is confirmably ready for retrieval.

    Used after an index write to verify the KB is still ``ready`` with a ready
    provider index and a raw document set — the last gate before a publication
    is marked ``published`` (§7.9.2 requirement 8).
    """
    entry = manager.get_kb_entry(kb_name)
    if not isinstance(entry, dict):
        return False
    if str(entry.get("status") or "") != "ready":
        return False
    if bool(entry.get("needs_reindex", False)):
        return False
    if is_connected_kb(entry):
        return False
    resolved_dir = Path(kb_dir) if kb_dir is not None else manager.get_knowledge_base_path(kb_name)
    if not resolved_dir.is_dir() or not kb_has_local_raw_doc_set(resolved_dir):
        return False
    provider = resolve_bound_provider(str(manager.base_dir), kb_name)
    return has_ready_provider_index(resolved_dir, provider)


__all__ = [
    "KbNotWritableError",
    "assert_kb_writable",
    "kb_has_local_raw_doc_set",
    "kb_is_ready",
]
