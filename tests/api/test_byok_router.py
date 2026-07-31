from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def mu_isolated_root(tmp_path, monkeypatch):
    from deeptutor.multi_user import grants, identity, paths

    admin_root = tmp_path / "data"
    system_root = admin_root / "system"
    users_root = admin_root / "users"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "data" / "user" / "auth_users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "data" / "user" / "auth_secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    admin_root.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def make_user(mu_isolated_root):
    def build(uid: str, *, username: str):
        from deeptutor.multi_user.models import CurrentUser, UserScope

        return CurrentUser(
            id=uid,
            username=username,
            role="user",
            scope=UserScope(
                kind="user",
                user_id=uid,
                root=(mu_isolated_root / "data" / "users" / uid).resolve(),
            ),
        )

    return build


@pytest.fixture
def seed_user():
    def seed(username: str):
        from deeptutor.multi_user.identity import save_user
        from deeptutor.services.auth import hash_password

        return save_user(username, hash_password("password1234"), role="user")

    return seed


@pytest.fixture
def byok_client(mu_isolated_root, make_user, seed_user, monkeypatch):
    import deeptutor.api.routers.byok as byok_router
    import deeptutor.multi_user.byok_policy as policy_module
    from deeptutor.multi_user.context import set_current_user
    from deeptutor.multi_user.grants import load_grant, save_grant
    from deeptutor.services.auth import TokenPayload

    # The first stored account is intentionally promoted to administrator by
    # the identity layer. Seed it separately so Alice and Bob exercise normal
    # user grants.
    seed_user("admin@example.com")
    alice = seed_user("alice@example.com")
    bob = seed_user("bob@example.com")
    users = {"alice": make_user(alice["id"], username="alice@example.com"), "bob": make_user(bob["id"], username="bob@example.com")}
    for user in users.values():
        grant = load_grant(user.id)
        grant["byok"] = {service: {"enabled": True} for service in ("llm", "embedding", "mineru")}
        save_grant(user.id, grant)

    monkeypatch.setenv("DEEPTUTOR_BYOK_MASTER_KEY", "test-master-key")
    monkeypatch.setattr(byok_router, "auth_is_enabled", lambda: True)
    monkeypatch.setattr(policy_module, "auth_is_enabled", lambda: True)
    monkeypatch.setattr(byok_router, "validate_endpoint", lambda endpoint, **_kwargs: endpoint)

    async def auth_override(x_test_user: str = Header(default="alice")):
        set_current_user(users[x_test_user])
        return TokenPayload(username=users[x_test_user].username, role="user", user_id=users[x_test_user].id)

    app = FastAPI()
    app.include_router(byok_router.router, prefix="/api/v1")
    app.dependency_overrides[byok_router.require_auth] = auth_override
    client = TestClient(app)
    client.app.state.byok_test_users = users
    return client


def _headers(user: str) -> dict[str, str]:
    return {"X-Test-User": user}


def test_byok_profile_api_is_owner_scoped_and_redacted(byok_client: TestClient):
    created = byok_client.post(
        "/api/v1/byok/profiles",
        headers=_headers("alice"),
        json={
            "service": "llm",
            "provider": "openai",
            "model": "gpt-test",
            "base_url": "https://api.openai.com/v1",
            "secret": "sk-owner-secret",
        },
    )
    assert created.status_code == 200
    profile = created.json()["profile"]
    assert profile["configured"] is True
    assert "secret" not in created.text
    assert "sk-owner-secret" not in created.text

    bob_status = byok_client.get("/api/v1/byok/status", headers=_headers("bob"))
    assert bob_status.status_code == 200
    assert bob_status.json()["profiles"] == []

    alice_status = byok_client.get("/api/v1/byok/status", headers=_headers("alice"))
    assert alice_status.json()["profiles"][0]["id"] == profile["id"]


def test_byok_profile_update_requires_current_generation(byok_client: TestClient):
    created = byok_client.post(
        "/api/v1/byok/profiles",
        headers=_headers("alice"),
        json={
            "service": "embedding",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "secret": "sk-embedding",
        },
    )
    profile = created.json()["profile"]
    updated = byok_client.patch(
        f"/api/v1/byok/profiles/{profile['id']}",
        headers=_headers("alice"),
        json={
            "service": "embedding",
            "provider": "openai",
            "model": "text-embedding-3-large",
            "generation": profile["generation"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["profile"]["generation"] == profile["generation"] + 1

    stale = byok_client.patch(
        f"/api/v1/byok/profiles/{profile['id']}",
        headers=_headers("alice"),
        json={
            "service": "embedding",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "generation": profile["generation"],
        },
    )
    assert stale.status_code == 409


def test_byok_profile_writes_require_user_grant(byok_client: TestClient):
    from deeptutor.multi_user.grants import load_grant, save_grant

    created = byok_client.post(
        "/api/v1/byok/profiles",
        headers=_headers("alice"),
        json={
            "service": "llm",
            "provider": "openai",
            "model": "gpt-test",
            "secret": "sk-before-revoke",
        },
    )
    assert created.status_code == 200
    profile = created.json()["profile"]

    alice = byok_client.app.state.byok_test_users["alice"]
    grant = load_grant(alice.id)
    grant["byok"]["llm"]["enabled"] = False
    save_grant(alice.id, grant)

    blocked_create = byok_client.post(
        "/api/v1/byok/profiles",
        headers=_headers("alice"),
        json={
            "service": "llm",
            "provider": "openai",
            "model": "gpt-blocked",
            "secret": "sk-blocked",
        },
    )
    assert blocked_create.status_code == 403
    assert blocked_create.json()["detail"] == "BYOK is not enabled for your account"

    blocked_update = byok_client.patch(
        f"/api/v1/byok/profiles/{profile['id']}",
        headers=_headers("alice"),
        json={
            "service": "llm",
            "provider": "openai",
            "model": "gpt-blocked",
            "generation": profile["generation"],
        },
    )
    assert blocked_update.status_code == 403
    assert blocked_update.json()["detail"] == "BYOK is not enabled for your account"


def test_byok_current_user_checks_auth_before_loading_context(monkeypatch):
    import deeptutor.api.routers.byok as byok_router

    monkeypatch.setattr(byok_router, "auth_is_enabled", lambda: False)
    monkeypatch.setattr(
        byok_router,
        "get_current_user",
        lambda: pytest.fail("current user must not be loaded while auth is disabled"),
    )

    with pytest.raises(HTTPException) as exc_info:
        byok_router._current_user()

    assert exc_info.value.status_code == 400
