"""Messages the learner sends while a turn runs are read at the next step."""

from __future__ import annotations

import json

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext
from deeptutor.services.session.turns.inbox import TurnInbox
from tests.agents.chat.test_agent_loop import (  # noqa: F401 — fixture
    _isolated_runtime,
    _llm_chunk,
    _Registry,
    _run,
    _ScriptedChatClient,
)


def test_inbox_keeps_order_drops_retries_and_takes_back_unread() -> None:
    inbox = TurnInbox()
    inbox.put("a", "first")
    inbox.put("b", "  ")
    inbox.put("c", "second")
    inbox.put("a", "first, retried")
    assert inbox.withdraw("c") is True
    assert inbox.withdraw("c") is False
    assert inbox.drain() == [{"command_id": "a", "content": "first"}]
    assert inbox.drain() == []


@pytest.mark.asyncio
async def test_a_message_sent_during_a_tool_reaches_the_next_round(monkeypatch) -> None:
    inbox = TurnInbox()

    class TypingWhileSearching(_Registry):
        async def execute(self, name, **kwargs):
            # The learner sends this while the search is in flight.
            inbox.put("cmd-1", "Only cover the discrete case.")
            return await super().execute(name, **kwargs)

    registry = TypingWhileSearching()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="Searching."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "arguments": json.dumps({"query": "Fourier"}),
                        }
                    ]
                ),
            ],
            [_llm_chunk(content="Here is the discrete transform.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Explain the Fourier transform",
            enabled_tools=["web_search"],
            runtime=TurnRuntimeContext(drain_user_inputs=inbox.drain),
        ),
    )

    first, second = (call["messages"] for call in client.calls)
    assert not any("discrete case" in str(m.get("content")) for m in first)
    # Read after the tool batch, as the learner's own words after the results.
    assert second[-2]["role"] == "tool"
    assert second[-1]["role"] == "user"
    assert "Only cover the discrete case." in second[-1]["content"]
    rows = [e for e in events if (e.metadata or {}).get("trace_kind") == "user_input"]
    assert len(rows) == 1
    assert rows[0].metadata["user_inputs"] == [
        {"command_id": "cmd-1", "content": "Only cover the discrete case."}
    ]
    assert inbox.drain() == []


@pytest.mark.asyncio
async def test_a_turn_without_an_inbox_runs_as_before(monkeypatch) -> None:
    client = _ScriptedChatClient([[_llm_chunk(content="Done.")]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Hi"))

    assert client.call_count == 1
    assert not [e for e in events if (e.metadata or {}).get("trace_kind") == "user_input"]


def test_a_reloaded_turn_keeps_what_the_learner_sent_mid_way(tmp_path) -> None:
    """The settled message is rebuilt from a preview, which keeps only a few
    kinds of row. The learner's mid-turn message has to be one of them, or a
    reload shows an answer to something nobody can see was said."""
    import asyncio

    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "answer"))
    said = {
        "type": "progress",
        "content": "",
        "metadata": {
            "trace_kind": "user_input",
            "user_inputs": [{"command_id": "cmd-1", "content": "Only the discrete case."}],
        },
    }
    asyncio.run(
        store.append_turn_events(
            turn["id"],
            [
                {"type": "progress", "content": "", "metadata": {"trace_kind": "call_status"}},
                said,
                {"type": "done", "content": "", "metadata": {}},
            ],
        )
    )
    asyncio.run(store.link_turn_message(turn["id"], message_id))

    detail = asyncio.run(store.get_session_with_messages(session["id"]))

    events = detail["messages"][0]["events"]
    kinds = [(event.get("metadata") or {}).get("trace_kind") for event in events]
    assert "user_input" in kinds
    assert "call_status" not in kinds
