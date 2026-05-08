"""Shared fixtures for the multi_user test suite.

These fixtures isolate each test under ``tmp_path`` so we never read or write
the developer's real ``data/`` or ``multi-user/`` directories. They also
provide a context manager that pushes a ``CurrentUser`` onto the contextvar
for tests that need to call user-scoped code without going through HTTP.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope


@pytest.fixture
def mu_isolated_root(tmp_path, monkeypatch) -> Path:
    """Redirect every ``multi_user`` global path under ``tmp_path``.

    Also clears the ``_path_services`` cache so ``get_path_service()`` can be
    re-resolved per test without leaking instances created in earlier tests.
    """
    from deeptutor.multi_user import grants, identity, paths

    project_root = tmp_path
    multi_user_root = tmp_path / "multi-user"
    system_root = multi_user_root / "_system"
    admin_root = (project_root / "data").resolve()

    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "MULTI_USER_ROOT", multi_user_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "_path_services", {})

    monkeypatch.setattr(identity, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(identity, "MULTI_USER_ROOT", multi_user_root)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(
        identity,
        "LEGACY_USERS_FILE",
        project_root / "data" / "user" / "auth_users.json",
    )
    monkeypatch.setattr(
        identity,
        "LEGACY_SECRET_FILE",
        project_root / "data" / "user" / "auth_secret",
    )

    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")

    admin_root.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def make_user(mu_isolated_root):
    """Build a ``CurrentUser`` rooted under the isolated tmp_path."""

    def _make(uid: str, *, role: str = "user", username: str | None = None) -> CurrentUser:
        from deeptutor.multi_user.paths import admin_scope

        if role == "admin":
            scope = admin_scope()
        else:
            scope = UserScope(
                kind="user",
                user_id=uid,
                root=(mu_isolated_root / "multi-user" / uid).resolve(),
            )
        return CurrentUser(
            id=uid,
            username=username or uid,
            role=role,
            scope=scope,
        )

    return _make


@pytest.fixture
def as_user(make_user):
    """Context manager that pushes a CurrentUser onto the contextvar.

    Usage:
        with as_user("u_alice", role="user"):
            ...
    """

    @contextmanager
    def _scope(uid: str, *, role: str = "user", username: str | None = None):
        token = set_current_user(make_user(uid, role=role, username=username))
        try:
            yield
        finally:
            reset_current_user(token)

    return _scope


@pytest.fixture
def seed_user(mu_isolated_root):
    """Create a user record on disk and return the resulting record dict."""

    def _seed(username: str, password: str = "password1234", role: str = "user") -> dict:
        from deeptutor.multi_user.identity import save_user
        from deeptutor.services.auth import hash_password

        return save_user(username, hash_password(password), role=role)  # type: ignore[arg-type]

    return _seed
