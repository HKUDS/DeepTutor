import asyncio

from fastapi import HTTPException
import pytest

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
        scope=UserScope(
            kind="admin" if role == "admin" else "user", user_id=uid, root=tmp_path / uid
        ),
    )


def test_grants_reject_secret_material(tmp_path, monkeypatch):
    from deeptutor.multi_user import grants, identity

    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(
        identity, "get_user_by_id", lambda user_id: ("alice", {}) if user_id == "u_alice" else None
    )
    monkeypatch.setattr(
        grants, "get_user_by_id", lambda user_id: ("alice", {}) if user_id == "u_alice" else None
    )

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


def test_new_user_gets_a_create_time_default_quota_snapshot(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user import grants, token_quota
    from deeptutor.multi_user.identity import get_user
    from deeptutor.services import auth

    monkeypatch.setattr(auth, "hash_password", lambda _password: "hashed")
    monkeypatch.setattr(
        token_quota,
        "default_quota",
        lambda: {
            "llm": {"daily_tokens": 12_000, "monthly_tokens": 34_000},
            "embedding": {"daily_tokens": 1_000_000, "monthly_tokens": 10_000_000},
            "mineru": {
                "daily_pages": 50,
                "monthly_pages": 500,
                "max_pages_per_file": 50,
            },
        },
    )

    # The first account is promoted to admin automatically, so create the
    # deployment owner before exercising a regular user's grant snapshot.
    auth.add_user("admin@example.com", "password1234")
    auth.add_user("alice@example.com", "password1234")
    record = get_user("alice@example.com")
    assert record is not None
    assert grants.load_grant(record["id"])["token_quota"] == {
        "daily_tokens": 12_000,
        "monthly_tokens": 34_000,
    }
    assert grants.load_grant(record["id"])["quota"]["llm"] == {
        "daily_tokens": 12_000,
        "monthly_tokens": 34_000,
    }

    # Retrying an existing account must not replace a grant an admin has
    # already edited, even if the deployment default changes later.
    monkeypatch.setattr(
        token_quota,
        "default_quota",
        lambda: {
            "llm": {"daily_tokens": 56_000, "monthly_tokens": 78_000},
            "embedding": {"daily_tokens": 2_000_000, "monthly_tokens": 20_000_000},
            "mineru": {
                "daily_pages": 60,
                "monthly_pages": 600,
                "max_pages_per_file": 60,
            },
        },
    )
    auth.add_user("alice@example.com", "new-password")
    assert grants.load_grant(record["id"])["token_quota"] == {
        "daily_tokens": 12_000,
        "monthly_tokens": 34_000,
    }


def test_admin_default_quota_api_normalizes_and_persists(tmp_path, monkeypatch):
    from deeptutor.multi_user import router as multi_user_router
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(multi_user_router, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(multi_user_router, "log_admin_action", lambda *args, **kwargs: None)

    payload = multi_user_router.DefaultTokenQuotaPayload(
        default_token_quota={
            "daily_tokens": -1,
            "monthly_tokens": 20_000_000_000,
        }
    )
    saved = asyncio.run(
        multi_user_router.put_default_token_quota(payload, object())
    )
    assert saved["default_token_quota"] == {
        "daily_tokens": 0,
        "monthly_tokens": 10_000_000_000,
    }
    assert saved["default_quota"]["llm"] == {
        "daily_tokens": 0,
        "monthly_tokens": 10_000_000_000,
    }
    assert service.load_auth(include_process_overrides=False)["default_quota"]["llm"] == {
        "daily_tokens": 0,
        "monthly_tokens": 10_000_000_000,
    }
