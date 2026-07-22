"""Event-payload safety for the parallel tool dispatcher.

Regression for the Mount-poisoning incident: server-injected private kwargs
(``_sandbox_mounts`` — a Mount dataclass — and friends) leaked into the
``tool_call`` event's ``args`` metadata. The event was not JSON-serializable,
which silently killed the WebSocket push (safe_send swallowed the error and
flagged the socket closed) AND turn persistence (json.dumps in the store),
leaving the turn stuck "running" and later mislabelled as a restart orphan.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.core.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.services.sandbox import Mount


class _Registry:
    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        return ToolResult(content="ok", success=True)


def _augment(tool_name: str, tool_args: dict[str, Any], _ctx: UnifiedContext) -> dict[str, Any]:
    # Mirrors the chat pipeline: server-side plumbing rides on private keys.
    return {
        **tool_args,
        "_sandbox_user_id": "u1",
        "_sandbox_workdir": "/tmp/x",
        "_sandbox_mounts": (Mount(host_path="/tmp/x", sandbox_path="/tmp/x", read_only=False),),
    }


@pytest.mark.asyncio
async def test_tool_call_event_args_exclude_private_kwargs() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    import asyncio

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await dispatch_tool_calls(
        tool_calls=[{"id": "c1", "name": "exec", "arguments": json.dumps({"command": "true"})}],
        context=UnifiedContext(session_id="s1", user_message="hi"),
        stream=bus,
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=_Registry(),
        kwarg_augmenter=_augment,
    )
    await bus.close()
    await consumer

    tool_calls = [e for e in events if e.type == StreamEventType.TOOL_CALL]
    assert tool_calls, "tool_call event must be emitted"
    args = tool_calls[0].metadata.get("args") or {}
    assert set(args.keys()) == {"command"}
    # The whole event must survive strict JSON serialization — this is what
    # the WS push and the turn-event store both rely on.
    json.dumps(tool_calls[0].to_dict())
