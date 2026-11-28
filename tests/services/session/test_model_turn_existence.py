"""Existence checks over stored model turns must not re-serialize them (#2788).

Grouping and the context-builder guards only ask whether a private turn record
is admissible; running the full normalize (clean + json round-trip deep copy)
for that question re-serializes multi-MB requests on the event loop.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.session import model_history
from deeptutor.services.session.model_history import (
    history_groups,
    normalize_model_turn,
)


def turn_record(payload: str = "tool evidence") -> dict:
    return {
        "version": 1,
        "system": "Standing tutor instructions",
        "tools": [
            {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}
        ],
        "route": {"provider": "openai", "model": "gpt-test"},
        "messages": [
            {"role": "user", "content": "Question"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"key": "value"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": payload},
            {"role": "assistant", "content": "Original answer"},
        ],
    }


def rows_with_turns(count: int, payload: str = "x" * 200_000) -> list[dict]:
    rows: list[dict] = []
    for i in range(count):
        rows.append({"id": 2 * i + 1, "role": "user", "content": f"Question {i}"})
        rows.append(
            {
                "id": 2 * i + 2,
                "role": "assistant",
                "content": f"Displayed answer {i}",
                "metadata": {"model_turn": turn_record(payload)},
            }
        )
    return rows


def test_history_groups_does_not_serialize_stored_turns(monkeypatch):
    calls: list[int] = []
    real_dumps = json.dumps

    def spy(obj, *args, **kwargs):
        calls.append(1)
        return real_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(model_history.json, "dumps", spy)
    groups = history_groups(rows_with_turns(6))
    assert [len(group) for group in groups] == [2] * 6
    assert calls == [], f"grouping re-serialized stored turns: {len(calls)} json.dumps calls"


def test_history_groups_does_not_normalize_stored_turns(monkeypatch):
    def forbidden(row):
        raise AssertionError("existence check must not run the full normalize/deep copy")

    monkeypatch.setattr(model_history, "model_turn", forbidden)
    groups = history_groups(rows_with_turns(4, payload="small"))
    assert [len(group) for group in groups] == [2] * 4


def test_has_model_turn_matches_normalize_acceptance():
    from deeptutor.services.session.model_history import has_model_turn

    valid = turn_record()
    assert has_model_turn({"metadata": {"model_turn": valid}}) is True
    assert has_model_turn({"metadata": {"model_turn": turn_record()}}) is True
    assert has_model_turn({}) is False
    assert has_model_turn({"metadata": None}) is False
    assert has_model_turn({"metadata": "not-a-dict"}) is False
    assert has_model_turn({"metadata": {}}) is False
    broken = turn_record()
    broken["messages"].pop(2)  # orphaned tool call
    assert has_model_turn({"metadata": {"model_turn": broken}}) is False
    assert normalize_model_turn(broken) is None


def _invalid_corpus() -> list[dict]:
    corpus: list[dict] = []

    def variant(mutate) -> None:
        record = turn_record()
        mutate(record)
        corpus.append(record)

    variant(lambda r: r.update(version=99))
    variant(lambda r: r.pop("version"))
    variant(lambda r: r.update(system=123))
    variant(lambda r: r.update(tools="not-a-list"))
    variant(lambda r: r.update(tools=[{"function": {"name": 7}}]))
    variant(lambda r: r.update(route={"provider": "openai"}))
    variant(lambda r: r.update(route="openai/gpt-test"))
    variant(lambda r: r.update(messages=[]))
    variant(lambda r: r.update(messages="not-a-list"))
    variant(lambda r: r["messages"].pop(2))  # tool result missing -> pending call
    variant(lambda r: r["messages"].insert(2, {"role": "tool", "tool_call_id": "ghost"}))
    variant(lambda r: r["messages"].insert(0, {"role": "banana", "content": "x"}))
    variant(lambda r: r["messages"][1].update(content=42))
    variant(lambda r: r["messages"][0].update(tool_calls=[{"id": "c", "function": {}}]))
    variant(
        lambda r: r["messages"][1]["tool_calls"].append(
            {"id": "call-1", "type": "function", "function": {"name": "lookup"}}
        )
    )
    return corpus


@pytest.mark.parametrize("record", _invalid_corpus(), ids=range(15))
def test_predicate_and_normalize_reject_the_same_invalid_records(record):
    from deeptutor.services.session.model_history import has_model_turn

    assert normalize_model_turn(record) is None
    assert has_model_turn({"metadata": {"model_turn": record}}) is False


def test_grouping_shape_is_unchanged_for_mixed_valid_and_invalid_rows():
    broken = turn_record()
    broken["messages"].pop(2)
    rows = [
        {"id": 1, "role": "user", "content": "q1"},
        {"id": 2, "role": "assistant", "content": "a1", "metadata": {"model_turn": turn_record()}},
        {"id": 3, "role": "user", "content": "q2"},
        {"id": 4, "role": "assistant", "content": "a2", "metadata": {"model_turn": broken}},
        {"id": 5, "role": "user", "content": "q3"},
        {"id": 6, "role": "assistant", "content": "a3"},
    ]
    groups = history_groups(rows)
    assert [[row["id"] for row in group] for group in groups] == [[1, 2], [3], [4], [5], [6]]
