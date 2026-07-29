"""Tests for the external SSO bridge (GET /api/v1/auth/sso).

A trusted partner app redirects the browser here with a short-lived,
single-use HS256 assertion signed with the dedicated ``auth.sso_secret``.
The endpoint verifies the assertion, JIT-provisions the user (never as the
first/admin account), optionally applies a grant template, sets the normal
``dt_token`` session cookie and 303-redirects to the app root.
"""

from __future__ import annotations

import json
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
import pytest

SSO_SECRET = "test-sso-secret"
SESSION_SECRET = "test-session-secret"


def _mint(
    secret: str = SSO_SECRET,
    sub: str | None = "apprentus_42",
    jti: str | None = "__new__",
    exp_delta: float = 120.0,
) -> str:
    """Mint an assertion the way the partner app does (HS256, sub/iat/exp/jti)."""
    now = time.time()
    payload: dict = {"iat": int(now), "exp": now + exp_delta}
    if sub is not None:
        payload["sub"] = sub
    if jti is not None:
        payload["jti"] = uuid4().hex if jti == "__new__" else jti
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture()
def sso_env(monkeypatch, tmp_path):
    """Enable the SSO bridge against a temp user store seeded with an admin."""
    from deeptutor.multi_user import identity
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "SSO_SECRET", SSO_SECRET)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", SESSION_SECRET)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    monkeypatch.setattr(auth_service, "_SSO_SEEN_JTIS", {})

    monkeypatch.setattr(identity, "USERS_FILE", tmp_path / "auth" / "users.json")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "legacy-users.json")
    monkeypatch.setattr(identity, "migrate_legacy_multi_user_tree", lambda: None)
    identity.save_user("root", "irrelevant-hash", role="admin")
    return tmp_path


@pytest.fixture()
def client() -> TestClient:
    from deeptutor.api.routers import auth as auth_router

    app = FastAPI()
    app.add_api_route("/sso", auth_router.sso_login, methods=["GET"])
    return TestClient(app, follow_redirects=False)


def test_sso_is_404_when_not_configured(monkeypatch, client) -> None:
    """Without a configured secret the endpoint must not exist observably."""
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "SSO_SECRET", "")

    assert client.get("/sso", params={"token": _mint()}).status_code == 404


def test_sso_logs_in_and_provisions_user(sso_env, client) -> None:
    from deeptutor.services import auth as auth_service

    resp = client.get("/sso", params={"token": _mint(sub="apprentus_42")})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    set_cookie = resp.headers.get("set-cookie", "")
    assert "dt_token=" in set_cookie
    assert "HttpOnly" in set_cookie

    # The cookie is a genuine DeepTutor session token for the new user.
    dt_token = resp.cookies["dt_token"]
    payload = auth_service.decode_token(dt_token)
    assert payload is not None
    assert payload.username == "apprentus_42"
    assert payload.role == "user"
    assert payload.user_id.startswith("u_")

    info = auth_service.get_user_info("apprentus_42")
    assert info is not None
    assert info["role"] == "user"


def test_sso_reuses_existing_user(sso_env, client) -> None:
    from deeptutor.services import auth as auth_service

    first = client.get("/sso", params={"token": _mint(sub="apprentus_42")})
    uid = auth_service.decode_token(first.cookies["dt_token"]).user_id

    second = client.get("/sso", params={"token": _mint(sub="apprentus_42")})
    assert second.status_code == 303
    assert auth_service.decode_token(second.cookies["dt_token"]).user_id == uid


def test_sso_rejects_bad_signature(sso_env, client) -> None:
    resp = client.get("/sso", params={"token": _mint(secret="wrong-secret")})
    assert resp.status_code == 401


def test_sso_rejects_expired_assertion(sso_env, client) -> None:
    resp = client.get("/sso", params={"token": _mint(exp_delta=-30)})
    assert resp.status_code == 401


def test_sso_rejects_missing_jti_or_sub(sso_env, client) -> None:
    assert client.get("/sso", params={"token": _mint(jti=None)}).status_code == 401
    assert client.get("/sso", params={"token": _mint(sub=None)}).status_code == 401


def test_sso_rejects_invalid_subject(sso_env, client) -> None:
    """Subjects must fit the plain-username shape accepted by /register."""
    assert client.get("/sso", params={"token": _mint(sub="ab")}).status_code == 401
    assert client.get("/sso", params={"token": _mint(sub="a b@c!")}).status_code == 401


def test_sso_assertion_is_single_use(sso_env, client) -> None:
    token = _mint()
    assert client.get("/sso", params={"token": token}).status_code == 303
    assert client.get("/sso", params={"token": token}).status_code == 401


def test_sso_refuses_empty_user_store(monkeypatch, sso_env, client) -> None:
    """An SSO user must never become the auto-promoted first admin."""
    from deeptutor.multi_user import identity
    from deeptutor.services import auth as auth_service

    identity.delete_user("root")
    assert auth_service.is_first_user()

    resp = client.get("/sso", params={"token": _mint()})
    assert resp.status_code == 409
    assert auth_service.get_user_info("apprentus_42") is None


def test_sso_rejects_disabled_account(sso_env, client) -> None:
    from deeptutor.multi_user import identity

    client.get("/sso", params={"token": _mint(sub="apprentus_42")})
    users = identity.load_users()
    users["apprentus_42"]["disabled"] = True
    identity._write_users(users)

    resp = client.get("/sso", params={"token": _mint(sub="apprentus_42")})
    assert resp.status_code == 403


def test_sso_applies_grant_template(monkeypatch, sso_env, tmp_path, client) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import grants
    from deeptutor.services import auth as auth_service

    template = tmp_path / "grant-template.json"
    template.write_text(
        json.dumps({"knowledge_bases": [{"kb_id": "spanish-101"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(auth_router, "SSO_GRANT_TEMPLATE", str(template))
    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(grants, "ensure_system_dirs", lambda: None)

    resp = client.get("/sso", params={"token": _mint(sub="apprentus_42")})
    assert resp.status_code == 303

    uid = str(auth_service.get_user_info("apprentus_42")["id"])
    grant = grants.load_grant(uid)
    assert grant["knowledge_bases"] == [{"kb_id": "spanish-101"}]
