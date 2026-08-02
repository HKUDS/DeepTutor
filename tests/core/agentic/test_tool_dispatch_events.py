"""Event payloads emitted by the parallel tool dispatcher.

Two regressions live here:

* Mount poisoning — server-injected private kwargs (``_sandbox_mounts``, a
  Mount dataclass, and friends) leaked into the ``tool_call`` event's ``args``
  metadata. The event was not JSON-serializable, which silently killed the
  WebSocket push (safe_send swallowed the error and flagged the socket closed)
  AND turn persistence (json.dumps in the store), leaving the turn stuck
  "running" and later mislabelled as a restart orphan.
* Flavour-gated status — running/terminal ``call_state`` and the per-tool
  event sink used to be wired only for retrieve-flavoured tools, so ``exec``,
  MCP and web tools never pulsed as running and a tool that raised rendered as
  a completed row (the frontend keys both on ``call_state``).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.core.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.core.trace import derive_trace_metadata
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.services.sandbox import Mount


class _Registry:
    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        return ToolResult(content="ok", success=True)


class _RaisingRegistry:
    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")


class _ProgressRegistry:
    """Tool that streams intermediate progress through the dispatcher's sink."""

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        sink = kwargs.get("event_sink")
        assert sink is not None, "every tool must get an event_sink"
        await sink("tool_log", "step 1/2")
        await sink("tool_log", "")  # empty messages stay dropped
        return ToolResult(content="ok", success=True)


def _augment(tool_name: str, tool_args: dict[str, Any], _ctx: UnifiedContext) -> dict[str, Any]:
    # Mirrors the chat pipeline: server-side plumbing rides on private keys.
    return {
        **tool_args,
        "_sandbox_user_id": "u1",
        "_sandbox_workdir": "/tmp/x",
        "_sandbox_mounts": (Mount(host_path="/tmp/x", sandbox_path="/tmp/x", read_only=False),),
    }


def _retrieve_meta_factory(
    tool_meta: dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
) -> dict[str, Any] | None:
    """Chat's ``_retrieve_trace_metadata`` rag branch, verbatim in shape."""
    if tool_name != "rag":
        return None
    return derive_trace_metadata(
        tool_meta,
        label="Retrieve",
        call_kind="rag_retrieval",
        trace_role="retrieve",
        trace_group="retrieve",
        query=str(tool_args.get("query", "") or ""),
    )


async def _run_dispatch(
    tool_calls: list[dict[str, Any]],
    *,
    registry: Any,
    kwarg_augmenter: Any = None,
    retrieve_meta_factory: Any = None,
) -> list[StreamEvent]:
    """Dispatch through a real StreamBus and return everything it emitted."""
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await dispatch_tool_calls(
        tool_calls=tool_calls,
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=bus,
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=registry,
        kwarg_augmenter=kwarg_augmenter,
        retrieve_meta_factory=retrieve_meta_factory,
    )
    await bus.close()
    await consumer
    return events


def _status_events(events: list[StreamEvent], call_id: str | None = None) -> list[StreamEvent]:
    return [
        event
        for event in events
        if (event.metadata or {}).get("trace_kind") == "call_status"
        and (call_id is None or (event.metadata or {}).get("call_id") == call_id)
    ]


def _call_states(events: list[StreamEvent], call_id: str | None = None) -> list[str]:
    return [
        str((event.metadata or {}).get("call_state") or "")
        for event in _status_events(events, call_id)
    ]


def _call_id_of(event: StreamEvent) -> str:
    return str((event.metadata or {}).get("call_id") or "")


@pytest.mark.asyncio
async def test_tool_call_event_args_exclude_private_kwargs() -> None:
    events = await _run_dispatch(
        [{"id": "c1", "name": "exec", "arguments": json.dumps({"command": "true"})}],
        registry=_Registry(),
        kwarg_augmenter=_augment,
    )

    tool_calls = [e for e in events if e.type == StreamEventType.TOOL_CALL]
    assert tool_calls, "tool_call event must be emitted"
    args = tool_calls[0].metadata.get("args") or {}
    assert set(args.keys()) == {"command"}
    # The whole event must survive strict JSON serialization — this is what
    # the WS push and the turn-event store both rely on.
    json.dumps(tool_calls[0].to_dict())


@pytest.mark.asyncio
async def test_non_retrieve_tool_emits_running_then_complete() -> None:
    events = await _run_dispatch(
        [{"id": "c1", "name": "exec", "arguments": json.dumps({"command": "true"})}],
        registry=_Registry(),
    )

    tool_call = next(e for e in events if e.type == StreamEventType.TOOL_CALL)
    statuses = _status_events(events)
    assert [str((e.metadata or {}).get("call_state")) for e in statuses] == [
        "running",
        "complete",
    ]
    # Status must land in the tool's own sub-trace, or the frontend has nothing
    # to group it with.
    assert {_call_id_of(e) for e in statuses} == {_call_id_of(tool_call)}
    assert all(e.type == StreamEventType.PROGRESS for e in statuses)
    # No narrated copy for a plain tool call: the CLI renderer prints non-empty
    # status lines and already headers the call from the ``tool_call`` event.
    assert [e.content for e in statuses] == ["", ""]
    assert all((e.metadata or {}).get("tool_name") == "exec" for e in statuses)


@pytest.mark.asyncio
async def test_retrieve_tool_keeps_its_labelled_variant() -> None:
    events = await _run_dispatch(
        [{"id": "c1", "name": "rag", "arguments": json.dumps({"query": "photosynthesis"})}],
        registry=_Registry(),
        retrieve_meta_factory=_retrieve_meta_factory,
    )

    statuses = _status_events(events)
    assert [e.content for e in statuses] == [
        "Query: photosynthesis",
        "Retrieve complete (2 chars)",
    ]
    for event in statuses:
        meta = event.metadata or {}
        assert meta["label"] == "Retrieve"
        assert meta["call_kind"] == "rag_retrieval"
        assert meta["trace_role"] == "retrieve"
        assert meta["trace_group"] == "retrieve"
        assert meta["query"] == "photosynthesis"


@pytest.mark.asyncio
async def test_raising_tool_emits_terminal_error() -> None:
    events = await _run_dispatch(
        [{"id": "c1", "name": "exec", "arguments": json.dumps({"command": "true"})}],
        registry=_RaisingRegistry(),
    )

    assert _call_states(events) == ["running", "error"]
    terminal = _status_events(events)[-1]
    assert (terminal.metadata or {}).get("error") == "boom"
    assert terminal.content == "exec failed: boom"
    # The model still reads the same result text as before.
    results = [e for e in events if e.type == StreamEventType.TOOL_RESULT]
    assert results[0].content == "Error executing exec: boom"


@pytest.mark.asyncio
async def test_one_failed_tool_does_not_raise_a_turn_level_error() -> None:
    """A failed tool call is recoverable; a stream ERROR is not.

    A partner turn collects ERROR events and, when the turn produced no text,
    re-runs the whole thing on its backup model — re-executing side-effecting
    tools (``exec``, file and notebook writes). Terminality therefore rides on
    ``call_state``, which is all the frontend reads, on a PROGRESS event.
    """
    events = await _run_dispatch(
        [{"id": "c1", "name": "exec", "arguments": json.dumps({"command": "true"})}],
        registry=_RaisingRegistry(),
    )

    assert _call_states(events) == ["running", "error"]
    assert [e for e in events if e.type == StreamEventType.ERROR] == []
    assert _status_events(events)[-1].type == StreamEventType.PROGRESS


@pytest.mark.asyncio
async def test_failed_retrieval_keeps_its_error_event() -> None:
    """Retrieval's ERROR event predates this and repeats no side effects."""
    events = await _run_dispatch(
        [{"id": "c1", "name": "rag", "arguments": json.dumps({"query": "x"})}],
        registry=_RaisingRegistry(),
        retrieve_meta_factory=_retrieve_meta_factory,
    )

    assert _status_events(events)[-1].type == StreamEventType.ERROR


@pytest.mark.asyncio
async def test_a_tool_reporting_failure_in_its_result_is_not_complete() -> None:
    """``success=False`` is this codebase's dominant failure idiom.

    Far more tools report failure in the result than raise, so a terminal state
    that ignored it would be confidently wrong for a failed ``read_file``.
    """

    class _SoftFailRegistry:
        async def execute(self, name: str, **kwargs: Any) -> ToolResult:
            return ToolResult(content="Error: file not found", success=False)

    events = await _run_dispatch(
        [{"id": "c1", "name": "read_file", "arguments": "{}"}],
        registry=_SoftFailRegistry(),
    )

    assert _call_states(events) == ["running", "error"]
    assert [e for e in events if e.type == StreamEventType.ERROR] == []


@pytest.mark.asyncio
async def test_unknown_tool_name_emits_terminal_error() -> None:
    # A real (empty) registry: an unknown name raises KeyError inside execute.
    events = await _run_dispatch(
        [{"id": "c1", "name": "nope", "arguments": "{}"}],
        registry=ToolRegistry(),
    )

    assert _call_states(events) == ["running", "error"]
    terminal = _status_events(events)[-1]
    assert "Unknown tool: nope" in str((terminal.metadata or {}).get("error") or "")


@pytest.mark.asyncio
async def test_parallel_calls_get_their_own_status_pair() -> None:
    events = await _run_dispatch(
        [
            {"id": "c1", "name": "exec", "arguments": json.dumps({"command": "one"})},
            {"id": "c2", "name": "read_source", "arguments": json.dumps({"index": 1})},
        ],
        registry=_Registry(),
    )

    tool_calls = [e for e in events if e.type == StreamEventType.TOOL_CALL]
    call_ids = [_call_id_of(e) for e in tool_calls]
    assert len(set(call_ids)) == 2, "each tool call owns its own sub-trace"
    for call_id in call_ids:
        assert _call_states(events, call_id) == ["running", "complete"]


@pytest.mark.asyncio
async def test_intermediate_progress_from_non_retrieve_tool_reaches_stream() -> None:
    events = await _run_dispatch(
        [{"id": "c1", "name": "exec", "arguments": json.dumps({"command": "true"})}],
        registry=_ProgressRegistry(),
    )

    call_id = _call_id_of(next(e for e in events if e.type == StreamEventType.TOOL_CALL))
    logs = [
        e
        for e in events
        if e.type == StreamEventType.PROGRESS
        and (e.metadata or {}).get("trace_kind") == "tool_log"
        and _call_id_of(e) == call_id
    ]
    assert [e.content for e in logs] == ["step 1/2"]
    # …and it arrives between the two status markers, inside the open sub-trace.
    ordered = [
        str((e.metadata or {}).get("trace_kind"))
        for e in events
        if _call_id_of(e) == call_id and e.type == StreamEventType.PROGRESS
    ]
    assert ordered == ["call_status", "tool_log", "call_status"]
