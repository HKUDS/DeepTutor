"""Canonical workspace ownership stored on chat sessions.

Workspace ownership is durable session metadata; ``capability`` is only the
action selected for one turn.  Older records predate that split and therefore
need a one-time upgrade before clients can safely rely on ``workspace_mode``.
"""

from __future__ import annotations

from typing import Any

WORKSPACE_MODE_READING = "immersive_reading"
WORKSPACE_MODE_MASTERY = "mastery_path"
WORKSPACE_MODES = frozenset({WORKSPACE_MODE_READING, WORKSPACE_MODE_MASTERY})


def upgrade_workspace_preferences(value: Any) -> dict[str, Any]:
    """Return preferences with an unambiguous legacy workspace made explicit.

    Only records that do not yet contain ``workspace_mode`` are candidates.
    An explicit empty value means the user left the workspace and must not be
    reconstructed from stale ids.  Association ids alone are also insufficient:
    a normal chat can retain one for references without belonging to that
    product surface.
    """

    preferences = dict(value) if isinstance(value, dict) else {}
    if "workspace_mode" in preferences:
        return preferences

    capability = str(preferences.get("capability") or "").strip()
    mastery_path_id = str(preferences.get("mastery_path_id") or "").strip()
    reading_workspace_id = str(preferences.get("reading_workspace_id") or "").strip()
    session_kind = str(preferences.get("session_kind") or "").strip()

    if capability == WORKSPACE_MODE_MASTERY and mastery_path_id:
        preferences["workspace_mode"] = WORKSPACE_MODE_MASTERY
    elif reading_workspace_id and (
        capability == WORKSPACE_MODE_READING or session_kind == WORKSPACE_MODE_READING
    ):
        preferences["workspace_mode"] = WORKSPACE_MODE_READING
    return preferences


__all__ = [
    "WORKSPACE_MODE_MASTERY",
    "WORKSPACE_MODE_READING",
    "WORKSPACE_MODES",
    "upgrade_workspace_preferences",
]
