"""No model/network calls: actual history projection and memory failure seams."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.capabilities.mastery.history import project_mastery_replay
from deeptutor.capabilities.mastery.memory import MasteryContextBuilder
from deeptutor.services.session.context_builder import (
    ContextBuilder,
    _ContextSummaryAgent,
    count_tokens,
)
from deeptutor.services.session.model_history import normalize_model_turn


@pytest.fixture(autouse=True)
def isolated_agent_settings(monkeypatch):
    # The provider is stubbed below; no installation-local settings are needed.
    monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _module: {})


def records(n=8, padding=2000):
    result = []
    for i in range(n):
        call_id = f"call-{i}"
        messages = [
            {"role": "user", "content": f"I confuse A with B; example {i} failed."},
            {
                "role": "assistant",
                "content": "We tried a different explanation.",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "mastery_grade", "arguments": '{"verdict":"partial"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"verdict": "partial", "reason": f"distinct-{i} " * padding}),
            },
            {"role": "assistant", "content": "This remains uncertain."},
        ]
        result.extend(
            [
                {"id": 2 * i + 1, "role": "user", "content": messages[0]["content"]},
                {
                    "id": 2 * i + 2,
                    "role": "assistant",
                    "content": "This remains uncertain.",
                    "metadata": {
                        "model_turn": {
                            "version": 1,
                            "messages": messages,
                            "system": "Huge tutor instructions " * 500,
                            "tools": [{"type": "function", "function": {"name": "mastery_grade"}}],
                        }
                    },
                },
            ]
        )
    return result


def store_for(rows, summary="", watermark=0):
    store = MagicMock()
    store.get_session = AsyncMock(
        return_value={"compressed_summary": summary, "summary_up_to_msg_id": watermark}
    )
    store.get_messages_for_context = AsyncMock(return_value=rows)
    store.update_summary = AsyncMock()
    return store


def memory(ids):
    return json.dumps(
        {
            "version": 1,
            "covered_archive_ids": ids,
            "learner_state": [
                {"note": "A versus B remains uncertain; explanation failed.", "archive_ids": ids}
            ],
            "preferences": [],
            "open_items": [],
            "teaching_history": [],
            "source_anchors": [],
        }
    )


def test_runtime_replacements_do_not_consume_learning_history_or_mutate_archive():
    messages = [
        {"role": "user", "content": "literal snapshot quotation"},
        {
            "role": "user",
            "content": "old runtime " * 1000,
            "_context_snapshot": "mastery_status_snapshot",
        },
        {"role": "assistant", "content": "You struggled with A."},
    ]
    original = deepcopy(messages)
    projected = project_mastery_replay(messages)
    assert projected == [messages[0], messages[2]]
    assert messages == original


@pytest.mark.asyncio
async def test_large_window_does_not_postpone_tutoring_compaction_and_recent_pairs_stay_full():
    rows = records()
    original = deepcopy(rows)
    store = store_for(rows)
    builder = MasteryContextBuilder(store)
    builder._summarize = AsyncMock(return_value=(memory(["hs-tutor-2"]), []))
    config = SimpleNamespace(model="gpt-6.1-sol", context_window=272000, max_tokens=8192)
    assert ContextBuilder(store)._history_budget(config) > 80000
    built = await builder.build(session_id="s", llm_config=config, language="hu")
    builder._summarize.assert_awaited_once()
    store.update_summary.assert_awaited_once()
    assert built.budget <= 20000
    assert rows[-1]["metadata"]["model_turn"]["messages"] == built.model_history[-4:]
    assert rows == original
    assert "I confuse A with B" in built.history_sources["hs-tutor-2"]
    assert "partial" in built.history_sources["hs-tutor-2"]
    assert "Huge tutor instructions" not in built.history_sources["hs-tutor-2"]


@pytest.mark.asyncio
async def test_summary_failure_bounds_inline_history_preserves_exact_recall_and_watermark():
    rows = records()
    store = store_for(rows)
    builder = MasteryContextBuilder(store)
    builder._summarize = AsyncMock(side_effect=ValueError("invalid memory"))
    built = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-6.1-sol", context_window=272000, max_tokens=8192),
    )
    store.update_summary.assert_not_awaited()
    assert built.token_count <= built.budget
    assert all(f"example {i} failed" in json.dumps(built.history_sources) for i in range(8))
    assert "example 7 failed" in json.dumps(built.model_history)


@pytest.mark.asyncio
async def test_short_session_needs_no_extra_model_call_and_recall_stays_on_selected_branch():
    rows = records(1, 1)
    store = store_for(rows, summary="other branch", watermark=900)
    builder = MasteryContextBuilder(store)
    builder._summarize = AsyncMock()
    built = await builder.build(
        session_id="s",
        leaf_message_id=2,
        llm_config=SimpleNamespace(model="gpt-6.1-sol", context_window=272000, max_tokens=8192),
    )
    builder._summarize.assert_not_awaited()
    assert "other branch" not in json.dumps(built.model_history)
    assert set(built.history_sources) == {"hs-tutor-2"}
    assert all(
        call.kwargs["leaf_message_id"] == 2
        for call in store.get_messages_for_context.call_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["not JSON", memory(["hs-tutor-999"]), memory([])])
async def test_invalid_or_incomplete_memory_is_rejected(monkeypatch, invalid):
    async def stream(_self, **kwargs):
        yield invalid

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    builder = MasteryContextBuilder(store_for(records(1, 1)))
    with pytest.raises(ValueError):
        await builder._summarize(
            session_id="s",
            language="hu",
            source_text="original",
            summary_budget=4096,
            replay_request={"rows": records(1, 1), "messages": [], "tools": []},
        )


@pytest.mark.asyncio
async def test_memory_call_is_task_scoped_preserves_language_and_exact_archive_anchors(monkeypatch):
    captured = {}

    async def stream(_self, **kwargs):
        captured.update(kwargs)
        yield memory(["hs-tutor-2"])

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    builder = MasteryContextBuilder(store_for(records(1, 1)))
    text, _ = await builder._summarize(
        session_id="s",
        language="fr",
        source_text="original",
        summary_budget=4096,
        replay_request={"rows": records(1, 1), "messages": [], "tools": []},
    )
    assert json.loads(text)["learner_state"]
    assert "I confuse A with B" in captured["user_prompt"]
    assert "partial" in captured["user_prompt"]
    assert "hs-tutor-2" in captured["user_prompt"]
    assert "Français" in captured["system_prompt"]
    assert "tools" not in captured and "messages" not in captured
    assert "Huge tutor instructions" not in captured["user_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("indent", [None, 2])
async def test_complete_json_near_budget_is_not_cut_as_an_incomplete_sentence(monkeypatch, indent):
    data = json.loads(memory(["hs-tutor-2"]))
    data["learner_state"][0]["note"] = "membrán " * 1300
    response = json.dumps(data, ensure_ascii=False, indent=indent)
    budget = count_tokens(response) + 20
    assert count_tokens(response) >= int(budget * 0.95)

    async def stream(_self, **kwargs):
        if "outcome" in kwargs:
            kwargs["outcome"].finish_reason = "stop"
        yield response

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    builder = MasteryContextBuilder(store_for(records(1, 1)))
    text, _ = await builder._summarize(
        session_id="s",
        language="hu",
        source_text="original",
        summary_budget=budget,
        replay_request={"rows": records(1, 1)},
    )
    assert json.loads(text) == data


@pytest.mark.asyncio
async def test_provider_truncated_memory_never_advances_watermark_even_if_json_parses(monkeypatch):
    from deeptutor.capabilities.mastery.memory import archive_id
    from deeptutor.services.session.model_history import history_groups

    async def stream(_self, **kwargs):
        kwargs["outcome"].finish_reason = "max_tokens"
        yield memory([archive_id(g) for g in history_groups(builder._summary_rows)])

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    store = store_for(records())
    builder = MasteryContextBuilder(store)
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-6.1-sol", context_window=272000, max_tokens=8192),
    )
    store.update_summary.assert_not_awaited()
    assert result.token_count <= result.budget
    assert "example 0 failed" in json.dumps(result.history_sources)


@pytest.mark.asyncio
async def test_complete_memory_still_has_a_hard_retained_size_limit(monkeypatch):
    data = json.loads(memory(["hs-tutor-2"]))
    data["learner_state"][0]["note"] = "membrán " * 5000

    async def stream(_self, **kwargs):
        kwargs["outcome"].finish_reason = "stop"
        yield json.dumps(data, ensure_ascii=False)

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    builder = MasteryContextBuilder(store_for(records(1, 1)))
    with pytest.raises(ValueError, match="exceeded its retained budget"):
        await builder._summarize(
            session_id="s",
            language="hu",
            source_text="original",
            summary_budget=4096,
            replay_request={"rows": records(1, 1)},
        )


def test_native_manifest_is_not_duplicated_but_deferred_discovery_and_kb_note_survive():
    from deeptutor.capabilities.mastery.pipeline import MasteryPromptAssembler
    from deeptutor.core.context import UnifiedContext

    assembler = MasteryPromptAssembler(prompts={}, language="hu")
    kwargs = dict(
        context=UnifiedContext(),
        tool_manifest="duplicate complete tool descriptions",
        deferred_tools_manifest="Deferred catalog retained",
        kb_note="KB scope retained",
    )
    assembler.native_tool_schemas = True
    blocks = assembler.blocks(**kwargs)
    assert not any(b.name == "tools" for b in blocks)
    assert any(b.content == "Deferred catalog retained" for b in blocks)
    assert any(b.content == "KB scope retained" for b in blocks)
    assembler.native_tool_schemas = False
    assert any(b.name == "tools" for b in assembler.blocks(**kwargs))


def test_turn_factory_uses_tutoring_memory_only_for_tutoring():
    from deeptutor.services.session.turns.context_assembler import TurnContextAssembler

    assembler = TurnContextAssembler()
    assembler.store = MagicMock()
    assert type(assembler._create_context_builder()) is ContextBuilder
    assert isinstance(assembler._create_context_builder(tutoring=True), MasteryContextBuilder)


@pytest.mark.asyncio
async def test_actual_store_recall_does_not_expose_sibling_branch(tmp_path):
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    from deeptutor.tools.builtin import ReadSourceTool

    store = SQLiteSessionStore(db_path=tmp_path / "history.db")
    session = await store.create_session()
    sid = session["id"]
    root = await store.add_message(sid, "user", "Root")
    first = await store.add_message(sid, "assistant", "Branch A", parent_message_id=root)
    other = await store.add_message(sid, "assistant", "Branch B private", parent_message_id=root)
    result = await MasteryContextBuilder(store).build(
        session_id=sid,
        leaf_message_id=first,
        llm_config=SimpleNamespace(model="gpt-test", context_window=128000, max_tokens=4096),
    )
    tool = ReadSourceTool()
    read = await tool.execute(source_index=result.history_sources, source_id=f"hs-tutor-{first}")
    assert read.success and "Branch A" in read.content and "Branch B private" not in read.content
    forbidden = await tool.execute(
        source_index=result.history_sources, source_id=f"hs-tutor-{other}"
    )
    assert not forbidden.success


@pytest.mark.asyncio
async def test_one_oversized_exchange_uses_exact_recall_without_cutting_tool_pairs():
    rows = records(n=1, padding=40000)
    original = deepcopy(rows)
    store = store_for(rows)
    builder = MasteryContextBuilder(store)
    builder._summarize = AsyncMock(side_effect=ValueError("invalid memory"))
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-6.1-sol", context_window=272000, max_tokens=8192),
    )
    store.update_summary.assert_not_awaited()
    assert result.token_count <= result.budget
    assert "hs-tutor-2" in json.dumps(result.model_history)
    assert "distinct-0 " * 40000 in result.history_sources["hs-tutor-2"]
    assert not any(
        message.get("tool_calls") or message.get("role") == "tool"
        for message in result.model_history
    )
    assert rows == original


@pytest.mark.asyncio
async def test_trailing_memory_snapshot_counts_toward_tutoring_budget():
    from deeptutor.services.session.context_builder import _count_model_context_tokens
    from deeptutor.services.session.model_history import summary_snapshot

    rows = records(n=2, padding=1)
    summary = memory(["hs-tutor-2"])
    builder = MasteryContextBuilder(store_for(rows, summary=summary, watermark=2))
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-6.1-sol", context_window=272000, max_tokens=8192),
    )
    assert result.conversation_summary == summary
    assert summary not in json.dumps(result.model_history)
    expected = _count_model_context_tokens(result.model_history) + _count_model_context_tokens(
        summary_snapshot(summary)
    )
    assert result.token_count == expected
    assert builder._model_tokens([], summary) == _count_model_context_tokens(
        []
    ) + _count_model_context_tokens(summary_snapshot(summary))


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_limit, saved", [(8192, True), (3000, False)])
async def test_reasoning_allowance_does_not_replace_the_retained_memory_budget(
    monkeypatch, configured_limit, saved
):
    """A 4k combined reasoning/output cap repeatedly cut off live JSON memory."""
    from deeptutor.capabilities.mastery.memory import archive_id
    from deeptutor.services.session.model_history import history_groups

    async def stream(_self, **kwargs):
        kwargs["outcome"].finish_reason = "stop" if kwargs["max_tokens"] >= 5000 else "max_tokens"
        assert kwargs["max_tokens"] <= configured_limit
        yield memory([archive_id(g) for g in history_groups(builder._summary_rows)])

    monkeypatch.setattr(_ContextSummaryAgent, "stream_llm", stream)
    store = store_for(records())
    builder = MasteryContextBuilder(store)
    result = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(
            model="reasoning-model", context_window=272000, max_tokens=configured_limit
        ),
    )
    assert store.update_summary.await_count == int(saved)
    assert result.token_count <= 20000
    assert "example 0 failed" in json.dumps(result.history_sources)
