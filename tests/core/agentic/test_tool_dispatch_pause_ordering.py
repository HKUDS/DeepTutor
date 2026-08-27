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


class _PathRegistry:
    """Stands in for the mastery path binding: switch moves it, writes follow it."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.active = "path-a"
        self.written_to: list[str] = []

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        self.order.append(name)
        if name == "mastery_switch":
            self.active = str(kwargs.get("path_id") or self.active)
        if name == "mastery_build":
            self.written_to.append(str(kwargs.get("_mastery_path_id") or ""))
        return ToolResult(content="ok", success=True)


async def _dispatch_with_rebinding(
    registry: _PathRegistry, tool_calls: list[dict[str, Any]]
) -> None:
    def augment(tool_name: str, tool_args: dict[str, Any], _ctx: UnifiedContext) -> dict[str, Any]:
        if tool_name.startswith("mastery_"):
            return {**tool_args, "_mastery_path_id": registry.active}
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
        rebinding_tools=frozenset({"mastery_switch"}),
    )


@pytest.mark.asyncio
async def test_a_rebinding_tool_runs_first_and_its_round_mates_follow_it() -> None:
    """A switch + build round must build the path it switched TO, not FROM."""
    registry = _PathRegistry()

    await _dispatch_with_rebinding(
        registry,
        [
            {"id": "c1", "name": "mastery_build", "arguments": "{}"},
            {"id": "c2", "name": "mastery_switch", "arguments": '{"path_id": "path-b"}'},
        ],
    )

    assert registry.order == ["mastery_switch", "mastery_build"]
    assert registry.written_to == ["path-b"]


@pytest.mark.asyncio
async def test_a_pausing_tool_still_runs_after_a_rebound_round() -> None:
    registry = _PathRegistry()

    await _dispatch_with_rebinding(
        registry,
        [
            {"id": "c1", "name": "ask_user", "arguments": "{}"},
            {"id": "c2", "name": "mastery_build", "arguments": "{}"},
            {"id": "c3", "name": "mastery_switch", "arguments": '{"path_id": "path-b"}'},
        ],
    )

    assert registry.order == ["mastery_switch", "mastery_build", "ask_user"]


@pytest.mark.asyncio
async def test_declaring_no_rebinding_tools_leaves_the_round_concurrent() -> None:
    registry = _PathRegistry()

    await dispatch_tool_calls(
        tool_calls=[
            {"id": "c1", "name": "mastery_build", "arguments": "{}"},
            {"id": "c2", "name": "mastery_switch", "arguments": '{"path_id": "path-b"}'},
        ],
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=StreamBus(),
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=registry,
    )

    assert sorted(registry.order) == ["mastery_build", "mastery_switch"]
