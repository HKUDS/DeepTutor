from __future__ import annotations

import asyncio
import json
import sqlite3

from deeptutor.services.session.event_preview import (
    MAX_LEGACY_EVENT_PAYLOAD_CHARS,
    compact_trace_preview,
)
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
