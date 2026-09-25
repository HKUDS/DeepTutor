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

    def __init__(self, store: SQLiteSessionStore) -> None:
        self.store = store
        self.calls: list[dict[str, Any]] = []
        self.replaced_assistant_ids: list[int | str] = []

    async def __call__(
        self,
        payload: dict[str, Any],
        *,
        replace_assistant_message_id: int | str | None = None,
    ) -> tuple[dict, dict]:
        self.calls.append(payload)
        if replace_assistant_message_id is not None:
            self.replaced_assistant_ids.append(replace_assistant_message_id)
            await self.store.delete_message(replace_assistant_message_id)
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
        recorder = _FakeStartTurnRecorder(store)

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
        assert payload["persist_user_message"] is False
        assert payload["regenerate"] is True
        assert payload["regenerated_from_message_id"] == user_id

        remaining = asyncio.run(store.get_messages(sid))
        assert [m["id"] for m in remaining] == [user_id]
        assert assistant_id is not None and assistant_id not in {m["id"] for m in remaining}

    @pytest.mark.parametrize("replay_snapshot", [False, True])
    def test_replays_rich_attachment_payload_without_breaking_turn_request(
        self, store: SQLiteSessionStore, replay_snapshot: bool
    ) -> None:
        """A turn whose persisted attachment carries the rich fields stored at
        upload (id, extracted_chars, extracted_text) must still produce a
        valid TurnRequest on regenerate.

        #1484: regenerate echoed the stored message-row attachments verbatim,
        whose extra fields OutgoingAttachment forbids, so start_turn's
        TurnRequest validation raised and the WS closed with no terminal
        event — the UI hung on "Thinking..." forever.
        """
        session = asyncio.run(store.create_session())
        sid = session["id"]
        asyncio.run(store.update_session_preferences(sid, {"capability": "chat", "language": "en"}))
        asyncio.run(
            store.add_message(
                sid,
                role="user",
                content="summarize the pdf",
                capability="chat",
                attachments=[
                    {
                        "type": "file",
                        "url": "/files/attachments/s1/att-1/a.pdf",
                        "base64": "",
                        "filename": "a.pdf",
                        "mime_type": "application/pdf",
                        # Extra fields persisted by the executor at upload.
                        "id": "att-1",
                        "extracted_chars": 67619,
                        "extracted_text": "--- Page 1 --- body text",
                    }
                ],
            )
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(
                runtime.regenerate_last_turn(
                    sid,
                    overrides={"replay_snapshot": True} if replay_snapshot else None,
                )
            )

        from deeptutor.core.turn_request import TurnRequest

        payload = recorder.calls[0]
        # The payload must validate against the wire contract...
        TurnRequest.model_validate(payload)
        # ...with the extra fields stripped to the allowed attachment shape.
        assert payload["attachments"] == [
            {
                "type": "file",
                "url": "/files/attachments/s1/att-1/a.pdf",
                "base64": "",
                "filename": "a.pdf",
                "mime_type": "application/pdf",
                "id": "att-1",
            }
        ]

    @pytest.mark.parametrize("replay_snapshot", [False, True])
    def test_saved_request_is_opt_in_and_explicit_clears_win(
        self, store: SQLiteSessionStore, replay_snapshot: bool
    ) -> None:
        snapshot = {
            "capability": "deep_solve",
            "enabledTools": ["web_search"],
            "knowledgeBases": ["old-kb"],
            "language": "zh",
            "config": {"steps": 3},
            "notebookReferences": [{"notebook_id": "notebook-1", "record_ids": ["r1"]}],
            "historyReferences": ["earlier-session"],
            "partnerGroupReferences": [{"group_id": "group-1", "session_key": "s1"}],
            "questionNotebookReferences": [42],
            "bookReferences": [{"book_id": "book-1", "page_ids": ["p1"]}],
            "readingReferences": [
                {"material_id": "0123456789abcdef", "revision": 2, "locators": [1]}
            ],
            "memoryReferences": ["summary"],
            "skills": [],
            "mcp": ["server-1"],
            "persona": "",
            "llmSelection": {"profile_id": "old-profile", "model_id": "old-model"},
            "workspaceMode": "",
            "courseId": "",
            "masteryPathId": "",
            "masterySessionMode": "study",
            "autoRoute": False,
        }
        sid, _, _ = _seed_session(store, user_metadata={"request_snapshot": snapshot})
        asyncio.run(
            store.update_session_preferences(
                sid,
                {
                    "capability": "chat",
                    "tools": ["brainstorm"],
                    "knowledge_bases": ["new-kb"],
                    "language": "en",
                    "skills": ["current-skill"],
                    "mcp": [],
                    "persona": "current-persona",
                },
            )
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        overrides = {"replay_snapshot": True} if replay_snapshot else None
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid, overrides=overrides))

        payload = recorder.calls[0]
        assert "replay_snapshot" not in payload
        if not replay_snapshot:
            assert "preserve_session_preferences" not in payload
            assert payload["capability"] == "chat"
            assert payload["tools"] == ["brainstorm"]
            assert payload["knowledge_bases"] == ["new-kb"]
            assert payload["language"] == "en"
            assert payload["config"] == {}
            assert "persona" not in payload
            return

        assert payload["capability"] == "deep_solve"
        assert payload["preserve_session_preferences"] is True
        assert payload["tools"] == ["web_search"]
        assert payload["knowledge_bases"] == ["old-kb"]
        assert payload["language"] == "zh"
        assert payload["config"] == {"steps": 3}
        assert payload["notebook_references"] == snapshot["notebookReferences"]
        assert payload["history_references"] == snapshot["historyReferences"]
        assert payload["partner_group_references"] == snapshot["partnerGroupReferences"]
        assert payload["question_notebook_references"] == [42]
        assert payload["book_references"] == snapshot["bookReferences"]
        assert payload["reading_references"] == snapshot["readingReferences"]
        assert payload["memory_references"] == ["summary"]
        assert payload["skills"] == []
        assert payload["mcp"] == ["server-1"]
        assert payload["persona"] == ""
        assert payload["llm_selection"] == snapshot["llmSelection"]
        assert payload["workspace_mode"] == ""
        assert payload["course_id"] == ""
        assert payload["mastery_path_id"] == ""
        assert payload["mastery_session_mode"] == "study"
        assert payload["auto_route"] is False

    def test_resend_overrides_saved_fields_including_empty_values(
        self, store: SQLiteSessionStore
    ) -> None:
        sid, _, _ = _seed_session(
            store,
            user_metadata={
                "request_snapshot": {
                    "enabledTools": ["web_search"],
                    "knowledgeBases": ["old-kb"],
                    "language": "zh",
                    "config": {"steps": 3},
                    "memoryReferences": ["summary"],
                    "persona": "socratic",
                    "llmSelection": {"profile_id": "old-profile", "model_id": "old-model"},
                }
            },
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(
                runtime.regenerate_last_turn(
                    sid,
                    overrides={
                        "replay_snapshot": True,
                        "tools": [],
                        "knowledge_bases": [],
                        "language": "fr",
                        "config": {},
                        "memory_references": [],
                        "persona": "",
                        "llm_selection": {"profile_id": "new-profile", "model_id": "new-model"},
                    },
                )
            )
        payload = recorder.calls[0]
        assert payload["tools"] == []
        assert payload["knowledge_bases"] == []
        assert payload["language"] == "fr"
        assert payload["config"] == {}
        assert payload["memory_references"] == []
        assert payload["persona"] == ""
        assert payload["llm_selection"] == {
            "profile_id": "new-profile",
            "model_id": "new-model",
        }

    def test_regenerate_preserves_pocketbase_message_id(self, store: SQLiteSessionStore) -> None:
        sid, _, _ = _seed_session(store, assistant_content=None)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        deleted_ids: list[str] = []

        async def last_message(_session_id: str, role: str | None = None):
            if role == "user":
                return {"id": "pbRecord123abc", "role": "user", "content": "try again"}
            return {"id": "pbAnswer123abc", "role": "assistant", "content": "old answer"}

        async def delete_message(message_id: int | str) -> bool:
            deleted_ids.append(str(message_id))
            return True

        with (
            patch.object(store, "get_last_message", new=last_message),
            patch.object(store, "delete_message", new=delete_message),
            patch.object(runtime, "start_turn", new=recorder),
        ):
            asyncio.run(runtime.regenerate_last_turn(sid, overrides={"replay_snapshot": True}))

        payload = recorder.calls[0]
        assert payload["regenerated_from_message_id"] == "pbRecord123abc"
        assert recorder.replaced_assistant_ids == ["pbAnswer123abc"]
        assert deleted_ids == ["pbAnswer123abc"]

    def test_validation_failure_preserves_existing_assistant_message(
        self, store: SQLiteSessionStore
    ) -> None:
        sid, user_id, assistant_id = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)

        with pytest.raises(ValueError):
            asyncio.run(
                runtime.regenerate_last_turn(
                    sid,
                    overrides={"llm_selection": {"profile_id": "missing-model"}},
                )
            )

        remaining = asyncio.run(store.get_messages(sid))
        assert [message["id"] for message in remaining] == [user_id, assistant_id]

    @pytest.mark.parametrize("rejected_at", ["capability", "workspace", "llm"])
    @pytest.mark.parametrize("replay_snapshot", [False, True])
    def test_admission_rejection_preserves_existing_assistant_message(
        self,
        store: SQLiteSessionStore,
        monkeypatch: pytest.MonkeyPatch,
        rejected_at: str,
        replay_snapshot: bool,
    ) -> None:
        sid, user_id, assistant_id = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)
        overrides: dict[str, Any] = {"replay_snapshot": True} if replay_snapshot else {}

        def reject(*_args: Any, **_kwargs: Any) -> None:
            raise PermissionError(f"{rejected_at} access revoked")

        if rejected_at == "capability":
            monkeypatch.setattr(
                "deeptutor.multi_user.learning_access.apply_learning_policy", reject
            )
        elif rejected_at == "workspace":
            asyncio.run(store.update_session_preferences(sid, {"workspace_id": "revoked"}))
            monkeypatch.setattr(
                "deeptutor.services.workspace.get_content_workspace_service", reject
            )
        else:
            overrides["llm_selection"] = {
                "profile_id": "revoked-profile",
                "model_id": "revoked-model",
            }
            monkeypatch.setattr(
                "deeptutor.multi_user.model_access.apply_allowed_llm_selection", reject
            )

        with pytest.raises((RuntimeError, PermissionError), match="access revoked"):
            asyncio.run(runtime.regenerate_last_turn(sid, overrides=overrides))

        # Admission did not launch a replacement, so both the old answer and
        # its original id must still be available for display or another try.
        remaining = asyncio.run(store.get_messages(sid))
        assert [message["id"] for message in remaining] == [user_id, assistant_id]
        assert remaining[-1]["content"] == "4"
        assert asyncio.run(store.get_active_turn(sid)) is None

    def test_replacement_deletion_failure_keeps_old_answer_and_aborts_launch(
        self,
        store: SQLiteSessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sid, user_id, assistant_id = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)

        async def refuse_delete(_message_id: int | str) -> bool:
            return False

        monkeypatch.setattr(store, "delete_message", refuse_delete)
        with pytest.raises(RuntimeError, match="Unable to replace the previous assistant"):
            asyncio.run(runtime.regenerate_last_turn(sid))

        assert [message["id"] for message in asyncio.run(store.get_messages(sid))] == [
            user_id,
            assistant_id,
        ]
        assert asyncio.run(store.get_active_turn(sid)) is None

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
        recorder = _FakeStartTurnRecorder(store)

        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))

        assert recorder.calls[0]["book_references"] == [
            {"book_id": "book-1", "page_ids": ["page-1"]}
        ]

    def test_replays_mastery_path_from_request_snapshot(self, store: SQLiteSessionStore) -> None:
        sid, _, _ = _seed_session(
            store,
            user_metadata={"request_snapshot": {"masteryPathId": "path-1"}},
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)

        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))

        assert recorder.calls[0]["mastery_path_id"] == "path-1"

    def test_user_tail_is_kept_and_no_delete(self, store: SQLiteSessionStore) -> None:
        sid, user_id, _ = _seed_session(store, assistant_content=None)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)

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

        responses = iter(["original answer", "regenerated answer", "resent answer"])

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

        # Resend replays the saved request, but a setting changed since that
        # request must remain the conversation setting for later turns.
        await store.update_session_preferences(sid, {"language": "zh"})
        _, resend_turn = await runtime.regenerate_last_turn(
            sid, overrides={"replay_snapshot": True}
        )
        async for _ in runtime.subscribe_turn(resend_turn["id"], after_seq=0):
            pass
        assert (await store.get_session(sid))["preferences"]["language"] == "zh"
        assert (await store.get_messages(sid))[-1]["content"] == "resent answer"

    def test_overrides_take_precedence(self, store: SQLiteSessionStore) -> None:
        sid, _, _ = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)

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
        assert payload["persist_user_message"] is False
        assert payload["regenerate"] is True
