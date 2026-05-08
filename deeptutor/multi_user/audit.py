"""Audit log for resource access and admin actions in the multi-user layer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from .context import get_current_user
from .paths import SYSTEM_ROOT, ensure_system_dirs


def _audit_file():
    # Resolved per call so monkey-patched SYSTEM_ROOT (e.g. in tests) takes
    # effect without a module reload.
    return SYSTEM_ROOT / "audit" / "usage.jsonl"


def _write(payload: dict[str, Any]) -> None:
    try:
        ensure_system_dirs()
        with _audit_file().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Auditing must never break a request.
        return


def log_usage(
    resource_type: str,
    resource_id: str,
    action: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record an ordinary user's access to an admin-curated resource.

    Admin self-access is intentionally not recorded here (admins constantly
    interact with their own workspace; logging every read would dilute the
    signal). Use :func:`log_admin_action` for admin-side write events.
    """
    user = get_current_user()
    if user.is_admin:
        return
    payload: dict[str, Any] = {
        "time": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "username": user.username,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
    }
    if extra:
        payload["extra"] = extra
    _write(payload)


def log_admin_action(
    action: str,
    target_user_id: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    """Record an admin-side write (grant change, user CRUD, etc.).

    The current user (the actor) is captured automatically; ``target_user_id``
    identifies which user the action affects (if any). ``summary`` may carry a
    short, non-secret payload describing what changed.
    """
    user = get_current_user()
    payload: dict[str, Any] = {
        "time": datetime.now(timezone.utc).isoformat(),
        "actor_id": user.id,
        "actor_username": user.username,
        "actor_role": user.role,
        "action": action,
    }
    if target_user_id:
        payload["target_user_id"] = target_user_id
    if summary:
        payload["summary"] = summary
    _write(payload)
