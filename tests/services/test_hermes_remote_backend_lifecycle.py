"""Lifecycle and configuration tests for the remote Hermes backend."""

from __future__ import annotations

import json
from typing import Any

import anyio
import httpx
import pytest

from deeptutor.services.subagent.config import BackendConfig, settings_from_dict
from deeptutor.services.subagent.hermes_remote import HermesRemoteBackend
from deeptutor.services.subagent.hermes_remote_client import (
    HermesRemoteClient,
    HermesRemoteProtocolError,
)
from deeptutor.services.subagent.types import EVENT_ERROR, EVENT_LOG
from tests.services.test_hermes_remote_backend import _backend, _HermesTransport


@pytest.mark.asyncio
async def test_approval_is_denied_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport(
        events=[
            {"event": "approval.request", "tool": "exec"},
            {"event": "run.completed", "output": "finished"},
        ],
    )
    backend = _backend(transport, auto_approve=False)
    emitted: list[Any] = []

    async def on_event(event: Any) -> None:
        emitted.append(event)

    result = await backend.consult("question", on_event=on_event, config=backend.config)
    assert result.success is True
    assert result.final_text == "finished"
    assert transport.approvals == [{"choice": "deny"}]
    assert any(event.kind == EVENT_LOG and "denied" in event.text for event in emitted)


@pytest.mark.asyncio
async def test_consult_http_error_never_leaks_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "synthetic-secret"
    monkeypatch.setenv("TEST_HERMES_KEY", secret)

    def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid token {secret}")

    backend = _backend(httpx.MockTransport(unauthorized))
    emitted: list[Any] = []

    async def on_event(event: Any) -> None:
        emitted.append(event)

    result = await backend.consult("question", on_event=on_event, config=backend.config)
    assert result.success is False
    assert emitted[-1].kind == EVENT_ERROR
    assert secret not in emitted[-1].text
    assert secret not in result.error


@pytest.mark.asyncio
async def test_cancellation_posts_stop_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport()
    transport.blocking = True
    backend = _backend(transport)
    cancellation: list[BaseException] = []

    async def on_event(_: Any) -> None:
        return None

    async def run_consult() -> None:
        try:
            await backend.consult("question", on_event=on_event, config=backend.config)
        except BaseException as exc:  # noqa: BLE001 - assert cancellation propagation
            cancellation.append(exc)
            raise

    async with anyio.create_task_group() as group:
        group.start_soon(run_consult)
        await transport.block_started.wait()
        group.cancel_scope.cancel()

    assert cancellation
    assert isinstance(cancellation[0], anyio.get_cancelled_exc_class())
    assert transport.stops == ["run-1"]


@pytest.mark.asyncio
async def test_idle_timeout_stops_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport()
    transport.blocking = True
    backend = HermesRemoteBackend(
        config=BackendConfig(
            base_url="http://hermes.test",
            api_key_env="TEST_HERMES_KEY",
            idle_timeout_seconds=0,
        ),
        transport=httpx.MockTransport(transport),
    )
    emitted: list[Any] = []

    async def on_event(event: Any) -> None:
        emitted.append(event)

    result = await backend.consult("question", on_event=on_event, config=backend.config)
    assert result.success is False
    assert "idle_timeout" in result.error
    assert emitted[-1].kind == EVENT_ERROR
    assert transport.stops == ["run-1"]


@pytest.mark.asyncio
async def test_missing_session_history_starts_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport(
        events=[{"event": "run.completed", "output": "fresh"}],
        history_status=404,
    )
    backend = _backend(transport)

    async def on_event(_: Any) -> None:
        return None

    config = BackendConfig(
        base_url="http://hermes.test",
        api_key_env="TEST_HERMES_KEY",
        system_prompt="reapply this instruction",
    )
    result = await backend.consult(
        "question",
        on_event=on_event,
        session_id="session-gone",
        config=config,
    )
    body = json.loads(transport.requests[1].content)
    assert result.success is True
    assert result.session_id == "run-1"
    assert transport.requests[0].url.path == "/api/sessions/session-gone/messages"
    assert "session_id" not in body
    assert "x-hermes-session-id" not in transport.requests[1].headers
    assert "x-hermes-session" not in transport.requests[1].headers
    assert "conversation_history" not in body
    assert body["instructions"].startswith("reapply this instruction")


def test_settings_persist_remote_fields_without_inline_secret() -> None:
    settings = settings_from_dict(
        {
            "backends": {
                "hermes_remote": {
                    "base_url": " http://hermes.test ",
                    "api_key_env": " TEST_HERMES_KEY ",
                    "profile": "study",
                    "idle_timeout_seconds": "42",
                    "api_key": "must-never-persist",
                },
            },
        },
    )
    config = settings.backend("hermes_remote")
    serialized = settings.to_dict()["backends"]["hermes_remote"]
    assert config.base_url == "http://hermes.test"
    assert config.api_key_env == "TEST_HERMES_KEY"
    assert config.profile == "study"
    assert config.idle_timeout_seconds == 42
    assert "api_key" not in serialized
    assert serialized["api_key_env"] == "TEST_HERMES_KEY"

    assert (
        settings_from_dict({"backends": {"hermes_remote": {"idle_timeout_seconds": 0}}})
        .backend("hermes_remote")
        .idle_timeout_seconds
        == 1
    )
    assert (
        settings_from_dict({"backends": {"hermes_remote": {"idle_timeout_seconds": 100_000}}})
        .backend("hermes_remote")
        .idle_timeout_seconds
        == 86_400
    )

    local_serialized = settings_from_dict({"backends": {"codex": {"model": "gpt-5.6"}}}).to_dict()[
        "backends"
    ]["codex"]
    assert "base_url" not in local_serialized
    assert "api_key_env" not in local_serialized


@pytest.mark.asyncio
async def test_redirect_response_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")

    def redirect(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://attacker.example.test"},
            json={"run_id": "must-not-be-accepted"},
        )

    backend = _backend(httpx.MockTransport(redirect))

    async def on_event(_: Any) -> None:
        return None

    result = await backend.consult("question", on_event=on_event, config=backend.config)
    assert result.success is False
    assert result.error == "http_302"


@pytest.mark.asyncio
async def test_stream_without_terminal_event_is_not_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    backend = _backend(_HermesTransport(events=[{"event": "message.delta", "delta": "partial"}]))

    async def on_event(_: Any) -> None:
        return None

    result = await backend.consult("question", on_event=on_event, config=backend.config)
    assert result.final_text == "partial"
    assert result.success is False
    assert result.error == "incomplete_stream"


@pytest.mark.asyncio
async def test_sse_comments_surface_as_quiet_keepalives() -> None:
    def stream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b': ping\n\ndata: {"event":"run.completed","output":"done"}\n\n',
        )

    async with HermesRemoteClient(
        "http://hermes.test",
        "synthetic-secret",
        transport=httpx.MockTransport(stream),
    ) as client:
        events = [event async for event in client.stream_events("run-1")]

    assert events == [
        {"event": "gateway.keepalive"},
        {"event": "run.completed", "output": "done"},
    ]


@pytest.mark.asyncio
async def test_detect_remote_backend_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "object": "hermes.api_server.capabilities",
                "model": "hermes",
                "features": {
                    "run_submission": True,
                    "run_events_sse": True,
                    "run_stop": True,
                    "run_approval_response": True,
                    "session_resources": True,
                },
            },
        ),
    )
    backend = HermesRemoteBackend(
        config=BackendConfig(base_url="http://hermes.test", api_key_env="TEST_HERMES_KEY"),
        transport=transport,
    )
    assert backend.local_cli is False
    assert backend.detectable is True
    result = await backend.detect()
    assert result.available is True


@pytest.mark.asyncio
async def test_client_preserves_multi_profile_url_prefix() -> None:
    requests: list[httpx.Request] = []

    def capabilities(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async with HermesRemoteClient(
        "https://hermes.test/p/study",
        "synthetic-secret",
        transport=httpx.MockTransport(capabilities),
    ) as client:
        await client.get_json("/v1/capabilities")

    assert requests[0].url.path == "/p/study/v1/capabilities"


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///etc/passwd",
        "https://user:secret@hermes.test",
        "https://hermes.test?key=secret",
        "https://hermes.test#fragment",
        "https://hermes.test:invalid",
    ],
)
def test_client_rejects_unsafe_or_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(HermesRemoteProtocolError, match="invalid_base_url"):
        HermesRemoteClient(base_url, "synthetic-secret")


@pytest.mark.asyncio
async def test_invalid_remote_identifiers_never_reach_request_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport(events=[{"event": "run.completed", "output": "done"}])
    backend = _backend(transport)

    async def on_event(_: Any) -> None:
        return None

    invalid_session = await backend.consult(
        "question",
        on_event=on_event,
        session_id="bad/session\r\nheader",
        config=backend.config,
    )
    assert invalid_session.success is False
    assert invalid_session.error == "invalid_session_id"
    assert transport.requests == []

    def invalid_run(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/runs":
            return httpx.Response(202, json={"run_id": "bad/run"})
        return httpx.Response(404)

    bad_run = _backend(httpx.MockTransport(invalid_run))
    invalid_result = await bad_run.consult(
        "question",
        on_event=on_event,
        config=bad_run.config,
    )
    assert invalid_result.success is False
    assert invalid_result.error == "missing_run_id"
