from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import deeptutor.core.agentic.labeled_step as labeled_step_module
from deeptutor.core.agentic.labeled_step import run_labeled_step
from deeptutor.core.agentic.usage import UsageTracker
from deeptutor.core.stream_bus import StreamBus


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
