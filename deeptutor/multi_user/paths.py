"""Path resolution for admin-local and per-user workspaces."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from deeptutor.services.path_service import PathService

from .models import CurrentUser, LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME, UserScope

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADMIN_WORKSPACE_ROOT = PROJECT_ROOT / "data"
MULTI_USER_ROOT = PROJECT_ROOT / "multi-user"
SYSTEM_ROOT = MULTI_USER_ROOT / "_system"

_path_services: dict[str, PathService] = {}


def admin_scope() -> UserScope:
    return UserScope(kind="admin", user_id=LOCAL_ADMIN_ID, root=ADMIN_WORKSPACE_ROOT.resolve())


def local_admin_user() -> CurrentUser:
    return CurrentUser(
        id=LOCAL_ADMIN_ID,
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        scope=admin_scope(),
    )


def scope_for_user(user_id: str, *, is_admin: bool) -> UserScope:
    if is_admin:
        return admin_scope()
    return UserScope(kind="user", user_id=user_id, root=(MULTI_USER_ROOT / user_id).resolve())


def ensure_user_workspace(user_id: str) -> Path:
    root = (MULTI_USER_ROOT / user_id).resolve()
    PathService(workspace_root=root).ensure_all_directories()
    (root / "knowledge_bases").mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(parents=True, exist_ok=True)
    return root


def ensure_system_dirs() -> None:
    for child in ("auth", "grants", "audit", "indexes"):
        (SYSTEM_ROOT / child).mkdir(parents=True, exist_ok=True)


def get_path_service_for_scope(scope: UserScope) -> PathService:
    key = scope.cache_key
    service = _path_services.get(key)
    if service is None:
        service = PathService(workspace_root=scope.root)
        _path_services[key] = service
    return service


def get_admin_path_service() -> PathService:
    return get_path_service_for_scope(admin_scope())


def get_current_path_service() -> PathService:
    from .context import get_current_user

    user = get_current_user()
    if user.scope.kind == "user":
        ensure_user_workspace(user.id)
    return get_path_service_for_scope(user.scope)


@contextmanager
def user_context(user: CurrentUser) -> Iterator[None]:
    from .context import reset_current_user, set_current_user

    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)
