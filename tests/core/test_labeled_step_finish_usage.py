from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest

import deeptutor.runtime.agentic.labeled_step as labeled_step_module
from deeptutor.runtime.agentic.labeled_step import run_labeled_step
from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm import LLMProviderTransportError


def _chunk(
    content: str | None = None,
    *,
    finish_reason: str | None = None,
    usage: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def _usage_chunk(*, prompt: int, completion: int, total: int) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        ),
    )


class _Stream:
    def __init__(self, chunks: list[SimpleNamespace], *, stall_after_chunks: bool = False) -> None:
        self._chunks = list(chunks)
        self.stall_after_chunks = stall_after_chunks
        self.closed = False

    def __aiter__(self) -> "_Stream":
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._chunks:
            return self._chunks.pop(0)
        if self.stall_after_chunks:
            await asyncio.sleep(60)
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(
        self,
        streams: list[_Stream],
        *,
        fail_first_stream_options: bool = False,
    ) -> None:
        self._streams = list(streams)
        self.fail_first_stream_options = fail_first_stream_options
        self.calls: list[dict[str, Any]] = []

        class _Completions:
            def __init__(self, parent: _Client) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any) -> _Stream:
                self.parent.calls.append(dict(kwargs))
                if (
                    self.parent.fail_first_stream_options
                    and len(self.parent.calls) == 1
                    and "stream_options" in kwargs
                ):
                    raise ValueError("unknown parameter: stream_options")
                if not self.parent._streams:
                    raise RuntimeError("no scripted stream")
                return self.parent._streams.pop(0)

        class _Chat:
            def __init__(self, parent: _Client) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


async def _run_step(client: _Client, usage: UsageTracker) -> Any:
    return await run_labeled_step(
        client=client,
        model="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        completion_kwargs={},
        tool_schemas=None,
        allowed_labels=("FINISH", "THINK", "TOOL"),
        final_labels=frozenset({"FINISH"}),
        tool_label="TOOL",
        stream=StreamBus(),
        source="test",
        stage="responding",
        iter_meta={"label": "Reasoning"},
        binding="openai",
        usage=usage,
    )


@pytest.mark.asyncio
async def test_finish_reason_closes_stalled_stream_and_estimates_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labeled_step_module, "_USAGE_TRAILER_GRACE_TIMEOUT_S", 0.01)
    stream = _Stream(
        [_chunk("``FINISH``\nDone.", finish_reason="stop")],
        stall_after_chunks=True,
    )
    usage = UsageTracker(model="gpt-test")
    client = _Client([stream])

    result = await _run_step(client, usage)

    assert result.label == "FINISH"
    assert result.text == "Done."
    assert stream.closed is True
    assert client.calls[0]["stream_options"] == {"include_usage": True}
    summary = usage.summary()
    assert summary is not None
    assert summary["total_calls"] == 1
    assert summary["total_tokens"] > 0


@pytest.mark.asyncio
async def test_finish_reason_consumes_usage_trailer_before_closing() -> None:
    stream = _Stream(
        [
            _chunk("``FINISH``\nDone.", finish_reason="stop"),
            _usage_chunk(prompt=10, completion=4, total=14),
        ]
    )
    usage = UsageTracker(model="gpt-test")
    client = _Client([stream])

    result = await _run_step(client, usage)

    assert result.label == "FINISH"
    summary = usage.summary()
    assert summary is not None
    assert summary["prompt_tokens"] == 10
    assert summary["completion_tokens"] == 4
    assert summary["total_tokens"] == 14
    assert summary["total_calls"] == 1


@pytest.mark.asyncio
async def test_stream_options_unsupported_retries_without_usage_request() -> None:
    stream = _Stream([_chunk("``FINISH``\nRetried.", finish_reason="stop")])
    usage = UsageTracker(model="gpt-test")
    client = _Client([stream], fail_first_stream_options=True)

    result = await _run_step(client, usage)

    assert result.label == "FINISH"
    assert result.text == "Retried."
    assert len(client.calls) == 2
    assert "stream_options" in client.calls[0]
    assert "stream_options" not in client.calls[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        None,
        "`",
        "``THINK``\nStill thinking.",
        "``TOOL``",
        "``FINISH``",
        "<think>reason</think>``FINISH``",
        "``FINISH``\n<think>reason</think>",
        ["<thi", "nk>reason</thi", "nk>``FINISH``"],
        ["``FINISH``\n<thi", "nk>reason</thi", "nk>"],
        "``FINISH``\n \t",
        "``FINISH``\n`<think>reason</think>`",
        ["``FINISH``\n`<thi", "nk>reason</thi", "nk>`"],
        "``FINISH``\n<think>reason</thinking>discarded",
        ["``FINISH``\n<think " + " " * 25, ">reason</think>"],
    ],
    ids=[
        "first-chunk",
        "partial-label",
        "thinking",
        "tool-label",
        "empty-final",
        "empty-final-after-thinking",
        "thinking-only-final",
        "fragmented-prelude",
        "fragmented-final-thinking",
        "whitespace-final",
        "quoted-thinking-only-final",
        "fragmented-quoted-thinking",
        "mismatched-thinking-close",
        "long-fragmented-thinking-opener",
    ],
)
async def test_stalled_incomplete_stream_raises_transport_error_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    content: str | list[str] | None,
) -> None:
    monkeypatch.setattr(labeled_step_module, "_STREAM_IDLE_TIMEOUT_S", 0.01, raising=False)
    monkeypatch.setattr(labeled_step_module, "_FINAL_LABEL_IDLE_TIMEOUT_S", 0.01)
    texts = content if isinstance(content, list) else [content]
    chunks = [_chunk(text) for text in texts if text is not None]
    stream = _Stream(chunks, stall_after_chunks=True)
    client = _Client([stream])

    with pytest.raises(LLMProviderTransportError, match="provider stream timed out"):
        await asyncio.wait_for(_run_step(client, UsageTracker(model="gpt-test")), timeout=0.3)

    assert stream.closed is True
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_stream_options", [False, True])
async def test_stalled_connection_raises_transport_error(
    monkeypatch: pytest.MonkeyPatch,
    reject_stream_options: bool,
) -> None:
    monkeypatch.setattr(labeled_step_module, "_STREAM_IDLE_TIMEOUT_S", 0.01)
    client = _Client([])
    create_cancelled = asyncio.Event()

    async def create(**kwargs: Any) -> _Stream:
        client.calls.append(dict(kwargs))
        if reject_stream_options and len(client.calls) == 1:
            raise ValueError("unknown parameter: stream_options")
        try:
            await asyncio.Event().wait()
        finally:
            create_cancelled.set()
        raise AssertionError("unreachable")

    monkeypatch.setattr(client.chat.completions, "create", create)

    with pytest.raises(LLMProviderTransportError, match="provider connection timed out"):
        await asyncio.wait_for(_run_step(client, UsageTracker(model="gpt-test")), timeout=0.3)

    assert create_cancelled.is_set()
    assert len(client.calls) == (2 if reject_stream_options else 1)


@pytest.mark.asyncio
async def test_incomplete_stream_resets_idle_timeout_for_each_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(labeled_step_module, "_STREAM_IDLE_TIMEOUT_S", 0.03)

    class SlowStream(_Stream):
        async def __anext__(self) -> SimpleNamespace:
            await asyncio.sleep(0.01)
            return await super().__anext__()

    stream = SlowStream([_chunk(text) for text in ["``THINK``\n", "a", "b", "c", "d"]])

    result = await asyncio.wait_for(
        _run_step(_Client([stream]), UsageTracker(model="gpt-test")), timeout=0.5
    )

    assert result.label == "THINK"
    assert result.text == "abcd"
    assert not result.stream_idle_timeout
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_text"),
    [
        ("``FINISH``\nDone.", "Done."),
        ("<think>reason</think>``FINISH``\nDone.", "Done."),
        ("``FINISH``\n<think>reason</think>Done.", "Done."),
        ("``FINISH``\n`Done.`", "`Done.`"),
    ],
)
async def test_final_answer_keeps_its_short_idle_settlement(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected_text: str,
) -> None:
    monkeypatch.setattr(labeled_step_module, "_FINAL_LABEL_IDLE_TIMEOUT_S", 0.01)
    stream = _Stream([_chunk(content)], stall_after_chunks=True)

    result = await asyncio.wait_for(
        _run_step(_Client([stream]), UsageTracker(model="gpt-test")), timeout=0.5
    )

    assert result.label == "FINISH"
    assert result.text == expected_text
    assert result.stream_idle_timeout
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("during_create", [False, True])
async def test_cancelling_labeled_step_propagates_and_closes_open_stream(
    during_create: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    class SignaledStream(_Stream):
        async def __anext__(self) -> SimpleNamespace:
            started.set()
            return await super().__anext__()

    stream = SignaledStream([], stall_after_chunks=True)
    client = _Client([stream])
    if during_create:

        async def create(**kwargs: Any) -> _Stream:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        monkeypatch.setattr(client.chat.completions, "create", create)

    task = asyncio.create_task(_run_step(client, UsageTracker(model="gpt-test")))
    try:
        await asyncio.wait_for(started.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert stream.closed is not during_create
