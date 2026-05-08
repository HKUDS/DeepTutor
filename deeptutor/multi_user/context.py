"""Request-local current user context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from .models import CurrentUser
from .paths import local_admin_user, scope_for_user

_current_user: ContextVar[CurrentUser | None] = ContextVar("deeptutor_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    _current_user.reset(token)


def get_current_user() -> CurrentUser:
    return _current_user.get() or local_admin_user()


def user_from_token_payload(payload: Any | None) -> CurrentUser:
    if payload is None:
        return local_admin_user()
    user_id = str(getattr(payload, "user_id", "") or "")
    username = str(getattr(payload, "username", "") or "local")
    role = str(getattr(payload, "role", "user") or "user")
    if role not in {"admin", "user"}:
        role = "user"
    if not user_id:
        user_id = "local-admin" if role == "admin" and username == "local" else username
    return CurrentUser(
        id=user_id,
        username=username,
        role=role,  # type: ignore[arg-type]
        scope=scope_for_user(user_id, is_admin=role == "admin"),
    )
