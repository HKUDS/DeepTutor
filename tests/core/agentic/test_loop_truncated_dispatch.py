"""A tool batch cut off by the output limit must never reach the host.

The chat loop learned this in #2719: ``dispatch_tool_calls`` repairs malformed
arguments before running a tool, which is right for a complete call that came
back mangled and wrong for one the provider cut off mid-string — repair closes
the partial value and the tool runs on it. The shared ``runtime/agentic`` loop
is the choke point quiz, research, PageIndex and explore_context dispatch
through, and it had no such check: ``LabeledStepResult.finish_reason`` was
captured and then ignored.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime.agentic.loop import LabelProtocol, run_agentic_loop
from deeptutor.runtime.agentic.tool_dispatch import (
    TRUNCATED_TOOL_CALL_NOTICE,
    DispatchOutcome,
)
from deeptutor.runtime.stream_bus import StreamBus

#: Cut off mid-string: ``json.loads`` fails, and a repair pass would close it.
_CUT_OFF = '{"note": "Calculus/Week 7", "content": "## Integration'
_CALL_ID = "call_truncated_1"


def _content_chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))]
    )


def _tool_call_chunk(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=call_id,
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                )
            )
        ]
    )


def _finish_chunk(reason: str) -> SimpleNamespace:
    """The terminal chunk: a reason, usually no delta at all."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=None), finish_reason=reason
            )
        ]
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ScriptedClient:
    def __init__(self, scripts: list[list[SimpleNamespace]]) -> None:
        self._scripts = list(scripts)
        self.calls: list[list[dict[str, Any]]] = []

        class _Completions:
            def __init__(self, parent: _ScriptedClient) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any):
                self.parent.calls.append(list(kwargs.get("messages") or []))
                if not self.parent._scripts:
                    raise RuntimeError("scripted client exhausted")
                return _async_stream(self.parent._scripts.pop(0))

        class _Chat:
            def __init__(self, parent: _ScriptedClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


class _Host:
    def __init__(self) -> None:
        self.dispatched: list[list[dict[str, Any]]] = []
        self.final_text: str | None = None

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        return None

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        return ({"iter": iteration}, {"iter": iteration, "final": True})

    async def dispatch_tools(self, *, iteration, tool_calls):
        self.dispatched.append(list(tool_calls))
        return DispatchOutcome(
            tool_messages=[
                {"role": "tool", "tool_call_id": call["id"], "content": "{}"} for call in tool_calls
            ]
        )

    async def resolve_pause(self, dispatch):  # pragma: no cover
        return False

    async def emit_terminator(self, payload):  # pragma: no cover
        return None

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        self.final_text = text

    def protocol_retry_notice(self) -> str:
        return "retry"

    def protocol_repair_message(self, violation: str) -> str:
        return f"repair:{violation}"

    async def force_finalize(self, *, messages, start_iteration):  # pragma: no cover
        return ("", False, 0)


_PROTOCOL = LabelProtocol(
    allowed=("TOOL", "FINISH"),
    terminal=frozenset({"FINISH"}),
    intermediate=frozenset(),
    final=frozenset({"FINISH"}),
    tool_label="TOOL",
)


async def _run(scripts: list[list[SimpleNamespace]]) -> tuple[_ScriptedClient, _Host]:
    client = _ScriptedClient(scripts)
    host = _Host()
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "hi"}],
            protocol=_PROTOCOL,
            client=client,
            model="deepseek-v4-flash",
            completion_kwargs={},
            binding="deepseek",
            tool_schemas=None,
            stream=bus,
            source="test",
            stage="test",
            max_iterations=4,
            host=host,
        )
    finally:
        await bus.close()
        await consumer
    return client, host


@pytest.mark.asyncio
async def test_a_truncated_tool_batch_is_refused_not_dispatched() -> None:
    client, host = await _run(
        [
            [
                _content_chunk("``TOOL``\n"),
                _tool_call_chunk(_CALL_ID, "obsidian_append", _CUT_OFF),
                _finish_chunk("length"),
            ],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    assert host.dispatched == []

    second_request = client.calls[1]
    tool_messages = [m for m in second_request if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == [_CALL_ID]
    assert tool_messages[0]["content"] == TRUNCATED_TOOL_CALL_NOTICE

    # The assistant turn is still recorded, arguments untouched: the model has
    # to see which call it was that did not run.
    assistant = [m for m in second_request if m.get("role") == "assistant"]
    replayed = assistant[0]["tool_calls"][0]
    assert replayed["function"]["arguments"] == _CUT_OFF


@pytest.mark.asyncio
async def test_a_complete_tool_batch_still_dispatches() -> None:
    """The guard keys on the finish reason, not on the call being suspicious."""
    client, host = await _run(
        [
            [
                _content_chunk("``TOOL``\n"),
                _tool_call_chunk("call_ok", "obsidian_append", '{"note": "n"}'),
                _finish_chunk("tool_calls"),
            ],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    assert len(host.dispatched) == 1
    assert host.dispatched[0][0]["id"] == "call_ok"
