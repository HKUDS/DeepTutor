"""Exercise Studio device login, rotation and model requests through the real clients."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import stat

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.deeptutor_account import DeepTutorAccount
from deeptutor.services.deeptutor_account.catalog import PROFILE_ID, preserve_managed_profile
from deeptutor.services.deeptutor_account.client import DeepTutorAccountError, GatewayClient
from deeptutor.services.deeptutor_account.storage import DeviceStore
from deeptutor.services.llm.provider_core.deeptutor_provider import DeepTutorProvider

BASE = "https://studio.test/api/gateway/v1"
MODEL = "o3-opaque/9x41"
ROOT = "/api/gateway/v1"
MESSAGES = [
    {"role": "system", "content": "Stable instructions."},
    {"role": "user", "content": "Earlier question."},
    {"role": "assistant", "content": "Earlier answer."},
    {"role": "user", "content": "Reply with OK."},
]


def tokens(serial=0):
    return {
        "device": {"id": "link-1"},
        "access_token": f"access-{serial}",
        "refresh_token": f"refresh-{serial}",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


def catalog_row(model, capabilities, *, available=True):
    return {
        "id": model,
        "model_serve": {
            "label": f"Label for {model}",
            "capabilities": capabilities,
            "available": available,
        },
    }


class Gateway:
    def __init__(self):
        self.challenge = ""
        self.poll_errors: list[str] = []
        self.refreshes = 0
        self.lose_refresh_response = False
        self.revoke = False
        self.logouts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "studio.test"
        path = request.url.path.removeprefix(ROOT)
        if path == "/device/start":
            data = json.loads(request.content)
            assert data["client_id"] == "deeptutor"
            self.challenge = data["code_challenge"]
            return httpx.Response(
                201,
                json={
                    "device_code": "device-flow",
                    "user_code": "TEST-CODE",
                    "verification_uri": "https://studio.test/account/device",
                    "verification_uri_complete": "https://studio.test/account/device?code=TEST-CODE",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        if path == "/device/token":
            data = json.loads(request.content)
            assert data["device_code"] == "device-flow"
            assert data["client_id"] == "deeptutor"
            assert 43 <= len(data["code_verifier"]) <= 128
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            assert challenge == self.challenge
            if self.poll_errors:
                return httpx.Response(200, json={"error": self.poll_errors.pop(0)})
            return httpx.Response(
                200,
                json={
                    **tokens(),
                    "cloud": {"public_url": "https://studio.test"},
                    "user": {"id": "u1", "email": "user@example.test", "name": "Learner"},
                    "account": {"id": "a1", "name": "Learner's account"},
                },
            )
        if path == "/device/refresh":
            data = json.loads(request.content)
            assert data["refresh_token"] in {"refresh-0", "refresh-1"}
            self.refreshes += 1
            if self.lose_refresh_response and self.refreshes == 1:
                raise httpx.ReadTimeout("simulated response loss", request=request)
            if self.revoke:
                return httpx.Response(401, json={"detail": {"code": "invalid_grant"}})
            return httpx.Response(200, json=tokens(self.refreshes))
        if path == "/device/logout":
            self.logouts.append(json.loads(request.content)["refresh_token"])
            return httpx.Response(200, json={"ok": True})
        if path == "/models":
            assert request.headers["Authorization"].startswith("Bearer access-")
            return httpx.Response(
                200,
                json={
                    "data": [
                        catalog_row(MODEL, ["chat", "vision", "tools"]),
                        catalog_row("unavailable", ["chat"], available=False),
                        catalog_row("embeddings", ["embedding"]),
                        catalog_row("@llm", ["chat", "tools"]),
                    ]
                },
            )
        if path == "/account":
            return httpx.Response(
                200,
                json={
                    "credit": {
                        "micro_per_credit": 100,
                        "pools": {"paid": {"available_micro_credits": 75}},
                    }
                },
            )
        raise AssertionError(f"Unexpected path: {path}")


@pytest.fixture()
def studio(tmp_path):
    gateway = Gateway()
    catalog = ModelCatalogService(tmp_path / "model_catalog.json")
    account = DeepTutorAccount(
        DeviceStore(tmp_path), catalog, GatewayClient(httpx.MockTransport(gateway))
    )
    return account, gateway


async def sign_in(account: DeepTutorAccount):
    started = await account.start(BASE, device_label="Test laptop")
    await account.finish(replace(started, interval=0.001))
    await account.cancel(started)


@pytest.mark.asyncio
async def test_device_login_publishes_only_callable_chat_models(studio):
    account, gateway = studio
    await sign_in(account)
    assert (await account.status())["state"] == "connected"
    if os.name == "posix":
        assert stat.S_IMODE(account.store.path.stat().st_mode) == 0o600
    models = await account.refresh_models()
    assert [(row["id"], row["available"]) for row in models] == [
        (MODEL, True),
        ("unavailable", False),
    ]
    await account.refresh_balance()
    status = await account.status()
    assert status["paid_balance"] == 0.75
    assert "access_token" not in json.dumps(status)
    assert "refresh_token" not in json.dumps(status)
    live = account.catalog.load()
    service = live["services"]["llm"]
    assert service["active_profile_id"] == PROFILE_ID
    profile = account.catalog.get_active_profile(live, "llm")
    assert profile["api_key"] == ""
    assert profile["owner_bound"] is True
    assert len(profile["models"]) == 1
    assert profile["models"][0]["capabilities"]["vision"] is True

    draft = {"services": {"llm": {"profiles": [], "active_profile_id": PROFILE_ID}}}
    preserve_managed_profile(live, draft)
    assert draft["services"]["llm"]["active_model_id"] == service["active_model_id"]

    await account.logout()
    assert gateway.logouts == ["refresh-0"]
    assert await account.status() == {"state": "idle"}
    assert not account.store.path.exists()
    assert account.catalog.get_active_profile(account.catalog.load(), "llm") is None


@pytest.mark.asyncio
async def test_poll_increases_interval_and_persists_terminal_state(studio, monkeypatch):
    account, gateway = studio
    gateway.poll_errors = ["authorization_pending", "slow_down", "access_denied"]
    started = await account.start(BASE)
    delays = []

    async def record_delay(delay):
        delays.append(delay)

    monkeypatch.setattr("deeptutor.services.deeptutor_account.asyncio.sleep", record_delay)
    with pytest.raises(DeepTutorAccountError, match="declined") as exc:
        await account.finish(started)
    assert delays == [5, 5, 10]
    await account.cancel(started, error=exc.value)
    status = await account.status()
    assert status["state"] == "error"
    assert status["error_code"] == "access_denied"
    assert "user_code" not in status


@pytest.mark.asyncio
async def test_pending_device_state_and_cancel_are_shared_by_workers(studio):
    account, gateway = studio
    started = await account.start(BASE)
    other_worker = DeepTutorAccount(
        DeviceStore(account.store.root.parent.parent), account.catalog, account.gateway
    )
    status = await other_worker.status()
    assert status["user_code"] == started.user_code
    assert started.verifier not in account.store.path.read_text()
    await other_worker.cancel()
    with pytest.raises(DeepTutorAccountError, match="connection changed"):
        await account.finish(replace(started, interval=0.001))
    assert await account.status() == {"state": "idle"}
    assert gateway.logouts == []


@pytest.mark.asyncio
async def test_refresh_is_single_flight_across_stores_and_clears_revoked_login(studio):
    account, gateway = studio
    await sign_in(account)
    await account.refresh_models()
    previous = await account.access()
    other_worker = DeepTutorAccount(
        DeviceStore(account.store.root.parent.parent), account.catalog, account.gateway
    )
    access = await asyncio.gather(
        account.access(previous, force_refresh=True),
        other_worker.access(previous, force_refresh=True),
    )
    assert [item.token for item in access] == ["access-1", "access-1"]
    assert gateway.refreshes == 1
    gateway.revoke = True
    with pytest.raises(DeepTutorAccountError, match="sign-in has ended"):
        await account.access(access[0], force_refresh=True)
    assert await account.status() == {"state": "idle"}
    assert account.catalog.get_active_profile(account.catalog.load(), "llm") is None


@pytest.mark.asyncio
async def test_refresh_response_loss_can_be_recovered(studio):
    account, gateway = studio
    await sign_in(account)
    original = await account.access()
    gateway.lose_refresh_response = True
    updated = await account.access(original, force_refresh=True)
    assert gateway.refreshes == 2
    assert updated.token == "access-2"
    assert (await account.access()).token == updated.token
    assert "refresh_started_at" not in account.store.path.read_text()


@pytest.mark.asyncio
async def test_stale_uncertain_refresh_never_replays_to_gateway(studio):
    account, gateway = studio
    await sign_in(account)
    with account.store.locked():
        state = account.store.load()
        state["credentials"]["refresh_started_at"] = 1
        account.store.save(state)

    with pytest.raises(DeepTutorAccountError, match="sign-in has ended"):
        await account.access()
    assert gateway.refreshes == 0
    assert await account.status() == {"state": "idle"}


async def provider_with_transport(account, handler):
    provider = DeepTutorProvider(MODEL, account=account)
    await provider.aclose()
    provider._client = AsyncOpenAI(
        api_key="placeholder",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return provider


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_model_uses_studio_chat_protocol_and_refreshes_only_once(studio, stream):
    account, gateway = studio
    await sign_in(account)
    requests = []
    usage = {
        "prompt_tokens": 20,
        "completion_tokens": 1,
        "total_tokens": 21,
        "prompt_tokens_details": {"cached_tokens": 12},
    }

    def handler(request):
        assert str(request.url) == f"{BASE}/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == MODEL
        assert body["max_tokens"] == 4096
        assert "max_completion_tokens" not in body
        assert "temperature" not in body
        assert "deeptutor_session_id" not in body
        assert 1 <= request.content.count(b"cache_control") <= 4
        requests.append((request.headers["Authorization"], body["prompt_cache_key"]))
        if len(requests) == 1:
            return httpx.Response(
                401, json={"error": {"message": "expired", "code": "token_expired"}}
            )
        assert request.headers["Authorization"] == "Bearer access-1"
        if not stream:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "OK", "role": "assistant"}, "finish_reason": "stop"}
                    ],
                    "usage": usage,
                },
            )
        assert body["stream_options"] == {"include_usage": True}
        chunk = {"choices": [{"index": 0, "delta": {"content": "OK"}, "finish_reason": "stop"}]}
        sse = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps({'choices': [], 'usage': usage})}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse)

    provider = await provider_with_transport(account, handler)
    try:
        send = provider.chat_stream if stream else provider.chat
        result = await send(messages=MESSAGES, deeptutor_session_id="session-1")
        assert result.content == "OK"
        assert result.usage["cache_read_input_tokens"] == 12
        assert requests[0][0] == "Bearer access-0"
        assert requests[0][1] == requests[1][1]
        assert gateway.refreshes == 1
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_credit_error_preserves_code_and_action_without_gateway_message(studio):
    account, _gateway = studio
    await sign_in(account)

    def handler(_request):
        return httpx.Response(
            402, json={"error": {"message": "raw upstream response", "code": "insufficient_credit"}}
        )

    provider = await provider_with_transport(account, handler)
    try:
        with pytest.raises(DeepTutorAccountError) as exc:
            await provider.chat_stream(messages=MESSAGES)
        assert exc.value.error_code == "insufficient_credit"
        assert exc.value.action_url == "https://studio.test/account/credits"
        assert "raw upstream response" not in str(exc.value)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_rate_limited_model_respects_retry_after(studio, monkeypatch):
    account, gateway = studio
    await sign_in(account)
    delays = []
    requests = []

    async def record_delay(delay):
        delays.append(delay)

    def handler(request):
        requests.append(request.headers["Authorization"])
        return httpx.Response(
            429, headers={"Retry-After": "9"}, json={"error": {"code": "rate_limit"}}
        )

    monkeypatch.setattr("deeptutor.services.deeptutor_account.asyncio.sleep", record_delay)
    provider = await provider_with_transport(account, handler)
    try:
        with pytest.raises(DeepTutorAccountError, match="rate limiting") as exc:
            await provider.chat(messages=MESSAGES)
        assert exc.value.retry_after == 9
        assert delays == [9]
        assert requests == ["Bearer access-0", "Bearer access-0"]
        assert gateway.refreshes == 0
    finally:
        await provider.aclose()
