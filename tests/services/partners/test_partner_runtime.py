"""PartnerRunner: chat-loop event mapping, tool config, session persistence."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.partners.bus.events import InboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.services.partners.manager import PartnerConfig
from deeptutor.services.partners.runtime import PartnerRunner
from deeptutor.services.partners.sessions import PartnerSessionStore


def _event(
    event_type: StreamEventType,
    *,
    content: str = "",
    source: str = "chat",
    metadata: dict[str, Any] | None = None,
) -> StreamEvent:
    return StreamEvent(type=event_type, source=source, content=content, metadata=metadata or {})


def _narration_round(call_id: str, text: str) -> list[StreamEvent]:
    return [
        _event(StreamEventType.CONTENT, content=text, metadata={"call_id": call_id}),
        _event(
            StreamEventType.PROGRESS,
            metadata={
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_role": "narration",
                "call_id": call_id,
            },
        ),
    ]


def _finish(text: str) -> list[StreamEvent]:
    return [
        _event(StreamEventType.CONTENT, content=text, metadata={"call_id": "c-finish"}),
        _event(StreamEventType.RESULT, metadata={"response": text}),
        _event(StreamEventType.DONE),
    ]


class _FakeOrchestrator:
    """Yields a scripted event sequence instead of running the chat loop."""

    script: list[StreamEvent] = []
    # Optional queue of per-turn scripts; when non-empty, each handle() call
    # pops the next one (lets tests model a failed turn + a backup retry).
    scripts: list[list[StreamEvent]] = []
    seen_contexts: list[Any] = []
    activated_selections: list[Any] = []
    # The memory root in effect while the turn runs — proves the partner reads
    # the owner's (admin) memory via memory_path_service_override, not its own.
    seen_memory_roots: list[Any] = []

    def __init__(self) -> None:
        pass

    async def handle(self, context):
        from deeptutor.services.memory.paths import memory_root

        type(self).seen_contexts.append(context)
        type(self).seen_memory_roots.append(memory_root())
        script = type(self).scripts.pop(0) if type(self).scripts else type(self).script
        for event in script:
            yield event


@pytest.fixture
def fake_orchestrator(monkeypatch):
    import deeptutor.runtime.orchestrator as orch_mod
    from deeptutor.services.model_selection import runtime as selection_runtime

    _FakeOrchestrator.script = []
    _FakeOrchestrator.scripts = []
    _FakeOrchestrator.seen_contexts = []
    _FakeOrchestrator.activated_selections = []
    _FakeOrchestrator.seen_memory_roots = []
    monkeypatch.setattr(orch_mod, "ChatOrchestrator", _FakeOrchestrator)

    def _record_activate(selection):
        _FakeOrchestrator.activated_selections.append(selection)
        return (None, None)

    monkeypatch.setattr(selection_runtime, "activate_llm_selection", _record_activate)
    monkeypatch.setattr(selection_runtime, "reset_llm_selection", lambda token: None)
    return _FakeOrchestrator


def _runner(partners_root, config: PartnerConfig | None = None) -> PartnerRunner:
    from deeptutor.partners.config.paths import get_partner_sessions_dir

    config = config or PartnerConfig(name="Ada")
    bus = MessageBus()
    store = PartnerSessionStore(get_partner_sessions_dir("ada"))
    return PartnerRunner("ada", config, bus, store)


def _msg(content: str = "hello", channel: str = "telegram") -> InboundMessage:
    return InboundMessage(channel=channel, sender_id="42", chat_id="42", content=content)


class TestTurnExecution:
    @pytest.mark.asyncio
    async def test_returns_finish_text_and_persists_session(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _narration_round("c1", "let me check") + _finish(
            "The answer is 4."
        )
        runner = _runner(partners_root)

        final = await runner.process_message(_msg("what is 2+2?"))
        assert final == "The answer is 4."

        history = runner.store.conversation_history("telegram:42")
        assert history == [
            {"role": "user", "content": "what is 2+2?"},
            {"role": "assistant", "content": "The answer is 4."},
        ]

    @pytest.mark.asyncio
    async def test_narration_streams_as_progress_outbound(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _narration_round("c1", "exploring…") + _finish("done")
        runner = _runner(partners_root)

        await runner.process_message(_msg())
        progress = await runner.bus.outbound.get()
        assert progress.content == "exploring…"
        assert progress.metadata["_progress"] is True
        assert progress.metadata["_tool_hint"] is False

    @pytest.mark.asyncio
    async def test_tool_calls_stream_as_hints_by_default(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = [
            _event(
                StreamEventType.TOOL_CALL,
                content="rag",
                metadata={"args": {"query": "hello world", "_internal": "x"}},
            ),
            *_finish("done"),
        ]
        runner = _runner(partners_root)

        await runner.process_message(_msg())
        hint = await runner.bus.outbound.get()
        assert hint.metadata["_tool_hint"] is True
        assert hint.content.startswith("⚙ rag(")
        assert "hello world" in hint.content
        assert "_internal" not in hint.content

    @pytest.mark.asyncio
    async def test_send_progress_flag_off_suppresses_narration(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = _narration_round("c1", "exploring…") + _finish("done")
        config = PartnerConfig(name="Ada", channels={"telegram": {"send_progress": False}})
        runner = _runner(partners_root, config)

        await runner.process_message(_msg())
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_web_channel_never_emits_progress_outbound(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = _narration_round("c1", "exploring…") + _finish("done")
        runner = _runner(partners_root)

        await runner.process_message(_msg(channel="web"))
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_unresolved_ask_user_question_becomes_reply(
        self, partners_root, fake_orchestrator
    ):
        # An unresolved ask_user pause emits the question as a final-response
        # CONTENT event while RESULT carries an empty response.
        fake_orchestrator.script = [
            _event(
                StreamEventType.CONTENT,
                content="Which topic do you mean?",
                metadata={"call_id": "f1", "call_kind": "llm_final_response"},
            ),
            _event(StreamEventType.RESULT, metadata={"response": ""}),
            _event(StreamEventType.DONE),
        ]
        runner = _runner(partners_root)

        final = await runner.process_message(_msg())
        assert final == "Which topic do you mean?"

    @pytest.mark.asyncio
    async def test_backup_model_retries_failed_turn(self, partners_root, fake_orchestrator):
        primary = {"profile_id": "p1", "model_id": "m1"}
        backup = {"profile_id": "p2", "model_id": "m2"}
        fake_orchestrator.scripts = [
            # Turn 1 (primary): hard failure, no answer.
            [
                _event(StreamEventType.ERROR, content="rate limited"),
                _event(StreamEventType.RESULT, metadata={"response": ""}),
                _event(StreamEventType.DONE),
            ],
            # Turn 2 (backup): succeeds.
            _finish("backup answer"),
        ]
        config = PartnerConfig(name="Ada", llm_selection=primary, backup_llm_selection=backup)
        runner = _runner(partners_root, config)

        final = await runner.process_message(_msg())
        assert final == "backup answer"
        assert fake_orchestrator.activated_selections == [primary, backup]

    @pytest.mark.asyncio
    async def test_no_backup_returns_error_text(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = [
            _event(StreamEventType.ERROR, content="rate limited"),
            _event(StreamEventType.RESULT, metadata={"response": ""}),
            _event(StreamEventType.DONE),
        ]
        runner = _runner(partners_root)

        final = await runner.process_message(_msg())
        assert "rate limited" in final
        assert len(fake_orchestrator.seen_contexts) == 1

    @pytest.mark.asyncio
    async def test_llm_config_error_folds_into_graceful_reply(
        self, partners_root, fake_orchestrator, monkeypatch
    ):
        # A setup failure with no resolvable LLM model (LLMConfigError) must
        # fold into the turn's error path — an apology carrying the real reason
        # — instead of propagating as an opaque crash / bare "Internal error".
        from deeptutor.services.llm.exceptions import LLMConfigError
        from deeptutor.services.model_selection import runtime as selection_runtime

        def _raise(selection):
            raise LLMConfigError("No active LLM model is configured.")

        monkeypatch.setattr(selection_runtime, "activate_llm_selection", _raise)
        runner = _runner(partners_root)

        final = await runner.process_message(_msg("hi"))
        assert "No active LLM model is configured." in final
        # The orchestrator is never reached when LLM-selection resolution fails.
        assert fake_orchestrator.seen_contexts == []

    @pytest.mark.asyncio
    async def test_backup_retried_when_primary_selection_unresolvable(
        self, partners_root, fake_orchestrator, monkeypatch
    ):
        # Selection resolution now runs inside the turn's try, so a primary
        # model that no longer resolves falls back to the backup model instead
        # of crashing the turn outright.
        from deeptutor.services.llm.exceptions import LLMConfigError
        from deeptutor.services.model_selection import runtime as selection_runtime

        primary = {"profile_id": "p1", "model_id": "m1"}
        backup = {"profile_id": "p2", "model_id": "m2"}
        attempted: list[Any] = []

        def _activate(selection):
            attempted.append(selection)
            if selection == primary:
                raise LLMConfigError("primary profile is gone")
            return (None, None)

        monkeypatch.setattr(selection_runtime, "activate_llm_selection", _activate)
        fake_orchestrator.script = _finish("backup answer")
        config = PartnerConfig(name="Ada", llm_selection=primary, backup_llm_selection=backup)
        runner = _runner(partners_root, config)

        final = await runner.process_message(_msg())
        assert final == "backup answer"
        assert attempted == [primary, backup]

    @pytest.mark.asyncio
    async def test_successful_turn_never_touches_backup(self, partners_root, fake_orchestrator):
        backup = {"profile_id": "p2", "model_id": "m2"}
        fake_orchestrator.script = _finish("first try works")
        config = PartnerConfig(name="Ada", backup_llm_selection=backup)
        runner = _runner(partners_root, config)

        final = await runner.process_message(_msg())
        assert final == "first try works"
        assert fake_orchestrator.activated_selections == [None]

    @pytest.mark.asyncio
    async def test_inbound_handler_publishes_reply_outbound(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _finish("reply text")
        runner = _runner(partners_root)

        await runner._handle_inbound(_msg())
        out = await runner.bus.outbound.get()
        assert out.channel == "telegram"
        assert out.chat_id == "42"
        assert out.content == "reply text"


class TestContextAssembly:
    @pytest.mark.asyncio
    async def test_context_carries_soul_tools_and_metadata(self, partners_root, fake_orchestrator):
        from deeptutor.services.partners.workspace import write_soul

        write_soul("ada", "# Soul\nBe kind.")
        fake_orchestrator.script = _finish("ok")
        config = PartnerConfig(
            name="Ada",
            language="zh",
            enabled_tools=["web_search"],
            mcp_tools=["mcp_github_search"],
        )
        runner = _runner(partners_root, config)

        await runner.process_message(
            InboundMessage(
                channel="telegram",
                sender_id="42",
                chat_id="42",
                content="hello",
                metadata={
                    "message_id": "m-1",
                    "thread_ts": "111.222",
                    "_cron_job_id": "cron-1",
                    "_wants_stream": True,
                },
            )
        )
        context = fake_orchestrator.seen_contexts[0]
        assert context.persona_context == "# Soul\nBe kind."
        assert context.enabled_tools == ["web_search"]
        assert context.metadata["mcp_tools_filter"] == ["mcp_github_search"]
        assert context.metadata["channel_metadata"] == {
            "message_id": "m-1",
            "thread_ts": "111.222",
        }
        assert context.metadata["cron_job_id"] == "cron-1"
        assert context.language == "zh"
        assert context.active_capability == "chat"
        assert context.metadata["partner_id"] == "ada"
        assert context.metadata["agent_identity"]["name"] == "Ada"
        assert "wait_for_user_reply" not in context.metadata

    @pytest.mark.asyncio
    async def test_default_tools_resolve_to_full_toggleable_set(
        self, partners_root, fake_orchestrator
    ):
        from deeptutor.agents._shared.tool_composition import default_optional_tools

        fake_orchestrator.script = _finish("ok")
        runner = _runner(partners_root)  # enabled_tools=None

        await runner.process_message(_msg())
        context = fake_orchestrator.seen_contexts[0]
        assert context.enabled_tools == default_optional_tools()
        assert "mcp_tools_filter" not in context.metadata

    @pytest.mark.asyncio
    async def test_history_feeds_next_turn(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _finish("first reply")
        runner = _runner(partners_root)
        await runner.process_message(_msg("first question"))

        fake_orchestrator.script = _finish("second reply")
        await runner.process_message(_msg("second question"))

        context = fake_orchestrator.seen_contexts[-1]
        assert {"role": "user", "content": "first question"} in context.conversation_history
        assert {
            "role": "assistant",
            "content": "first reply",
        } in context.conversation_history

    @pytest.mark.asyncio
    async def test_image_media_becomes_context_attachment_and_session_record(
        self, partners_root, fake_orchestrator
    ):
        image_path = partners_root / "image.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        fake_orchestrator.script = _finish("saw it")
        runner = _runner(partners_root)
        msg = _msg("what is in this image?")
        msg.media = [str(image_path)]

        await runner.process_message(msg)

        context = fake_orchestrator.seen_contexts[-1]
        assert len(context.attachments) == 1
        assert context.attachments[0].type == "image"
        assert context.attachments[0].filename == "image.png"
        records = runner.store.messages("telegram:42")
        assert records[0]["attachments"][0]["type"] == "image"
        assert records[0]["attachments"][0]["filename"] == "image.png"

    @pytest.mark.asyncio
    async def test_document_media_becomes_attached_source(self, partners_root, fake_orchestrator):
        doc_path = partners_root / "notes.txt"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("Gradient descent uses a learning rate.", encoding="utf-8")
        fake_orchestrator.script = _finish("noted")
        runner = _runner(partners_root)
        msg = _msg("summarize this")
        msg.media = [str(doc_path)]

        await runner.process_message(msg)

        context = fake_orchestrator.seen_contexts[-1]
        assert "notes.txt" in context.source_manifest
        source_index = context.metadata["source_index"]
        assert len(source_index) == 1
        assert "Gradient descent" in next(iter(source_index.values()))
        records = runner.store.messages("telegram:42")
        attachment = records[0]["attachments"][0]
        assert attachment["filename"] == "notes.txt"
        assert "Gradient descent" in attachment["extracted_text"]


class TestBuiltinToolsAndMemory:
    @pytest.mark.asyncio
    async def test_builtin_tools_default_to_no_gating(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _finish("ok")
        runner = _runner(partners_root)  # builtin_tools=None

        await runner.process_message(_msg())

        context = fake_orchestrator.seen_contexts[0]
        # None = no gating: every built-in mounts under its usual condition.
        assert context.allowed_builtin_tools is None

    @pytest.mark.asyncio
    async def test_builtin_tools_whitelist_flows_to_context(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _finish("ok")
        config = PartnerConfig(name="Ada", builtin_tools=["rag", "web_fetch"])
        runner = _runner(partners_root, config)

        await runner.process_message(_msg())

        context = fake_orchestrator.seen_contexts[0]
        assert context.allowed_builtin_tools == ["rag", "web_fetch"]

    @pytest.mark.asyncio
    async def test_turn_runs_against_partner_memory(self, partners_root, fake_orchestrator):
        """The turn resolves memory to the partner's OWN synthetic workspace, not
        the owner's. The partner_* tools (force-mounted) own the split-memory
        model: partner_read folds in the owner's shared L3 on top, while
        partner_memorize writes only the partner's own scope."""
        from deeptutor.partners.config.paths import get_partner_workspace

        fake_orchestrator.script = _finish("ok")
        runner = _runner(partners_root)

        await runner.process_message(_msg())

        partner_memory = (get_partner_workspace("ada") / "memory").resolve()
        seen = fake_orchestrator.seen_memory_roots[0].resolve()
        assert seen == partner_memory
        assert "partners" in seen.parts  # the partner's own scope, NOT admin

    @pytest.mark.asyncio
    async def test_memory_override_is_reset_after_turn(self, partners_root, fake_orchestrator):
        from deeptutor.services.memory.paths import memory_root

        fake_orchestrator.script = _finish("ok")
        runner = _runner(partners_root)
        before = memory_root()

        await runner.process_message(_msg())

        # The ContextVar override must not leak past the turn.
        assert memory_root() == before

    @pytest.mark.asyncio
    async def test_turn_trace_persisted_for_rehydration(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _narration_round("c1", "let me check") + _finish("4.")
        runner = _runner(partners_root)

        await runner.process_message(_msg("what is 2+2?"))

        records = runner.store.messages("telegram:42")
        assistant = next(r for r in records if r["role"] == "assistant")
        events = assistant.get("events")
        assert events, "assistant turn must persist its trace events"
        # done/session are excluded; the narration + finish content survive.
        assert all(e.get("type") != "done" for e in events)
        assert any(e.get("type") == "content" for e in events)

    @pytest.mark.asyncio
    async def test_session_title_is_first_user_message(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _finish("the answer is 4")
        runner = _runner(partners_root)

        await runner.process_message(_msg("what is two plus two?"))

        session = runner.store.list_sessions()[0]
        assert session["title"] == "what is two plus two?"


class TestSessionStoreOps:
    def test_archive_flag_is_soft_and_reversible(self, partners_root):
        store = PartnerSessionStore(_runner(partners_root).store._dir)
        store.append("web-a", "user", "hi")
        assert store.is_archived("web-a") is False
        store.set_archived("web-a", True)
        assert store.is_archived("web-a") is True
        # File is untouched (still resumable) and excluded from the merged view.
        assert store._path("web-a").exists()
        assert store.merged_messages() == []
        store.set_archived("web-a", False)
        assert store.is_archived("web-a") is False

    def test_branch_copies_history_and_archives_source(self, partners_root):
        store = PartnerSessionStore(_runner(partners_root).store._dir)
        store.append("web-a", "user", "q1")
        store.append("web-a", "assistant", "a1", events=[{"type": "content"}])
        summary = store.branch("web-a", "web-b")
        assert summary is not None and summary["message_count"] == 2
        assert store.is_archived("web-a") is True
        assert [m["content"] for m in store.messages("web-b")] == ["q1", "a1"]
        # Events ride along so the branched copy rehydrates its trace too.
        assert store.messages("web-b")[1].get("events")

    def test_delete_removes_file_and_index(self, partners_root):
        store = PartnerSessionStore(_runner(partners_root).store._dir)
        store.append("web-a", "user", "hi")
        store.set_archived("web-a", True)
        assert store.delete_session("web-a") is True
        assert store.delete_session("web-a") is False
        assert store.list_sessions() == []


class TestLiveTurn:
    def test_buffer_replays_for_late_subscriber(self):
        from deeptutor.services.partners.manager import LiveTurn

        turn = LiveTurn(user_content="q")
        turn.emit({"type": "stream_event", "event": {"i": 1}})
        turn.emit({"type": "stream_event", "event": {"i": 2}})
        # A client that reconnects mid-turn replays the whole backlog...
        late = turn.subscribe()
        assert [late.get_nowait()["event"]["i"] for _ in range(2)] == [1, 2]
        # ...and keeps receiving new frames after subscribing.
        turn.emit({"type": "stream_event", "event": {"i": 3}})
        assert late.get_nowait()["event"]["i"] == 3

    def test_finish_pushes_terminal_and_marks_done(self):
        from deeptutor.services.partners.manager import LiveTurn

        turn = LiveTurn()
        q = turn.subscribe()
        turn.finish([{"type": "content", "content": "hi"}, {"type": "done"}])
        assert turn.done is True
        assert q.get_nowait()["type"] == "content"
        assert q.get_nowait()["type"] == "done"
        # A subscriber arriving after completion still replays the full turn.
        post = turn.subscribe()
        kinds = [post.get_nowait()["type"] for _ in range(post.qsize())]
        assert kinds == ["content", "done"]

    @pytest.mark.asyncio
    async def test_web_turn_runs_on_instance_and_survives_resubscribe(
        self, partners_root, fake_orchestrator
    ):
        from deeptutor.services.partners.manager import PartnerManager

        fake_orchestrator.script = _narration_round("c1", "working") + _finish("done!")
        mgr = PartnerManager()
        mgr.save_config("ada", PartnerConfig(name="Ada"), auto_start=True)
        await mgr.start_partner("ada")
        try:
            turn = mgr.start_web_turn("ada", "web-x", "hello", [])
            queue = turn.subscribe()
            frames: list[dict] = []
            while True:
                frame = await asyncio.wait_for(queue.get(), timeout=5)
                frames.append(frame)
                if frame["type"] in {"done", "stopped"}:
                    break
            assert any(f["type"] == "content" and f["content"] == "done!" for f in frames)
            assert turn.done is True
            # Reconnect after completion → no live turn to attach to (history
            # serves it); a still-running turn would return the LiveTurn.
            assert mgr.subscribe_web_turn("ada", "web-x") is None
            # The completed turn persisted to the session store.
            assert mgr.session_store("ada").messages("web-x")[-1]["content"] == "done!"
        finally:
            await mgr.stop_partner("ada")


class TestPartnerCommands:
    @pytest.mark.asyncio
    async def test_sessions_resume_delete_commands(self, partners_root, fake_orchestrator):
        from deeptutor.services.partners.commands import PartnerCommandHandler

        runner = _runner(partners_root)
        fake_orchestrator.script = _finish("ok")
        await runner.process_message(_msg("hello"))  # creates telegram:42

        handler = PartnerCommandHandler(partner_id="ada", config=runner.config, store=runner.store)
        listed = handler.dispatch(_msg("/sessions"))
        assert listed is not None and "telegram_42" in listed.content

        # /delete an existing key, /resume clears an archived flag.
        runner.store.set_archived("telegram:42", True)
        resumed = handler.dispatch(_msg("/resume telegram:42"))
        assert resumed is not None and not runner.store.is_archived("telegram:42")
        deleted = handler.dispatch(_msg("/delete telegram:42"))
        assert deleted is not None and "Deleted" in deleted.content
        assert handler.dispatch(_msg("/delete telegram:42")).content.startswith("No conversation")

    @pytest.mark.asyncio
    async def test_stop_command_is_a_noop_on_im(self, partners_root, fake_orchestrator):
        from deeptutor.services.partners.commands import PartnerCommandHandler

        runner = _runner(partners_root)
        handler = PartnerCommandHandler(partner_id="ada", config=runner.config, store=runner.store)
        result = handler.dispatch(_msg("/stop"))
        assert result is not None and "nothing" in result.content.lower()

    @pytest.mark.asyncio
    async def test_new_archives_current_session_without_calling_orchestrator(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = _finish("first reply")
        runner = _runner(partners_root)
        await runner.process_message(_msg("first question"))
        assert len(fake_orchestrator.seen_contexts) == 1

        reply = await runner.process_message(_msg("/new"))

        assert "Started a new conversation" in reply
        assert len(fake_orchestrator.seen_contexts) == 1
        assert runner.store.conversation_history("telegram:42") == []
        archived = [session for session in runner.store.list_sessions() if session["archived"]]
        assert len(archived) == 1
        assert archived[0]["message_count"] == 2
        assert archived[0]["session_key"].startswith("_archived_")

    @pytest.mark.asyncio
    async def test_archived_session_does_not_feed_next_turn(self, partners_root, fake_orchestrator):
        runner = _runner(partners_root)
        fake_orchestrator.script = _finish("old reply")
        await runner.process_message(_msg("old question"))
        await runner.process_message(_msg("/new"))

        fake_orchestrator.script = _finish("fresh reply")
        await runner.process_message(_msg("fresh question"))

        context = fake_orchestrator.seen_contexts[-1]
        assert context.conversation_history == []

    @pytest.mark.asyncio
    async def test_telegram_bot_command_suffix_is_supported(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = _finish("first reply")
        runner = _runner(partners_root)
        await runner.process_message(_msg("first question"))

        reply = await runner.process_message(_msg("/new@DeepTutorBot"))

        assert "Started a new conversation" in reply
        assert len(fake_orchestrator.seen_contexts) == 1
