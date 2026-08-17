"""A pausing tool binds its arguments after its round-mates have run.

Every tool call in a round used to have its arguments bound up front and then
run concurrently. That is wrong for a tool whose job is to *show the user what
the round produced*: a mastery tutor that poses a question (``mastery_quiz``)
and presents it (``ask_user``) in one round had the card bound before the
question was persisted, so the card could only carry the model's own draft of
it — and grading then had to guess how the shown options mapped onto the stored
ones.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.core.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import ToolResult


class _RecordingRegistry:
    """Stands in for the persisted question: the quiz commits, ask_user reads."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.committed: str | None = None
        self.seen_by_ask_user: str | None = None

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        self.order.append(name)
        if name == "mastery_quiz":
            self.committed = "persisted question"
        if name == "ask_user":
            self.seen_by_ask_user = kwargs.get("prompt")
        return ToolResult(content="ok", success=True)


async def _dispatch(registry: _RecordingRegistry, tool_calls: list[dict[str, Any]]) -> None:
    def augment(tool_name: str, tool_args: dict[str, Any], _ctx: UnifiedContext) -> dict[str, Any]:
        # Mirrors the mastery binder: an ask_user card is rebound onto whatever
        # question is committed at bind time, and left alone when none is.
        if tool_name == "ask_user" and registry.committed:
            return {**tool_args, "prompt": registry.committed}
        return dict(tool_args)

    await dispatch_tool_calls(
        tool_calls=tool_calls,
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=StreamBus(),
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=registry,
        kwarg_augmenter=augment,
    )


@pytest.mark.asyncio
async def test_ask_user_runs_last_and_rebinds_against_the_round() -> None:
    registry = _RecordingRegistry()

    await _dispatch(
        registry,
        [
            {"id": "c1", "name": "ask_user", "arguments": '{"prompt": "model draft"}'},
            {"id": "c2", "name": "mastery_quiz", "arguments": "{}"},
        ],
    )

    # Declared first by the model, still run last.
    assert registry.order == ["mastery_quiz", "ask_user"]
    assert registry.seen_by_ask_user == "persisted question"


@pytest.mark.asyncio
async def test_a_round_without_a_pausing_tool_is_unchanged() -> None:
    registry = _RecordingRegistry()

    await _dispatch(
        registry,
        [
            {"id": "c1", "name": "rag", "arguments": "{}"},
            {"id": "c2", "name": "web_search", "arguments": "{}"},
        ],
    )

    assert sorted(registry.order) == ["rag", "web_search"]


@pytest.mark.asyncio
async def test_results_stay_paired_with_their_tool_calls() -> None:
    """Reordering execution must not reorder the role=tool messages."""

    class _EchoRegistry:
        async def execute(self, name: str, **kwargs: Any) -> ToolResult:
            return ToolResult(content=f"{name}-done", success=True)

    outcome = await dispatch_tool_calls(
        tool_calls=[
            {"id": "c1", "name": "ask_user", "arguments": "{}"},
            {"id": "c2", "name": "rag", "arguments": "{}"},
            {"id": "c3", "name": "web_search", "arguments": "{}"},
        ],
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=StreamBus(),
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=_EchoRegistry(),
    )

    assert [(m["tool_call_id"], m["content"]) for m in outcome.tool_messages] == [
        ("c1", "ask_user-done"),
        ("c2", "rag-done"),
        ("c3", "web_search-done"),
    ]
