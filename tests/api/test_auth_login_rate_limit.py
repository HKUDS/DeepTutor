"""Login endpoint rate-limit and registration-status regressions."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest_plugins = ["tests.multi_user.conftest"]


@pytest.fixture
def login_client(mu_isolated_root, monkeypatch):
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.login_rate_limit import LoginRateLimiter

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "login_rate_limiter", LoginRateLimiter())
    monkeypatch.setattr(auth_router, "authenticate", lambda username, password: None)
    monkeypatch.setattr(
        auth_router,
        "create_token",
        lambda username, role, user_id: f"{username}:{role}:{user_id}",
    )

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app)


def test_sixth_failed_login_from_one_ip_is_rejected(login_client):
    payload = {"username": "alice", "password": "wrong-password"}
    for _ in range(5):
        response = login_client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 401

    response = login_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["detail"] == "Too many failed login attempts. Try again later."


def test_successful_login_clears_the_failure_counter(login_client, monkeypatch):
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    payload = {"username": "alice", "password": "wrong-password"}
    for _ in range(4):
        assert login_client.post("/api/v1/auth/login", json=payload).status_code == 401

    valid = TokenPayload("alice", "admin", "u_alice")
    monkeypatch.setattr(auth_router, "authenticate", lambda username, password: valid)
    assert (
        login_client.post("/api/v1/auth/login", json=payload | {"password": "correct"}).status_code
        == 200
    )
    monkeypatch.setattr(auth_router, "authenticate", lambda username, password: None)
    assert login_client.post("/api/v1/auth/login", json=payload).status_code == 401


def test_registration_status_closes_after_bootstrap_admin(login_client, monkeypatch):
    import deeptutor.api.routers.auth as auth_router

    monkeypatch.setattr(auth_router, "is_first_user", lambda: False)
    monkeypatch.setattr(auth_router, "AUTH_ALLOW_REGISTRATION", False)
    body = login_client.get("/api/v1/auth/is_first_user").json()
    assert body == {"is_first_user": False, "registration_open": False}
