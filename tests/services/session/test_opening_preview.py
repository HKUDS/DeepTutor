"""Opening a conversation returns bubble text and unfinished question cards."""

from __future__ import annotations

import asyncio

from deeptutor.services.session.opening_preview import select_opening_events
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _pose(question_id: str, seq: int = 1) -> dict:
    return {
        "type": "tool_result",
        "seq": seq,
        "content": "",
        "metadata": {
            "tool_metadata": {
                "mastery_question": {"question_id": question_id, "prompt": "Which reducer?"}
            }
        },
    }


def _grade(question_id: str, *, complete: bool = True, seq: int = 2) -> dict:
    return {
        "type": "tool_result",
        "seq": seq,
        "metadata": {
            "tool_metadata": {
                "mastery_grade": {
                    "question_id": question_id,
                    "result": {
                        "question_id": question_id,
                        "is_correct": True,
                        "complete": complete,
                        "final": True,
                    },
                }
            }
        },
    }


def test_unfinished_mastery_card_is_kept_and_a_settled_one_is_not() -> None:
    kept = select_opening_events(
        [
            {
                "id": 1,
                "role": "assistant",
                "metadata": {},
                "project": True,
                "candidates": [
                    _pose("q-open", 1),
                    {"type": "tool_call", "seq": 2, "content": "page"},
                ],
            },
            {
                "id": 2,
                "role": "assistant",
                "metadata": {},
                "project": True,
                "candidates": [_pose("q-done", 1), _grade("q-done", seq=3)],
            },
        ]
    )

    assert [event["seq"] for event in kept[1]] == [1]
    assert 2 not in kept


def test_a_handed_in_answer_closes_the_card_until_it_is_rejected() -> None:
    pose = _pose("q-1")
    rejection = {
        "type": "tool_result",
        "seq": 4,
        "metadata": {
            "tool_metadata": {"mastery_answer_rejected": {"question_id": "q-1"}}
        },
    }
    handed_in = select_opening_events(
        [
            {"id": 1, "role": "assistant", "metadata": {}, "project": True, "candidates": [pose]},
            {
                "id": 2,
                "role": "user",
                "metadata": {
                    "request_snapshot": {"masteryAnswer": {"question_id": "q-1", "text": "B"}}
                },
                "project": False,
                "candidates": [],
            },
        ]
    )
    reopened = select_opening_events(
        [
            {"id": 1, "role": "assistant", "metadata": {}, "project": True, "candidates": [pose]},
            {
                "id": 2,
                "role": "user",
                "metadata": {
                    "request_snapshot": {"masteryAnswer": {"question_id": "q-1", "text": "B"}}
                },
                "project": False,
                "candidates": [],
            },
            {
                "id": 3,
                "role": "assistant",
                "metadata": {},
                "project": True,
                "candidates": [rejection],
            },
        ]
    )

    assert handed_in == {}
    assert [event["seq"] for event in reopened[1]] == [1]
    rejected = reopened[3][0]["metadata"]["tool_metadata"]["mastery_answer_rejected"]
    assert rejected["question_id"] == "q-1"


def test_resolved_ask_user_waits_for_the_trace() -> None:
    pose = {
        "type": "tool_result",
        "seq": 1,
        "metadata": {
            "tool_call_id": "call-1",
            "tool_metadata": {"ask_user": {"questions": [{"id": "level", "prompt": "Level?"}]}},
        },
    }
    resolved = {
        "type": "progress",
        "seq": 2,
        "metadata": {"ask_user_resolved": True, "ask_user_tool_call_id": "call-1"},
    }
    kept = select_opening_events(
        [
            {
                "id": 1,
                "role": "assistant",
                "metadata": {},
                "project": True,
                "candidates": [pose, resolved],
            }
        ]
    )
    pending = select_opening_events(
        [{"id": 1, "role": "assistant", "metadata": {}, "project": True, "candidates": [pose]}]
    )

    assert kept == {}
    assert pending[1] == [pose]


def test_sqlite_open_omits_tool_payloads_and_keeps_an_open_card(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "Here is the idea."))
    asyncio.run(
        store.append_turn_events(
            turn["id"],
            [
                {"type": "tool_result", "content": "x" * 20_000, "metadata": {"tool": "web_fetch"}},
                _pose("q-1", seq=2),
                {"type": "done", "metadata": {"status": "completed"}},
            ],
        )
    )
    asyncio.run(store.link_turn_message(turn["id"], message_id))

    detail = asyncio.run(store.get_session_with_messages(session["id"]))

    assert detail is not None
    message = detail["messages"][0]
    assert message["content"] == "Here is the idea."
    assert message["trace"]["truncated"] is True
    assert message["trace"]["total"] == 3
    assert [event["type"] for event in message["events"]] == ["tool_result"]
    question = message["events"][0]["metadata"]["tool_metadata"]["mastery_question"]
    assert question["question_id"] == "q-1"
    assert all("x" * 100 not in str(event.get("content") or "") for event in message["events"])


def test_sqlite_open_drops_a_huge_model_turn_from_the_public_row(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    asyncio.run(
        store.add_message(
            session["id"],
            "assistant",
            "KP0 is done.",
            metadata={
                "turn_id": "turn-1",
                "model_turn": {"messages": [{"role": "tool", "content": "z" * 50_000}]},
            },
        )
    )

    detail = asyncio.run(store.get_session_with_messages(session["id"]))

    assert detail is not None
    metadata = detail["messages"][0]["metadata"]
    assert metadata.get("turn_id") == "turn-1"
    assert "model_turn" not in metadata
