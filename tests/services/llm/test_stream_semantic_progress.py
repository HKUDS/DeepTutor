"""Transport liveness is not generation progress (#2538).

``chat_stream`` bounds each Responses iterator read, so every event the SDK
yields starts another read deadline -- including lifecycle frames that carry
no answer, reasoning or tool output. A gateway emitting only those can hold a
turn open indefinitely while it produces nothing.

These tests pin a reporting-only slice: such a stretch is named in a warning,
and nothing else about the stream changes. The read deadline, the terminal
result and every caller callback stay exactly as they were.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from loguru import logger
import pytest

from deeptutor.services.llm.provider_core import (
    openai_compat_provider as provider_module,
)
from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name

_MESSAGES = [{"role": "user", "content": "Explain Fourier transform"}]

# One gap is a fraction of the reporting window; only a sustained run of
# lifecycle frames crosses it. ``asyncio.sleep`` is a lower bound, so a slower
# machine lengthens both sides of that ratio rather than flipping a verdict.
_GAP_S = 0.05
_SILENT_RUN = 14


class _PacedStream:
    """Yields events with a real gap between reads, so monotonic time advances."""

    def __init__(self, events: list[SimpleNamespace], gap: float) -> None:
        self._events = list(events)
        self._gap = gap

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        if self._gap:
            await asyncio.sleep(self._gap)
        return self._events.pop(0)


def _provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="test-key",
        api_base="https://gateway.example/v1",
        default_model="responses-only-model",
        spec=find_by_name("custom"),
        provider_name="custom",
        wire_api="responses",
    )


def _install(provider: OpenAICompatProvider, events, gap: float = 0.0) -> None:
    async def create(**_body):
        return _PacedStream(events, gap)

    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace()),
    )


@contextmanager
def _captured_warnings():
    """loguru does not reach pytest's caplog; add a sink of our own."""
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="WARNING",
    )
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def _lifecycle(count: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(type="response.in_progress") for _ in range(count)]


def _answer(text: str = "A Fourier transform decomposes a signal.") -> list[SimpleNamespace]:
    return [
        SimpleNamespace(type="response.output_text.delta", delta=text),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", usage=None),
        ),
    ]


@pytest.fixture
def short_report_window(monkeypatch):
    """A single gap stays under the window; a full silent run crosses it."""
    monkeypatch.setattr(provider_module, "_SEMANTIC_SILENCE_REPORT_S", 0.5, raising=False)


@pytest.mark.asyncio
async def test_lifecycle_only_stretch_is_reported_once(short_report_window) -> None:
    provider = _provider()
    _install(provider, _lifecycle(_SILENT_RUN) + _answer(), gap=_GAP_S)

    with _captured_warnings() as warnings:
        result = await provider.chat_stream(messages=_MESSAGES)

    assert len(warnings) == 1
    assert "response.in_progress" in warnings[0]
    # Reporting only: the turn still completes with its answer intact.
    assert result.content == "A Fourier transform decomposes a signal."
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_semantic_output_rearms_the_report(short_report_window) -> None:
    provider = _provider()
    events = (
        _lifecycle(_SILENT_RUN)
        + [SimpleNamespace(type="response.output_text.delta", delta="First. ")]
        + _lifecycle(_SILENT_RUN)
        + [SimpleNamespace(type="response.output_text.delta", delta="Second.")]
        + [
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(status="completed", usage=None),
            )
        ]
    )
    _install(provider, events, gap=_GAP_S)

    with _captured_warnings() as warnings:
        result = await provider.chat_stream(messages=_MESSAGES)

    assert len(warnings) == 2
    assert result.content == "First. Second."


@pytest.mark.asyncio
async def test_reasoning_output_counts_as_progress(short_report_window) -> None:
    """A long visible reasoning phase is productive, not a silent stretch."""
    provider = _provider()
    events = []
    for _ in range(3):
        events += _lifecycle(2)
        events.append(SimpleNamespace(type="response.reasoning_text.delta", delta="Think. "))
    events += _answer()
    _install(provider, events, gap=_GAP_S)

    with _captured_warnings() as warnings:
        result = await provider.chat_stream(messages=_MESSAGES)

    assert warnings == []
    assert result.reasoning_content == "Think. Think. Think. "


@pytest.mark.asyncio
async def test_tool_argument_output_counts_as_progress(short_report_window) -> None:
    provider = _provider()
    call = SimpleNamespace(type="function_call", id="fc_1", call_id="call_1", name="web_search")
    events = (
        _lifecycle(1)
        + [SimpleNamespace(type="response.output_item.added", item=call)]
        + _lifecycle(1)
        + [
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="fc_1",
                call_id="call_1",
                delta='{"query": "fourier"}',
            ),
            SimpleNamespace(type="response.output_item.done", item=call),
        ]
        + _lifecycle(1)
        + [
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(status="completed", usage=None),
            )
        ]
    )
    _install(provider, events, gap=_GAP_S)

    with _captured_warnings() as warnings:
        result = await provider.chat_stream(messages=_MESSAGES)

    assert warnings == []
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {"query": "fourier"}


@pytest.mark.asyncio
async def test_a_brisk_stream_is_never_reported(monkeypatch) -> None:
    """The window is a silence threshold, not a per-event tax."""
    monkeypatch.setattr(provider_module, "_SEMANTIC_SILENCE_REPORT_S", 5.0, raising=False)
    provider = _provider()
    _install(provider, _lifecycle(20) + _answer(), gap=0.0)

    with _captured_warnings() as warnings:
        result = await provider.chat_stream(messages=_MESSAGES)

    assert warnings == []
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_caller_callbacks_still_receive_every_delta(short_report_window) -> None:
    """Wrapping the hooks must not swallow, reorder or duplicate them."""
    provider = _provider()
    events = (
        _lifecycle(_SILENT_RUN)
        + [SimpleNamespace(type="response.reasoning_text.delta", delta="Why. ")]
        + _lifecycle(2)
        + _answer()
    )
    _install(provider, events, gap=_GAP_S)
    content: list[str] = []
    reasoning: list[str] = []

    async def on_content(text: str) -> None:
        content.append(text)

    async def on_reasoning(text: str) -> None:
        reasoning.append(text)

    with _captured_warnings() as warnings:
        result = await provider.chat_stream(
            messages=_MESSAGES,
            on_content_delta=on_content,
            on_reasoning_delta=on_reasoning,
        )

    assert content == ["A Fourier transform decomposes a signal."]
    assert reasoning == ["Why. "]
    assert len(warnings) == 1
    assert result.content == "A Fourier transform decomposes a signal."
