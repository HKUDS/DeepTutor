"""Password change endpoints.

Covers the two paths added for self-service and admin reset:

* ``PUT /profile/password`` — the user must prove they know the current
  password, so a stolen session cannot silently take the account over.
* ``PUT /users/{username}/password`` — admin reset for colleagues who forgot
  theirs; it must not be reachable without the admin dependency.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.services.auth import TokenPayload


def _client(route_fn, path: str, name: str, payload=None, method: str = "PUT") -> TestClient:
    app = FastAPI()
    app.add_api_route(path, route_fn, methods=[method], name=name)
    if payload is not None:
        from deeptutor.api.routers import auth as auth_router

        app.dependency_overrides[auth_router.require_auth] = lambda: payload
        app.dependency_overrides[auth_router.require_admin] = lambda: payload
    return TestClient(app)


@pytest.fixture
def alice(monkeypatch):
    """A user record store holding one account with a known password."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import identity

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)

    store = {"alice": {"hash": "HASH_OF_oldpassword", "role": "user"}}
    monkeypatch.setattr(identity, "get_user", lambda u: store.get(u))
    monkeypatch.setattr(
        identity,
        "set_password",
        lambda u, h: store[u].update({"hash": h}) or store[u] if u in store else None,
    )
    monkeypatch.setattr(
        "deeptutor.services.auth.verify_password",
        lambda plain, hashed: hashed == f"HASH_OF_{plain}",
    )
    monkeypatch.setattr("deeptutor.services.auth.hash_password", lambda plain: f"HASH_OF_{plain}")
    return store


def test_change_password_success(alice) -> None:
    from deeptutor.api.routers import auth as auth_router

    client = _client(
        auth_router.change_password,
        "/profile/password",
        "change_password",
        TokenPayload(username="alice", role="user", user_id="u1"),
    )

    resp = client.put(
        "/profile/password",
        json={"current_password": "oldpassword", "new_password": "brand-new-pass"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert alice["alice"]["hash"] == "HASH_OF_brand-new-pass"


def test_change_password_rejects_wrong_current(alice) -> None:
    from deeptutor.api.routers import auth as auth_router

    client = _client(
        auth_router.change_password,
        "/profile/password",
        "change_password",
        TokenPayload(username="alice", role="user", user_id="u1"),
    )

    resp = client.put(
        "/profile/password",
        json={"current_password": "guess", "new_password": "brand-new-pass"},
    )

    assert resp.status_code == 400
    assert "incorrect" in resp.json()["detail"].lower()
    assert alice["alice"]["hash"] == "HASH_OF_oldpassword", "失败的校验不能改动密码"


def test_change_password_rejects_identical(alice) -> None:
    from deeptutor.api.routers import auth as auth_router

    client = _client(
        auth_router.change_password,
        "/profile/password",
        "change_password",
        TokenPayload(username="alice", role="user", user_id="u1"),
    )

    resp = client.put(
        "/profile/password",
        json={"current_password": "oldpassword", "new_password": "oldpassword"},
    )

    assert resp.status_code == 400


def test_change_password_rejects_short_password(alice) -> None:
    from deeptutor.api.routers import auth as auth_router

    client = _client(
        auth_router.change_password,
        "/profile/password",
        "change_password",
        TokenPayload(username="alice", role="user", user_id="u1"),
    )

    resp = client.put(
        "/profile/password",
        json={"current_password": "oldpassword", "new_password": "short"},
    )

    assert resp.status_code == 422


def test_admin_reset_password(alice) -> None:
    from deeptutor.api.routers import auth as auth_router

    app = FastAPI()
    app.add_api_route(
        "/users/{username}/password", auth_router.admin_reset_password, methods=["PUT"]
    )
    app.dependency_overrides[auth_router.require_admin] = lambda: TokenPayload(
        username="root", role="admin", user_id="u0"
    )

    with TestClient(app) as client:
        resp = client.put("/users/alice/password", json={"new_password": "reset-by-admin"})

    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
    assert alice["alice"]["hash"] == "HASH_OF_reset-by-admin"


def test_admin_reset_unknown_user(alice) -> None:
    from deeptutor.api.routers import auth as auth_router

    app = FastAPI()
    app.add_api_route(
        "/users/{username}/password", auth_router.admin_reset_password, methods=["PUT"]
    )
    app.dependency_overrides[auth_router.require_admin] = lambda: TokenPayload(
        username="root", role="admin", user_id="u0"
    )

    with TestClient(app) as client:
        resp = client.put("/users/nobody/password", json={"new_password": "reset-by-admin"})

    assert resp.status_code == 404


def test_change_password_clears_the_initial_password_flag(alice, monkeypatch) -> None:
    """A successful change ends the "still on the admin-assigned password" state."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import identity

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        identity, "set_must_change_password", lambda u, v: calls.append((u, v)) or True
    )

    client = _client(
        auth_router.change_password,
        "/profile/password",
        "change_password",
        TokenPayload(username="alice", role="user", user_id="u1"),
    )

    resp = client.put(
        "/profile/password",
        json={"current_password": "oldpassword", "new_password": "brand-new-pass"},
    )

    assert resp.status_code == 200
    assert calls == [("alice", False)], "改密成功后必须清掉初始密码标记"


def test_failed_change_leaves_the_flag_alone(alice, monkeypatch) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import identity

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        identity, "set_must_change_password", lambda u, v: calls.append((u, v)) or True
    )

    client = _client(
        auth_router.change_password,
        "/profile/password",
        "change_password",
        TokenPayload(username="alice", role="user", user_id="u1"),
    )
    resp = client.put(
        "/profile/password",
        json={"current_password": "wrong", "new_password": "brand-new-pass"},
    )

    assert resp.status_code == 400
    assert calls == [], "校验失败时不能清标记"


@pytest.mark.parametrize("admin", [False, True])
def test_password_endpoints_reject_pocketbase(alice, monkeypatch, admin):
    from deeptutor.api.routers import auth as router

    monkeypatch.setattr(router, "POCKETBASE_ENABLED", True)
    endpoint = router.admin_reset_password if admin else router.change_password
    path = "/users/{username}/password" if admin else "/profile/password"
    client = _client(
        endpoint, path, "password", TokenPayload(username="alice", role="admin", user_id="u1")
    )
    response = client.put(
        path.replace("{username}", "alice"),
        json={"current_password": "oldpassword", "new_password": "new-password"},
    )
    assert response.status_code == 400
    assert alice["alice"]["hash"] == "HASH_OF_oldpassword"


def test_admin_reset_sets_temporary_password_flag(alice, monkeypatch):
    from deeptutor.api.routers import auth as router
    from deeptutor.multi_user import identity

    calls = []
    monkeypatch.setattr(
        identity, "set_must_change_password", lambda u, v: calls.append((u, v)) or True
    )
    client = _client(
        router.admin_reset_password,
        "/users/{username}/password",
        "password",
        TokenPayload(username="root", role="admin", user_id="u0"),
    )
    response = client.put("/users/alice/password", json={"new_password": "new-password"})
    assert response.status_code == 200
    assert calls == [("alice", True)]


def test_public_identity_exposes_temporary_password_flag(monkeypatch):
    from deeptutor.multi_user import identity

    monkeypatch.setattr(
        identity,
        "load_users",
        lambda *args, **kwargs: {
            "alice": {"id": "u1", "hash": "secret", "role": "user", "must_change_password": True}
        },
    )
    info = identity.list_user_info()[0]
    assert info["must_change_password"] is True
    assert "hash" not in info
