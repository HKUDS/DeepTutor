"""HTTP regression tests for the private-to-public auth handoff."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.multi_user import session_handoff
from deeptutor.services import auth as auth_service


def _loopback_proxy(app):
    async def forwarded(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "client": ("127.0.0.1", 12345)}
        await app(scope, receive, send)

    return forwarded


def _handoff_client(
    tmp_path: Path,
    monkeypatch,
    *,
    pocketbase: bool = False,
) -> tuple[TestClient, str]:
    state_root = tmp_path / "state"
    monkeypatch.setattr(session_handoff, "AUTH_DIR", state_root / "auth")
    monkeypatch.setattr(session_handoff, "_DEFAULT_STORE", None)
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: "test-secret")

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(auth_service, "TOKEN_EXPIRE_HOURS", 24)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", pocketbase)
    monkeypatch.setattr(auth_router, "PRIVATE_LOGIN_HOSTS", frozenset({"private.example:8443"}))

    if pocketbase:
        monkeypatch.setattr(
            auth_router,
            "decode_token",
            lambda _token: auth_service.TokenPayload(
                username="alice@example.test", role="user", user_id="pb-user"
            ),
        )
        bearer = "pb-bearer-token-that-must-not-persist"
    else:
        bearer = auth_service.create_token("alice", "user", "u-alice")

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(_loopback_proxy(app)), bearer


def test_private_create_public_exchange_and_complete(tmp_path, monkeypatch) -> None:
    client, bearer = _handoff_client(tmp_path, monkeypatch)
    monkeypatch.setattr(auth_router, "_SECURE", True)
    monkeypatch.setattr(auth_router, "_SAMESITE", "none")

    created = client.post(
        "/api/auth/session-handoff",
        headers={
            "x-deeptutor-frontend-host": "private.example:8443",
            "Authorization": f"Bearer {bearer}",
        },
        json={"public_origin": "https://app.example"},
    )
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    body = created.json()
    assert body["handoff_url"] == f"https://app.example/handoff?code={body['code']}"

    exchanged = client.post(
        "/api/auth/session-handoff/exchange",
        headers={"x-deeptutor-frontend-host": "app.example"},
        json={"code": body["code"]},
    )
    assert exchanged.status_code == 200
    assert exchanged.headers["cache-control"] == "no-store"
    ticket = exchanged.json()["ticket"]

    completed = client.post(
        "/api/auth/session-handoff/complete",
        headers={"x-deeptutor-frontend-host": "app.example"},
        json={"ticket": ticket},
    )
    assert completed.status_code == 200
    cookie = completed.headers["set-cookie"]
    assert "httponly" in cookie.lower()
    assert "secure" in cookie.lower()
    assert "samesite=none" in cookie.lower()
    session = auth_service.decode_token(
        completed.cookies.get("dt_token", ""),
    )
    assert session is not None
    assert (session.username, session.role, session.user_id) == ("alice", "user", "u-alice")

    replayed = client.post(
        "/api/auth/session-handoff/complete",
        headers={"x-deeptutor-frontend-host": "app.example"},
        json={"ticket": ticket},
    )
    assert replayed.status_code == 400


def test_codes_and_tickets_reject_mismatched_frontend_hosts(tmp_path, monkeypatch) -> None:
    client, bearer = _handoff_client(tmp_path, monkeypatch)
    created = client.post(
        "/api/auth/session-handoff",
        headers={
            "x-deeptutor-frontend-host": "private.example:8443",
            "Authorization": f"Bearer {bearer}",
        },
        json={"public_origin": "https://app.example"},
    ).json()

    assert (
        client.post(
            "/api/auth/session-handoff/exchange",
            headers={"x-deeptutor-frontend-host": "attacker.example"},
            json={"code": created["code"]},
        ).status_code
        == 400
    )
    exchanged = client.post(
        "/api/auth/session-handoff/exchange",
        headers={"x-deeptutor-frontend-host": "app.example"},
        json={"code": created["code"]},
    )
    assert exchanged.status_code == 200
    assert (
        client.post(
            "/api/auth/session-handoff/complete",
            headers={"x-deeptutor-frontend-host": "attacker.example"},
            json={"ticket": exchanged.json()["ticket"]},
        ).status_code
        == 400
    )


def test_malformed_frontend_host_is_rejected_without_server_error(tmp_path, monkeypatch) -> None:
    client, _ = _handoff_client(tmp_path, monkeypatch)

    exchange = client.post(
        "/api/auth/session-handoff/exchange",
        headers={"x-deeptutor-frontend-host": "app.example:not-a-port"},
        json={"code": "1234567890abcdef"},
    )
    complete = client.post(
        "/api/auth/session-handoff/complete",
        headers={"x-deeptutor-frontend-host": "app.example:not-a-port"},
        json={"ticket": "x" * 32},
    )

    assert exchange.status_code == 400
    assert complete.status_code == 400


def test_pocketbase_bearer_is_jwe_wrapped_and_cookie_is_http_only(tmp_path, monkeypatch) -> None:
    client, bearer = _handoff_client(tmp_path, monkeypatch, pocketbase=True)
    monkeypatch.setattr(auth_router, "_SECURE", True)
    monkeypatch.setattr(auth_router, "_SAMESITE", "none")

    created = client.post(
        "/api/auth/session-handoff",
        headers={"x-deeptutor-frontend-host": "private.example:8443"},
        cookies={"dt_token": bearer},
        json={"public_origin": "https://app.example"},
    ).json()
    ticket = client.post(
        "/api/auth/session-handoff/exchange",
        headers={"x-deeptutor-frontend-host": "app.example"},
        json={"code": created["code"]},
    ).json()["ticket"]
    completed = client.post(
        "/api/auth/session-handoff/complete",
        headers={"x-deeptutor-frontend-host": "app.example"},
        json={"ticket": ticket},
    )

    assert completed.status_code == 200
    assert completed.cookies.get("dt_token") == bearer
    assert "httponly" in completed.headers["set-cookie"].lower()

    connection = sqlite3.connect(tmp_path / "state" / "auth" / "session_handoff.sqlite3")
    persisted = " ".join(
        str(value) for row in connection.execute("SELECT * FROM handoff_records") for value in row
    )
    connection.close()
    assert bearer not in persisted


def test_private_login_host_policy_gates_password_login(tmp_path, monkeypatch) -> None:
    _, bearer = _handoff_client(tmp_path, monkeypatch)
    payload = auth_service.TokenPayload(username="alice", role="user", user_id="u-alice")
    monkeypatch.setattr(auth_router, "authenticate", lambda _username, _password: payload)
    monkeypatch.setattr(auth_router, "create_token", lambda *_args, **_kwargs: bearer)

    app = FastAPI()
    app.add_api_route("/login", auth_router.login, methods=["POST"])
    with TestClient(_loopback_proxy(app)) as client:
        refused = client.post(
            "/login",
            headers={"x-deeptutor-frontend-host": "app.example"},
            json={"username": "alice", "password": "password123"},
        )
        allowed = client.post(
            "/login",
            headers={"x-deeptutor-frontend-host": "127.0.0.1:8001"},
            json={"username": "alice", "password": "password123"},
        )

    assert refused.status_code == 403
    assert allowed.status_code == 200


def test_direct_backend_request_cannot_forge_private_frontend_host(tmp_path, monkeypatch) -> None:
    _, bearer = _handoff_client(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    with TestClient(app) as direct:
        response = direct.post(
            "/api/auth/session-handoff",
            headers={
                "x-deeptutor-frontend-host": "private.example:8443",
                "host": "private.example:8443",
                "Authorization": f"Bearer {bearer}",
            },
            json={"public_origin": "https://app.example"},
        )
    assert response.status_code == 403


def test_pairing_ticket_expires_after_exchange_even_near_code_expiry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: "test-secret")
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    created_at = 1000
    ticket = session_handoff.encrypt_ticket_payload(
        {"host": "app.example", "exp": created_at + 420}
    )
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=created_at,
    )
    exchanged_at = created_at + session_handoff.CODE_LIFETIME_SECONDS - 1
    fresh = store.exchange(code=record.code, public_host="app.example", now=exchanged_at)
    assert (
        session_handoff.decrypt_ticket_payload(fresh)["exp"]
        == exchanged_at + session_handoff.TICKET_LIFETIME_SECONDS
    )
    assert (
        store.consume_ticket(ticket=fresh, public_host="app.example", now=exchanged_at + 119)
        == fresh
    )


def test_pairing_ticket_rejects_completion_after_its_exchange_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: "test-secret")
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    ticket = session_handoff.encrypt_ticket_payload({"host": "app.example", "exp": 2420})
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=2000,
    )
    exchanged = store.exchange(code=record.code, public_host="app.example", now=2299)
    with pytest.raises(session_handoff.HandoffRejected):
        store.consume_ticket(ticket=exchanged, public_host="app.example", now=2419)
