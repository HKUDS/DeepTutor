import pytest
from fastapi import HTTPException

from deeptutor.api.routers import settings as settings_router
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.grants import save_grant
from deeptutor.multi_user.models import CurrentUser, UserScope


def make_user(tmp_path, role="user"):
    uid = "u_admin" if role == "admin" else "u_alice"
    return CurrentUser(
        id=uid,
        username="admin" if role == "admin" else "alice",
        role=role,
        scope=UserScope(kind="admin" if role == "admin" else "user", user_id=uid, root=tmp_path / uid),
    )


def test_grants_reject_secret_material(tmp_path, monkeypatch):
    from deeptutor.multi_user import grants, identity

    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(identity, "get_user_by_id", lambda user_id: ("alice", {}) if user_id == "u_alice" else None)
    monkeypatch.setattr(grants, "get_user_by_id", lambda user_id: ("alice", {}) if user_id == "u_alice" else None)

    with pytest.raises(ValueError):
        save_grant("u_alice", {"models": {"llm": [{"profile_id": "p", "api_key": "sk"}]}})


def test_grants_reject_admin_users(tmp_path, monkeypatch):
    from deeptutor.multi_user import grants

    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(
        grants,
        "get_user_by_id",
        lambda user_id: ("admin", {"role": "admin"}) if user_id == "u_admin" else None,
    )

    with pytest.raises(ValueError, match="Admin users"):
        save_grant("u_admin", {"knowledge_bases": [{"resource_id": "admin:kb:demo"}]})


def test_non_admin_settings_catalog_is_forbidden(tmp_path):
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        with pytest.raises(HTTPException) as exc:
            settings_router._require_settings_admin()
        assert exc.value.status_code == 403
    finally:
        reset_current_user(token)
