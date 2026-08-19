"""Stable identity rules for Mastery Path aggregates.

The path id used by the runtime, capability, tools, and persistence layer must
be resolved exactly once. Keeping that rule here prevents a turn from leasing
one path while the capability mutates another.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_mastery_path_id(raw: str) -> str:
    """Return a storage-safe path id, falling back to ``default``."""
    cleaned = _UNSAFE_ID_CHARS.sub("_", str(raw or "")).strip("_")
    return cleaned or "default"


def _first_book_id(book_references: Any) -> str:
    if not isinstance(book_references, (list, tuple)) or not book_references:
        return ""
    reference = book_references[0]
    if isinstance(reference, str):
        return reference.strip()
    if isinstance(reference, dict):
        return str(reference.get("book_id") or reference.get("id") or "").strip()
    return ""


@dataclass(frozen=True, slots=True)
class MasteryPathBinding:
    """Resolved path identity and its lifecycle relationship to a session."""

    path_id: str
    owned_by_session: bool


def resolve_mastery_path_binding(
    *,
    configured_path_id: str = "",
    book_references: Any = None,
    session_id: str = "",
) -> MasteryPathBinding:
    """Resolve explicit path -> selected book -> session-owned fallback."""
    configured = str(configured_path_id or "").strip()
    if configured:
        return MasteryPathBinding(sanitize_mastery_path_id(configured), False)

    book_id = _first_book_id(book_references)
    if book_id:
        return MasteryPathBinding(sanitize_mastery_path_id(book_id), False)

    return MasteryPathBinding(
        sanitize_mastery_path_id(str(session_id or "default")),
        True,
    )


__all__ = [
    "MasteryPathBinding",
    "resolve_mastery_path_binding",
    "sanitize_mastery_path_id",
]
