from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.services.session.context_builder import ContextBuilder, _ContextSummaryAgent
from deeptutor.services.session.model_history import (
    complete_tool_results,
    normalize_model_turn,
    replay_history,
)
from deeptutor.services.session.provider_response_state import redact_private_message_metadata


def turn_record(text="tool evidence"):
    return {
        "version": 1,
        "system": "Standing tutor instructions",
        "tools": [
            {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}
        ],
        "route": {"provider": "openai", "model": "gpt-test"},
        "messages": [
            {"role": "user", "content": "Question with prepared seed"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "private plan",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{ "key": "value" }'},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": text},
            {"role": "assistant", "content": "Original answer"},
        ],
    }


def rows(record, start=1):
    return [
        {"id": start, "role": "user", "content": "Question"},
        {
            "id": start + 1,
            "role": "assistant",
            "content": "Displayed answer",
            "metadata": {"model_turn": record},
        },
    ]


def test_replay_preserves_exact_protocol_without_duplicating_the_display_rows():
    record = turn_record()
    source = rows(record)
    result = replay_history(source)
    assert result == record["messages"]
    result[-1]["content"] = "mutated by the next turn"
    assert record["messages"][-1]["content"] == "Original answer"
    redact_private_message_metadata(source)
    assert source[-1]["metadata"] == {}


def test_invalid_or_incomplete_protocol_uses_display_history():
    record = turn_record()
    record["messages"].pop(2)
    assert normalize_model_turn(record) is None
    assert replay_history(rows(record)) == [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Displayed answer"},
    ]
    record["version"] = 99
    assert normalize_model_turn(record) is None


def test_interruption_closes_unfinished_calls_without_claiming_success():
    messages = turn_record()["messages"][:2]
    closed = complete_tool_results(messages)
    assert len(messages) == 2
    assert closed[-1]["tool_call_id"] == "call-1"
    assert "interrupted" in closed[-1]["content"]
    assert normalize_model_turn({"version": 1, "messages": closed}) is not None


def test_model_switch_keeps_tool_evidence_but_drops_provider_private_state():
    record = turn_record()
    record["messages"][1]["_provider_response_state"] = {
        "responses_output_items": [{"type": "reasoning", "id": "provider-only"}]
    }
    source = rows(record)
    same = replay_history(source, route=record["route"])
    switched = replay_history(source, route={"provider": "anthropic", "model": "claude-test"})
    assert same[1]["reasoning_content"] == "private plan"
    assert "reasoning_content" not in switched[1]
    assert "_provider_response_state" not in switched[1]
    assert switched[1]["tool_calls"] == same[1]["tool_calls"]
    assert switched[2]["content"] == "tool evidence"


def test_image_and_resolved_user_reply_survive_the_private_history_projection():
    record = turn_record()
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}}
    record["messages"][0]["content"] = [{"type": "text", "text": "Explain this"}, image]
    record["messages"][1]["tool_calls"][0]["function"]["name"] = "ask_user"
    record["messages"][2]["content"] = "The user answered: use a geometric proof."
    rebuilt = replay_history(rows(record))
    assert rebuilt[0]["content"][1] == image
    assert rebuilt[2]["tool_call_id"] == "call-1"
    assert "geometric proof" in rebuilt[2]["content"]


@pytest.mark.asyncio
async def test_compaction_preserves_whole_tool_turns_and_reuses_the_old_prefix():
    old = turn_record("evidence " * 1800)
    recent = turn_record("recent evidence")
    records = rows(old) + rows(recent, 3)
    store = MagicMock()
    store.get_session = AsyncMock(
        return_value={"compressed_summary": "", "summary_up_to_msg_id": 0}
    )
    store.get_messages_for_context = AsyncMock(return_value=records)
    store.update_summary = AsyncMock()
    builder = ContextBuilder(store)
    builder._summarize = AsyncMock(return_value=("Summary preserving the evidence", []))
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(
            model="gpt-test",
            max_tokens=512,
            context_window=4096,
        ),
    )
    request = builder._summarize.call_args.kwargs["replay_request"]
    assert request["messages"] == [
        {"role": "system", "content": recent["system"]},
        *old["messages"],
    ]
    assert request["tools"] == recent["tools"]
    store.update_summary.assert_awaited_once_with("s", "Summary preserving the evidence", 2)
    assert result.model_history[1:] == recent["messages"]
    assert result.conversation_history[-1]["content"] == "Displayed answer"


@pytest.mark.asyncio
async def test_summary_instruction_is_appended_after_original_messages_and_tools(monkeypatch):
    captured = {}

    async def stream(_self, **kwargs):
        captured.update(kwargs)
        yield "Summary"

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    record = turn_record()
    request = {
        "messages": [{"role": "system", "content": record["system"]}, *record["messages"]],
        "tools": record["tools"],
    }
    original = deepcopy(request)
    await ContextBuilder(MagicMock())._summarize(
        session_id="s",
        language="en",
        source_text="fallback transcript",
        summary_budget=256,
        replay_request=request,
    )
    assert captured["messages"][:-1] == request["messages"]
    assert captured["messages"][-1]["role"] == "user"
    assert captured["tools"] == request["tools"]
    assert "tool_choice" not in captured
    assert request == original


@pytest.mark.asyncio
async def test_branch_replay_and_public_export_are_isolated(tmp_path):
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(db_path=tmp_path / "history.db")
    session = await store.create_session()
    sid = session["id"]
    root = await store.add_message(sid, "user", "Root")
    first = await store.add_message(
        sid,
        "assistant",
        "Branch A",
        parent_message_id=root,
        metadata={"model_turn": turn_record("A only")},
    )
    await store.add_message(
        sid,
        "assistant",
        "Branch B",
        parent_message_id=root,
        metadata={"model_turn": turn_record("B only")},
    )
    built = await ContextBuilder(store).build(
        session_id=sid,
        leaf_message_id=first,
        llm_config=SimpleNamespace(model="gpt-test", context_window=128000, max_tokens=4096),
    )
    tool_results = [m["content"] for m in built.model_history if m["role"] == "tool"]
    assert tool_results == ["A only"]
