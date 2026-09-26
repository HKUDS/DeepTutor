"""Durable resource preferences are a subset of the current turn's choices."""

from typing import Any


def apply_resource_reuse(
    preferences: dict[str, Any], reuse: object, persistent_kbs: object
) -> None:
    if not isinstance(reuse, dict):
        return
    if isinstance(persistent_kbs, list):
        allowed = {name for name in persistent_kbs if isinstance(name, str)}
        preferences["knowledge_bases"] = [
            name for name in preferences.get("knowledge_bases", []) if name in allowed
        ]
    for kind in ("persona", "skills", "mcp"):
        if reuse.get(kind) is False and kind in preferences:
            preferences[kind] = "" if kind == "persona" else []
