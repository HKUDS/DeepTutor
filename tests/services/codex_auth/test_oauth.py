from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from deeptutor.services.codex_auth.constants import (
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_SCOPE,
)
from deeptutor.services.codex_auth.contracts import CodexAuthError, CodexCredentials
from deeptutor.services.codex_auth.oauth import (
    CodexOAuthClient,
    LoopbackCallback,
    OAuthCallbackResult,
    PkceCodes,
    build_authorize_url,
    generate_pkce,
)


async def _send_get(port: int, target: str) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {target} HTTP/1.1\r\nHost: localhost:{port}\r\nConnection: close\r\n\r\n".encode()
    )
    await writer.drain()
    response = (await reader.read()).decode("utf-8", errors="replace")
    writer.close()
    await writer.wait_closed()
    return response


class _EagerReader:
    async def readuntil(self, _separator: bytes) -> bytes:
        return (
            b"GET /auth/callback?code=eager-code&state=eager-state HTTP/1.1\r\n"
            b"Host: localhost\r\n\r\n"
        )


class _EagerWriter:
    def __init__(self) -> None:
        self.response = bytearray()

    def write(self, data: bytes) -> None:
        self.response.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class _EagerSocket:
    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", 1455)


class _EagerServer:
    def __init__(self, handler: object) -> None:
        self._handler = handler
        self.sockets = [_EagerSocket()]

    async def start_serving(self) -> None:
        await self._handler(_EagerReader(), _EagerWriter())  # type: ignore[operator]

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def _pause_callback_close(
    callback: LoopbackCallback,
) -> tuple[asyncio.Event, asyncio.Event]:
    original_close = callback._close
    close_started = asyncio.Event()
    release_close = asyncio.Event()

    async def blocked_close() -> None:
        close_started.set()
        await release_close.wait()
        await original_close()

    callback._close = blocked_close  # type: ignore[method-assign]
    return close_started, release_close


def _credentials() -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id="account-123",
        expires_at=2_000_000_000,
        generation=1,
    )


def test_authorize_url_matches_audited_codex_contract() -> None:
    pkce = PkceCodes(verifier="v" * 64, challenge="challenge")
    url = build_authorize_url(
        redirect_uri="http://localhost:1455/auth/callback",
        state="state-123",
        pkce=pkce,
    )
    query = parse_qs(urlsplit(url).query)

    assert query["client_id"] == [CODEX_OAUTH_CLIENT_ID]
    assert query["scope"] == [CODEX_OAUTH_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state-123"]
    assert query["id_token_add_organizations"] == ["true"]
    assert query["codex_cli_simplified_flow"] == ["true"]
    assert query["originator"] == ["codex_cli_rs"]


def test_generated_pkce_is_url_safe_and_self_consistent() -> None:
    first = generate_pkce()
    second = generate_pkce()

    assert 43 <= len(first.verifier) <= 128
    assert "=" not in first.verifier
    assert "=" not in first.challenge
    assert first != second


@pytest.mark.asyncio
async def test_loopback_accepts_callback_without_echoing_secrets() -> None:
    callback = await LoopbackCallback.start(ports=(0,))

    response = await _send_get(
        callback.port,
        "/auth/callback?code=secret-code&state=expected",
    )
    result = await callback.wait(timeout=1)

    assert result.code == "secret-code"
    assert result.state == "expected"
    assert result.error is None
    assert "200 OK" in response
    assert "secret-code" not in response
    assert "expected" not in response


@pytest.mark.asyncio
async def test_loopback_submit_wakes_waiter_and_rejects_late_delivery() -> None:
    callback = await LoopbackCallback.start(ports=(0,))
    waiter = asyncio.create_task(callback.wait(timeout=1))
    result = OAuthCallbackResult(
        code="authorization-code",
        state="expected-state",
        error=None,
    )

    callback.submit(result)

    assert await waiter == result
    with pytest.raises(CodexAuthError) as exc_info:
        callback.submit(result)
    assert exc_info.value.code == "login_not_active"
    assert exc_info.value.http_status == 409


@pytest.mark.asyncio
async def test_loopback_does_not_serve_before_callback_closure_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def eager_start_server(
        handler: object,
        _hosts: object,
        _port: int,
        *,
        start_serving: bool = True,
    ) -> _EagerServer:
        server = _EagerServer(handler)
        if start_serving:
            await server.start_serving()
        return server

    monkeypatch.setattr(asyncio, "start_server", eager_start_server)

    callback = await LoopbackCallback.start(ports=(0,))
    result = await callback.wait(timeout=1)

    assert result == OAuthCallbackResult(
        code="eager-code",
        state="eager-state",
        error=None,
    )


@pytest.mark.asyncio
async def test_loopback_ignores_wrong_path_then_accepts_oauth_error() -> None:
    callback = await LoopbackCallback.start(ports=(0,))

    response = await _send_get(callback.port, "/wrong?code=do-not-accept")
    assert "404 Not Found" in response
    result_task = asyncio.create_task(callback.wait(timeout=1))
    await asyncio.sleep(0)
    assert not result_task.done()

    await _send_get(
        callback.port,
        "/auth/callback?error=access_denied&state=expected",
    )
    result = await result_task
    assert result.code is None
    assert result.error == "access_denied"
    assert result.state == "expected"


@pytest.mark.asyncio
async def test_loopback_rejects_invalid_state_then_accepts_correct_callback() -> None:
    callback = await LoopbackCallback.start(ports=(0,), expected_state="expected-state")
    waiter = asyncio.create_task(callback.wait(timeout=1))

    invalid_targets = (
        "/auth/callback?code=wrong-code&state=wrong-state",
        "/auth/callback?code=missing-state",
        "/auth/callback?code=unicode-state&state=snowman-%E2%98%83",
        f"/auth/callback?code=long-state&state={'a' * 129}",
        "/auth/callback?code=repeated-state&state=expected-state&state=expected-state",
    )
    for target in invalid_targets:
        response = await _send_get(callback.port, target)
        assert "400 Bad Request" in response
        assert not waiter.done()

    response = await _send_get(
        callback.port,
        "/auth/callback?code=correct-code&state=expected-state",
    )
    result = await waiter

    assert "200 OK" in response
    assert result == OAuthCallbackResult(
        code="correct-code",
        state="expected-state",
        error=None,
    )


@pytest.mark.asyncio
async def test_loopback_returns_conflict_when_callback_cannot_be_submitted() -> None:
    callback = await LoopbackCallback.start(ports=(0,), expected_state="expected-state")
    first = OAuthCallbackResult(
        code="first-code",
        state="expected-state",
        error=None,
    )
    callback.submit(first)

    response = await _send_get(
        callback.port,
        "/auth/callback?code=second-code&state=expected-state",
    )

    assert "409 Conflict" in response
    assert "200 OK" not in response
    assert await callback.wait(timeout=1) == first


@pytest.mark.asyncio
async def test_loopback_falls_back_when_first_port_is_occupied() -> None:
    occupied = await asyncio.start_server(lambda _reader, _writer: None, "127.0.0.1", 0)
    occupied_port = int(occupied.sockets[0].getsockname()[1])
    callback = await LoopbackCallback.start(ports=(occupied_port, 0))
    try:
        assert callback.hosts[0] == "127.0.0.1"
        assert all(host in {"127.0.0.1", "::1"} for host in callback.hosts)
        assert callback.port != occupied_port
    finally:
        await callback.cancel()
        occupied.close()
        await occupied.wait_closed()


@pytest.mark.asyncio
async def test_loopback_timeout_and_cancel_are_public_errors() -> None:
    timed_out = await LoopbackCallback.start(ports=(0,))
    with pytest.raises(CodexAuthError) as timeout_error:
        await timed_out.wait(timeout=0.01)
    assert timeout_error.value.code == "login_timeout"
    assert f"localhost:{timed_out.port}" in timeout_error.value.public_message
    assert "did not receive" in timeout_error.value.public_message

    cancelled = await LoopbackCallback.start(ports=(0,))
    waiter = asyncio.create_task(cancelled.wait(timeout=1))
    await asyncio.sleep(0)
    await cancelled.cancel()
    with pytest.raises(CodexAuthError) as cancel_error:
        await waiter
    assert cancel_error.value.code == "login_cancelled"
    with pytest.raises(CodexAuthError) as late_submit:
        cancelled.submit(OAuthCallbackResult(code="late-code", state="late-state", error=None))
    assert late_submit.value.code == "login_not_active"
    assert late_submit.value.http_status == 409


@pytest.mark.asyncio
async def test_loopback_timeout_stops_submit_before_close_finishes() -> None:
    callback = await LoopbackCallback.start(ports=(0,))
    close_started, release_close = _pause_callback_close(callback)
    waiter = asyncio.create_task(callback.wait(timeout=0.01))
    await asyncio.wait_for(close_started.wait(), timeout=1)

    with pytest.raises(CodexAuthError) as exc_info:
        callback.submit(OAuthCallbackResult(code="too-late", state="too-late", error=None))

    assert exc_info.value.code == "login_not_active"
    release_close.set()
    with pytest.raises(CodexAuthError) as timeout_error:
        await waiter
    assert timeout_error.value.code == "login_timeout"


@pytest.mark.asyncio
async def test_loopback_wait_cancellation_stops_submit_before_close_finishes() -> None:
    callback = await LoopbackCallback.start(ports=(0,))
    close_started, release_close = _pause_callback_close(callback)
    waiter = asyncio.create_task(callback.wait(timeout=1))
    await asyncio.sleep(0)
    waiter.cancel()
    await asyncio.wait_for(close_started.wait(), timeout=1)

    with pytest.raises(CodexAuthError) as exc_info:
        callback.submit(OAuthCallbackResult(code="too-late", state="too-late", error=None))

    assert exc_info.value.code == "login_not_active"
    release_close.set()
    with pytest.raises(asyncio.CancelledError):
        await waiter


@pytest.mark.asyncio
async def test_loopback_cancel_stops_submit_before_close_finishes() -> None:
    callback = await LoopbackCallback.start(ports=(0,))
    close_started, release_close = _pause_callback_close(callback)
    cancel_task = asyncio.create_task(callback.cancel())
    await asyncio.wait_for(close_started.wait(), timeout=1)

    with pytest.raises(CodexAuthError) as exc_info:
        callback.submit(OAuthCallbackResult(code="too-late", state="too-late", error=None))

    assert exc_info.value.code == "login_not_active"
    release_close.set()
    await cancel_task


@pytest.mark.asyncio
async def test_oauth_http_requests_match_exchange_refresh_and_revoke_contracts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "id_token": "new-id",
                "expires_in": 3600,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CodexOAuthClient(http)
        exchanged = await client.exchange_code(
            code="authorization-code",
            redirect_uri="http://localhost:1455/auth/callback",
            verifier="verifier",
        )
        refreshed = await client.refresh("refresh-secret")
        await client.revoke(_credentials())

    exchange_body = parse_qs(requests[0].content.decode())
    assert requests[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert exchange_body == {
        "client_id": [CODEX_OAUTH_CLIENT_ID],
        "grant_type": ["authorization_code"],
        "code": ["authorization-code"],
        "redirect_uri": ["http://localhost:1455/auth/callback"],
        "code_verifier": ["verifier"],
    }
    assert json.loads(requests[1].content) == {
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": "refresh-secret",
    }
    revoke_body = parse_qs(requests[2].content.decode())
    assert revoke_body == {
        "client_id": [CODEX_OAUTH_CLIENT_ID],
        "token": ["refresh-secret"],
        "token_type_hint": ["refresh_token"],
    }
    assert exchanged["access_token"] == "new-access"
    assert refreshed["refresh_token"] == "new-refresh"


@pytest.mark.asyncio
async def test_oauth_http_failure_does_not_echo_upstream_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="private-upstream-detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CodexOAuthClient(http)
        with pytest.raises(CodexAuthError) as exc_info:
            await client.refresh("refresh-secret")

    assert exc_info.value.code == "token_refresh_failed"
    assert "private-upstream-detail" not in str(exc_info.value)
    assert "refresh-secret" not in str(exc_info.value)
