"""Which provider is running, on every event of a tool call's sub-trace.

This is what lets the activity row say "Using wolfram" or "Running blender"
instead of title-casing a generated name into "Mcp Wolfram Wolframalpha". The
identity is resolved from the tool object here because it is the only place that
knows it; the alternative — the frontend splitting ``mcp_<server>_<tool>`` on
underscores — is ambiguous the moment a server's own name contains one.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.core.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult


class _Tool(BaseTool):
    def __init__(self, name: str, **attrs: Any) -> None:
        self._name = name
        for key, value in attrs.items():
            setattr(self, key, value)

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(name=self._name, description="d")

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(content="ok")


class _Registry:
    def __init__(self, *tools: BaseTool) -> None:
        self._tools = {tool.get_definition().name: tool for tool in tools}

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    async def execute(self, name: str, /, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        kwargs.pop("event_sink", None)
        return await tool.execute(**kwargs)


def _call(name: str, index: int = 0) -> dict[str, Any]:
    return {"id": f"c{index}", "name": name, "arguments": "{}"}


async def _dispatch(registry: _Registry, *names: str) -> list[Any]:
    """Dispatch through a real StreamBus and return everything it emitted."""
    bus = StreamBus()
    seen: list[Any] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            seen.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await dispatch_tool_calls(
        tool_calls=[_call(name, index) for index, name in enumerate(names)],
        registry=registry,  # type: ignore[arg-type]
        context=UnifiedContext(session_id="s1", user_message="hi", metadata={"turn_id": "t1"}),
        stream=bus,
        source="chat",
        stage="responding",
        iteration_index=0,
    )
    await bus.close()
    await consumer
    return seen


def _metas(events: list[Any], tool_name: str) -> list[dict[str, Any]]:
    return [
        event.metadata
        for event in events
        if isinstance(getattr(event, "metadata", None), dict)
        and event.metadata.get("tool_name") == tool_name
    ]


@pytest.mark.asyncio
async def test_an_mcp_tool_call_carries_its_server() -> None:
    registry = _Registry(
        _Tool("mcp_wolfram_WolframAlpha", provider_kind="mcp", provider_id="wolfram")
    )
    events = await _dispatch(registry, "mcp_wolfram_WolframAlpha")

    metas = _metas(events, "mcp_wolfram_WolframAlpha")
    assert metas, "the call produced no trace events"
    # Every event in the group, not only the opening one: a reconnect mid-turn
    # can drop the first event, and the row still has to be labelled.
    for meta in metas:
        assert meta["tool_source"] == "mcp"
        assert meta["tool_provider"] == "wolfram"


@pytest.mark.asyncio
async def test_a_cli_app_call_carries_its_app_id() -> None:
    registry = _Registry(_Tool("cli_blender", provider_kind="cli", provider_id="blender"))
    events = await _dispatch(registry, "cli_blender")

    meta = _metas(events, "cli_blender")[0]
    assert meta["tool_source"] == "cli"
    assert meta["tool_provider"] == "blender"


@pytest.mark.asyncio
async def test_a_builtin_carries_neither_key() -> None:
    """Absent rather than empty, so a row without them is unambiguously "not an
    external provider" instead of "one we failed to identify"."""
    events = await _dispatch(_Registry(_Tool("read_file")), "read_file")

    meta = _metas(events, "read_file")[0]
    assert "tool_source" not in meta
    assert "tool_provider" not in meta


@pytest.mark.asyncio
async def test_an_adapter_that_still_spells_it_server_name_is_recognised() -> None:
    """``server_name`` predates ``provider_id``; the reader accepts both."""
    registry = _Registry(_Tool("mcp_legacy_ping", provider_kind="mcp", server_name="legacy"))
    events = await _dispatch(registry, "mcp_legacy_ping")

    assert _metas(events, "mcp_legacy_ping")[0]["tool_provider"] == "legacy"


@pytest.mark.asyncio
async def test_a_tool_the_registry_cannot_resolve_still_gets_a_trace_row() -> None:
    """A hallucinated tool name is the normal case for this path."""
    events = await _dispatch(_Registry(), "no_such_tool")

    meta = _metas(events, "no_such_tool")[0]
    assert "tool_source" not in meta


@pytest.mark.asyncio
async def test_two_providers_in_one_parallel_batch_do_not_borrow_each_others_identity() -> None:
    registry = _Registry(
        _Tool("mcp_wolfram_Alpha", provider_kind="mcp", provider_id="wolfram"),
        _Tool("cli_blender", provider_kind="cli", provider_id="blender"),
    )
    events = await _dispatch(registry, "mcp_wolfram_Alpha", "cli_blender")

    assert _metas(events, "mcp_wolfram_Alpha")[0]["tool_provider"] == "wolfram"
    assert _metas(events, "cli_blender")[0]["tool_provider"] == "blender"


@pytest.mark.asyncio
async def test_a_registry_whose_lookup_raises_does_not_break_the_turn() -> None:
    class _Hostile(_Registry):
        def get(self, name: str) -> BaseTool | None:
            raise RuntimeError("registry is unwell")

    events = await _dispatch(_Hostile(_Tool("read_file")), "read_file")

    assert _metas(events, "read_file"), "the trace row has to exist regardless"
