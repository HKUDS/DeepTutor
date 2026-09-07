"""The ``ask_user`` card is published while its arguments are still streaming.

Covers the emitter's three jobs: throttling a token-rate delta stream down to
a few card updates, never publishing a frame that would shrink the card, and
giving the finished call the last word even when the throttle swallowed its
closing fragments.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents.loop.ask_user_drafts import (
    ASK_USER_DRAFT_TRACE_KIND,
    AskUserDraftEmitter,
)

_ARGUMENTS = (
    '{"intro": "Which path?", "questions": [{"id": "which", "prompt": '
    '"Where to?", "options": [{"label": "Advanced", "description": "15 goals, '
    'picks up where you stopped"}, {"label": "Core", "description": "4 goals, '
    'more focused"}, {"label": "Survey", "description": "15 goals, comparison '
    'framing"}]}]}'
)


class _RecordingStream:
    def __init__(self) -> None:
        self.metadata: list[dict[str, Any]] = []

    async def progress(
        self,
        message: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.metadata.append(metadata or {})


def _emitter(stream: _RecordingStream) -> AskUserDraftEmitter:
    return AskUserDraftEmitter(
        stream=stream,
        source="chat",
        stage="responding",
        metadata={"call_id": "chat-responding-1"},
    )


def _drafts(stream: _RecordingStream) -> list[dict[str, Any]]:
    return [meta["ask_user_draft"] for meta in stream.metadata]


def _shape(draft: dict[str, Any]) -> tuple[int, int]:
    questions = draft["questions"]
    return len(questions), sum(len(q["options"]) for q in questions)


async def _stream_arguments(
    emitter: AskUserDraftEmitter,
    *,
    chunk: int,
    call_id: str = "call_1",
) -> None:
    accumulated = ""
    for start in range(0, len(_ARGUMENTS), chunk):
        accumulated += _ARGUMENTS[start : start + chunk]
        await emitter.observe(
            call_id=call_id,
            tool_name="ask_user",
            arguments=accumulated,
        )


@pytest.mark.asyncio
async def test_card_grows_and_never_shrinks() -> None:
    stream = _RecordingStream()
    emitter = _emitter(stream)

    await _stream_arguments(emitter, chunk=1)
    await emitter.settle([{"id": "call_1", "name": "ask_user", "arguments": _ARGUMENTS}])

    drafts = _drafts(stream)
    assert drafts, "nothing was previewed"
    shapes = [_shape(draft) for draft in drafts]
    assert shapes == sorted(shapes), f"the card shrank mid-stream: {shapes}"
    assert shapes[-1] == (1, 3)
    labels = [
        option["label"] for question in drafts[-1]["questions"] for option in question["options"]
    ]
    assert labels == ["Advanced", "Core", "Survey"]


@pytest.mark.asyncio
async def test_a_token_rate_stream_is_throttled_into_a_few_updates() -> None:
    stream = _RecordingStream()

    await _stream_arguments(_emitter(stream), chunk=1)

    # One event per token would be hundreds; the growth floor collapses them.
    assert 0 < len(stream.metadata) < len(_ARGUMENTS) // 10


@pytest.mark.asyncio
async def test_events_are_addressed_to_the_card_and_carry_the_call() -> None:
    stream = _RecordingStream()

    await _stream_arguments(_emitter(stream), chunk=40)

    assert stream.metadata
    for meta in stream.metadata:
        assert meta["trace_kind"] == ASK_USER_DRAFT_TRACE_KIND
        assert meta["tool_name"] == "ask_user"
        assert meta["draft_call_id"] == "call_1"
        # The round's own trace identity rides along unchanged.
        assert meta["call_id"] == "chat-responding-1"


@pytest.mark.asyncio
async def test_settle_completes_a_card_the_throttle_left_half_written() -> None:
    stream = _RecordingStream()
    emitter = _emitter(stream)

    # One big chunk: everything after the first preview is inside the
    # interval floor, so the closing options never get their own event.
    await emitter.observe(
        call_id="call_1",
        tool_name="ask_user",
        arguments=_ARGUMENTS[:60],
    )
    await emitter.observe(
        call_id="call_1",
        tool_name="ask_user",
        arguments=_ARGUMENTS,
    )
    before_settle = _shape(_drafts(stream)[-1])

    # The dispatched call carries the Responses-API composite id; the
    # emitter keyed its state on the call id alone.
    await emitter.settle([{"id": "call_1|item_9", "name": "ask_user", "arguments": _ARGUMENTS}])

    assert before_settle < (1, 3)
    assert _shape(_drafts(stream)[-1]) == (1, 3)


@pytest.mark.asyncio
async def test_settle_ignores_calls_that_were_never_previewed() -> None:
    stream = _RecordingStream()

    await _emitter(stream).settle([{"id": "call_9", "name": "ask_user", "arguments": _ARGUMENTS}])

    assert stream.metadata == []


@pytest.mark.asyncio
async def test_no_other_tool_is_previewed() -> None:
    stream = _RecordingStream()

    await _emitter(stream).observe(
        call_id="call_1",
        tool_name="rag_search",
        arguments='{"query": "agentic rag"}',
    )

    assert stream.metadata == []


@pytest.mark.asyncio
async def test_an_unchanged_payload_is_not_republished() -> None:
    """Trailing whitespace and a repeated final payload publish nothing."""
    stream = _RecordingStream()
    emitter = _emitter(stream)

    await emitter.observe(call_id="call_1", tool_name="ask_user", arguments=_ARGUMENTS)
    published = len(stream.metadata)
    await emitter.settle([{"id": "call_1", "name": "ask_user", "arguments": _ARGUMENTS + "  "}])

    assert len(stream.metadata) == published
