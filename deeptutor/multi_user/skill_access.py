"""Skill visibility guards for non-admin users."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import get_current_user
from .grants import load_grant
from .paths import get_admin_path_service


def assigned_skill_ids(user_id: str | None = None) -> set[str]:
    user = get_current_user()
    uid = user_id or user.id
    return {
        str(item.get("skill_id") or item.get("id") or "").strip()
        for item in load_grant(uid).get("skills", []) or []
        if str(item.get("skill_id") or item.get("id") or "").strip()
    }


def _admin_skill_service():
    """Return a SkillService rooted at the admin workspace (for assigned-skill loads)."""
    from deeptutor.services.skill.service import SkillService

    return SkillService(root=get_admin_path_service().get_workspace_dir() / "skills")


def assigned_skill_infos(user_id: str | None = None) -> list[dict[str, Any]]:
    """Return SkillInfo-shape dicts for the admin skills assigned to the user.

    Each dict is annotated with ``source="admin"`` and ``assigned=True`` so the
    UI can render them next to the user's own skills.
    """
    allowed = assigned_skill_ids(user_id)
    if not allowed:
        return []
    out: list[dict[str, Any]] = []
    for info in _admin_skill_service().list_skills():
        if info.name in allowed:
            entry = info.to_dict()
            entry.update({"source": "admin", "assigned": True, "read_only": True})
            out.append(entry)
    return out


def assigned_skill_detail(name: str) -> dict[str, Any] | None:
    """Return the SkillDetail-shape dict for an admin-assigned skill, or None.

    Caller must already have verified the skill is assigned to the current user
    (e.g. via ``assert_skill_allowed``).
    """
    try:
        detail = _admin_skill_service().get_detail(name)
    except Exception:
        return None
    payload = detail.to_dict()
    payload.update({"source": "admin", "assigned": True, "read_only": True})
    return payload


def assert_skill_allowed(name: str) -> None:
    """Raise 403 when a non-admin tries to read a skill they don't own and
    don't have an admin grant for.

    Pass ``user_owns_skill`` separately from the caller (the skills router
    already knows whether the name exists in the user's own workspace).
    """
    user = get_current_user()
    if user.is_admin:
        return
    if name not in assigned_skill_ids(user.id):
        raise HTTPException(status_code=403, detail="Skill is not assigned to you")
