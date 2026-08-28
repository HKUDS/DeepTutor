"""Regression coverage for the Tailscale-to-Quick-Tunnel auth handoff."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def tunnel_file(mu_isolated_root) -> Path:
    from deeptutor.multi_user import paths

    path = paths.SYSTEM_ROOT / "auth" / "deeptutor_tunnel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def clean_tickets():
    from deeptutor.services.tunnel_handoff import clear_pairings, clear_tickets

    clear_tickets()
    clear_pairings()
    yield
    clear_tickets()
    clear_pairings()


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
    monkeypatch.setattr(
        auth_router,
        "load_auth_settings",
        lambda: {"cookie_secure": False, "private_login_hosts": ["100.101.207.44"]},
    )
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


def test_handoff_pairing_requires_authentication(handoff_client):
    response = handoff_client.post("/api/v1/auth/handoff/pairing")
    assert response.status_code == 401


def test_handoff_pairing_flow_is_single_use_and_burns_after_exchange(handoff_client):
    headers = {"Authorization": "Bearer session-token"}
    created = handoff_client.post("/api/v1/auth/handoff/pairing", headers=headers)
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    data = created.json()
    assert "pairing_id" in data
    assert data["expires_in"] == 120
    pairing_id = data["pairing_id"]
    assert len(pairing_id) >= 40

    # Unauthenticated phone can exchange the pairing ID for a fresh 60s ticket
    exchanged = handoff_client.get(f"/api/v1/auth/handoff/pairing/{pairing_id}")
    assert exchanged.status_code == 200
    assert exchanged.headers["cache-control"] == "no-store"
    ticket_data = exchanged.json()
    assert ticket_data["tunnel_url"] == "https://example-deep.trycloudflare.com"
    assert ticket_data["expires_in"] == 60
    assert len(ticket_data["code"]) >= 40

    # Replay on pairing ID is rejected (single-use)
    replay = handoff_client.get(f"/api/v1/auth/handoff/pairing/{pairing_id}")
    assert replay.status_code == 400

    # Target host can consume the resulting code
    target_headers = {"x-deeptutor-frontend-host": "example-deep.trycloudflare.com"}
    consumed = handoff_client.post(
        "/api/v1/auth/handoff/consume",
        data={"code": ticket_data["code"]},
        headers=target_headers,
        follow_redirects=False,
    )
    assert consumed.status_code == 303
    assert "alice:admin:u_alice" in consumed.headers["set-cookie"]


def test_password_login_is_private_network_only(handoff_client, monkeypatch):
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    monkeypatch.setattr(
        auth_router,
        "authenticate",
        lambda username, password: TokenPayload(username, "admin", "u_alice"),
    )

    public = handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "example-deep.trycloudflare.com"},
    )
    assert public.status_code == 403

    private = handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "100.101.207.44:3782"},
    )
    assert private.status_code == 200


def test_registration_is_private_network_only(handoff_client):
    public = handoff_client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "password-123"},
        headers={"x-deeptutor-frontend-host": "example-deep.trycloudflare.com"},
    )
    assert public.status_code == 403


def test_handoff_pairing_expires_after_120_seconds(tunnel_file):
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.tunnel_handoff import create_pairing, exchange_pairing

    pairing_id, ttl = create_pairing(TokenPayload("alice", "admin", "u_alice"), now=100)
    assert ttl == 120
    assert exchange_pairing(pairing_id, now=221) is None


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


def test_extension_handoff_sets_redirect_and_declared_cookie(handoff_client):
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.tunnel_handoff import HandoffCookie, SessionHandoff, create_pairing

    payload = TokenPayload("alice", "admin", "u_alice")
    handoff = SessionHandoff(
        redirect_path="/video-learning?viewer_session=session-1",
        cookies=(
            HandoffCookie(
                name="dt_video_controller",
                value="session-1:controller-secret",
                path="/",
                max_age=12 * 60 * 60,
            ),
        ),
    )
    pairing_id, _ = create_pairing(payload, handoff=handoff)
    exchanged = handoff_client.get(f"/api/v1/auth/handoff/pairing/{pairing_id}")
    assert exchanged.status_code == 200
    ticket = exchanged.json()

    consumed = handoff_client.post(
        "/api/v1/auth/handoff/consume",
        data={"code": ticket["code"]},
        headers={"x-deeptutor-frontend-host": "example-deep.trycloudflare.com"},
        follow_redirects=False,
    )
    assert consumed.status_code == 303
    assert consumed.headers["location"] == "/video-learning?viewer_session=session-1"
    cookies = consumed.headers.get_list("set-cookie")
    assert any("dt_video_controller=session-1:controller-secret" in cookie for cookie in cookies)
    controller_cookie = next(
        cookie for cookie in cookies if "dt_video_controller=session-1" in cookie
    ).lower()
    assert "path=/" in controller_cookie
    assert "httponly" in controller_cookie
    assert "secure" in controller_cookie
    assert "samesite=lax" in controller_cookie
    assert "max-age=43200" in controller_cookie

    replay = handoff_client.get(f"/api/v1/auth/handoff/pairing/{pairing_id}")
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


def test_handoff_rejects_untrusted_redirects_and_cookie_values(tunnel_file):
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.tunnel_handoff import HandoffCookie, SessionHandoff, create_pairing

    payload = TokenPayload("alice", "admin", "u_alice")
    invalid = [
        SessionHandoff(redirect_path="https://example.com"),
        SessionHandoff(redirect_path="//example.com"),
        SessionHandoff(redirect_path="/path#fragment"),
        SessionHandoff(cookies=(HandoffCookie("bad name", "value"),)),
        SessionHandoff(cookies=(HandoffCookie("dt_cookie", "bad;value"),)),
        SessionHandoff(cookies=(HandoffCookie("dt_cookie", "value", path="?path"),)),
        SessionHandoff(cookies=(HandoffCookie("dt_cookie", "value", max_age=0),)),
    ]
    for handoff in invalid:
        with pytest.raises(ValueError):
            create_pairing(payload, handoff=handoff)

    valid = SessionHandoff(
        redirect_path="/video-learning",
        cookies=(HandoffCookie("dt_video_controller", "session-1:secret", max_age=60),),
    )
    assert create_pairing(payload, handoff=valid)[0]


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


def test_password_login_is_fail_closed_on_unknown_or_corrupted_tunnel_state(handoff_client, monkeypatch, tunnel_file):
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    monkeypatch.setattr(
        auth_router,
        "authenticate",
        lambda username, password: TokenPayload(username, "admin", "u_alice"),
    )
    monkeypatch.setattr(
        auth_router,
        "load_auth_settings",
        lambda: {"private_login_hosts": ["100.101.207.44"], "cookie_secure": False},
    )

    # Tunnel file removed / corrupted
    tunnel_file.unlink(missing_ok=True)

    # Allowed: configured Tailscale host and implicit loopback
    assert handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "100.101.207.44:3782"},
    ).status_code == 200

    assert handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "localhost:3782"},
    ).status_code == 200

    assert handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "127.0.0.1:3782"},
    ).status_code == 200

    # Rejected: unknown public hosts, trycloudflare domains, empty hosts
    assert handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "attacker.com"},
    ).status_code == 403

    assert handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": "any-subdomain.trycloudflare.com"},
    ).status_code == 403

    assert handoff_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "password"},
        headers={"x-deeptutor-frontend-host": ""},
    ).status_code == 403


def test_learning_activation_is_private_network_only(handoff_client):
    public = handoff_client.post(
        "/api/v1/auth/activate-learning",
        json={"username": "alice", "password": "password-123", "code": "ACT-1234"},
        headers={"x-deeptutor-frontend-host": "example-deep.trycloudflare.com"},
    )
    assert public.status_code == 403


def test_proxy_client_ip_rejects_malformed_or_forged_ips():
    from starlette.requests import Request

    import deeptutor.api.routers.auth as auth_router

    def req(ip_hdr: str) -> Request:
        return Request(
            scope={
                "type": "http",
                "headers": [(b"x-deeptutor-client-ip", ip_hdr.encode())],
                "client": ("127.0.0.1", 50000),
                "scheme": "http",
                "server": ("example.internal", 80),
                "path": "/",
                "query_string": b"",
            }
        )

    assert auth_router._request_client_ip(req("203.0.113.195")) == "203.0.113.195"
    assert auth_router._request_client_ip(req("2001:db8::1")) == "2001:db8::1"
    # Non-IP garbage / injection fallback to peer host 127.0.0.1
    assert auth_router._request_client_ip(req("invalid-ip-string")) == "127.0.0.1"
    assert auth_router._request_client_ip(req("1.2.3.4; DROP TABLE")) == "127.0.0.1"


def test_session_handoff_strictly_validates_security_boundaries(tunnel_file):
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.tunnel_handoff import HandoffCookie, SessionHandoff, create_pairing

    payload = TokenPayload("alice", "admin", "u_alice")

    # Cannot set or clear dt_token
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(cookies=(HandoffCookie("dt_token", "val", max_age=60),)))
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(clear_cookie_names=("dt_token",)))

    # Cannot duplicate cookie names or set & clear same name
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(cookies=(
            HandoffCookie("c1", "val1", max_age=60),
            HandoffCookie("c1", "val2", max_age=60),
        )))
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(
            cookies=(HandoffCookie("c1", "val1", max_age=60),),
            clear_cookie_names=("c1",),
        ))

    # Reject backslash and encoded backslash in redirect path
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(redirect_path="/path\evil"))
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(redirect_path="/path%5cevil"))
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(redirect_path="/\evil"))

    # Reject path with whitespace or semicolons in cookie path
    with pytest.raises(ValueError):
        create_pairing(payload, handoff=SessionHandoff(cookies=(HandoffCookie("c1", "val", path="/path; secure", max_age=60),)))


def test_default_handoff_clears_dt_video_controller(handoff_client):
    headers = {"Authorization": "Bearer session-token"}
    created = handoff_client.post("/api/v1/auth/handoff", headers=headers)
    assert created.status_code == 200
    code = created.json()["code"]

    consumed = handoff_client.post(
        "/api/v1/auth/handoff/consume",
        data={"code": code},
        headers={"x-deeptutor-frontend-host": "example-deep.trycloudflare.com"},
        follow_redirects=False,
    )
    assert consumed.status_code == 303
    cookies = consumed.headers.get_list("set-cookie")
    # dt_video_controller is cleared by delete_cookie (Max-Age=0 or expires in the past)
    assert any("dt_video_controller=" in c and ("max-age=0" in c.lower() or "1970" in c) for c in cookies)
