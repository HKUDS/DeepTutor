"""Loopback, token rotation, and Responses contracts for ChatGPT plan usage."""

import asyncio
import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api import chatgpt_plan_origin
from deeptutor.services import chatgpt_plan
from deeptutor.services.chatgpt_plan_context import request_scope
from deeptutor.services.llm.exceptions import LLMChatGPTPlanUsageLimit
from deeptutor.services.llm.provider_core import chatgpt_plan_provider


def test_desktop_session_requires_a_shell_header_and_strips_it(monkeypatch):
    token = "a" * 43
    origin = "http://127.0.0.1:18802"
    monkeypatch.setenv("DEEPTUTOR_CHATGPT_PLAN_SESSION", token)
    readiness_key = "b" * 64
    monkeypatch.setenv("DEEPTUTOR_DESKTOP_READY_KEY", readiness_key)
    monkeypatch.setattr(chatgpt_plan_origin, "_session_token", None)
    monkeypatch.setattr(chatgpt_plan_origin, "_readiness_key", None)
    assert chatgpt_plan_origin.configure_desktop_request_auth()
    challenge = "c" * 64
    assert (
        chatgpt_plan_origin.desktop_ready_proof(challenge)
        == hmac.new(readiness_key.encode(), challenge.encode(), "sha256").hexdigest()
    )
    assert chatgpt_plan_origin.desktop_ready_proof("") is None

    app = FastAPI()
    app.add_middleware(chatgpt_plan_origin.DesktopOriginMiddleware, origin=origin)

    @app.api_route("/test", methods=["GET", "POST"])
    async def status(request: Request):
        return {
            "desktop": chatgpt_plan_origin.is_desktop_frontend(request.scope),
            "header_forwarded": "x-deeptutor-desktop-session" in request.headers,
        }

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        await ws.send_json(chatgpt_plan_origin.is_desktop_frontend(ws.scope))

    client = TestClient(app)
    valid = {"origin": origin, "x-deeptutor-desktop-session": token}
    assert client.post("/test", headers=valid).json() == {
        "desktop": True,
        "header_forwarded": False,
    }
    assert client.get("/test", headers={"x-deeptutor-desktop-session": token}).json()["desktop"]
    assert not client.get("/test", headers={"origin": origin}).json()["desktop"]
    assert not client.post("/test", headers={"x-deeptutor-desktop-session": token}).json()[
        "desktop"
    ]
    wrong_origin = client.post("/test", headers={**valid, "origin": "https://example.test"})
    assert wrong_origin.status_code == 200
    assert wrong_origin.json() == {"desktop": False, "header_forwarded": False}
    with client.websocket_connect("/ws", headers={"origin": origin}) as ws:
        assert ws.receive_json() is False
    with client.websocket_connect("/ws", headers=valid) as ws:
        assert ws.receive_json() is True

    monkeypatch.setenv("DEEPTUTOR_CHATGPT_PLAN_SESSION", token)
    assert not chatgpt_plan_origin.configure_desktop_request_auth()
    assert chatgpt_plan_origin.desktop_ready_proof(challenge) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refresh_status", "error", "connected"),
    [
        (400, "invalid_grant", False),
        (503, "invalid_grant", True),
        (400, "invalid_client", True),
    ],
)
async def test_resource_rejection_clears_only_confirmed_invalid_grants(
    tmp_path, monkeypatch, refresh_status, error, connected
):
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())
    active = {
        "client_id": "selected",
        "credentials": dict(
            access_token="old",
            refresh_token="first",
            expires_at=10**12,
            scope=chatgpt_plan.USAGE_SCOPE,
        ),
    }
    session._save(
        dict(
            active="selected",
            accounts={"selected": active, "other": {"credentials": {"access_token": "other"}}},
        )
    )

    def response(request):
        if request.url.path == "/v1/models":
            return httpx.Response(401, json={"detail": "authentication failed"})
        assert str(request.url) == chatgpt_plan.TOKEN_URL
        return httpx.Response(refresh_status, json={"error": error})

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        chatgpt_plan.httpx,
        "AsyncClient",
        lambda **_: factory(transport=httpx.MockTransport(response)),
    )
    expected = "connection_failed" if connected else "login_required"
    with pytest.raises(chatgpt_plan.PlanError, match=expected):
        await session.models()
    status = session.status()
    assert status["connected"] is connected
    assert status["sharing"] is connected
    assert status["error"] == (None if connected else "login_required")
    assert status["accounts"][1]["connected"]
    assert session._load()["accounts"]["selected"]["client_id"] == "selected"


@pytest.mark.asyncio
async def test_disconnect_retries_transient_failure_then_clears_local_credentials(
    tmp_path, monkeypatch
):
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())
    session._save(dict(client_id="selected", credentials={"refresh_token": "fixture"}))
    calls = []

    def response(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200, json={"revocation_endpoint": f"{chatgpt_plan.ISSUER}/revoke"}
            )
        assert request.url.path == "/revoke"
        assert not session.status()["connected"]
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200)

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        chatgpt_plan.httpx,
        "AsyncClient",
        lambda **_: factory(transport=httpx.MockTransport(response)),
    )
    assert await session.disconnect()
    assert len(calls) == 2
    assert not session.status()["connected"]


@pytest.mark.asyncio
async def test_revocation_retry_after_reopen_cannot_reuse_the_saved_grant(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", key)
    session._save(
        dict(
            client_id="fixture",
            credentials=dict(
                access_token="access", refresh_token="refresh", scope=chatgpt_plan.USAGE_SCOPE
            ),
        )
    )
    account = session.status()["active_account_id"]

    async def failed(token, client_id):
        assert (token, client_id) == ("refresh", "fixture")
        return False

    monkeypatch.setattr(session, "_revoke", failed)
    assert not await session.disconnect()
    reopened = chatgpt_plan.PlanSession(session.path, key)
    assert reopened.status()["accounts"][0]["revocation_pending"]
    assert reopened.status()["error"] == "revoke_unconfirmed"
    with pytest.raises(chatgpt_plan.PlanError, match="login_required"):
        await reopened.access_token()
    with pytest.raises(chatgpt_plan.PlanError, match="revoke_unconfirmed"):
        await reopened.start(account_id=account)

    async def no_exchange(*args):
        pytest.fail("pending revocation must be rejected before the OAuth exchange")

    monkeypatch.setattr(reopened, "_exchange", no_exchange)
    params = parse_qs(urlsplit(await reopened.start(add=True)).query)
    assert await reopened.complete(
        urlsplit(params["redirect_uri"][0]).netloc,
        {"state": params["state"], "code": ["unused"], "client_id": ["fixture"]},
    )
    assert reopened.status()["accounts"][0]["revocation_pending"]

    async def revoked(token, client_id):
        assert (token, client_id) == ("refresh", "fixture")
        return True

    monkeypatch.setattr(reopened, "_revoke", revoked)
    assert await reopened.disconnect(account_id=account)
    assert not reopened.status()["accounts"][0]["revocation_pending"]
    assert not reopened.status()["connected"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "expected"),
    [({}, chatgpt_plan.SCOPES), ({"scope": "openid"}, "openid"), ({"scope": ""}, "")],
)
async def test_token_exchange_scope_defaults_only_when_omitted(
    tmp_path, monkeypatch, fields, expected
):
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())
    factory = httpx.AsyncClient
    monkeypatch.setattr(
        chatgpt_plan.httpx,
        "AsyncClient",
        lambda **_: factory(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"access_token": "fixture", **fields})
            )
        ),
    )
    result = await session._exchange({"grant_type": "authorization_code"}, chatgpt_plan.SCOPES)
    assert result["scope"] == expected


@pytest.mark.asyncio
async def test_loopback_accepts_one_callback_and_keeps_credentials_out_of_status(
    tmp_path, monkeypatch
):
    key = Fernet.generate_key().decode()
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", key)
    attempts = []

    async def exchange(data, scope):
        assert scope == chatgpt_plan.SCOPES
        attempts.append(data)
        return {
            "access_token": "only-in-vault",
            "scope": chatgpt_plan.USAGE_SCOPE,
            "id_token": "fixture-identity",
            "expires_at": 10**12,
            "refresh_token": "refresh-fixture",
        }

    async def identity(token, audience, nonce):
        assert token == "fixture-identity"
        assert audience == "oaiapp_fixture"
        assert nonce == params["nonce"][0]
        return {"sub": "fixture", "email": "learner@example.test"}

    monkeypatch.setattr(session, "_exchange", exchange)
    monkeypatch.setattr(session, "_identity", identity)
    url = await session.start()
    params = parse_qs(urlsplit(url).query)
    redirect = params["redirect_uri"][0]
    assert params["client_id"] == ["dynamic_agent_client"]
    assert urlsplit(redirect).hostname == "127.0.0.1"
    async with httpx.AsyncClient(trust_env=False) as client:
        accepted = {"state": params["state"][0], "code": "sample", "client_id": "oaiapp_fixture"}
        bad = await client.get(redirect, params={**accepted, "state": "wrong"})
        assert bad.status_code == 400 and not attempts
        assert session.status()["pending"]
        good = await client.get(redirect, params=accepted)
        assert good.status_code == 200
    assert len(attempts) == 1
    assert attempts[0]["redirect_uri"] == redirect
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(attempts[0]["code_verifier"].encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert params["code_challenge"] == [expected_challenge]
    status = session.status()
    assert status["connected"] and status["sharing"] and status["show_welcome"]
    assert status["account"] == "learner@example.test"
    assert status["active_account_id"] == status["accounts"][0]["id"]
    assert not status["pending"] and status["error"] is None
    await session.dismiss_welcome()
    assert b"only-in-vault" not in session.path.read_bytes()
    assert await session.access_token() == "only-in-vault"
    reopened = chatgpt_plan.PlanSession(session.path, key)
    assert reopened.status()["connected"]
    assert not reopened.status()["show_welcome"]
    next_url = await session.start()
    assert parse_qs(urlsplit(next_url).query)["client_id"] == ["oaiapp_fixture"]
    await session.cancel()
    assert session.status()["connected"]


@pytest.mark.asyncio
async def test_denial_never_exchanges_code(tmp_path, monkeypatch):
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())

    async def no_exchange(data, scope):
        pytest.fail("denial must not exchange tokens")

    monkeypatch.setattr(session, "_exchange", no_exchange)
    params = parse_qs(urlsplit(await session.start()).query)
    host = urlsplit(params["redirect_uri"][0]).netloc
    assert await session.complete(host, {"error": ["access_denied"], "state": params["state"]})
    assert session.status()["error"] == "authorization_denied"
    with pytest.raises(chatgpt_plan.PlanError, match="login_required"):
        await session.access_token()


@pytest.mark.asyncio
async def test_saved_workspaces_are_isolated_and_switch_only_on_verified_callback(
    tmp_path, monkeypatch
):
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())
    session._save(
        dict(
            client_id="first-client",
            host_id="urn:uuid:fixture",
            subject="same-sub",
            account="learner@example.test",
            credentials=dict(
                access_token="first", expires_at=10**12, scope=chatgpt_plan.USAGE_SCOPE
            ),
        )
    )
    old_id = session.status()["active_account_id"]

    async def exchange(data, scope):
        return dict(
            access_token=data["client_id"], expires_at=10**12, scope=chatgpt_plan.USAGE_SCOPE
        )

    async def identity(*args):
        return {"sub": "same-sub", "email": "learner@example.test"}

    monkeypatch.setattr(session, "_exchange", exchange)
    monkeypatch.setattr(session, "_identity", identity)
    new = parse_qs(urlsplit(await session.start(add=True, label="Study workspace")).query)
    assert new["client_id"] == ["dynamic_agent_client"]
    assert new["ext_agent_host_id"] == ["urn:uuid:fixture"]
    assert await session.access_token() == "first"
    assert await session.complete(
        urlsplit(new["redirect_uri"][0]).netloc,
        {"state": new["state"], "code": ["sample"], "client_id": ["second-client"]},
    )
    status = session.status()
    assert [row["label"] for row in status["accounts"]] == [
        "learner@example.test",
        "Study workspace",
    ]
    assert await session.access_token() == "second-client"
    assert status["active_account_id"] != old_id
    with request_scope(True, account_id=old_id):
        with pytest.raises(chatgpt_plan.PlanError, match="request_account_changed"):
            await session.access_token()
    returning = parse_qs(urlsplit(await session.start(account_id=old_id)).query)
    assert returning["client_id"] == ["first-client"]
    assert "agent_name_hint" not in returning
    assert await session.complete(
        urlsplit(returning["redirect_uri"][0]).netloc,
        {"state": returning["state"], "error": ["access_denied"]},
    )
    assert session.status()["active_account_id"] == status["active_account_id"]
    returning = parse_qs(urlsplit(await session.start(account_id=old_id)).query)
    assert await session.complete(
        urlsplit(returning["redirect_uri"][0]).netloc,
        {"state": returning["state"], "code": ["sample"]},
    )
    assert session.status()["active_account_id"] == old_id
    assert await session.access_token() == "first-client"
    assert not await session.disconnect()
    assert not session.status()["connected"]
    assert session.status()["accounts"][1]["connected"]


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["rotated", None])
async def test_cancelled_request_waits_for_refreshed_credentials(
    tmp_path, monkeypatch, replacement
):
    session = chatgpt_plan.PlanSession(
        tmp_path / "plan.enc", Fernet.generate_key().decode(), loop=asyncio.get_running_loop()
    )
    session._save(
        dict(
            client_id="oaiapp_fixture",
            credentials={
                "access_token": "old",
                "refresh_token": "old",
                "expires_at": 0,
                "scope": chatgpt_plan.USAGE_SCOPE,
            },
        )
    )
    started, finish = asyncio.Event(), asyncio.Event()
    refreshes = []

    async def exchange(data, scope):
        refreshes.append(data["refresh_token"])
        started.set()
        await finish.wait()
        return dict(
            access_token="replacement", refresh_token=replacement, scope=scope, expires_at=10**12
        )

    monkeypatch.setattr(session, "_exchange", exchange)
    first = asyncio.create_task(session.access_token())
    await started.wait()
    first.cancel()
    second = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(session.access_token())))
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second == "replacement"
    assert session._load()["accounts"]["oaiapp_fixture"]["credentials"]["refresh_token"] == (
        replacement or "old"
    )
    assert refreshes == ["old"]


@pytest.mark.asyncio
async def test_refresh_resumes_after_jwks_outage_without_returning_an_expired_token(
    tmp_path, monkeypatch
):
    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())
    session._save(
        dict(
            client_id="fixture",
            subject="account",
            pending_refresh=True,
            credentials=dict(
                access_token="expired",
                refresh_token="retained",
                id_token="old-id",
                expires_at=0,
                scope=chatgpt_plan.USAGE_SCOPE,
            ),
        )
    )

    async def unreachable(*args, **kwargs):
        raise httpx.ConnectTimeout("fixture")

    monkeypatch.setattr(session, "_identity", unreachable)
    with pytest.raises(httpx.ConnectTimeout):
        await session.access_token()
    assert session.status()["connected"]

    async def identity(token, audience, nonce, *, allow_expired):
        assert (token, audience, nonce, allow_expired) == ("old-id", "fixture", None, True)
        return {"sub": "account", "exp": 0}

    async def exchange(data, scope):
        assert data["refresh_token"] == "retained"
        return dict(access_token="fresh", refresh_token="rotated", expires_at=10**12, scope=scope)

    monkeypatch.setattr(session, "_identity", identity)
    monkeypatch.setattr(session, "_exchange", exchange)
    assert await session.access_token() == "fresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False, "limit"])
async def test_provider_uses_restricted_responses_and_requires_completion(monkeypatch, complete):
    class Session:
        async def access_token(self):
            return "mock-token"

    def handle(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer mock-token"
        payload = json.loads(request.content)
        assert payload == {
            "model": "fixture-model",
            "store": False,
            "stream": True,
            "input": [{"role": "developer", "content": "Guide"}, {"role": "user", "content": "Hi"}],
        }
        events = 'data: {"type":"response.output_text.delta","delta":"Hi!"}\n\n'
        if complete == "limit":
            events += (
                'data: {"type":"error","code":"subscription_sharing_usage_limit_exceeded"}\n\n'
            )
        elif complete:
            events += 'data: {"type":"response.completed","response":{"status":"completed","usage":{"total_tokens":9}}}\n\n'
        return httpx.Response(200, text=events)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(chatgpt_plan, "get_session", Session)
    monkeypatch.setattr(chatgpt_plan_provider.httpx, "AsyncClient", lambda **kwargs: http_client)
    provider = chatgpt_plan_provider.ChatGPTPlanProvider("fixture-model")
    messages = [{"role": "system", "content": "Guide"}, {"role": "user", "content": "Hi"}]
    denied = await provider.chat(messages)
    assert denied.finish_reason == "error"
    assert "Desktop chat" in denied.content
    with request_scope(True):
        from deeptutor.services.model_selection.tasks import TaskKind, task_llm_scope

        with task_llm_scope(TaskKind.SESSION_TITLE):
            background = await provider.chat(messages)
            assert background.finish_reason == "error"
            assert background.content == denied.content
        if complete == "limit":
            with pytest.raises(LLMChatGPTPlanUsageLimit):
                await provider.chat(messages)
            return
        result = await provider.chat(messages, temperature=0.5, max_tokens=100)
    if complete:
        assert result.content == "Hi!"
        assert result.usage["total_tokens"] == 9
    else:
        assert result.finish_reason == "error"
        assert result.content != "Hi!"


@pytest.mark.asyncio
async def test_id_token_requires_signature_audience_and_nonce(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwt

    session = chatgpt_plan.PlanSession(tmp_path / "plan.enc", Fernet.generate_key().decode())
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    numbers = private.public_key().public_numbers()

    def encoded(num):
        return (
            base64.urlsafe_b64encode(num.to_bytes((num.bit_length() + 7) // 8, "big"))
            .decode()
            .rstrip("=")
        )

    def jwks(request):
        assert str(request.url) == "https://auth.openai.com/.well-known/jwks.json"
        return httpx.Response(
            200,
            json={
                "keys": [
                    {
                        "alg": "RS256",
                        "kty": "RSA",
                        "kid": "test",
                        "n": encoded(numbers.n),
                        "e": encoded(numbers.e),
                    }
                ]
            },
        )

    client_factory = httpx.AsyncClient
    http_client = client_factory(transport=httpx.MockTransport(jwks))
    monkeypatch.setattr(chatgpt_plan.httpx, "AsyncClient", lambda **kwargs: http_client)
    identity = {
        "iss": chatgpt_plan.ISSUER,
        "sub": "persona",
        "aud": "oaiapp_test",
        "nonce": "nonce",
        "exp": 2200000000,
    }
    token = jwt.encode(identity, key, algorithm="RS256", headers={"kid": "test"})
    assert (await session._identity(token, "oaiapp_test", "nonce"))["sub"] == "persona"
    http_client = client_factory(transport=httpx.MockTransport(jwks))
    with pytest.raises(chatgpt_plan.PlanError, match="invalid_identity"):
        await session._identity(token, "different-client", "nonce")
    http_client = client_factory(transport=httpx.MockTransport(jwks))
    with pytest.raises(chatgpt_plan.PlanError, match="invalid_identity"):
        await session._identity(token, "oaiapp_test", "different-nonce")
    expired = jwt.encode({**identity, "exp": 1}, key, algorithm="RS256", headers={"kid": "test"})
    http_client = client_factory(transport=httpx.MockTransport(jwks))
    with pytest.raises(chatgpt_plan.PlanError, match="invalid_identity"):
        await session._identity(expired, "oaiapp_test", "nonce")
    http_client = client_factory(transport=httpx.MockTransport(jwks))
    verified = await session._identity(expired, "oaiapp_test", None, allow_expired=True)
    assert verified["sub"] == "persona" and verified["exp"] == 1
