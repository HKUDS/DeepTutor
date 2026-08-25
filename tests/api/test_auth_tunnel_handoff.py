"""Regression coverage for the Tailscale-to-Quick-Tunnel auth handoff."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest_plugins = ["tests.multi_user.conftest"]


@pytest.fixture
def tunnel_file(mu_isolated_root) -> Path:
    from deeptutor.multi_user import paths

    path = paths.SYSTEM_ROOT / "auth" / "deeptutor_tunnel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def clean_tickets():
    from deeptutor.services.tunnel_handoff import clear_tickets

    clear_tickets()
    yield
    clear_tickets()


@pytest.fixture
def handoff_client(mu_isolated_root, monkeypatch, tunnel_file):
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    tunnel_file.write_text(
        json.dumps({"url": "https://example-deep.trycloudflare.com"}),
        encoding="utf-8",
    )
    payload = TokenPayload(username="alice", role="admin", user_id="u_alice")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "_COOKIE_MAX_AGE", 30 * 24 * 60 * 60)
    monkeypatch.setattr(auth_router, "decode_token", lambda _: payload)
    monkeypatch.setattr(
        auth_router, "create_token", lambda username, role, user_id: f"{username}:{role}:{user_id}"
    )

    app = FastAPI()

    @app.middleware("http")
    async def simulate_local_proxy(request, call_next):
        request.scope["client"] = ("127.0.0.1", 50000)
        return await call_next(request)

    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app)


def test_tunnel_state_accepts_only_https_quick_tunnel_hosts(tunnel_file):
    from deeptutor.services.tunnel_handoff import load_tunnel_state

    valid = [
        "https://example-deep.trycloudflare.com",
        "https://a-b.trycloudflare.com/",
    ]
    invalid = [
        "http://example-deep.trycloudflare.com",
        "https://example-deep.trycloudflare.com:8443",
        "https://user@example-deep.trycloudflare.com",
        "https://example-deep.trycloudflare.com?x=1",
        "https://example-deep.evil.com",
        "https://.trycloudflare.com",
        "not-a-url",
    ]
    for url in valid:
        tunnel_file.write_text(json.dumps({"url": url}), encoding="utf-8")
        assert load_tunnel_state() is not None, url
    for url in invalid:
        tunnel_file.write_text(json.dumps({"url": url}), encoding="utf-8")
        assert load_tunnel_state() is None, url


def test_handoff_requires_authentication(handoff_client):
    response = handoff_client.post("/api/v1/auth/handoff")
    assert response.status_code == 401


def test_handoff_is_single_use_and_bound_to_current_tunnel_host(handoff_client):
    headers = {"Authorization": "Bearer session-token"}
    created = handoff_client.post("/api/v1/auth/handoff", headers=headers)
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    body = created.json()
    assert body["tunnel_url"] == "https://example-deep.trycloudflare.com"
    assert len(body["code"]) >= 40

    second = handoff_client.post("/api/v1/auth/handoff", headers=headers)
    assert second.status_code == 200
    second_code = second.json()["code"]

    target_headers = {"x-deeptutor-frontend-host": "wrong-host.trycloudflare.com"}
    wrong_host = handoff_client.post(
        "/api/v1/auth/handoff/consume",
        data={"code": body["code"]},
        headers=target_headers,
        follow_redirects=False,
    )
    assert wrong_host.status_code == 400

    target_headers["x-deeptutor-frontend-host"] = "example-deep.trycloudflare.com"
    consumed = handoff_client.post(
        "/api/v1/auth/handoff/consume",
        data={"code": second_code},
        headers=target_headers,
        follow_redirects=False,
    )
    assert consumed.status_code == 303
    assert consumed.headers["location"] == "/"
    assert "alice:admin:u_alice" in consumed.headers["set-cookie"]
    cookie = consumed.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=2592000" in cookie
    assert consumed.headers["cache-control"] == "no-store"
    assert consumed.headers["referrer-policy"] == "no-referrer"

    replay = handoff_client.post(
        "/api/v1/auth/handoff/consume",
        data={"code": second_code},
        headers=target_headers,
        follow_redirects=False,
    )
    assert replay.status_code == 400


def test_handoff_ticket_expires_after_sixty_seconds(tunnel_file):
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.tunnel_handoff import consume_ticket, create_ticket

    tunnel_file.write_text(
        json.dumps({"url": "https://example-deep.trycloudflare.com"}),
        encoding="utf-8",
    )
    code, state = create_ticket(TokenPayload("alice", "admin", "u_alice"), now=100)
    assert consume_ticket(code, state.host, now=160) is None


def test_proxy_headers_are_trusted_only_from_loopback_peers():
    from starlette.requests import Request

    import deeptutor.api.routers.auth as auth_router

    def request_for(peer_host: str, *, ip: str, host: str) -> Request:
        return Request(
            scope={
                "type": "http",
                "headers": [
                    (b"x-deeptutor-client-ip", ip.encode()),
                    (b"x-deeptutor-frontend-host", host.encode()),
                ],
                "client": (peer_host, 50000),
                "scheme": "http",
                "server": ("example.internal", 80),
                "path": "/",
                "query_string": b"",
            }
        )

    forged = request_for(
        "203.0.113.10",
        ip="198.51.100.10",
        host="attacker.trycloudflare.com",
    )
    assert auth_router._request_client_ip(forged) == "203.0.113.10"
    assert auth_router._request_host(forged) == "example.internal"

    proxied = request_for(
        "127.0.0.1",
        ip="198.51.100.10",
        host="example-deep.trycloudflare.com",
    )
    assert auth_router._request_client_ip(proxied) == "198.51.100.10"
    assert auth_router._request_host(proxied) == "example-deep.trycloudflare.com"
