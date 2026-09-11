from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

from deeptutor.services.session.event_preview import (
    MAX_LEGACY_EVENT_PAYLOAD_CHARS,
    MAX_TRACE_PREVIEW_EVENTS,
    compact_trace_preview,
)
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_preview_keeps_semantic_events_and_bounds_legacy_payloads() -> None:
    events = [
        {"type": "content", "content": "delta"},
        {
            "type": "tool_result",
            "content": "x" * (MAX_LEGACY_EVENT_PAYLOAD_CHARS + 10),
            "metadata": {},
        },
        {"type": "result", "metadata": {"summary": "ok"}},
        {"type": "done", "metadata": {"status": "completed"}},
    ]

    preview, truncated = compact_trace_preview(events)

    assert truncated is True
    assert events[1]["content"] == "x" * (MAX_LEGACY_EVENT_PAYLOAD_CHARS + 10)
    assert [event["type"] for event in preview] == ["tool_result", "result", "done"]
    assert len(preview[0]["content"]) == MAX_LEGACY_EVENT_PAYLOAD_CHARS + len("...[truncated]")


def test_preview_prioritizes_the_terminal_tail() -> None:
    events = [{"type": "tool_call", "content": str(i)} for i in range(250)]
    events.append({"type": "done", "metadata": {"status": "completed"}})

    preview, truncated = compact_trace_preview(events)

    assert truncated is True
    assert len(preview) == 200
    assert preview[-1]["type"] == "done"


def test_migration_backfills_assistant_message_link_from_legacy_done(tmp_path) -> None:
    path = tmp_path / "chat.db"
    store = SQLiteSessionStore(path)
    session = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    asyncio.run(store.transition_turn(turn["id"], "completed"))
    second_turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "answer"))
    second_message_id = asyncio.run(store.add_message(session["id"], "assistant", "second"))

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE messages SET events_json = ? WHERE id = ?",
            (
                json.dumps(
                    [
                        {
                            "type": "done",
                            "turn_id": turn["id"],
                            "metadata": {"assistant_message_id": message_id},
                        }
                    ]
                ),
                message_id,
            ),
        )
        conn.execute(
            "UPDATE messages SET events_json = ? WHERE id = ?",
            (
                json.dumps(
                    [
                        {
                            "type": "done",
                            "turn_id": second_turn["id"],
                            "metadata": {"assistant_message_id": second_message_id},
                        }
                    ]
                ),
                second_message_id,
            ),
        )
        conn.execute("UPDATE turns SET assistant_message_id = NULL")
        conn.execute("DROP INDEX idx_turns_assistant_message")
        conn.execute("ALTER TABLE turns DROP COLUMN assistant_message_id")

    reopened = SQLiteSessionStore(path)
    linked = asyncio.run(reopened.get_turn(turn["id"]))
    assert linked is not None
    assert linked["assistant_message_id"] == message_id
    second_linked = asyncio.run(reopened.get_turn(second_turn["id"]))
    assert second_linked is not None
    assert second_linked["assistant_message_id"] == second_message_id


def test_context_rehydrates_ask_user_from_canonical_turn_events(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "answer"))
    asyncio.run(
        store.append_turn_events(
            turn["id"],
            [
                {"type": "content", "content": "delta", "metadata": {}},
                {
                    "type": "tool_result",
                    "metadata": {"tool_metadata": {"ask_user": {"questions": []}}},
                },
                {"type": "progress", "metadata": {"ask_user_resolved": True}},
            ],
        )
    )
    asyncio.run(store.link_turn_message(turn["id"], message_id))

    context = asyncio.run(store.get_messages_for_context(session["id"]))

    assert [event["type"] for event in context[-1]["events"]] == [
        "tool_result",
        "progress",
    ]


def test_session_preview_reads_a_bounded_number_of_canonical_rows(tmp_path, monkeypatch) -> None:
    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "answer"))
    asyncio.run(
        store.append_turn_events(
            turn["id"],
            [
                {"type": "tool_call", "content": f"call-{index}", "metadata": {}}
                for index in range(1_000)
            ],
        )
    )
    asyncio.run(store.link_turn_message(turn["id"], message_id))

    converted = 0
    original = store._turn_event_row_to_payload

    def count_conversion(row):
        nonlocal converted
        converted += 1
        return original(row)

    monkeypatch.setattr(store, "_turn_event_row_to_payload", count_conversion)
    detail = asyncio.run(store.get_session_with_messages(session["id"]))

    assert detail is not None
    message = detail["messages"][0]
    assert message["trace"]["total"] == 1_000
    assert message["trace"]["truncated"] is True
    assert len(message["events"]) == 200
    assert converted == 200


def test_an_early_mastery_card_survives_a_long_turns_preview(tmp_path) -> None:
    """A posed question is the one row the settled message cannot render without.

    The card used to travel on the ``ask_user`` channel, which both the
    critical-row query and the preview compactor named explicitly. It has its
    own channel now, so both had to learn the new key — otherwise a course
    turn long enough to fill the preview budget dropped the question and left
    the learner with prose about a card that was no longer there.
    """
    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "answer"))
    card = {
        "type": "tool_result",
        "content": "",
        "metadata": {
            "tool_call_id": "call-quiz",
            "tool_metadata": {
                "mastery_question": {"question_id": "q-1", "prompt": "Which reducer?"}
            },
        },
    }
    asyncio.run(
        store.append_turn_events(
            turn["id"],
            [
                card,
                *[
                    {"type": "tool_call", "content": f"call-{index}", "metadata": {}}
                    for index in range(1_000)
                ],
            ],
        )
    )
    asyncio.run(store.link_turn_message(turn["id"], message_id))

    detail = asyncio.run(store.get_session_with_messages(session["id"]))

    assert detail is not None
    events = detail["messages"][0]["events"]
    assert len(events) == MAX_TRACE_PREVIEW_EVENTS
    posed = [
        (event.get("metadata") or {}).get("tool_metadata", {}).get("mastery_question")
        for event in events
    ]
    assert [card["question_id"] for card in posed if card] == ["q-1"]


def test_pocketbase_trace_uses_server_side_pagination(monkeypatch) -> None:
    events = [
        SimpleNamespace(
            id=f"event-{seq}",
            turn_id="turn-1",
            seq=seq,
            type="tool_call",
            source="chat",
            stage="",
            content=f"call-{seq}",
            metadata_json={},
            event_timestamp=float(seq),
        )
        for seq in range(1, 1_201)
    ]
    records = {
        "sessions": [SimpleNamespace(id="pb-session", session_id="session-1", user_id="u_ada")],
        "messages": [SimpleNamespace(id="message-1", session_id="session-1", role="assistant")],
        "turns": [
            SimpleNamespace(id="pb-turn", turn_id="turn-1", assistant_message_id="message-1")
        ],
        "turn_events": events,
    }
    full_event_reads = 0

    class Collection:
        def __init__(self, name: str) -> None:
            self.name = name

        def get_full_list(self, query_params=None):
            nonlocal full_event_reads
            if self.name == "turn_events":
                full_event_reads += 1
            return list(records[self.name])

        def get_list(self, page, per_page, query_params=None):
            rows = list(records[self.name])
            params = query_params or {}
            if self.name == "turn_events":
                marker = "seq>"
                filter_value = str(params.get("filter") or "")
                if marker in filter_value:
                    after_seq = int(filter_value.rsplit(marker, 1)[1])
                    rows = [row for row in rows if row.seq > after_seq]
                rows.sort(key=lambda row: row.seq, reverse=params.get("sort") == "-seq")
            start = (page - 1) * per_page
            return SimpleNamespace(items=rows[start : start + per_page], total_items=len(rows))

    class Client:
        def collection(self, name: str) -> Collection:
            return Collection(name)

    monkeypatch.setattr(
        "deeptutor.services.session.pocketbase_store._current_user_id",
        lambda: "u_ada",
    )
    monkeypatch.setattr("deeptutor.services.session.pocketbase_store._pb", lambda: Client())
    store = PocketBaseSessionStore()

    page = asyncio.run(store.get_message_trace("session-1", "message-1", after_seq=100, limit=50))

    assert page is not None
    assert [event["seq"] for event in page["events"]] == list(range(101, 151))
    assert page["total"] == 1_200
    assert page["last_seq"] == 1_200
    assert page["next_seq"] == 150
    assert page["complete"] is False
    assert full_event_reads == 0
