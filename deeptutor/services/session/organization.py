"""Integrity helpers for session organization metadata."""

from __future__ import annotations

from typing import Any


async def list_all_sessions_snapshot(
    store: Any,
    *,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """Read a stable session list before any preference mutation begins.

    Preference updates change ``updated_at``, which is also the session-list
    sort key. Mutating while walking offset pages can therefore move rows into
    an earlier page and silently skip them.
    """
    sessions: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = await store.list_sessions(limit=page_size, offset=offset)
        sessions.extend(page)
        if len(page) < page_size:
            return sessions
        offset += len(page)


async def validate_parent_assignment(
    store: Any,
    *,
    session_id: str,
    parent_session_id: str,
) -> dict[str, Any]:
    """Return the parent row, rejecting missing parents and ancestry cycles."""
    parent = await store.get_session(parent_session_id)
    if parent is None:
        raise LookupError(parent_session_id)

    visited = {session_id}
    current: dict[str, Any] | None = parent
    while current is not None:
        current_id = str(current.get("session_id") or current.get("id") or "")
        if not current_id or current_id in visited:
            raise ValueError("Session organization cannot contain a parent cycle")
        visited.add(current_id)
        preferences = current.get("preferences") or {}
        ancestor_id = str(preferences.get("parent_session_id") or "").strip()
        if not ancestor_id:
            break
        current = await store.get_session(ancestor_id)
        if current is None:
            # An already-orphaned ancestor does not make the proposed edge a
            # cycle. The caller only promises that the immediate parent exists.
            break
    return parent


__all__ = ["list_all_sessions_snapshot", "validate_parent_assignment"]
