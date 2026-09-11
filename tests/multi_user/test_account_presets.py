"""Account preset persistence, expansion, and admin HTTP behavior."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def preset_client(mu_isolated_root, monkeypatch, as_user):
    from deeptutor.api.routers import multi_user as multi_user_router
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.api.routers.auth import require_admin
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload

    admin = save_user("admin", "$2b$12$placeholder", role="admin")
    tokens = {"admin-token": TokenPayload(username="admin", role="admin", user_id=admin["id"])}
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    app.dependency_overrides[require_admin] = lambda: tokens["admin-token"]
    return TestClient(app), admin, tokens


def test_legacy_and_new_standard_users_default_to_standard(seed_user):
    user = seed_user("legacy")
    assert user["preset"] == "standard"


def test_learning_surface_routing_matches_complete_path_segments():
    from deeptutor.api.routers.auth import _learning_surface_for_path

    assert _learning_surface_for_path("/api/reading/materials") == "reading"
    assert _learning_surface_for_path("/api/courses/course/state") == "reading"
    assert _learning_surface_for_path("/api/question-notebook/entries") == "chat"
    assert _learning_surface_for_path("/api/reading-private") == ""
    assert _learning_surface_for_path("/api/questions") == ""


@pytest.mark.parametrize("preset", ["standard", "custom"])
def test_non_learner_presets_do_not_install_a_learning_grant(preset_client, preset):
    client, _admin, _tokens = preset_client

    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": f"{preset}-user",
            "password": "reading-password-1",
            "preset": preset,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["preset"] == preset
    from deeptutor.multi_user.grants import load_grant

    assert load_grant(body["user_id"])["learning_policy"] is None


def test_learner_preset_expands_to_a_conservative_grant(preset_client):
    from deeptutor.multi_user.grants import load_grant

    client, _admin, _tokens = preset_client

    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "user"
    assert body["preset"] == "learner"

    grant = load_grant(body["user_id"])
    assert grant["enabled_tools"] == []
    assert grant["mcp_tools"] == []
    assert grant["cli_apps"] == []
    assert grant["exec_enabled"] is False
    assert grant["learning_policy"] == {
        "age_band": "9-12",
        "locked_persona": "teacher",
        "allowed_capabilities": ["chat", "immersive_reading"],
        "default_capability": "immersive_reading",
        "allowed_surfaces": ["chat", "reading"],
        "reading": {
            "allow_upload": False,
            "material_ids": [],
            "extensions": [],
        },
    }


def test_learner_creation_rolls_back_when_grant_initialization_fails(preset_client, monkeypatch):
    from deeptutor.multi_user import grants
    from deeptutor.multi_user.identity import get_user

    client, _admin, _tokens = preset_client

    def fail_save_grant(*args, **kwargs):
        raise RuntimeError("grant store unavailable")

    monkeypatch.setattr(grants, "save_grant", fail_save_grant)
    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "The learner preset could not be initialized."
    assert get_user("student") is None


def test_learner_accounts_cannot_disable_the_learning_policy(preset_client):
    client, _admin, _tokens = preset_client
    created = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    ).json()

    response = client.put(
        f"/api/multi-user/users/{created['user_id']}/grants",
        headers={"Authorization": "Bearer admin-token"},
        json={"grant": {"learning_policy": None}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Learner accounts must retain a learning policy."


@pytest.mark.parametrize("preset", ["learner", "custom"])
def test_pocketbase_rejects_presets_it_cannot_enforce(preset_client, monkeypatch, preset):
    import deeptutor.api.routers.auth as auth_router

    client, _admin, _tokens = preset_client
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", True)
    response = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "remote-student",
            "password": "reading-password-1",
            "preset": preset,
        },
    )

    assert response.status_code == 400
    assert "standard preset" in response.json()["detail"]


def test_auth_status_returns_the_effective_learning_policy(preset_client):
    client, _admin, tokens = preset_client
    created = client.post(
        "/api/auth/users",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "username": "student",
            "password": "reading-password-1",
            "preset": "learner",
        },
    ).json()
    from deeptutor.services.auth import TokenPayload

    tokens["learner-token"] = TokenPayload(
        username="student", role="user", user_id=created["user_id"]
    )
    response = client.get(
        "/api/auth/status",
        headers={"Authorization": "Bearer learner-token"},
    )

    assert response.status_code == 200
    assert response.json()["preset"] == "learner"
    assert response.json()["learning_policy"]["default_capability"] == ("immersive_reading")


def test_assigning_a_material_copies_the_admin_material_once(
    preset_client, as_user, seed_user, tmp_path
):
    from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user
    from deeptutor.reading import ReadingStore

    client, admin, _tokens = preset_client
    learner = seed_user("student")
    source = tmp_path / "lesson.txt"
    source.write_text("Assigned reading passage.", encoding="utf-8")
    with as_user(admin["id"], role="admin", username="admin"):
        material = ReadingStore().ingest(source)

    grant = {
        "enabled_tools": [],
        "mcp_tools": [],
        "cli_apps": [],
        "exec_enabled": False,
        "learning_policy": {
            "age_band": "9-12",
            "locked_persona": "teacher",
            "allowed_capabilities": ["chat", "immersive_reading"],
            "default_capability": "immersive_reading",
            "allowed_surfaces": ["chat", "reading"],
            "reading": {
                "allow_upload": False,
                "material_ids": [material.material_id],
                "extensions": [],
            },
        },
    }
    response = client.put(
        f"/api/multi-user/users/{learner['id']}/grants",
        headers={"Authorization": "Bearer admin-token"},
        json={"grant": grant},
    )

    assert response.status_code == 200, response.text
    user_root = get_path_service_for_scope(
        scope_for_user(learner["id"], is_admin=False)
    ).get_workspace_feature_dir("reading")
    staged = user_root / material.material_id
    assert staged.is_dir()
