"""Exact recall must not archive its own output again (#2032)."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.capabilities.mastery.history import project_mastery_replay
from deeptutor.capabilities.mastery.memory import MasteryContextBuilder, archive_text
from deeptutor.services.session.model_history import normalize_model_turn
from deeptutor.tools.builtin import ReadSourceTool


def exchange(number, source_id, content, *, tool_name="read_source"):
    calls = [
        {
            "id": f"recall-{i}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps({"source_id": source_id}),
            },
        }
        for i in range(2)
    ]
    messages = [
        {"role": "user", "content": f"Learner correction {number}"},
        {"role": "assistant", "content": "Let me recall.", "tool_calls": calls},
        *[{"role": "tool", "tool_call_id": call["id"], "content": content} for call in calls],
        {"role": "assistant", "content": f"Tutor explanation {number}"},
    ]
    return [
        {"id": number * 2 - 1, **messages[0]},
        {
            "id": number * 2,
            **messages[-1],
            "metadata": {"model_turn": {"version": 1, "messages": messages}},
        },
    ]


@pytest.mark.asyncio
async def test_repeated_recall_archive_cycles_do_not_nest_or_grow_exponentially():
    tool = ReadSourceTool()
    sources = {
        "hs-tutor-0": json.dumps(
            {
                "archive_id": "hs-tutor-0",
                "messages": [{"role": "user", "content": "Original learner misconception"}],
            }
        )
    }
    for number in range(1, 20):
        previous = f"hs-tutor-{(number - 1) * 2}"
        read = await tool.execute(source_id=previous, source_index=sources)
        assert read.success
        rows = exchange(number, previous, read.content)
        original = deepcopy(rows)
        archived = archive_text(rows)
        messages = json.loads(archived)["messages"]
        assert normalize_model_turn({"version": 1, "messages": messages}) is not None
        assert f"Learner correction {number}" in archived
        assert f"Tutor explanation {number}" in archived
        for message in messages:
            if message["role"] == "tool":
                assert json.loads(message["content"])["archive_id"] == previous
                assert read.content not in message["content"]
        assert len(archived) < 2000
        assert rows == original
        sources[f"hs-tutor-{number * 2}"] = archived
    # Following a reference still retrieves the original evidence.
    read = await tool.execute(source_id="hs-tutor-0", source_index=sources)
    assert json.loads(read.content)["messages"][0]["content"] == "Original learner misconception"


@pytest.mark.asyncio
async def test_legacy_oversized_recall_is_projected_without_rewriting_saved_turns():
    # Simulate an already polluted stored result. No recursive JSON decoding is
    # needed: the original call tells us which archive owns that evidence.
    rows = exchange(2, "hs-tutor-2", 'old nested "archive" \\ payload ' * 100_000)
    original = deepcopy(rows)
    store = MagicMock()
    store.get_session = AsyncMock(return_value={})
    store.get_messages_for_context = AsyncMock(return_value=rows)
    store.update_summary = AsyncMock()
    builder = MasteryContextBuilder(store)
    builder._summarize = AsyncMock()
    built = await builder.build(
        session_id="s",
        llm_config=SimpleNamespace(model="gpt-test", context_window=128000, max_tokens=4096),
    )
    builder._summarize.assert_not_awaited()
    store.update_summary.assert_not_awaited()
    assert len(built.history_sources["hs-tutor-4"]) < 2000
    assert len(json.dumps(built.model_history)) < 2000
    assert normalize_model_turn({"version": 1, "messages": built.model_history}) is not None
    assert rows == original


@pytest.mark.parametrize(
    "source_id, tool_name, content",
    [
        ("nb-1", "read_source", "Original notebook evidence"),
        ("hs-other-session", "read_source", "Other session evidence"),
        ("hs-tutor-2", "rag", "Original retrieved evidence"),
        ("hs-tutor-2", "read_source", "Error: unknown source_id 'hs-tutor-2'."),
    ],
)
def test_other_evidence_and_failed_reads_stay_verbatim(source_id, tool_name, content):
    rows = exchange(2, source_id, content, tool_name=tool_name)
    messages = rows[-1]["metadata"]["model_turn"]["messages"]
    assert project_mastery_replay(messages) == messages
    assert json.loads(archive_text(rows))["messages"] == messages


def test_reused_call_ids_in_separate_turns_reference_the_correct_archive():
    first = exchange(2, "hs-tutor-2", "First archive body")
    second = exchange(3, "hs-tutor-4", "Second archive body")
    messages = [
        *first[-1]["metadata"]["model_turn"]["messages"],
        *second[-1]["metadata"]["model_turn"]["messages"],
    ]
    original = deepcopy(messages)
    projected = project_mastery_replay(messages)
    references = [json.loads(m["content"])["archive_id"] for m in projected if m["role"] == "tool"]
    assert references == ["hs-tutor-2", "hs-tutor-2", "hs-tutor-4", "hs-tutor-4"]
    assert project_mastery_replay(projected) == projected
    assert messages == original


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["read_source", "pdf"])
async def test_inferred_single_history_source_does_not_reenter_archive(tool_name):
    original = archive_text(exchange(1, "nb-1", "Original notebook evidence"))
    read = await ReadSourceTool().execute(source_index={"hs-tutor-2": original})
    rows = exchange(2, "", read.content, tool_name=tool_name)
    archived = json.loads(archive_text(rows))
    results = [m["content"] for m in archived["messages"] if m["role"] == "tool"]
    assert all(json.loads(result)["archive_id"] == "hs-tutor-2" for result in results)
    assert all("Original notebook evidence" not in result for result in results)
