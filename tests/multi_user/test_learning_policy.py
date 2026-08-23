"""Learning-account grant normalization and runtime policy enforcement."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from deeptutor.multi_user.grants import load_grant, normalize_grant, save_grant
from deeptutor.multi_user.learning_access import (
    allowed_reading_extensions,
    apply_learning_policy,
    assert_learning_material,
    assert_learning_surface,
    current_learning_policy,
    learning_policy_for_user,
)


@pytest.fixture
def grantable_alice(mu_isolated_root, monkeypatch):
    from deeptutor.multi_user import grants

    monkeypatch.setattr(
        grants,
        "get_user_by_id",
        lambda user_id: ("alice", {"role": "user"}) if user_id == "u_alice" else None,
    )
    return "u_alice"


def test_learning_policy_is_absent_for_legacy_grants():
    grant = normalize_grant("u_alice", {"version": 2})
    assert grant["learning_policy"] is None


def test_learning_policy_round_trips_and_is_enforced(grantable_alice, as_user):
    policy = {
        "age_band": "9-12",
        "locked_persona": "teacher",
        "allowed_capabilities": ["chat", "immersive_reading"],
        "default_capability": "immersive_reading",
    }
    save_grant(grantable_alice, {"learning_policy": policy})
    assert load_grant(grantable_alice)["learning_policy"] == policy

    with as_user(grantable_alice):
        assert current_learning_policy() == policy
        with pytest.raises(PermissionError):
            apply_learning_policy({"capability": "visualize", "persona": "researcher"})


def test_learning_policy_rejects_unsupported_modes(grantable_alice, as_user):
    save_grant(
        grantable_alice,
        {
            "learning_policy": {
                "age_band": "9-12",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat", "immersive_reading"],
                "default_capability": "chat",
            }
        },
    )
    with as_user(grantable_alice):
        with pytest.raises(PermissionError):
            apply_learning_policy({"capability": "deep_research"})
        applied = apply_learning_policy(
            {
                "capability": "chat",
                "persona": "",
                "tools": ["exec"],
                "knowledge_bases": ["private"],
            }
        )
        assert applied["persona"] == "teacher"
        assert applied["tools"] == []
        assert applied["knowledge_bases"] == []


def test_learning_policy_validation_rejects_invalid_shape(grantable_alice):
    with pytest.raises(ValueError, match="age_band"):
        save_grant(
            grantable_alice,
            {
                "learning_policy": {
                    "age_band": "adult",
                    "locked_persona": "teacher",
                    "allowed_capabilities": ["chat"],
                    "default_capability": "chat",
                }
            },
        )


def test_extended_learning_policy_enforces_surfaces_materials_and_extensions(
    grantable_alice, as_user
):
    save_grant(
        grantable_alice,
        {
            "learning_policy": {
                "age_band": "9-12",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat", "immersive_reading"],
                "default_capability": "immersive_reading",
                "allowed_surfaces": ["chat", "reading"],
                "reading": {
                    "allow_upload": False,
                    "material_ids": ["abc12345"],
                    "extensions": ["read_aloud", "quiz"],
                },
            }
        },
    )
    with as_user(grantable_alice):
        assert_learning_surface("reading")
        with pytest.raises(PermissionError):
            assert_learning_surface("knowledge")
        assert_learning_material("abc12345")
        with pytest.raises(PermissionError):
            assert_learning_material("def67890")
        with pytest.raises(PermissionError):
            assert_learning_material("", upload=True)
        assert allowed_reading_extensions() == {"read_aloud", "quiz"}


def test_admin_policy_is_always_none(as_user):
    with as_user("u_admin", role="admin"):
        assert current_learning_policy() is None
        assert learning_policy_for_user("u_admin", is_admin=True) is None


@pytest.mark.asyncio
async def test_http_surface_guard_returns_403_for_default_denied_surface(
    monkeypatch, as_user
):
    from fastapi import HTTPException

    from deeptutor.api.routers.auth import require_learning_surface

    request = Request({"type": "http", "method": "GET", "path": "/api/v1/memory", "headers": []})
    monkeypatch.setattr(
        "deeptutor.multi_user.learning_access.current_learning_policy",
        lambda: {"allowed_surfaces": ["chat", "reading"]},
    )
    with as_user("u_alice"):
        with pytest.raises(HTTPException) as exc:
            await require_learning_surface(request)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_status_exposes_only_the_public_policy(monkeypatch, grantable_alice):
    from deeptutor.api.routers import auth as auth_router

    policy = {
        "age_band": "9-12",
        "locked_persona": "teacher",
        "allowed_capabilities": ["chat", "immersive_reading"],
        "default_capability": "immersive_reading",
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "_extract_token",
        lambda *_args: "test-token",
    )
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _token: SimpleNamespace(user_id=grantable_alice, username="alice", role="user"),
    )
    monkeypatch.setattr(auth_router, "get_user_info", lambda _username: {})
    monkeypatch.setattr(
        auth_router,
        "learning_policy_for_user",
        lambda user_id, is_admin=False: policy if user_id == grantable_alice else None,
    )

    response = await auth_router.auth_status()
    assert response.learning_policy == policy


@pytest.mark.asyncio
async def test_grant_router_audits_learning_policy(monkeypatch, grantable_alice):
    from deeptutor.multi_user import router as multi_user_router

    policy = {
        "age_band": "6-8",
        "locked_persona": "teacher",
        "allowed_capabilities": ["chat"],
        "default_capability": "chat",
    }
    captured = {}
    monkeypatch.setattr(multi_user_router, "_require_assignable_user", lambda _user_id: None)

    def capture_log(action, **kwargs):
        captured["action"] = action
        captured["summary"] = kwargs.get("summary")

    monkeypatch.setattr(multi_user_router, "log_admin_action", capture_log)

    result = await multi_user_router.put_user_grants(
        grantable_alice,
        multi_user_router.GrantPayload(grant={"learning_policy": policy}),
    )

    assert result["grant"]["learning_policy"] == policy
    assert captured["action"] == "grant_set"
    assert captured["summary"]["learning_policy"] == policy
