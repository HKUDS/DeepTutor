"""Regression coverage for pre-execution chat quiz routing (#807)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


async def _noop_async(*_args, **_kwargs):
    return None


def _fake_skill_service() -> SimpleNamespace:
    return SimpleNamespace(
        summary_entries=lambda: [],
        load_always_for_context=lambda: "",
        load_for_context=lambda _skills: "",
        list_skills=lambda: [],
    )


def _fake_persona_service() -> SimpleNamespace:
    return SimpleNamespace(load_for_context=lambda _name: "")


def _configure_runtime(monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
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
            captured["active_capability"] = context.active_capability
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
        lambda: {"capability_routing_enabled": captured["global_enabled"]},
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
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)


async def _run_quiz_turn(tmp_path, captured: dict, config: dict | None = None):
    runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "routing.db"))
    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "Please generate 3 quiz questions",
            "session_id": None,
            "capability": "chat",
            "tools": ["web_search", "brainstorm"],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": config or {},
        }
    )
    events = []
    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(_event)
    done = next(event for event in events if event["type"] == "done")
    captured["done_metadata"] = done["metadata"]
    detail = await runtime.store.get_session(session["id"])
    assert detail is not None
    return turn, detail


@pytest.mark.asyncio
async def test_quiz_requests_stay_in_chat_by_default(tmp_path) -> None:
    captured: dict = {"global_enabled": False}
    _configure_runtime(pytest.MonkeyPatch(), captured)

    turn, session = await _run_quiz_turn(tmp_path, captured)

    assert turn["capability"] == "chat"
    assert captured["active_capability"] == "chat"
    assert captured["metadata"]["capability_route"] is None
    assert "capability_route" not in captured["done_metadata"]
    assert session["preferences"]["capability"] == "chat"


@pytest.mark.asyncio
async def test_enabled_explicit_quiz_routes_for_one_turn(tmp_path) -> None:
    captured: dict = {"global_enabled": True}
    _configure_runtime(pytest.MonkeyPatch(), captured)

    turn, session = await _run_quiz_turn(tmp_path, captured)

    assert turn["capability"] == "deep_question"
    assert captured["active_capability"] == "deep_question"
    assert captured["metadata"]["capability_route"]["auto_routed"] is True
    assert captured["metadata"]["capability_route"]["strategy"] == "rule"
    assert captured["done_metadata"]["capability_route"]["capability"] == "deep_question"
    assert session["preferences"]["capability"] == "chat"


@pytest.mark.asyncio
async def test_auto_route_false_overrides_global_setting(tmp_path) -> None:
    captured: dict = {"global_enabled": True}
    _configure_runtime(pytest.MonkeyPatch(), captured)

    turn, session = await _run_quiz_turn(tmp_path, captured, {"auto_route": False})

    assert turn["capability"] == "chat"
    assert captured["active_capability"] == "chat"
    assert session["preferences"]["capability"] == "chat"


@pytest.mark.asyncio
async def test_per_turn_flag_opts_in_when_global_default_is_off(tmp_path) -> None:
    captured: dict = {"global_enabled": False}
    _configure_runtime(pytest.MonkeyPatch(), captured)

    turn, session = await _run_quiz_turn(tmp_path, captured, {"auto_route": True})

    assert turn["capability"] == "deep_question"
    assert captured["active_capability"] == "deep_question"
    assert session["preferences"]["capability"] == "chat"
