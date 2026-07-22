"""Synthetic user scope for partner runtimes.

A partner is executed as a *synthetic user*: its workspace
(``data/partners/<id>/workspace``) is laid out exactly like a chat user
workspace, and every service that resolves paths through
``get_current_path_service()`` (rag, skills, notebooks, memory, task
workspaces) transparently reads the partner's own assets once the partner
scope is installed via ``user_context(...)``.
"""

from __future__ import annotations

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.partners.config.paths import get_partner_workspace

PARTNER_USER_PREFIX = "partner_"


def partner_user_id(partner_id: str) -> str:
    return f"{PARTNER_USER_PREFIX}{partner_id}"


def partner_scope(partner_id: str) -> UserScope:
    workspace = get_partner_workspace(partner_id)
    return UserScope(
        kind="user",
        user_id=partner_user_id(partner_id),
        root=workspace.resolve(),
    )


def partner_user(partner_id: str, *, name: str = "") -> CurrentUser:
    scope = partner_scope(partner_id)
    return CurrentUser(
        id=scope.user_id,
        username=name or partner_id,
        role="user",
        scope=scope,
    )


__all__ = ["PARTNER_USER_PREFIX", "partner_scope", "partner_user", "partner_user_id"]
