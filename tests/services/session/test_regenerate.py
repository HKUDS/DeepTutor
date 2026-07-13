"""Tests for the chat regenerate-last-turn flow.

Covers the SQLite store helpers added for tail rollback as well as the
``TurnRuntimeManager.regenerate_last_turn`` orchestration: assistant tail
deletion, user-message preservation, ``_persist_user_message`` propagation,
busy/empty session rejection, and skipping the long-term memory refresh on
regeneration.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import (
    TurnRuntimeManager,
    _extract_regenerate_flag,
)


async def _noop_refresh(**_kwargs):
    return None


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "regenerate.db")


# ---------------------------------------------------------------------------
# _extract_regenerate_flag
# ---------------------------------------------------------------------------


class TestExtractRegenerateFlag:
    def test_default_is_false(self) -> None:
        assert _extract_regenerate_flag({}) is False

    def test_none_config_is_false(self) -> None:
        assert _extract_regenerate_flag(None) is False

    def test_true_bool(self) -> None:
        config = {"_regenerate": True}
        assert _extract_regenerate_flag(config) is True
        assert "_regenerate" not in config  # popped

    def test_true_string(self) -> None:
        assert _extract_regenerate_flag({"_regenerate": "true"}) is True

    def test_one_string(self) -> None:
        assert _extract_regenerate_flag({"_regenerate": "1"}) is True

    def test_false_string(self) -> None:
        assert _extract_regenerate_flag({"_regenerate": "false"}) is False


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


class TestStoreTailRollback:
    def test_delete_message_removes_only_target(self, store: SQLiteSessionStore) -> None:
        session = asyncio.run(store.create_session())
        sid = session["id"]
        m1 = asyncio.run(store.add_message(sid, role="user", content="hi"))
        m2 = asyncio.run(store.add_message(sid, role="assistant", content="hello"))

        deleted = asyncio.run(store.delete_message(m2))
        assert deleted is True

        remaining = asyncio.run(store.get_messages(sid))
        assert [m["id"] for m in remaining] == [m1]
        assert remaining[0]["role"] == "user"

    def test_delete_message_returns_false_when_missing(self, store: SQLiteSessionStore) -> None:
        assert asyncio.run(store.delete_message(99999)) is False

    def test_get_last_message_no_filter(self, store: SQLiteSessionStore) -> None:
        session = asyncio.run(store.create_session())
        sid = session["id"]
        asyncio.run(store.add_message(sid, role="user", content="q1"))
        last_id = asyncio.run(store.add_message(sid, role="assistant", content="a1"))

        last = asyncio.run(store.get_last_message(sid))
        assert last is not None
        assert last["id"] == last_id
        assert last["role"] == "assistant"

    def test_get_last_message_filtered_by_role(self, store: SQLiteSessionStore) -> None:
        session = asyncio.run(store.create_session())
        sid = session["id"]
        u1 = asyncio.run(store.add_message(sid, role="user", content="q1"))
        asyncio.run(store.add_message(sid, role="assistant", content="a1"))
        u2 = asyncio.run(store.add_message(sid, role="user", content="q2"))
        asyncio.run(store.add_message(sid, role="assistant", content="a2"))

        last_user = asyncio.run(store.get_last_message(sid, role="user"))
        assert last_user is not None
        assert last_user["id"] == u2
        assert last_user["content"] == "q2"
        # Sanity: u1 still exists but is not the last user.
        assert u1 != u2

    def test_get_last_message_empty_session(self, store: SQLiteSessionStore) -> None:
        session = asyncio.run(store.create_session())
        assert asyncio.run(store.get_last_message(session["id"])) is None


# ---------------------------------------------------------------------------
# TurnRuntimeManager.regenerate_last_turn
# ---------------------------------------------------------------------------


class _FakeStartTurnRecorder:
    """Captures the payload passed to ``start_turn`` without launching it."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, payload: dict[str, Any]) -> tuple[dict, dict]:
        self.calls.append(payload)
        return (
            {"id": payload["session_id"]},
            {"id": "fake-turn", "session_id": payload["session_id"]},
        )


def _seed_session(
    store: SQLiteSessionStore,
    *,
    user_content: str = "what is 2+2?",
    assistant_content: str | None = "4",
    user_metadata: dict[str, Any] | None = None,
) -> tuple[str, int, int | None]:
    """Create a session with a user (and optional assistant) message."""
    session = asyncio.run(store.create_session())
    sid = session["id"]
    asyncio.run(
        store.update_session_preferences(
            sid,
            {
                "capability": "chat",
                "tools": ["rag"],
                "knowledge_bases": ["kb1"],
                "language": "en",
            },
        )
    )
    user_id = asyncio.run(
        store.add_message(
            sid,
            role="user",
            content=user_content,
            capability="chat",
            attachments=[{"type": "file", "filename": "a.pdf"}],
            metadata=user_metadata,
        )
    )
    assistant_id: int | None = None
    if assistant_content is not None:
        assistant_id = asyncio.run(
            store.add_message(
                sid,
                role="assistant",
                content=assistant_content,
                capability="chat",
            )
        )
    return sid, user_id, assistant_id


class TestRegenerateLastTurn:
    def test_assistant_tail_is_deleted_and_payload_replays_user(
        self, store: SQLiteSessionStore
    ) -> None:
        sid, user_id, assistant_id = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder()

        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))

        assert len(recorder.calls) == 1
        payload = recorder.calls[0]
        assert payload["session_id"] == sid
        assert payload["content"] == "what is 2+2?"
        assert payload["capability"] == "chat"
        assert payload["tools"] == ["rag"]
        assert payload["knowledge_bases"] == ["kb1"]
        assert payload["language"] == "en"
        assert payload["attachments"] == [{"type": "file", "filename": "a.pdf"}]
        assert payload["config"]["_persist_user_message"] is False
        assert payload["config"]["_regenerate"] is True
        assert payload["config"]["_regenerated_from_message_id"] == user_id

        remaining = asyncio.run(store.get_messages(sid))
        assert [m["id"] for m in remaining] == [user_id]
        assert assistant_id is not None and assistant_id not in {m["id"] for m in remaining}

    def test_replays_book_references_from_request_snapshot(self, store: SQLiteSessionStore) -> None:
        sid, _, _ = _seed_session(
            store,
            user_metadata={
                "request_snapshot": {
                    "bookReferences": [{"book_id": "book-1", "page_ids": ["page-1"]}]
                }
            },
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder()

        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))

        assert recorder.calls[0]["book_references"] == [
            {"book_id": "book-1", "page_ids": ["page-1"]}
        ]

    def test_user_tail_is_kept_and_no_delete(self, store: SQLiteSessionStore) -> None:
        sid, user_id, _ = _seed_session(store, assistant_content=None)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder()

        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))

        assert len(recorder.calls) == 1
        remaining = asyncio.run(store.get_messages(sid))
        assert [m["id"] for m in remaining] == [user_id]

    def test_empty_session_raises_nothing_to_regenerate(self, store: SQLiteSessionStore) -> None:
        session = asyncio.run(store.create_session())
        runtime = TurnRuntimeManager(store=store)

        with pytest.raises(RuntimeError) as exc:
            asyncio.run(runtime.regenerate_last_turn(session["id"]))
        assert str(exc.value) == "nothing_to_regenerate"

    def test_missing_session_raises_nothing_to_regenerate(self, store: SQLiteSessionStore) -> None:
        runtime = TurnRuntimeManager(store=store)
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(runtime.regenerate_last_turn("does-not-exist"))
        assert str(exc.value) == "nothing_to_regenerate"

    def test_active_running_turn_raises_busy(self, store: SQLiteSessionStore) -> None:
        sid, _, _ = _seed_session(store)
        # Create a running turn directly via the store.
        asyncio.run(store.create_turn(sid, capability="chat"))

        runtime = TurnRuntimeManager(store=store)
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(runtime.regenerate_last_turn(sid))
        assert str(exc.value) == "regenerate_busy"

    @pytest.mark.asyncio
    async def test_end_to_end_skips_memory_refresh_and_no_duplicate_user(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Run a real turn, regenerate it, and confirm the runtime contracts.

        - The original user message is preserved (no duplicate row).
        - The previous assistant message is replaced.
        - ``memory_store.emit`` is **not** invoked for the regenerate turn
          (it would have been invoked for the original).
        - The new SESSION event carries ``regenerate``/``regenerated_from_message_id``.
        """
        store = SQLiteSessionStore(tmp_path / "regen_e2e.db")
        runtime = TurnRuntimeManager(store)

        class FakeContextBuilder:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def build(self, **_kwargs):
                return SimpleNamespace(
                    conversation_history=[],
                    conversation_summary="",
                    context_text="",
                    token_count=0,
                    budget=0,
                )

        responses = iter(["original answer", "regenerated answer"])

        class FakeOrchestrator:
            async def handle(self, _context):
                yield StreamEvent(
                    type=StreamEventType.CONTENT,
                    source="chat",
                    stage="responding",
                    content=next(responses),
                    metadata={"call_kind": "llm_final_response"},
                )
                yield StreamEvent(type=StreamEventType.DONE, source="chat")

        refresh_calls: list[Any] = []

        async def tracking_emit(event):
            refresh_calls.append(event)

        monkeypatch.setattr(
            "deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace()
        )
        monkeypatch.setattr(
            "deeptutor.services.session.context_builder.ContextBuilder",
            FakeContextBuilder,
        )
        monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
        monkeypatch.setattr(
            "deeptutor.services.memory.get_memory_store",
            lambda: SimpleNamespace(
                read_l3_concat=lambda: "",
                emit=tracking_emit,
            ),
        )

        # First turn — populates user + assistant rows and triggers memory refresh.
        session, first_turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "what is 2+2?",
                "session_id": None,
                "capability": "chat",
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
            }
        )
        async for _ in runtime.subscribe_turn(first_turn["id"], after_seq=0):
            pass

        sid = session["id"]
        before = await store.get_messages(sid)
        assert [m["role"] for m in before] == ["user", "assistant"]
        assert before[1]["content"] == "original answer"
        original_user_id = before[0]["id"]
        first_turn_refresh_count = len(refresh_calls)

        # Regenerate — must not duplicate user, must replace assistant, must skip memory refresh.
        _, regen_turn = await runtime.regenerate_last_turn(sid)
        events = []
        async for event in runtime.subscribe_turn(regen_turn["id"], after_seq=0):
            events.append(event)

        assert events[0]["type"] == "session"
        session_meta = events[0].get("metadata") or {}
        assert session_meta.get("regenerate") is True
        assert session_meta.get("regenerated_from_message_id") == original_user_id

        after = await store.get_messages(sid)
        assert [m["role"] for m in after] == ["user", "assistant"]
        assert after[0]["id"] == original_user_id
        assert after[1]["content"] == "regenerated answer"
        # Memory refresh count must not increase on regenerate.
        assert len(refresh_calls) == first_turn_refresh_count

    def test_overrides_take_precedence(self, store: SQLiteSessionStore) -> None:
        sid, _, _ = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder()

        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(
                runtime.regenerate_last_turn(
                    sid,
                    overrides={
                        "tools": ["web_search"],
                        "knowledge_bases": [],
                        "language": "zh",
                        "config": {"temperature": 0.2},
                    },
                )
            )

        payload = recorder.calls[0]
        assert payload["tools"] == ["web_search"]
        assert payload["knowledge_bases"] == []
        assert payload["language"] == "zh"
        assert payload["config"]["temperature"] == 0.2
        # Runtime flags must still be set even when overrides supply config.
        assert payload["config"]["_persist_user_message"] is False
        assert payload["config"]["_regenerate"] is True
