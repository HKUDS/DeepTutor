"""The shared agentic loop must echo a round's reasoning on the next request.

DeepSeek's thinking models reject a continuation whose history has lost the
previous assistant turn's reasoning:

    The `reasoning_content` in the thinking mode must be passed back to the API.

Chat's own loop has always replayed it. The shared ``runtime/agentic`` loop —
the one quiz, research, PageIndex and explore_context all run on — read
``reasoning_content`` off the stream, pushed it to the trace UI for display,
and then dropped it. Round one could not fail (system + user only); round two
always did.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime.agentic.loop import LabelProtocol, run_agentic_loop
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.stream_bus import StreamBus


def _content_chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))]
    )


def _reasoning_chunk(reasoning: str) -> SimpleNamespace:
    """A thinking model's reasoning phase emits no ``delta.content`` at all."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=None, reasoning_content=reasoning)
            )
        ]
    )


def _signed_thinking_chunk(blocks: list[dict[str, Any]]) -> SimpleNamespace:
    """Anthropic's signed blocks ride on the choice, not the delta."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=None),
                provider_specific_fields={"thinking_blocks": blocks},
            )
        ]
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
        self.final_text: str | None = None

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        return None

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        return ({"iter": iteration}, {"iter": iteration, "final": True})

    async def dispatch_tools(self, *, iteration, tool_calls):
        return DispatchOutcome(
            sources=[],
            tool_messages=[
                {"role": "tool", "tool_call_id": call["id"], "content": "{}"} for call in tool_calls
            ],
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

    async def force_finalize(self, *, messages, start_iteration):
        return ("", False, 0)


_PROTOCOL = LabelProtocol(
    allowed=("THINK", "TOOL", "FINISH"),
    terminal=frozenset({"FINISH"}),
    intermediate=frozenset({"THINK"}),
    final=frozenset({"FINISH"}),
    tool_label="TOOL",
)


async def _run(scripts: list[list[SimpleNamespace]]) -> _ScriptedClient:
    client = _ScriptedClient(scripts)
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
            host=_Host(),
        )
    finally:
        await bus.close()
        await consumer
    return client


def _assistant_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in messages if m.get("role") == "assistant"]


@pytest.mark.asyncio
async def test_a_tool_round_replays_its_reasoning() -> None:
    """The strict case: DeepSeek requires it on the turn that called tools."""
    client = await _run(
        [
            [
                _reasoning_chunk("I should look this up."),
                _content_chunk("``TOOL``\n"),
                _tool_call_chunk("c1", "read_source", "{}"),
            ],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    second_request = _assistant_messages(client.calls[1])
    assert len(second_request) == 1
    assert second_request[0]["reasoning_content"] == "I should look this up."
    assert second_request[0]["tool_calls"]


@pytest.mark.asyncio
async def test_an_intermediate_round_replays_its_reasoning() -> None:
    client = await _run(
        [
            [
                _reasoning_chunk("Weighing two framings."),
                _content_chunk("``THINK``\nstill working"),
            ],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    second_request = _assistant_messages(client.calls[1])
    assert second_request[0]["reasoning_content"] == "Weighing two framings."


@pytest.mark.asyncio
async def test_a_repair_round_replays_its_reasoning() -> None:
    """A protocol violation still produced a round, and it still had reasoning."""
    client = await _run(
        [
            [
                _reasoning_chunk("Forgot the label."),
                _content_chunk("no label at all"),
            ],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    second_request = _assistant_messages(client.calls[1])
    assert second_request[0]["reasoning_content"] == "Forgot the label."


@pytest.mark.asyncio
async def test_signed_thinking_blocks_survive_the_round() -> None:
    """Anthropic's blocks are signed, so they cannot be rebuilt from text."""
    blocks = [{"type": "thinking", "thinking": "…", "signature": "sig-1"}]
    client = await _run(
        [
            [
                _signed_thinking_chunk(blocks),
                _content_chunk("``TOOL``\n"),
                _tool_call_chunk("c1", "read_source", "{}"),
            ],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    second_request = _assistant_messages(client.calls[1])
    assert second_request[0]["thinking_blocks"] == blocks


@pytest.mark.asyncio
async def test_a_round_without_reasoning_adds_no_field() -> None:
    """An ordinary model's history must be byte-identical to before."""
    client = await _run(
        [
            [_content_chunk("``THINK``\nplain"), _content_chunk("")],
            [_content_chunk("``FINISH``\ndone")],
        ]
    )

    second_request = _assistant_messages(client.calls[1])
    assert "reasoning_content" not in second_request[0]
    assert "thinking_blocks" not in second_request[0]
