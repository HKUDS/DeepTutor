"""Create-mode (``create_target``) session plumbing: persist, explicit clear,
regenerate restore, and the Resend replay table.

Mirrors the harnesses already proven for persona/note_document_id in
``test_capability_routing.py`` (full ``start_turn`` with a fake orchestrator
capturing ``context.metadata``) and ``test_regenerate.py`` (a fake
``start_turn`` recorder feeding ``regenerate_last_turn``).
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
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from deeptutor.services.skill.service import SkillService


async def _noop_async(*_args, **_kwargs):
    return None


def _fake_persona_service() -> SimpleNamespace:
    return SimpleNamespace(load_for_context=lambda _name: "")


def _configure_runtime(monkeypatch: pytest.MonkeyPatch, captured: dict, tmp_path: Path) -> None:
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

    class FakeOrchestrator:
        async def handle(self, context):
            captured["metadata"] = context.metadata
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                content="ok",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(
                type=StreamEventType.DONE,
                source=context.active_capability,
                metadata={},
            )

    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_system_settings",
        lambda: {"capability_routing_enabled": False},
    )
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        lambda: SkillService(root=tmp_path / "skills", builtin_root=None),
    )
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)


async def _run_turn(runtime: TurnRuntimeManager, payload: dict) -> tuple[dict, dict]:
    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "capability": "chat",
            "content": "hello",
            **payload,
        }
    )
    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass
    detail = await runtime.store.get_session(session["id"])
    assert detail is not None
    return turn, detail


# ---------------------------------------------------------------------------
# Persist + explicit clear (TurnRequestPreparer.start_turn)
# ---------------------------------------------------------------------------


class TestPersistAndExplicitClear:
    @pytest.mark.asyncio
    async def test_explicit_kind_is_persisted_and_reaches_turn_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        _configure_runtime(monkeypatch, captured, tmp_path)
        runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "sessions.db"))

        _turn, session = await _run_turn(runtime, {"create_target": "skill"})

        assert captured["metadata"]["create_target"] == "skill"
        assert session["preferences"]["create_target"] == "skill"

    @pytest.mark.asyncio
    async def test_explicit_empty_string_clears_a_previously_set_kind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        _configure_runtime(monkeypatch, captured, tmp_path)
        runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "sessions.db"))

        _turn, session = await _run_turn(runtime, {"create_target": "persona"})
        assert session["preferences"]["create_target"] == "persona"

        _turn2, session2 = await _run_turn(
            runtime, {"session_id": session["id"], "create_target": ""}
        )
        assert captured["metadata"]["create_target"] == ""
        assert session2["preferences"]["create_target"] == ""

    @pytest.mark.asyncio
    async def test_omitting_the_key_does_not_touch_the_stored_preference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        _configure_runtime(monkeypatch, captured, tmp_path)
        runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "sessions.db"))

        _turn, session = await _run_turn(runtime, {"create_target": "skill"})
        _turn2, session2 = await _run_turn(runtime, {"session_id": session["id"]})

        # Preference untouched (the omitted key is not an explicit clear) even
        # though this turn did not activate create mode itself.
        assert session2["preferences"]["create_target"] == "skill"
        assert captured["metadata"]["create_target"] == ""


# ---------------------------------------------------------------------------
# Regenerate restore + Resend replay table
# ---------------------------------------------------------------------------


class _FakeStartTurnRecorder:
    """Captures the payload passed to ``start_turn`` without launching it."""

    def __init__(self, store: SQLiteSessionStore) -> None:
        self.store = store
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        payload: dict[str, Any],
        *,
        replace_assistant_message_id: int | str | None = None,
        persist_llm_selection_only: bool = False,
    ) -> tuple[dict, dict]:
        self.calls.append(payload)
        if replace_assistant_message_id is not None:
            await self.store.delete_message(replace_assistant_message_id)
        return (
            {"id": payload["session_id"]},
            {"id": "fake-turn", "session_id": payload["session_id"]},
        )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "regenerate.db")


def _seed_session(
    store: SQLiteSessionStore,
    *,
    preferences: dict[str, Any] | None = None,
    user_metadata: dict[str, Any] | None = None,
) -> str:
    session = asyncio.run(store.create_session())
    sid = session["id"]
    asyncio.run(
        store.update_session_preferences(
            sid, {"capability": "chat", "language": "en", **(preferences or {})}
        )
    )
    asyncio.run(
        store.add_message(
            sid,
            role="user",
            content="let's make a skill",
            capability="chat",
            metadata=user_metadata,
        )
    )
    asyncio.run(store.add_message(sid, role="assistant", content="ok", capability="chat"))
    return sid


class TestRegenerateRestore:
    def test_override_wins_over_everything(self, store: SQLiteSessionStore) -> None:
        sid = _seed_session(
            store,
            preferences={"create_target": "persona"},
            user_metadata={"request_snapshot": {"createTarget": "skill"}},
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid, overrides={"create_target": ""}))
        assert recorder.calls[0]["create_target"] is None

    def test_snapshot_wins_over_preferences_when_no_override(
        self, store: SQLiteSessionStore
    ) -> None:
        sid = _seed_session(
            store,
            preferences={"create_target": "persona"},
            user_metadata={"request_snapshot": {"createTarget": "skill"}},
        )
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))
        assert recorder.calls[0]["create_target"] == "skill"

    def test_falls_back_to_preferences_without_a_snapshot(self, store: SQLiteSessionStore) -> None:
        sid = _seed_session(store, preferences={"create_target": "persona"})
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))
        assert recorder.calls[0]["create_target"] == "persona"

    def test_none_when_nothing_restores_it(self, store: SQLiteSessionStore) -> None:
        sid = _seed_session(store)
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid))
        assert recorder.calls[0]["create_target"] is None


class TestResendReplayTable:
    def test_replay_snapshot_restores_create_target(self, store: SQLiteSessionStore) -> None:
        sid = _seed_session(store, user_metadata={"request_snapshot": {"createTarget": "persona"}})
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(runtime.regenerate_last_turn(sid, overrides={"replay_snapshot": True}))
        assert recorder.calls[0]["create_target"] == "persona"

    def test_explicit_override_clears_it_even_during_replay(
        self, store: SQLiteSessionStore
    ) -> None:
        sid = _seed_session(store, user_metadata={"request_snapshot": {"createTarget": "persona"}})
        runtime = TurnRuntimeManager(store=store)
        recorder = _FakeStartTurnRecorder(store)
        with patch.object(runtime, "start_turn", new=recorder):
            asyncio.run(
                runtime.regenerate_last_turn(
                    sid, overrides={"replay_snapshot": True, "create_target": ""}
                )
            )
        assert recorder.calls[0]["create_target"] == ""
