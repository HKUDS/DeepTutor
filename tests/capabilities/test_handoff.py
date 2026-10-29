"""Handing a turn over: the delegate's run becomes the conversation's own."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.handoff import capability as handoff
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.core.turn_request import TurnRequest
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.session._turn_runtime_shared import _should_capture_assistant_content
from deeptutor.services.subagent.types import ConsultResult, SubagentEvent


async def _drain(bus: StreamBus, work) -> list:
    events = []

    async def collect():
        async for event in bus.subscribe():
            events.append(event)

    reader = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await work()
    await bus.close()
    await reader
    return events


def _context(answer_by: str) -> UnifiedContext:
    return UnifiedContext(
        session_id="chat-1",
        user_message="Why does BM25 saturate?",
        runtime=TurnRuntimeContext(answer_by=answer_by),
    )


def test_answer_by_names_a_kind_and_a_target() -> None:
    assert handoff.parse_answer_by("partner:p1") == ("partner", "p1")
    assert handoff.parse_answer_by("subagent:Claude Code") == ("subagent", "Claude Code")
    assert handoff.parse_answer_by("deeptutor:x") is None
    assert handoff.parse_answer_by("partner:") is None
    assert TurnRequest(content="hi", answer_by="partner:p1").answer_by == "partner:p1"
    with pytest.raises(ValueError):
        TurnRequest(content="hi", answer_by="everyone")


@pytest.mark.asyncio
async def test_an_agent_run_is_written_as_rounds_and_tool_rows(monkeypatch) -> None:
    """Running text becomes deltas; a tool closes the round it interrupts; the
    last round is the finish — so the answer persists and the process folds."""

    class Backend:
        async def consult(self, question, *, on_event, config, **_):
            assert question == "Why does BM25 saturate?"
            seen_config["prompt"] = config.system_prompt
            await on_event(SubagentEvent("reasoning", "Check the", meta={"merge_id": "r:1"}))
            await on_event(
                SubagentEvent("reasoning", "Check the formula", meta={"merge_id": "r:1"})
            )
            await on_event(SubagentEvent("text", "Let me look", meta={"merge_id": "t:1"}))
            await on_event(SubagentEvent("tool", "Bash: grep -n k1 bm25.py"))
            await on_event(SubagentEvent("tool_result", "12: k1 = 1.2"))
            await on_event(SubagentEvent("text", "Term frequency", meta={"merge_id": "t:2"}))
            await on_event(
                SubagentEvent("text", "Term frequency saturates at k1.", meta={"merge_id": "t:2"})
            )
            return ConsultResult(final_text="Term frequency saturates at k1.", session_id="s-9")

    import deeptutor.multi_user.knowledge_access as access
    import deeptutor.services.subagent as subagent
    import deeptutor.services.subagent.sessions as sessions

    monkeypatch.setattr(
        access,
        "resolve_kb_metadata",
        lambda ref: {"type": "subagent", "agent_kind": "claude_code", "name": ref, "cwd": "/repo"},
    )
    monkeypatch.setattr(subagent, "get_backend", lambda kind: Backend())
    seen_config = {}

    from deeptutor.services.subagent.config import BackendConfig

    monkeypatch.setattr(
        subagent,
        "load_subagent_settings",
        lambda: SimpleNamespace(backend=lambda kind: BackendConfig()),
    )
    remembered = {}
    monkeypatch.setattr(sessions, "get_session", lambda key: None)
    monkeypatch.setattr(
        sessions, "remember_session", lambda key, sid, **_: remembered.setdefault(key, sid)
    )

    bus = StreamBus()
    events = await _drain(
        bus, lambda: handoff.HandoffCapability().run(_context("subagent:Claude Code"), bus)
    )

    answer = "".join(e.content for e in events if _should_capture_assistant_content(e))
    assert answer == "Let me look\n\nTerm frequency saturates at k1."
    thinking = "".join(e.content for e in events if e.type == StreamEventType.THINKING)
    assert thinking == "Check the formula"
    roles = [
        e.metadata["call_role"]
        for e in events
        if e.metadata.get("trace_kind") == "call_status"
        and e.metadata.get("call_kind") == "agent_loop_round"
        and e.metadata.get("call_state") == "complete"
    ]
    assert roles == ["narration", "finish"]
    tool = next(e for e in events if e.type == StreamEventType.TOOL_CALL)
    result = next(e for e in events if e.type == StreamEventType.TOOL_RESULT)
    assert tool.content == "Bash" and tool.metadata["args"] == {"input": "grep -n k1 bm25.py"}
    assert result.metadata["call_id"] == tool.metadata["call_id"]
    final = next(e for e in events if e.type == StreamEventType.RESULT)
    assert final.metadata["response"] == "Term frequency saturates at k1."
    assert final.metadata["metadata"]["answered_by"]["name"] == "Claude Code"
    assert final.metadata["metadata"]["answered_by"]["agent"] == "claude_code"
    assert remembered == {"chat-1::Claude Code": "s-9"}
    # It is told it is answering the learner, not being consulted by DeepTutor.
    assert "answering the user directly" in seen_config["prompt"]


@pytest.mark.asyncio
async def test_a_partner_reply_is_forwarded_as_its_own_work(monkeypatch) -> None:
    """The partner already speaks this protocol: its events pass through,
    tagged with who wrote them, and its own turn frames stay behind."""

    class Live:
        def __init__(self):
            self.task = None
            self.subscribers = set()
            self.queue: asyncio.Queue = asyncio.Queue()

        def subscribe(self):
            self.subscribers.add(self.queue)
            return self.queue

    live = Live()
    round_meta = {"call_id": "r1", "call_kind": "agent_loop_round"}
    for frame in (
        {"type": "stream_event", "event": {"type": "stage_start", "metadata": {}}},
        {
            "type": "stream_event",
            "event": {"type": "content", "content": "Hi, ", "metadata": round_meta},
        },
        {
            "type": "stream_event",
            "event": {"type": "content", "content": "I'm Ada.", "metadata": round_meta},
        },
        {"type": "stream_event", "event": {"type": "result", "metadata": {"response": "x"}}},
        {"type": "content", "content": "Hi, I'm Ada."},
        {"type": "done"},
    ):
        live.queue.put_nowait(frame)

    started = {}

    class Manager:
        def partner_exists(self, pid):
            return True

        def get_partner(self, pid):
            return SimpleNamespace(running=True)

        def subscribe_web_turn(self, pid, key):
            return None

        def start_web_turn(self, pid, key, content, media=None):
            started.update(pid=pid, key=key, content=content)
            return live

    import deeptutor.multi_user.partner_access as access
    import deeptutor.services.partners as partners
    import deeptutor.services.subagent.sessions as sessions

    monkeypatch.setattr(access, "assert_partner_allowed", lambda pid: None)
    monkeypatch.setattr(
        access,
        "visible_partner_cards",
        lambda: [{"partner_id": "p1", "name": "Ada", "emoji": "🦉", "color": "#8b5cf6"}],
    )
    monkeypatch.setattr(partners, "get_partner_manager", lambda: Manager())
    monkeypatch.setattr(sessions, "get_session", lambda key: "dt-kept")
    monkeypatch.setattr(sessions, "remember_session", lambda *a, **k: None)

    bus = StreamBus()
    events = await _drain(bus, lambda: handoff.HandoffCapability().run(_context("partner:p1"), bus))

    assert started == {"pid": "p1", "key": "dt-kept", "content": "Why does BM25 saturate?"}
    contents = [e for e in events if e.type == StreamEventType.CONTENT]
    assert [e.content for e in contents] == ["Hi, ", "I'm Ada."]
    assert all(e.metadata["delegate_name"] == "Ada" for e in contents)
    # Enough to draw the partner's mark, nothing heavier.
    assert contents[0].metadata["delegate_emoji"] == "🦉"
    assert contents[0].metadata["delegate_color"] == "#8b5cf6"
    # Its own stage and result never reach this turn; only ours does.
    assert not [
        e for e in events if e.type == StreamEventType.STAGE_START and e.source != "handoff"
    ]
    results = [e for e in events if e.type == StreamEventType.RESULT]
    assert len(results) == 1 and results[0].metadata["response"] == "Hi, I'm Ada."
    assert results[0].metadata["metadata"]["answered_by"] == {
        "kind": "partner",
        "id": "p1",
        "name": "Ada",
        "emoji": "🦉",
        "color": "#8b5cf6",
    }
