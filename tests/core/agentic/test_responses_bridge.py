"""Unit tests for the Responses API bridge on agentic clients."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.agentic.client import LLMClientConfig, build_openai_client
import deeptutor.core.agentic.responses_bridge as bridge_module
from deeptutor.core.agentic.responses_bridge import (
    ENV_USE_RESPONSES_API,
    build_responses_body,
    failure_counts_toward_breaker,
    reset_bridge_breaker,
    response_to_chat_shape,
    responses_events_to_chat_chunks,
    wrap_responses_bridge,
)


class _StatusError(Exception):
    """Exception carrying an HTTP status, like openai.APIStatusError."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status


def _evt(event_type: str, **attrs: Any) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, **attrs)


async def _agen(items: list[Any]) -> Any:
    for item in items:
        yield item


def _cloud_config() -> LLMClientConfig:
    return LLMClientConfig(
        binding="custom",
        model="gpt-5.6-terra",
        api_key="test-key",
        base_url="https://relay.example/v1",
    )


@pytest.fixture(autouse=True)
def _isolated_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_USE_RESPONSES_API, raising=False)
    reset_bridge_breaker()


# ---------------------------------------------------------------------------
# Activation policy
# ---------------------------------------------------------------------------


def test_env_off_returns_inner_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_USE_RESPONSES_API, "off")
    inner = SimpleNamespace()
    assert wrap_responses_bridge(inner, _cloud_config()) is inner


def test_env_on_forces_bridge_for_local_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_USE_RESPONSES_API, "on")
    config = LLMClientConfig(
        binding="ollama",
        model="local-model",
        api_key="test-key",
        base_url="http://127.0.0.1:11434/v1",
    )
    wrapped = wrap_responses_bridge(SimpleNamespace(), config)
    assert isinstance(wrapped, bridge_module._BridgeClient)


def test_auto_mode_skips_local_binding() -> None:
    config = LLMClientConfig(
        binding="ollama",
        model="local-model",
        api_key="test-key",
        base_url="http://127.0.0.1:11434/v1",
    )
    inner = SimpleNamespace()
    assert wrap_responses_bridge(inner, config) is inner


def test_auto_mode_wraps_cloud_binding() -> None:
    wrapped = wrap_responses_bridge(SimpleNamespace(), _cloud_config())
    assert isinstance(wrapped, bridge_module._BridgeClient)


def test_build_openai_client_returns_bridged_client() -> None:
    client = build_openai_client(_cloud_config())
    assert hasattr(client.chat.completions, "create")
    # Non-chat attributes delegate to the raw SDK client.
    assert hasattr(client, "responses")


# ---------------------------------------------------------------------------
# Request conversion
# ---------------------------------------------------------------------------


def test_body_merges_system_messages_and_drops_chat_kwargs() -> None:
    body = build_responses_body(
        {
            "model": "gemini-3.1-pro",
            "messages": [
                {"role": "system", "content": "base prompt"},
                {"role": "system", "content": [{"type": "text", "text": "extra"}]},
                {"role": "user", "content": "hi"},
            ],
            "temperature": 0.2,
            "max_tokens": 256,
            "stream_options": {"include_usage": True},
            "deeptutor_session_id": "sess-1",
        }
    )
    assert body["instructions"] == "base prompt\n\nextra"
    assert body["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]}
    ]
    assert body["max_output_tokens"] == 256
    assert body["temperature"] == 0.2
    assert "stream_options" not in body
    assert "deeptutor_session_id" not in body


def test_body_drops_temperature_for_reasoning_models() -> None:
    body = build_responses_body(
        {
            "model": "gpt-5.6-terra",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.3,
            "reasoning_effort": "high",
        }
    )
    assert "temperature" not in body
    assert body["reasoning"] == {"effort": "high"}


def test_body_converts_tools() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    body = build_responses_body(
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": tools,
        }
    )
    assert body["tools"] == [
        {
            "type": "function",
            "name": "web_search",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert body["tool_choice"] == "auto"


# ---------------------------------------------------------------------------
# Stream conversion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_conversion_shapes_and_usage() -> None:
    events = [
        _evt("response.output_text.delta", delta="Hello"),
        _evt("response.output_text.delta", delta=" world"),
        _evt("response.reasoning_summary_text.delta", delta="thinking"),
        _evt(
            "response.output_item.added",
            item=SimpleNamespace(
                type="function_call", call_id="call_1", id="fc_1", name="search"
            ),
        ),
        _evt("response.function_call_arguments.delta", call_id="call_1", delta='{"q'),
        _evt(
            "response.function_call_arguments.done",
            call_id="call_1",
            arguments='{"query": "deep tutor"}',
        ),
        _evt(
            "response.output_item.done",
            item=SimpleNamespace(
                type="function_call",
                call_id="call_1",
                name="search",
                arguments='{"query": "deep tutor"}',
            ),
        ),
        _evt(
            "response.completed",
            response=SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(
                    input_tokens=120,
                    output_tokens=30,
                    total_tokens=150,
                    input_tokens_details=SimpleNamespace(cached_tokens=96),
                ),
            ),
        ),
    ]

    chunks = [chunk async for chunk in responses_events_to_chat_chunks(events)]

    content = "".join(
        chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices
    )
    reasoning = "".join(
        chunk.choices[0].delta.reasoning_content or "" for chunk in chunks if chunk.choices
    )
    assert content == "Hello world"
    assert reasoning == "thinking"

    tool_chunks = [
        chunk.choices[0].delta.tool_calls
        for chunk in chunks
        if chunk.choices and chunk.choices[0].delta.tool_calls
    ]
    # Arguments buffered and emitted exactly once, with the full payload.
    assert len(tool_chunks) == 1
    call = tool_chunks[0][0]
    assert call.index == 0
    assert call.id == "call_1"
    assert call.function.name == "search"
    assert call.function.arguments == '{"query": "deep tutor"}'

    finish_chunk = next(
        chunk for chunk in chunks if chunk.choices and chunk.choices[0].finish_reason
    )
    assert finish_chunk.choices[0].finish_reason == "tool_calls"

    usage_frames = [chunk for chunk in chunks if not chunk.choices]
    assert len(usage_frames) == 1
    usage = usage_frames[-1].usage
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (
        120,
        30,
        150,
    )
    assert usage.prompt_tokens_details.cached_tokens == 96
    # Usage-only frame arrives last, matching Chat Completions ordering.
    assert chunks[-1] is usage_frames[-1]


@pytest.mark.asyncio
async def test_stream_error_event_raises() -> None:
    events = [_evt("error", error="boom")]
    with pytest.raises(RuntimeError, match="boom"):
        async for _ in responses_events_to_chat_chunks(events):
            pass


# ---------------------------------------------------------------------------
# Non-stream conversion
# ---------------------------------------------------------------------------


def test_nonstream_response_shape() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="Answer")],
            ),
            SimpleNamespace(
                type="function_call",
                call_id="call_9",
                name="calc",
                arguments='{"x": 1}',
            ),
        ],
        status="completed",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
    )
    shaped = response_to_chat_shape(response)
    choice = shaped.choices[0]
    assert choice.message.content == "Answer"
    assert choice.message.tool_calls[0].id == "call_9"
    assert choice.message.tool_calls[0].function.name == "calc"
    assert choice.finish_reason == "tool_calls"
    assert shaped.usage.prompt_tokens == 10


# ---------------------------------------------------------------------------
# Fallback + circuit breaker
# ---------------------------------------------------------------------------


class _FakeInnerFactory:
    def __init__(self, *, responses_error: Exception | None = None) -> None:
        self.responses_create_calls = 0
        self.chat_create_calls = 0
        self.last_chat_kwargs: dict[str, Any] | None = None
        self.last_body: dict[str, Any] | None = None
        self._responses_error = responses_error

    def build(self) -> Any:
        return SimpleNamespace(
            responses=SimpleNamespace(create=self._responses_create),
            chat=SimpleNamespace(completions=SimpleNamespace(create=self._chat_create)),
        )

    async def _responses_create(self, **body: Any) -> Any:
        self.responses_create_calls += 1
        self.last_body = body
        if self._responses_error is not None:
            raise self._responses_error
        if body.get("stream"):
            return _agen([_evt("response.output_text.delta", delta="hi")])
        return SimpleNamespace(output=[], status="completed", usage=None)

    async def _chat_create(self, **kwargs: Any) -> Any:
        self.chat_create_calls += 1
        self.last_chat_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback"))]
        )


def _bridge_over(factory: _FakeInnerFactory) -> Any:
    config = _cloud_config()
    return wrap_responses_bridge(factory.build(), config).chat.completions


@pytest.mark.asyncio
async def test_stream_success_produces_chunks_via_responses() -> None:
    factory = _FakeInnerFactory()
    completions = _bridge_over(factory)
    kwargs = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    stream = await completions.create(**kwargs)
    chunks = [chunk async for chunk in stream]
    assert factory.responses_create_calls == 1
    assert any(
        chunk.choices and chunk.choices[0].delta.content == "hi" for chunk in chunks
    )
    assert factory.chat_create_calls == 0


@pytest.mark.asyncio
async def test_failure_falls_back_then_breaker_skips_responses() -> None:
    factory = _FakeInnerFactory(responses_error=_StatusError(404, "no /responses"))
    completions = _bridge_over(factory)
    kwargs = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    first = await completions.create(**kwargs)
    assert first.choices[0].message.content == "fallback"
    second = await completions.create(**kwargs)
    assert second.choices[0].message.content == "fallback"
    # Two probes tripped the breaker.
    assert factory.responses_create_calls == 2

    third = await completions.create(**kwargs)
    assert third.choices[0].message.content == "fallback"
    assert factory.responses_create_calls == 2  # unchanged: direct chat only
    assert factory.chat_create_calls == 3


@pytest.mark.asyncio
async def test_success_resets_breaker_failures() -> None:
    factory = _FakeInnerFactory()
    completions = _bridge_over(factory)
    key = bridge_module._breaker_key("https://relay.example/v1", "m")
    bridge_module._record_bridge_failure(key)

    await completions.create(
        **{"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert bridge_module._bridge_failures.get(key) is None

@pytest.mark.asyncio
async def test_transient_503_never_trips_breaker() -> None:
    """Relay channel exhaustion (new-api 503) must not lock out /responses."""
    factory = _FakeInnerFactory(responses_error=_StatusError(503, "no channel"))
    completions = _bridge_over(factory)
    kwargs = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    for _ in range(5):
        result = await completions.create(**kwargs)
        assert result.choices[0].message.content == "fallback"

    # Every request still probes /responses — no 5-minute all-chat window.
    assert factory.responses_create_calls == 5
    assert factory.chat_create_calls == 5


def test_failure_classification_by_status() -> None:
    assert not failure_counts_toward_breaker(_StatusError(503, "no channel"))
    assert not failure_counts_toward_breaker(_StatusError(429, "rate limited"))
    assert not failure_counts_toward_breaker(_StatusError(500, "upstream"))
    assert not failure_counts_toward_breaker(RuntimeError("connection reset"))
    assert failure_counts_toward_breaker(_StatusError(404, "no endpoint"))
    assert failure_counts_toward_breaker(_StatusError(400, "bad request"))
    assert failure_counts_toward_breaker(_StatusError(401, "bad key"))
