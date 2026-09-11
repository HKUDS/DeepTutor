"""Behavioral tests for the remote Hermes Connected Agents backend."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any

import anyio
import httpx
import pytest

from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.hermes_remote import (
    CONSULT_ORIGIN_INSTRUCTION,
    HermesRemoteBackend,
)
from deeptutor.services.subagent.types import EVENT_TEXT, EVENT_TOOL, EVENT_TOOL_RESULT


class _BlockingStream(httpx.AsyncByteStream):
    def __init__(self, started: anyio.Event) -> None:
        self._started = started

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self._started.set()
        await anyio.sleep_forever()
        yield b""  # pragma: no cover


class _HermesTransport:
    def __init__(
        self,
        *,
        events: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        history_status: int = 200,
    ) -> None:
        self.events = events or []
        self.history = history or []
        self.history_status = history_status
        self.requests: list[httpx.Request] = []
        self.approvals: list[dict[str, Any]] = []
        self.stops: list[str] = []
        self.block_started = anyio.Event()
        self.blocking = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/v1/capabilities":
            return httpx.Response(
                200,
                json={
                    "object": "hermes.api_server.capabilities",
                    "model": "hermes-agent",
                    "features": {
                        "run_submission": True,
                        "run_events_sse": True,
                        "run_stop": True,
                        "run_approval_response": True,
                        "session_resources": True,
                    },
                },
            )
        if request.method == "GET" and path.endswith("/messages"):
            if self.history_status != 200:
                return httpx.Response(self.history_status)
            return httpx.Response(200, json={"object": "list", "data": self.history})
        if request.method == "POST" and path == "/v1/runs":
            return httpx.Response(202, json={"run_id": "run-1", "status": "started"})
        if request.method == "POST" and path.endswith("/approval"):
            self.approvals.append(json.loads(request.content))
            return httpx.Response(200, json={"resolved": 1})
        if request.method == "POST" and path.endswith("/stop"):
            self.stops.append(path.rsplit("/", 2)[-2])
            return httpx.Response(200, json={"status": "stopping"})
        if request.method == "GET" and path.endswith("/events"):
            if self.blocking:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    stream=_BlockingStream(self.block_started),
                )
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in self.events)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body.encode(),
            )
        return httpx.Response(404)


def _backend(
    transport: httpx.AsyncBaseTransport | _HermesTransport,
    *,
    auto_approve: bool = True,
) -> HermesRemoteBackend:
    actual = (
        httpx.MockTransport(transport) if isinstance(transport, _HermesTransport) else transport
    )
    return HermesRemoteBackend(
        config=BackendConfig(
            base_url="http://hermes.test",
            api_key_env="TEST_HERMES_KEY",
            auto_approve=auto_approve,
        ),
        transport=actual,
    )


@pytest.mark.asyncio
async def test_detect_distinguishes_configuration_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_HERMES_KEY", raising=False)
    missing_url = await HermesRemoteBackend(config=BackendConfig()).detect()
    missing_key = await HermesRemoteBackend(
        config=BackendConfig(base_url="http://hermes.test", api_key_env="TEST_HERMES_KEY"),
    ).detect()
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    invalid_url = await HermesRemoteBackend(
        config=BackendConfig(base_url="file:///etc/passwd", api_key_env="TEST_HERMES_KEY"),
    ).detect()
    invalid_key_env = await HermesRemoteBackend(
        config=BackendConfig(base_url="http://hermes.test", api_key_env="INVALID=NAME"),
    ).detect()

    def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    unauthorized_result = await _backend(httpx.MockTransport(unauthorized)).detect()

    def incompatible(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    incompatible_result = await _backend(httpx.MockTransport(incompatible)).detect()

    def unreachable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    unreachable_result = await _backend(httpx.MockTransport(unreachable)).detect()

    assert missing_url.detail == "not_configured"
    assert missing_key.detail == "key_missing"
    assert invalid_url.detail == "invalid_base_url"
    assert invalid_key_env.detail == "invalid_key_env"
    assert unauthorized_result.detail == "unauthorized"
    assert incompatible_result.detail == "incompatible"
    assert unreachable_result.detail == "unreachable"


@pytest.mark.asyncio
async def test_consult_streams_text_tools_and_session_continuity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport(
        events=[
            {"event": "message.delta", "delta": "Hello "},
            {"event": "tool.started", "tool": "read", "preview": "notes"},
            {"event": "tool.completed", "tool": "read", "error": False},
            {"event": "message.delta", "delta": "world"},
            {"event": "run.completed", "output": "Hello world"},
        ],
        history=[
            *({"role": "user", "content": f"turn-{index}"} for index in range(42)),
            {"role": "tool", "content": "omit this tool row"},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "latest answer"},
        ],
    )
    backend = _backend(transport)
    emitted: list[Any] = []

    async def on_event(event: Any) -> None:
        emitted.append(event)

    first = await backend.consult(
        "question",
        on_event=on_event,
        config=backend.config,
    )
    second = await backend.consult(
        "follow-up",
        on_event=on_event,
        session_id=first.session_id,
        config=BackendConfig(
            base_url="http://hermes.test",
            api_key_env="TEST_HERMES_KEY",
            system_prompt="must not be repeated",
        ),
    )
    first_body = json.loads(transport.requests[0].content)

    second_body = json.loads(transport.requests[3].content)
    assert first.success is True
    assert first.final_text == "Hello world"
    assert first.session_id == "run-1"
    assert second.session_id == "run-1"
    assert first_body["instructions"] == CONSULT_ORIGIN_INSTRUCTION
    assert CONSULT_ORIGIN_INSTRUCTION in first_body["instructions"]
    assert second_body["session_id"] == "run-1"
    assert second_body["instructions"] == CONSULT_ORIGIN_INSTRUCTION
    assert len(second_body["conversation_history"]) == 40
    assert second_body["conversation_history"][0] == {"role": "user", "content": "turn-3"}
    assert second_body["conversation_history"][-1] == {
        "role": "assistant",
        "content": "latest answer",
    }
    assert all(row["role"] in {"user", "assistant"} for row in second_body["conversation_history"])
    assert all(row["content"] for row in second_body["conversation_history"])
    assert "must not be repeated" not in second_body["instructions"]
    assert [event.kind for event in emitted[:4]] == [
        EVENT_TEXT,
        EVENT_TOOL,
        EVENT_TOOL_RESULT,
        EVENT_TEXT,
    ]
    assert emitted[0].meta["merge_id"] == "hermes_remote:final"


@pytest.mark.asyncio
async def test_consult_prepends_custom_system_prompt_on_fresh_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_HERMES_KEY", "synthetic-secret")
    transport = _HermesTransport(events=[{"event": "run.completed", "output": "done"}])
    backend = _backend(transport)

    async def on_event(_: Any) -> None:
        return None

    config = BackendConfig(
        base_url="http://hermes.test",
        api_key_env="TEST_HERMES_KEY",
        system_prompt="custom instruction",
        model="hermes-agent",
        effort="high",
    )
    result = await backend.consult(
        "question",
        on_event=on_event,
        config=config,
        images=["/private/deeptutor/secret-image.png"],
    )
    body = json.loads(transport.requests[0].content)
    assert result.success is True
    assert body["instructions"].startswith("custom instruction")
    assert CONSULT_ORIGIN_INSTRUCTION in body["instructions"]
    assert body["model"] == "hermes-agent"
    assert body["model_options"]["reasoning_effort"] == "high"
    assert "secret-image.png" not in json.dumps(body)
