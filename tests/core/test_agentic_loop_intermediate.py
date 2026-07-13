"""Tests for the optional ``LoopHost.on_intermediate`` hook.

The hook fires after the loop appends an intermediate-label assistant
message; if the host returns a non-empty string it gets injected as
the next iteration's user message. Used by research's ``APPEND`` label
to feed structured "queue mutated" feedback back to the LLM. Existing
hosts (chat, solve) do not implement the hook and must continue to
work unchanged.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.agentic.loop import LabelProtocol, run_agentic_loop
from deeptutor.core.agentic.tool_dispatch import DispatchOutcome
from deeptutor.core.stream_bus import StreamBus

# --------------------------- scripted LLM client ---------------------------


def _llm_chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))]
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ScriptedClient:
    """Minimal LLM client returning pre-scripted streamed chunks."""

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


# ---------------------------- host implementations ---------------------------


class _BaseHost:
    """LoopHost stub with the minimal required surface, no ``on_intermediate``."""

    def __init__(self) -> None:
        self.final_text: str | None = None

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        return None

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        return ({"iter": iteration}, {"iter": iteration, "final": True})

    async def dispatch_tools(self, *, iteration, tool_calls):  # pragma: no cover
        return DispatchOutcome(sources=[], tool_messages=[])

    async def resolve_pause(self, dispatch):  # pragma: no cover
        return False

    async def emit_terminator(self, payload):  # pragma: no cover
        return None

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        self.final_text = text

    def assistant_message_with_tool_calls(self, *, content, tool_calls):
        return {"role": "assistant", "content": content, "tool_calls": tool_calls}

    def protocol_retry_notice(self) -> str:
        return "retry"

    def protocol_repair_message(self, violation: str) -> str:
        return f"repair:{violation}"

    async def force_finalize(self, *, messages, start_iteration):
        return ("", False, 0)


class _AppendHost(_BaseHost):
    """Host that mutates state on a synthetic ``APPEND`` intermediate label
    and returns a confirmation note the loop will inject as user feedback."""

    def __init__(self) -> None:
        super().__init__()
        self.appended: list[str] = []

    async def on_intermediate(self, label: str, text: str) -> str | None:
        if label != "APPEND":
            return None
        title = (text or "").strip().split("\n", 1)[0].strip()
        if not title:
            return None
        self.appended.append(title)
        return f"Appended block #{len(self.appended)}: {title}"


# ------------------------------- tests -------------------------------


_PROTOCOL = LabelProtocol(
    allowed=("THINK", "APPEND", "FINISH"),
    terminal=frozenset({"FINISH"}),
    intermediate=frozenset({"THINK", "APPEND"}),
    final=frozenset({"FINISH"}),
    tool_label=None,
)


def _script_for_two_iterations(
    first_label: str,
    first_body: str,
    final_body: str = "done",
) -> list[list[SimpleNamespace]]:
    return [
        [_llm_chunk(f"``{first_label}``\n{first_body}")],
        [_llm_chunk(f"``FINISH``\n{final_body}")],
    ]


@pytest.mark.asyncio
async def test_loop_without_on_intermediate_hook_preserves_legacy_behavior() -> None:
    """A host that does NOT implement ``on_intermediate`` (e.g. chat,
    solve) must still drive the loop end-to-end. The intermediate
    label's text becomes an assistant message; no user feedback is
    injected."""
    client = _ScriptedClient(_script_for_two_iterations("THINK", "reasoning step"))
    host = _BaseHost()
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        outcome = await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "hi"}],
            protocol=_PROTOCOL,
            client=client,
            model="x",
            completion_kwargs={},
            binding="openai",
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

    assert outcome.completed is True
    assert outcome.final_text.strip() == "done"
    # Iteration 2 saw the THINK text as assistant context; no user feedback.
    iter2_msgs = client.calls[1]
    assistant_msgs = [m for m in iter2_msgs if m.get("role") == "assistant"]
    user_msgs = [m for m in iter2_msgs if m.get("role") == "user"]
    assert any("reasoning step" in (m.get("content") or "") for m in assistant_msgs)
    # Only the original user prompt — no feedback injected.
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "hi"


@pytest.mark.asyncio
async def test_loop_calls_on_intermediate_and_injects_feedback() -> None:
    """A host implementing ``on_intermediate`` for ``APPEND`` should
    (a) be called with the label + text, and
    (b) have its non-empty return value injected as a user message
    visible to the next LLM iteration."""
    client = _ScriptedClient(_script_for_two_iterations("APPEND", "Quantum entanglement basics"))
    host = _AppendHost()
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        outcome = await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "go"}],
            protocol=_PROTOCOL,
            client=client,
            model="x",
            completion_kwargs={},
            binding="openai",
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

    assert outcome.completed is True
    assert host.appended == ["Quantum entanglement basics"]

    # Iteration 2's messages must include both the assistant APPEND
    # prose AND a user feedback note carrying the host's confirmation.
    iter2_msgs = client.calls[1]
    assistant_texts = [m.get("content") or "" for m in iter2_msgs if m.get("role") == "assistant"]
    user_texts = [m.get("content") or "" for m in iter2_msgs if m.get("role") == "user"]
    assert any("Quantum entanglement basics" in t for t in assistant_texts)
    assert any("Appended block #1: Quantum entanglement basics" in t for t in user_texts)


@pytest.mark.asyncio
async def test_loop_validate_terminal_can_repair_premature_finish() -> None:
    """A host can reject a terminal label when stateful requirements have
    not been met, causing the loop to inject a normal protocol repair and
    continue instead of accepting the FINISH."""

    class _TerminalGuardHost(_BaseHost):
        def __init__(self) -> None:
            super().__init__()
            self.rejections = 0

        async def validate_terminal(self, label: str, text: str) -> str | None:
            if self.rejections == 0:
                self.rejections += 1
                return "finish_without_tool"
            return None

    client = _ScriptedClient(
        [
            [_llm_chunk("``FINISH``\nPremature synthesis")],
            [_llm_chunk("``FINISH``\nEvidence-backed synthesis")],
        ]
    )
    host = _TerminalGuardHost()
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        outcome = await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "go"}],
            protocol=_PROTOCOL,
            client=client,
            model="x",
            completion_kwargs={},
            binding="openai",
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

    assert outcome.completed is True
    assert outcome.final_text.strip() == "Evidence-backed synthesis"
    assert host.rejections == 1
    iter2_user_texts = [m.get("content") or "" for m in client.calls[1] if m.get("role") == "user"]
    assert any("repair:finish_without_tool" in t for t in iter2_user_texts)


@pytest.mark.asyncio
async def test_intermediate_label_in_final_set_streams_body_and_continues() -> None:
    """A label that is BOTH intermediate AND final (e.g. chat's PAUSE)
    must:
      1. emit its post-label text to the user-facing body via
         ``emit_final`` so the chat bubble streams it,
      2. NOT exit the loop — the next iteration runs and can FINISH.
    """

    class _RecordingHost(_BaseHost):
        def __init__(self) -> None:
            super().__init__()
            self.emit_final_calls: list[str] = []

        async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
            self.emit_final_calls.append(text)
            self.final_text = text

    protocol = LabelProtocol(
        allowed=("THINK", "PAUSE", "FINISH"),
        terminal=frozenset({"FINISH"}),
        intermediate=frozenset({"THINK", "PAUSE"}),
        # ``PAUSE`` is intermediate AND final — body-streaming + loop continues.
        final=frozenset({"FINISH", "PAUSE"}),
        tool_label=None,
    )
    client = _ScriptedClient(
        [
            [_llm_chunk("``PAUSE``\nlet me check first")],
            [_llm_chunk("``FINISH``\nhere is the answer")],
        ]
    )
    host = _RecordingHost()
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        outcome = await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "hi"}],
            protocol=protocol,
            client=client,
            model="x",
            completion_kwargs={},
            binding="openai",
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

    # Loop completed via FINISH, not via PAUSE.
    assert outcome.completed is True
    assert outcome.final_label == "FINISH"
    assert outcome.final_text.strip() == "here is the answer"
    # emit_final was called twice: once for PAUSE (mid-loop), once for FINISH.
    assert len(host.emit_final_calls) == 2
    assert host.emit_final_calls[0].strip() == "let me check first"
    assert host.emit_final_calls[1].strip() == "here is the answer"
    # The PAUSE prose is also kept as assistant context for iteration 2.
    iter2_msgs = client.calls[1]
    assistant_texts = [m.get("content") or "" for m in iter2_msgs if m.get("role") == "assistant"]
    assert any("let me check first" in t for t in assistant_texts)


@pytest.mark.asyncio
async def test_before_iteration_hook_runs_each_iteration() -> None:
    """``LoopHost.before_iteration`` (optional) fires once per iteration
    after ``guard_context_window`` and before the LLM call. The host can
    use it to inject per-iteration context — e.g. a "you are at N/M"
    marker so the LLM can pace itself."""

    class _MarkerHost(_BaseHost):
        def __init__(self) -> None:
            super().__init__()
            self.fired: list[tuple[int, int]] = []

        async def before_iteration(
            self,
            *,
            messages: list[dict[str, Any]],
            iteration: int,
            max_iterations: int,
        ) -> None:
            self.fired.append((iteration, max_iterations))
            messages.append(
                {"role": "user", "content": f"[marker] {iteration + 1}/{max_iterations}"}
            )

    client = _ScriptedClient(
        [
            [_llm_chunk("``THINK``\nfirst pass")],
            [_llm_chunk("``FINISH``\ndone")],
        ]
    )
    host = _MarkerHost()
    bus = StreamBus()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        outcome = await run_agentic_loop(
            initial_messages=[{"role": "user", "content": "hi"}],
            protocol=_PROTOCOL,
            client=client,
            model="x",
            completion_kwargs={},
            binding="openai",
            tool_schemas=None,
            stream=bus,
            source="test",
            stage="test",
            max_iterations=5,
            host=host,
        )
    finally:
        await bus.close()
        await consumer

    assert outcome.completed is True
    # Fired twice — once per iteration, with the right counters.
    assert host.fired == [(0, 5), (1, 5)]
    # Both LLM calls saw a marker in their messages tail.
    iter1_markers = [m for m in client.calls[0] if "[marker]" in (m.get("content") or "")]
    iter2_markers = [m for m in client.calls[1] if "[marker]" in (m.get("content") or "")]
    assert any("1/5" in m.get("content", "") for m in iter1_markers)
    assert any("2/5" in m.get("content", "") for m in iter2_markers)


@pytest.mark.asyncio
async def test_loop_on_intermediate_returning_none_injects_nothing() -> None:
    """If ``on_intermediate`` returns ``None`` (or empty), the loop must
    not inject any user message — same as the no-hook behavior."""

    class _SilentHost(_BaseHost):
        async def on_intermediate(self, label: str, text: str) -> str | None:
            return None  # never inject

    client = _ScriptedClient(_script_for_two_iterations("THINK", "x"))
    host = _SilentHost()
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
            model="x",
            completion_kwargs={},
            binding="openai",
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

    iter2_msgs = client.calls[1]
    user_msgs = [m for m in iter2_msgs if m.get("role") == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "hi"
