"""Shared fixtures for the payment/cdk test suite.

These fixtures isolate each test under ``tmp_path`` so the CDK store and the
multi-user stores never touch the developer's real ``data/`` tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def pay_isolated_root(tmp_path, monkeypatch) -> Path:
    """Redirect the CDK and multi-user roots under ``tmp_path``."""
    from deeptutor.multi_user import (
        grants,
        identity,
        paths,
    )
    from deeptutor.payment import cdk as cdk_module

    project_root = tmp_path
    admin_root = (project_root / "data").resolve()
    system_root = admin_root / "system"

    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", project_root / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})

    monkeypatch.setattr(identity, "PROJECT_ROOT", project_root)
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

    # CDK module paths are resolved dynamically through ``mu_paths.SYSTEM_ROOT``,
    # so the monkeypatch above is enough — the module caches no globals to clear.
    assert cdk_module.cdk_store_path().parent == system_root / "payment"

    system_root.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def seed_user(pay_isolated_root):
    """Create a user record on disk and return the record.

    The very first account in an empty store is auto-promoted to admin by
    ``save_user``, so a "root" admin is seeded ahead of any normal user to
    keep ``role="user"`` meaningful — same convention as the multi-user test
    suite.
    """

    def _seed(username: str, password: str = "password1234", role: str = "user") -> dict:
        from deeptutor.multi_user.identity import save_user
        from deeptutor.services.auth import hash_password

        if username != "root" and role != "admin":
            # Ensure a non-admin account is not silently promoted.
            from deeptutor.multi_user.identity import get_user

            if get_user("root") is None:
                save_user("root", hash_password(password), role="admin")  # type: ignore[arg-type]
        return save_user(username, hash_password(password), role=role)  # type: ignore[arg-type]

    return _seed


@pytest.fixture
def make_user(pay_isolated_root):
    """Build a ``CurrentUser`` rooted under the isolated tmp_path."""

    def _make(uid: str, *, role: str = "user", username: str | None = None):
        from deeptutor.multi_user.models import CurrentUser, UserScope
        from deeptutor.multi_user.paths import admin_scope

        if role == "admin":
            scope = admin_scope()
        else:
            scope = UserScope(
                kind="user",
                user_id=uid,
                root=(pay_isolated_root / "data" / "users" / uid).resolve(),
            )
        return CurrentUser(
            id=uid,
            username=username or uid,
            role=role,
            scope=scope,
        )

    return _make
