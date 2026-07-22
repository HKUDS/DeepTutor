"""Tests for the pre-label ``<think>...</think>`` prelude handling in
:func:`deeptutor.core.agentic.labeled_step.run_labeled_step`.

Reasoning models (Qwen, Deepseek-R1 via certain proxies, …) sometimes
emit a literal ``<think>...</think>`` block *before* the protocol label.
The streaming parser must:

1. Route prelude content live into the reasoning sub-trace immediately
   (so the user sees activity during reasoning, not a frozen UI).
2. After ``</think>``, resume label probing on the remainder.
3. If the resolved label is intermediate (e.g. ``THINK``), the post-label
   text continues into the *same* reasoning sub-trace.
4. If the resolved label is final (e.g. ``FINISH``), the post-label text
   routes to the final-response area via ``final_meta``.
5. Strip the ``<think>...</think>`` markers + body from the returned
   ``text`` so the next iteration's assistant context isn't polluted.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.agentic.labeled_step import run_labeled_step
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus


def _chunk(content: str | None = None, tool_calls: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=None,
    )


def _reasoning_chunk(reasoning_text: str) -> SimpleNamespace:
    """A chunk that surfaces reasoning via the dedicated ``reasoning_content``
    field (e.g. DeepSeek-R1 in OpenAI-compatible mode). ``delta.content`` is
    empty during the reasoning phase for these models."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=None,
                    reasoning_content=reasoning_text,
                )
            )
        ],
        usage=None,
    )


def _tc_chunk(
    *,
    index: int = 0,
    tc_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    fn = SimpleNamespace(name=name, arguments=arguments)
    return _chunk(
        content=None,
        tool_calls=[SimpleNamespace(index=index, id=tc_id, function=fn)],
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ScriptedClient:
    """Minimal OpenAI-compatible streaming client returning pre-scripted
    chunk lists for each ``chat.completions.create`` call."""

    def __init__(self, scripts: list[list[SimpleNamespace]]) -> None:
        self._scripts = list(scripts)

        class _Completions:
            def __init__(self, parent: _ScriptedClient) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any):
                if not self.parent._scripts:
                    raise RuntimeError("scripted client exhausted")
                return _async_stream(self.parent._scripts.pop(0))

        class _Chat:
            def __init__(self, parent: _ScriptedClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


async def _collect_events(bus: StreamBus, fn) -> list[Any]:
    """Run ``fn(bus)`` to completion and return the events that landed on
    the bus during it."""
    events: list[Any] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        result = await fn()
    finally:
        await bus.close()
        await consumer
    return events, result


def _thinking_texts(events: list[Any]) -> list[str]:
    return [e.content for e in events if e.type == StreamEventType.THINKING]


def _content_texts(events: list[Any]) -> list[str]:
    return [e.content for e in events if e.type == StreamEventType.CONTENT]


_ALLOWED = ("FINISH", "TOOL", "THINK", "PAUSE")
_FINAL = frozenset({"FINISH"})
_FINAL_MIXED = frozenset({"FINISH", "PAUSE"})


async def _run(
    chunks: list[SimpleNamespace],
    *,
    allowed: tuple[str, ...] = _ALLOWED,
    final_labels: frozenset[str] = _FINAL,
    tool_label: str | None = "TOOL",
    final_meta: dict[str, Any] | None = None,
    implicit_think_label: str | None = None,
):
    client = _ScriptedClient([chunks])
    bus = StreamBus()
    iter_meta = {"label": "Reasoning", "trace_id": "iter-1"}

    async def _do():
        return await run_labeled_step(
            client=client,
            model="x",
            messages=[{"role": "user", "content": "hi"}],
            completion_kwargs={},
            tool_schemas=None,
            allowed_labels=allowed,
            final_labels=final_labels,
            tool_label=tool_label,
            stream=bus,
            source="test",
            stage="test",
            iter_meta=iter_meta,
            binding="openai",
            final_meta=final_meta,
            implicit_think_label=implicit_think_label,
        )

    events, result = await _collect_events(bus, _do)
    return events, result


# ---------------------------- the tests ----------------------------


@pytest.mark.asyncio
async def test_prelude_then_finish_routes_split_streams_and_strips_prelude() -> None:
    """A ``<think>prelude</think>`` then ``FINISH`` should stream the prelude
    *including* its ``<think>``/``</think>`` markers into the reasoning
    sub-trace (so users see the model's native structure), the final answer
    into the chat bubble (when ``final_meta`` is supplied), and return text
    with the prelude block fully stripped."""
    final_meta = {"label": "Final", "trace_id": "final-1"}
    events, result = await _run(
        [
            _chunk("<think>let me reason about this</think>"),
            _chunk("``FINISH``\nThe answer is 42."),
        ],
        final_meta=final_meta,
    )

    assert result.label == "FINISH"
    assert result.text == "The answer is 42."
    thinking_joined = "".join(_thinking_texts(events))
    # Prelude content streamed live as THINKING (reasoning sub-trace).
    assert "let me reason about this" in thinking_joined
    # The ``<think>``/``</think>`` markers ARE visible in the trace.
    assert "<think>" in thinking_joined
    assert "</think>" in thinking_joined
    # Final-label body streamed live as CONTENT (chat bubble).
    assert "The answer is 42." in "".join(_content_texts(events))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label_prefix", "expected_text"),
    [
        ("`FINISH`\n", "Single-backtick final."),
        ("```FINISH```\n", "Triple-backtick final."),
        ("FINISH：", "Fullwidth-colon final."),
    ],
)
async def test_prelude_then_finish_accepts_common_label_variants(
    label_prefix: str,
    expected_text: str,
) -> None:
    """Reasoning models often obey the action token but alter the wrapper
    after ``</think>``. The parser should still recognize the real FINISH
    label rather than letting the implicit-THINK fallback consume it."""
    final_meta = {"label": "Final", "trace_id": "final-1"}
    events, result = await _run(
        [
            _chunk("<think>native reasoning</think>"),
            _chunk(f"{label_prefix}{expected_text}"),
        ],
        final_meta=final_meta,
        implicit_think_label="THINK",
    )

    assert result.label == "FINISH"
    assert result.text == expected_text
    assert "native reasoning" in "".join(_thinking_texts(events))
    assert expected_text in "".join(_content_texts(events))


@pytest.mark.asyncio
async def test_prelude_then_bare_finish_at_stream_end_wins_over_implicit_think() -> None:
    """A terminal bare label with no body is only decidable at EOF. If a
    prelude was seen, it must still resolve as FINISH instead of falling
    through to implicit THINK."""
    events, result = await _run(
        [
            _chunk("<think>done thinking</think>"),
            _chunk("FINISH"),
        ],
        implicit_think_label="THINK",
    )

    assert result.label == "FINISH"
    assert result.text == ""
    assert "done thinking" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_prelude_then_think_merges_into_same_subtrace() -> None:
    """Prelude content + a subsequent ``THINK`` label should both route to
    the THINKING channel (same reasoning sub-trace). The returned text
    keeps only the post-label body — ``<think>...</think>`` is stripped."""
    events, result = await _run(
        [
            _chunk("<think>prelude reasoning</think>"),
            _chunk("``THINK``\nstill thinking out loud"),
        ],
    )

    assert result.label == "THINK"
    assert result.text == "still thinking out loud"
    thinking = _thinking_texts(events)
    joined = "".join(thinking)
    # Both prelude and post-label text on the reasoning sub-trace.
    assert "prelude reasoning" in joined
    assert "still thinking out loud" in joined
    # Nothing on the final-content channel.
    assert _content_texts(events) == []


@pytest.mark.asyncio
async def test_prelude_close_tag_split_across_chunks_still_detected() -> None:
    """If ``</think>`` arrives split across chunks (e.g. ``</think`` then
    ``>``), the parser still recognizes the close tag thanks to the trailing
    guard window."""
    events, result = await _run(
        [
            _chunk("<think>reasoning content here</think"),
            _chunk(">"),
            _chunk("``FINISH``\nDone."),
        ],
    )

    assert result.label == "FINISH"
    assert result.text == "Done."
    assert "reasoning content here" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_prelude_then_split_wrapped_finish_waits_for_matching_backticks() -> None:
    """The tolerant wrapper parser must not resolve ````FINISH``` after
    seeing only one of the two closing backticks; otherwise the remaining
    backtick leaks into the final answer."""
    events, result = await _run(
        [
            _chunk("<think>reasoning</think>"),
            _chunk("``FINISH`"),
            _chunk("`\nDone."),
        ],
    )

    assert result.label == "FINISH"
    assert result.text == "Done."
    assert "reasoning" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_prelude_entire_response_in_single_chunk() -> None:
    """A single chunk that carries prelude, label, and body must still
    resolve the label inside the same ingestion — not get stuck waiting
    for a next chunk that never arrives."""
    final_meta = {"label": "Final", "trace_id": "final-1"}
    events, result = await _run(
        [
            _chunk("<think>quick thought</think>``FINISH``\nAll done."),
        ],
        final_meta=final_meta,
    )

    assert result.label == "FINISH"
    assert result.text == "All done."
    assert "quick thought" in "".join(_thinking_texts(events))
    assert "All done." in "".join(_content_texts(events))


@pytest.mark.asyncio
async def test_prelude_then_tool_call_routes_correctly() -> None:
    """Prelude content followed by a ``TOOL`` label + real tool_calls must
    resolve the TOOL label, parse the tool call, and stream the prelude
    into the reasoning sub-trace."""
    events, result = await _run(
        [
            _chunk("<think>need to look this up</think>"),
            _chunk("``TOOL``\nCalling search now."),
            _tc_chunk(tc_id="call_1", name="search", arguments=""),
            _tc_chunk(arguments='{"q": "x"}'),
        ],
    )

    assert result.label == "TOOL"
    assert result.tool_calls == [{"id": "call_1", "name": "search", "arguments": '{"q": "x"}'}]
    assert result.text == "Calling search now."
    joined_think = "".join(_thinking_texts(events))
    assert "need to look this up" in joined_think
    assert "Calling search now." in joined_think


@pytest.mark.asyncio
async def test_tool_calls_mid_prelude_close_prelude_synthetically() -> None:
    """Tool-call deltas without a formal ``TOOL`` label are not enough to
    choose the action. The tool calls are still accumulated so the caller can
    include them in diagnostics, but the step is a missing-label violation."""
    events, result = await _run(
        [
            _chunk("<think>still reasoning"),  # never closes
            _tc_chunk(tc_id="call_a", name="lookup", arguments='{"k":1}'),
        ],
    )

    assert result.label == "UNKNOWN"
    assert result.tool_calls == [{"id": "call_a", "name": "lookup", "arguments": '{"k":1}'}]
    # Even though </think> never arrived, the returned text must not leak
    # the prelude content (clean_thinking_tags strips the synthesized block).
    assert "<think>" not in result.text
    assert "still reasoning" not in result.text
    # Prelude content was still streamed live so the user saw activity.
    assert "still reasoning" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_prelude_unclosed_then_stream_ends() -> None:
    """If the stream ends mid-prelude with no ``</think>`` and no label,
    fall back to ``LABEL_UNKNOWN``, surface the partial reasoning to the
    user via the sub-trace, and strip the prelude from the returned text."""
    events, result = await _run(
        [
            _chunk("<think>incomplete reasoning, no close tag"),
        ],
    )

    assert result.label == "UNKNOWN"
    # No prelude leakage in the returned text.
    assert "incomplete reasoning" not in result.text
    assert "<think>" not in result.text
    # User still saw the partial reasoning live.
    assert "incomplete reasoning, no close tag" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_no_prelude_still_works() -> None:
    """Regression: when the model follows the protocol cleanly (no ``<think>``
    prelude), behavior must be identical to the previous implementation."""
    final_meta = {"label": "Final", "trace_id": "final-1"}
    events, result = await _run(
        [
            _chunk("``FINISH``\nDirect answer."),
        ],
        final_meta=final_meta,
    )
    assert result.label == "FINISH"
    assert result.text == "Direct answer."
    assert "Direct answer." in "".join(_content_texts(events))
    # No reasoning trace events emitted for a clean FINISH.
    assert _thinking_texts(events) == []


@pytest.mark.asyncio
async def test_wrapped_finish_with_adjacent_body_routes_to_final_not_reasoning() -> None:
    """Some models attach CJK/prose directly after the inline-code label
    (````FINISH``你好``). That is still a valid completed wrapper and must
    not be treated as missing-label reasoning."""
    final_meta = {"label": "Final", "trace_id": "final-1"}
    events, result = await _run(
        [
            _chunk("``FINISH``你好！我是 DeepTutor。"),
        ],
        final_meta=final_meta,
    )

    assert result.label == "FINISH"
    assert result.text == "你好！我是 DeepTutor。"
    assert "你好！我是 DeepTutor。" in "".join(_content_texts(events))
    assert _thinking_texts(events) == []


@pytest.mark.asyncio
async def test_reasoning_content_field_streams_to_reasoning_subtrace() -> None:
    """Models that put chain-of-thought in ``delta.reasoning_content`` (rather
    than inline ``<think>`` in content) must still surface live activity in
    the reasoning sub-trace, and the subsequent labeled answer in
    ``delta.content`` must resolve normally."""
    events, result = await _run(
        [
            _reasoning_chunk("step 1 of my reasoning"),
            _reasoning_chunk(" — step 2 continues"),
            _chunk("``FINISH``\nThe answer is X."),
        ],
    )

    assert result.label == "FINISH"
    assert result.text == "The answer is X."
    thinking_joined = "".join(_thinking_texts(events))
    assert "step 1 of my reasoning" in thinking_joined
    assert "step 2 continues" in thinking_joined


@pytest.mark.asyncio
async def test_reasoning_content_does_not_imply_action_for_unlabeled_body() -> None:
    """The dedicated reasoning stream is rendered as a trace, but the formal
    content stream still needs a protocol label. Unlabeled body text is a
    missing-label draft, not an implicit ``THINK`` or ``FINISH``."""
    events, result = await _run(
        [
            _reasoning_chunk("private reasoning trace"),
            _chunk("This reads like a final answer but has no label."),
        ],
        implicit_think_label="FINISH",
    )

    assert result.label == "UNKNOWN"
    assert result.text == "This reads like a final answer but has no label."
    assert "private reasoning trace" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_tool_calls_without_tool_label_stay_unknown() -> None:
    """Native tool calls are parsed, but they do not override the formal
    first-line action protocol. The caller should repair the missing label."""
    events, result = await _run(
        [
            _reasoning_chunk("I need a lookup"),
            _tc_chunk(tc_id="call_1", name="search", arguments='{"q":"x"}'),
        ]
    )

    assert result.label == "UNKNOWN"
    assert result.tool_calls == [{"id": "call_1", "name": "search", "arguments": '{"q":"x"}'}]
    assert "I need a lookup" in "".join(_thinking_texts(events))


@pytest.mark.asyncio
async def test_reasoning_content_then_inline_think_merge_into_same_subtrace() -> None:
    """Some providers emit *both* a ``reasoning_content`` stream AND inline
    ``<think>...</think>`` in ``content``. Both should land in the same
    reasoning sub-trace; the final returned text must not leak either."""
    events, result = await _run(
        [
            _reasoning_chunk("external reasoning"),
            _chunk("<think>inline reasoning</think>``FINISH``\nDone."),
        ],
    )
    assert result.label == "FINISH"
    assert result.text == "Done."
    thinking_joined = "".join(_thinking_texts(events))
    assert "external reasoning" in thinking_joined
    assert "inline reasoning" in thinking_joined


@pytest.mark.asyncio
async def test_thinking_trace_without_protocol_label_stays_unknown() -> None:
    """A reasoning trace is trace data, not an action label. Even when the
    caller passes the legacy ``implicit_think_label`` argument, the formal
    content must still provide ``THINK`` / ``FINISH`` / ``TOOL`` / ``PAUSE``."""
    events, result = await _run(
        [
            _chunk("<think>I'm thinking about this carefully</think>"),
        ],
        implicit_think_label="THINK",
    )

    assert result.label == "UNKNOWN"
    assert result.text == ""


@pytest.mark.asyncio
async def test_unlabeled_tail_after_thinking_trace_stays_unknown() -> None:
    """A long formal body after a thinking trace still needs a first-line
    protocol label. The parser preserves the draft text for repair context
    but does not silently convert it to ``THINK``."""
    long_unlabeled_tail = "x" * 200  # well past the 64-char probe window
    events, result = await _run(
        [
            _chunk(f"<think>some reasoning</think>{long_unlabeled_tail}"),
        ],
        implicit_think_label="THINK",
    )
    assert result.label == "UNKNOWN"
    assert "<think>" not in result.text
    assert "some reasoning" not in result.text
    assert long_unlabeled_tail in result.text


@pytest.mark.asyncio
async def test_implicit_think_does_not_fire_without_opt_in() -> None:
    """Existing callers that don't opt into implicit-THINK must keep the
    legacy ``LABEL_UNKNOWN`` fallback so their repair / retry paths are
    not silently bypassed."""
    events, result = await _run(
        [
            _chunk("<think>private reasoning</think>"),
        ],
    )
    assert result.label == "UNKNOWN"


@pytest.mark.asyncio
async def test_implicit_think_skips_when_label_not_in_allowed() -> None:
    """A caller whose protocol does not include the implicit label (e.g.
    a ``FINISH``-only forced-finalization step) must not get an implicit
    ``THINK`` resolution — it would corrupt their state machine."""
    events, result = await _run(
        [
            _chunk("<think>reasoning</think>"),
        ],
        allowed=("FINISH",),
        final_labels=frozenset({"FINISH"}),
        tool_label=None,
        implicit_think_label="THINK",  # not in allowed
    )
    assert result.label == "UNKNOWN"


@pytest.mark.asyncio
async def test_prelude_with_long_body_emits_chunks_progressively() -> None:
    """A long prelude body should be emitted live in pieces, not buffered
    until ``</think>`` arrives. The trailing guard window keeps at most a
    small slice unsent so a split close tag stays detectable."""
    long_body = "x" * 500
    events, result = await _run(
        [
            _chunk("<think>" + long_body),  # huge prelude, no close yet
            _chunk("</think>``FINISH``\nok"),
        ],
    )
    assert result.label == "FINISH"
    assert result.text == "ok"
    # Most of the long body must have been flushed live (the guard window
    # only holds back ~24 trailing chars).
    flushed = "".join(_thinking_texts(events))
    assert flushed.count("x") >= 500 - 24
