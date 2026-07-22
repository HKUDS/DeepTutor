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
    # Non-empty render so the resolved persona is recorded in the snapshot.
    return SimpleNamespace(
        load_for_context=lambda name: (
            f"## Active Persona\n### Persona: {name}\n\nbody" if name else ""
        )
    )


def _model_catalog() -> dict:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "p-default",
                "active_model_id": "m-default",
                "profiles": [
                    {
                        "id": "p-default",
                        "name": "Default",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-test",
                        "models": [
                            {
                                "id": "m-default",
                                "name": "Default",
                                "model": "gpt-4o-mini",
                            }
                        ],
                    },
                    {
                        "id": "p-alt",
                        "name": "Alt",
                        "binding": "openrouter",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-alt",
                        "models": [
                            {
                                "id": "m-alt",
                                "name": "Alt Model",
                                "model": "anthropic/claude-sonnet-4",
                            }
                        ],
                    },
                ],
            }
        },
    }


@pytest.mark.asyncio
async def test_turn_runtime_replays_events_and_materializes_messages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}
    publish_order: list[str] = []
    original_publish = runtime._publish_live_event

    async def publish_with_status_capture(execution, event):
        publish_order.append(event.type.value)
        if event.type == StreamEventType.DONE:
            persisted_turn = await store.get_turn(execution.turn_id)
            captured["turn_status_when_done_published"] = (persisted_turn or {}).get("status")
        return await original_publish(execution, event)

    monkeypatch.setattr(runtime, "_publish_live_event", publish_with_status_capture)

    async def title_after_done(*_args, **_kwargs):
        captured["title_started_after_done"] = "done" in publish_order

    monkeypatch.setattr(runtime, "_maybe_generate_session_title", title_after_done)

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            on_event = kwargs.get("on_event")
            if on_event is not None:
                await on_event(
                    StreamEvent(
                        type=StreamEventType.PROGRESS,
                        source="context",
                        stage="summarizing",
                        content="summarize context",
                    )
                )
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["user_message"] = context.user_message
            captured["metadata"] = context.metadata
            captured["source_manifest"] = context.source_manifest
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Hello Frank",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            text="## Page: Signal Basics\nA selected page.",
            references=[{"book_id": "book-1", "page_ids": ["page-1"]}],
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        _fake_skill_service,
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        _fake_persona_service,
    )

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "hello, i'm frank",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "persona": "socratic",
            "memory_references": ["summary"],
            "book_references": [{"book_id": "book-1", "page_ids": ["page-1"]}],
            "config": {},
        }
    )

    events = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    # session_meta may arrive after `done` from the title generator —
    # filter it out so the timing race doesn't flake the assertion.
    assert [e["type"] for e in events if e["type"] != "session_meta"] == [
        "session",
        "content",
        "done",
    ]
    done_event = next(e for e in events if e["type"] == "done")
    assert done_event["metadata"]["status"] == "completed"
    assert captured["turn_status_when_done_published"] == "completed"
    assert captured["title_started_after_done"] is True

    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["metadata"]["request_snapshot"]["persona"] == "socratic"
    assert detail["messages"][0]["metadata"]["request_snapshot"]["memoryReferences"] == ["summary"]
    assert detail["messages"][0]["metadata"]["request_snapshot"]["bookReferences"] == [
        {"book_id": "book-1", "page_ids": ["page-1"]}
    ]
    # Chat capability now routes attached sources through the manifest +
    # ``read_source`` tool instead of inlining ``[Book Context]`` into the
    # user message. The raw user message stays raw; the book payload
    # surfaces in ``context.source_manifest`` and ``metadata.source_index``.
    assert str(captured["user_message"]) == "hello, i'm frank"
    manifest = str(captured.get("source_manifest") or "")
    assert "[Attached Sources]" in manifest
    # Book source id is now per-book (``bk-{book_id}``) so multi-book
    # sessions can read_source each independently. The mocked book has id
    # "book-1".
    assert "bk-book-1" in manifest
    source_index = (captured.get("metadata") or {}).get("source_index") or {}
    assert "bk-book-1" in source_index
    assert "A selected page." in source_index["bk-book-1"]
    assert captured["metadata"] and captured["metadata"]["book_references"] == [
        {"book_id": "book-1", "page_ids": ["page-1"]}
    ]
    assert detail["messages"][1]["content"] == "Hello Frank"
    assert detail["preferences"] == {
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "language": "en",
        # Explicit persona in the payload is persisted as a session-level
        # preference (survives reloads; later turns fall back to it).
        "persona": "socratic",
    }

    persisted_turn = await store.get_turn(turn["id"])
    assert persisted_turn is not None
    assert persisted_turn["status"] == "completed"


@pytest.mark.asyncio
async def test_turn_runtime_persists_llm_selection_in_turn_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            captured["builder_llm_config"] = kwargs["llm_config"]
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
                source="chat",
                stage="responding",
                content="Alt reply",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    def fake_activate(selection):
        captured["activated_selection"] = selection
        return SimpleNamespace(
            model="anthropic/claude-sonnet-4", provider_name="openrouter"
        ), object()

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: SimpleNamespace(load=_model_catalog),
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection",
        fake_activate,
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.reset_llm_selection",
        lambda _token: captured.setdefault("reset_called", True),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    selection = {"profile_id": "p-alt", "model_id": "m-alt"}
    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "use the alt model",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
            "llm_selection": selection,
        }
    )

    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass

    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert detail["preferences"]["llm_selection"] == selection
    assert detail["messages"][0]["metadata"]["request_snapshot"]["llmSelection"] == selection
    assert captured["activated_selection"] == selection
    assert captured["builder_llm_config"].model == "anthropic/claude-sonnet-4"
    assert captured["metadata"]["llm_selection"] == selection
    assert captured["metadata"]["llm_model"] == "anthropic/claude-sonnet-4"
    assert captured["metadata"]["llm_provider"] == "openrouter"
    assert captured["reset_called"] is True


@pytest.mark.asyncio
async def test_turn_runtime_session_persona_persists_falls_back_and_clears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Persona is a session preference: explicit key persists (incl. ""),
    absent key falls back to the stored preference."""
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
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

    class FakeOrchestrator:
        async def handle(self, context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="ok",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

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

    async def run_turn(session_id, extra):
        session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "hi",
                "session_id": session_id,
                "capability": None,
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
                **extra,
            }
        )
        async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
            pass
        return session

    # Turn 1 — explicit persona: applied to the turn AND persisted.
    session = await run_turn(None, {"persona": "socratic"})
    detail = await store.get_session_with_messages(session["id"])
    assert detail["preferences"]["persona"] == "socratic"
    assert detail["messages"][0]["metadata"]["request_snapshot"]["persona"] == "socratic"

    # Turn 2 — persona key ABSENT: falls back to the stored preference, so
    # the persona keeps applying to follow-up questions in the session.
    await run_turn(session["id"], {})
    detail = await store.get_session_with_messages(session["id"])
    assert detail["preferences"]["persona"] == "socratic"
    assert detail["messages"][2]["metadata"]["request_snapshot"]["persona"] == "socratic"

    # Turn 3 — explicit "" (Default): clears the stored preference and the
    # turn runs without a persona.
    await run_turn(session["id"], {"persona": ""})
    detail = await store.get_session_with_messages(session["id"])
    assert detail["preferences"]["persona"] == ""
    assert "persona" not in detail["messages"][4]["metadata"]["request_snapshot"]


@pytest.mark.asyncio
async def test_turn_runtime_rejects_invalid_llm_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: SimpleNamespace(load=_model_catalog),
    )

    with pytest.raises(RuntimeError, match="Invalid LLM selection"):
        await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "bad model",
                "session_id": None,
                "capability": None,
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
                "llm_selection": {"profile_id": "p-alt", "model_id": "m-default"},
            }
        )


@pytest.mark.asyncio
async def test_turn_runtime_allows_model_switching_within_same_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    activated: list[dict] = []
    metadata_seen: list[dict] = []

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
            metadata_seen.append(context.metadata)
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content=f"Reply from {context.metadata['llm_model']}",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    def fake_activate(selection):
        activated.append(dict(selection or {}))
        is_alt = (selection or {}).get("profile_id") == "p-alt"
        return (
            SimpleNamespace(
                model="anthropic/claude-sonnet-4" if is_alt else "gpt-4o-mini",
                provider_name="openrouter" if is_alt else "openai",
            ),
            object(),
        )

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: SimpleNamespace(load=_model_catalog),
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection",
        fake_activate,
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.reset_llm_selection",
        lambda _token: None,
    )
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    first_selection = {"profile_id": "p-default", "model_id": "m-default"}
    second_selection = {"profile_id": "p-alt", "model_id": "m-alt"}

    session, first_turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "first model",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
            "llm_selection": first_selection,
        }
    )
    async for _event in runtime.subscribe_turn(first_turn["id"], after_seq=0):
        pass

    same_session, second_turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "second model",
            "session_id": session["id"],
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
            "llm_selection": second_selection,
        }
    )
    async for _event in runtime.subscribe_turn(second_turn["id"], after_seq=0):
        pass

    detail = await store.get_session_with_messages(session["id"])
    assert same_session["id"] == session["id"]
    assert detail is not None
    assert detail["preferences"]["llm_selection"] == second_selection
    assert activated == [first_selection, second_selection]
    assert metadata_seen[0]["llm_model"] == "gpt-4o-mini"
    assert metadata_seen[1]["llm_model"] == "anthropic/claude-sonnet-4"
    user_messages = [message for message in detail["messages"] if message["role"] == "user"]
    assert user_messages[0]["metadata"]["request_snapshot"]["llmSelection"] == first_selection
    assert user_messages[1]["metadata"]["request_snapshot"]["llmSelection"] == second_selection


@pytest.mark.asyncio
async def test_regenerate_reuses_snapshot_or_override_llm_selection(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    captured_payloads: list[dict] = []

    class CapturingRuntime(TurnRuntimeManager):
        async def start_turn(self, payload: dict):
            captured_payloads.append(payload)
            return {"id": payload["session_id"]}, {"id": "turn-test"}

    runtime = CapturingRuntime(store)
    session = await store.create_session(session_id="session-with-snapshot")
    await store.update_session_preferences(
        session["id"],
        {"llm_selection": {"profile_id": "p-default", "model_id": "m-default"}},
    )
    await store.add_message(
        session_id=session["id"],
        role="user",
        content="again",
        capability="chat",
        metadata={
            "request_snapshot": {
                "content": "again",
                "llmSelection": {"profile_id": "p-alt", "model_id": "m-alt"},
            }
        },
    )

    await runtime.regenerate_last_turn(session["id"])
    assert captured_payloads[-1]["llm_selection"] == {
        "profile_id": "p-alt",
        "model_id": "m-alt",
    }

    await runtime.regenerate_last_turn(
        session["id"],
        overrides={"llm_selection": {"profile_id": "p-default", "model_id": "m-default"}},
    )
    assert captured_payloads[-1]["llm_selection"] == {
        "profile_id": "p-default",
        "model_id": "m-default",
    }


@pytest.mark.asyncio
async def test_turn_runtime_bootstraps_question_followup_context_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}

    class FakeContextBuilder:
        def __init__(self, session_store, *_args, **_kwargs) -> None:
            self.store = session_store

        async def build(self, **kwargs):
            messages = await self.store.get_messages_for_context(kwargs["session_id"])
            captured["history_messages"] = messages
            return SimpleNamespace(
                conversation_history=[
                    {"role": item["role"], "content": item["content"]} for item in messages
                ],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["conversation_history"] = context.conversation_history
            captured["config_overrides"] = context.config_overrides
            captured["metadata"] = context.metadata
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Let's discuss this question.",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "Why is my answer wrong?",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {
                "followup_question_context": {
                    "parent_quiz_session_id": "quiz_session_1",
                    "question_id": "q_2",
                    "question_type": "choice",
                    "difficulty": "hard",
                    "concentration": "win-rate comparison",
                    "question": "Which criterion best describes density?",
                    "options": {
                        "A": "Coverage",
                        "B": "Informative value",
                        "C": "Relevant content without redundancy",
                        "D": "Credibility",
                    },
                    "user_answer": "B",
                    "correct_answer": "C",
                    "explanation": "Density focuses on including relevant content without redundancy.",
                    "knowledge_context": "Density measures whether content is relevant and non-redundant.",
                }
            },
        }
    )

    events = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    # session_meta may arrive after `done` from the title generator —
    # filter it out so the timing race doesn't flake the assertion.
    assert [e["type"] for e in events if e["type"] != "session_meta"] == [
        "session",
        "content",
        "done",
    ]
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert [message["role"] for message in detail["messages"]] == ["system", "user", "assistant"]
    assert "Question Follow-up Context" in detail["messages"][0]["content"]
    assert "Which criterion best describes density?" in detail["messages"][0]["content"]
    assert "User answer: B" in detail["messages"][0]["content"]
    assert captured["conversation_history"][0]["role"] == "system"
    assert "followup_question_context" not in captured["config_overrides"]
    assert captured["metadata"]["question_followup_context"]["question_id"] == "q_2"


@pytest.mark.asyncio
async def test_turn_runtime_rejects_deep_research_without_explicit_config(
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)

    with pytest.raises(RuntimeError, match="Invalid deep research config"):
        await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "research transformers",
                "session_id": None,
                "capability": "deep_research",
                "tools": ["rag"],
                "knowledge_bases": ["research-kb"],
                "attachments": [],
                "language": "en",
                "config": {},
            }
        )


@pytest.mark.asyncio
async def test_turn_runtime_persists_deep_research_session_preference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
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

    class FakeOrchestrator:
        async def handle(self, _context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="deep_research",
                stage="reporting",
                content="Research report ready.",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="deep_research")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "research transformers",
            "session_id": None,
            "capability": "deep_research",
            "tools": ["rag", "web_search"],
            "knowledge_bases": ["research-kb"],
            "attachments": [],
            "language": "en",
            "config": {
                "mode": "report",
                "depth": "standard",
            },
        }
    )

    events = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    # session_meta may arrive after `done` from the title generator —
    # filter it out so the timing race doesn't flake the assertion.
    assert [e["type"] for e in events if e["type"] != "session_meta"] == [
        "session",
        "content",
        "done",
    ]
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert detail["preferences"]["capability"] == "deep_research"
    assert detail["preferences"]["tools"] == ["rag", "web_search"]


@pytest.mark.asyncio
async def test_turn_runtime_injects_memory_and_refreshes_after_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="Recent chat summary",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["conversation_history"] = context.conversation_history
            captured["memory_context"] = context.memory_context
            captured["conversation_context_text"] = context.metadata.get(
                "conversation_context_text"
            )
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Stored reply",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    emit_calls: list[object] = []

    async def fake_emit(event):
        emit_calls.append(event)
        return None

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "## Memory\n## Preferences\n- Prefer concise answers.",
            emit=fake_emit,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    _session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "hello, i'm frank",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "memory_references": ["preferences"],
            "language": "en",
            "config": {},
        }
    )

    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass

    assert captured["memory_context"] == "## Memory\n## Preferences\n- Prefer concise answers."
    assert captured["conversation_history"] == []
    assert captured["conversation_context_text"] == "Recent chat summary"
