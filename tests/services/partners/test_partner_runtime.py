"""PartnerRunner: chat-loop event mapping, tool config, session persistence."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.partners.bus.events import InboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.services.partners.interaction import session_store_for
from deeptutor.services.partners.manager import PartnerConfig
from deeptutor.services.partners.runtime import PartnerRunner, PartnerTurnOptions
from deeptutor.services.partners.sessions import PartnerSessionStore
from tests.services.partners.scripts import (
    answer_visible_narration,
    event,
    finish,
    narration_round,
)


def _runner(partners_root, config: PartnerConfig | None = None) -> PartnerRunner:
    config = config or PartnerConfig(name="Ada")
    return PartnerRunner("ada", config, MessageBus())


def _shared_store(partner_id: str = "ada") -> PartnerSessionStore:
    """The partner's shared thread pool — where un-attributed turns land."""
    return session_store_for(partner_id, None)


def _msg(content: str = "hello", channel: str = "telegram") -> InboundMessage:
    return InboundMessage(channel=channel, sender_id="42", chat_id="42", content=content)


class TestTurnExecution:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("channel", ["weixin", "telegram"])
    async def test_all_im_channels_mirror_user_trace_and_answer_to_web_activity(
        self, partners_root, fake_orchestrator, channel
    ):
        fake_orchestrator.script = [
            event(
                StreamEventType.TOOL_CALL,
                content="partner_read",
                metadata={"args": {"topic": "profile"}},
            ),
            *finish("I remember."),
        ]
        frames: list[dict[str, Any]] = []

        async def capture(_msg: InboundMessage, frame: dict[str, Any]) -> None:
            frames.append(frame)

        runner = PartnerRunner(
            "ada",
            PartnerConfig(name="Ada"),
            MessageBus(),
            on_channel_activity=capture,
        )

        await runner._handle_inbound(_msg("What do you know about me?", channel=channel))

        assert frames[0]["type"] == "user_echo"
        assert frames[0]["content"] == "What do you know about me?"
        assert frames[0]["channel"] == channel
        assert frames[0]["external"] is True
        assert any(
            frame["type"] == "stream_event" and frame["event"]["type"] == "tool_call"
            for frame in frames
        )
        assert [frame["type"] for frame in frames[-2:]] == ["content", "done"]
        assert frames[-2]["content"] == "I remember."
        assert len({frame["activity_id"] for frame in frames}) == 1

        records = _shared_store().messages(f"{channel}:42")
        assert [record["role"] for record in records] == ["user", "assistant"]
        assert records[0]["metadata"]["activity_id"] == frames[0]["activity_id"]
        assert records[1]["metadata"]["activity_id"] == frames[0]["activity_id"]
        assert any(event["type"] == "tool_call" for event in records[1]["events"])

    @pytest.mark.asyncio
    async def test_returns_finish_text_and_persists_session(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = narration_round("c1", "let me check") + finish(
            "The answer is 4."
        )
        runner = _runner(partners_root)

        final = await runner.process_message(_msg("what is 2+2?"))
        assert final == "The answer is 4."

        history = _shared_store().conversation_history("telegram:42")
        assert history == [
            {"role": "user", "content": "what is 2+2?"},
            {"role": "assistant", "content": "The answer is 4."},
        ]

    @pytest.mark.asyncio
    async def test_a_group_conversation_records_where_it_happened(
        self, partners_root, fake_orchestrator
    ):
        """#1229: one partner serving three subject groups looked like three DMs.

        Feishu states the kind of chat on the inbound event, so the turn that
        is being written is the only moment the origin is known for certain.
        The conversation list reads it back from there.
        """
        fake_orchestrator.script = finish("noted")
        runner = _runner(partners_root)
        group = InboundMessage(
            channel="feishu",
            sender_id="ou_student",
            chat_id="oc_math_group",
            content="老师这题怎么做",
            metadata={"chat_type": "group"},
        )

        await runner.process_message(group)

        summary = next(
            row
            for row in _shared_store().list_sessions()
            if row["session_key"] == "feishu_oc_math_group"
        )
        assert summary["chat_id"] == "oc_math_group"
        assert summary["scope"] == "group"

    @pytest.mark.asyncio
    async def test_a_direct_message_is_marked_as_one(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("noted")
        runner = _runner(partners_root)
        direct = InboundMessage(
            channel="feishu",
            sender_id="ou_parent",
            chat_id="ou_parent",
            content="他最近怎么样",
            metadata={"chat_type": "p2p"},
        )

        await runner.process_message(direct)

        summary = next(
            row
            for row in _shared_store().list_sessions()
            if row["session_key"] == "feishu_ou_parent"
        )
        assert summary["scope"] == "direct"

    @pytest.mark.asyncio
    async def test_a_channel_that_says_nothing_is_left_unlabelled(
        self, partners_root, fake_orchestrator
    ):
        """A conversation list that guesses is worse than one that stays quiet."""
        fake_orchestrator.script = finish("noted")
        runner = _runner(partners_root)

        await runner.process_message(_msg("hello"))

        summary = next(
            row for row in _shared_store().list_sessions() if row["session_key"] == "telegram_42"
        )
        assert summary["chat_id"] == "42"
        assert "scope" not in summary

    @pytest.mark.asyncio
    async def test_narration_streams_as_progress_outbound(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = narration_round("c1", "exploring…") + finish("done")
        runner = _runner(partners_root)

        await runner.process_message(_msg())
        progress = await runner.bus.outbound.get()
        assert progress.content == "exploring…"
        assert progress.metadata["_progress"] is True
        assert progress.metadata["_tool_hint"] is False

    @pytest.mark.asyncio
    async def test_answer_visible_narration_stays_in_reply(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = answer_visible_narration(
            "c1", "Great job on that answer."
        ) + finish("Choose the next topic.")
        runner = _runner(partners_root)

        final = await runner.process_message(_msg())

        assert final == "Great job on that answer.\n\nChoose the next topic."
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_answer_visible_prefix_is_not_duplicated_when_result_is_canonical(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = answer_visible_narration("c1", "Part one. ") + [
            event(StreamEventType.CONTENT, content="Part two.", metadata={"call_id": "c2"}),
            event(
                StreamEventType.PROGRESS,
                metadata={
                    "trace_kind": "call_status",
                    "call_state": "complete",
                    "call_role": "finish",
                    "call_id": "c2",
                },
            ),
            event(
                StreamEventType.RESULT,
                metadata={"response": "Part one. Part two."},
            ),
        ]
        runner = _runner(partners_root)

        final = await runner.process_message(_msg())

        assert final == "Part one. Part two."
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_tool_calls_stream_as_hints_by_default(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = [
            event(
                StreamEventType.TOOL_CALL,
                content="rag",
                metadata={"args": {"query": "hello world", "_internal": "x"}},
            ),
            *finish("done"),
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
        fake_orchestrator.script = narration_round("c1", "exploring…") + finish("done")
        config = PartnerConfig(name="Ada", channels={"telegram": {"send_progress": False}})
        runner = _runner(partners_root, config)

        await runner.process_message(_msg())
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_web_channel_never_emits_progress_outbound(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = narration_round("c1", "exploring…") + finish("done")
        runner = _runner(partners_root)

        await runner.process_message(_msg(channel="web"))
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_group_turn_injects_public_context_without_persisting_private_trace(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = narration_round("private", "private scratch") + finish(
            "public answer"
        )
        runner = _runner(partners_root)
        message = _msg("current question", channel="web_group")
        message.session_key_override = "group-session"

        final = await runner.process_message(
            message,
            options=PartnerTurnOptions(
                conversation_history=[],
                shared_context="Socrates: earlier public answer",
                group_name="Study panel",
                persist=False,
                allow_commands=False,
                capture_events=False,
            ),
        )

        assert final == "public answer"
        context = fake_orchestrator.seen_contexts[0]
        assert context.conversation_history == []
        assert "Socrates: earlier public answer" in context.user_message
        assert "current question" in context.user_message
        assert "respond only as yourself" in context.persona_context.lower()
        assert _shared_store().messages("group-session") == []
        assert runner.bus.outbound.empty()

    @pytest.mark.asyncio
    async def test_group_collaboration_publishes_saved_formal_answer_not_decision_ack(
        self, partners_root, fake_orchestrator, monkeypatch
    ):
        import deeptutor.runtime.orchestrator as orchestrator_module

        seen_contexts = []

        class SavedAnswerOrchestrator:
            async def handle(self, context):
                seen_contexts.append(context)
                context.extension("partner_group")["formal_answer"] = "The formal answer"
                for item in finish("NO_INVOKE"):
                    yield item

        monkeypatch.setattr(orchestrator_module, "ChatOrchestrator", SavedAnswerOrchestrator)
        runner = _runner(partners_root)
        message = _msg("question", channel="web_group")
        message.session_key_override = "group-session"

        final = await runner.process_message(
            message,
            options=PartnerTurnOptions(
                conversation_history=[],
                shared_context="public transcript",
                group_id="panel",
                group_name="Panel",
                group_members=(
                    {"partner_id": "ada", "name": "Ada", "description": "proof specialist"},
                    {
                        "partner_id": "bob",
                        "name": "Bob",
                        "description": "experimental physicist",
                    },
                ),
                allow_invoke_other=True,
                persist=False,
                allow_commands=False,
            ),
        )

        assert final == "The formal answer"
        persona = seen_contexts[0].persona_context
        assert "independent voice in the parallel panel" in persona
        assert "Bob (@bob): experimental physicist" in persona
        assert "instead of restating generic consensus" in persona

    @pytest.mark.asyncio
    async def test_unresolved_ask_user_question_becomes_reply(
        self, partners_root, fake_orchestrator
    ):
        # An unresolved ask_user pause emits the question as a final-response
        # CONTENT event while RESULT carries an empty response.
        fake_orchestrator.script = [
            event(
                StreamEventType.CONTENT,
                content="Which topic do you mean?",
                metadata={"call_id": "f1", "call_kind": "llm_final_response"},
            ),
            event(StreamEventType.RESULT, metadata={"response": ""}),
            event(StreamEventType.DONE),
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
                event(StreamEventType.ERROR, content="rate limited"),
                event(StreamEventType.RESULT, metadata={"response": ""}),
                event(StreamEventType.DONE),
            ],
            # Turn 2 (backup): succeeds.
            finish("backup answer"),
        ]
        config = PartnerConfig(name="Ada", llm_selection=primary, backup_llm_selection=backup)
        runner = _runner(partners_root, config)

        final = await runner.process_message(_msg())
        assert final == "backup answer"
        assert fake_orchestrator.activated_selections == [primary, backup]

    @pytest.mark.asyncio
    async def test_no_backup_returns_error_text(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = [
            event(StreamEventType.ERROR, content="rate limited"),
            event(StreamEventType.RESULT, metadata={"response": ""}),
            event(StreamEventType.DONE),
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
        fake_orchestrator.script = finish("backup answer")
        config = PartnerConfig(name="Ada", llm_selection=primary, backup_llm_selection=backup)
        runner = _runner(partners_root, config)

        final = await runner.process_message(_msg())
        assert final == "backup answer"
        assert attempted == [primary, backup]

    @pytest.mark.asyncio
    async def test_successful_turn_never_touches_backup(self, partners_root, fake_orchestrator):
        backup = {"profile_id": "p2", "model_id": "m2"}
        fake_orchestrator.script = finish("first try works")
        config = PartnerConfig(name="Ada", backup_llm_selection=backup)
        runner = _runner(partners_root, config)

        final = await runner.process_message(_msg())
        assert final == "first try works"
        assert fake_orchestrator.activated_selections == [None]

    @pytest.mark.asyncio
    async def test_inbound_handler_publishes_reply_outbound(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("reply text")
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
        fake_orchestrator.script = finish("ok")
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

        fake_orchestrator.script = finish("ok")
        runner = _runner(partners_root)  # enabled_tools=None

        await runner.process_message(_msg())
        context = fake_orchestrator.seen_contexts[0]
        assert context.enabled_tools == default_optional_tools()
        # MCP is the exception to "default = fully equipped": these tools reach
        # host-side capabilities, so an untouched partner ships an empty filter
        # (deny) rather than no filter (unrestricted).
        assert context.metadata["mcp_tools_filter"] == []

    @staticmethod
    def _write_admin_enabled_tools(partners_root, names: list[str]) -> None:
        """Persist the admin's Settings → Chat → Tools toggles under the
        isolated admin workspace, using the same path the runtime reads."""
        import json

        from deeptutor.multi_user.paths import get_admin_path_service

        path = get_admin_path_service().get_settings_file("interface")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"enabled_optional_tools": names}), encoding="utf-8")

    def test_globally_disabled_tool_dropped_from_explicit_config(self, partners_root):
        # web_search is turned off in Settings → Chat → Tools, so even though
        # the partner config saved it, it must not surface at runtime.
        self._write_admin_enabled_tools(partners_root, ["reason"])
        runner = _runner(
            partners_root,
            PartnerConfig(name="Ada", enabled_tools=["web_search", "reason"]),
        )
        assert runner._resolved_enabled_tools() == ["reason"]

    def test_globally_disabled_tool_dropped_from_default_config(self, partners_root):
        # The default (None = fully equipped) config still bows to the global
        # toggle: only the tools the admin left on survive.
        self._write_admin_enabled_tools(partners_root, ["reason"])
        runner = _runner(partners_root)  # enabled_tools=None
        assert runner._resolved_enabled_tools() == ["reason"]

    def test_missing_admin_settings_fall_open_to_full_set(self, partners_root):
        from deeptutor.agents._shared.tool_composition import default_optional_tools

        # No interface.json → fail-open: the partner's saved selection stands.
        runner = _runner(partners_root, PartnerConfig(name="Ada", enabled_tools=["web_search"]))
        assert runner._resolved_enabled_tools() == ["web_search"]
        assert _runner(partners_root)._resolved_enabled_tools() == default_optional_tools()

    @pytest.mark.asyncio
    async def test_owner_can_opt_partner_into_all_mcp_tools(self, partners_root, fake_orchestrator):
        """``mcp_tools=None`` is still the deliberate unrestricted state: it
        emits no filter, which the chat pipeline reads as no MCP narrowing."""
        fake_orchestrator.script = finish("ok")
        runner = _runner(partners_root, PartnerConfig(name="Ada", mcp_tools=None))

        await runner.process_message(_msg())

        assert "mcp_tools_filter" not in fake_orchestrator.seen_contexts[0].metadata

    @pytest.mark.asyncio
    async def test_history_feeds_next_turn(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("first reply")
        runner = _runner(partners_root)
        await runner.process_message(_msg("first question"))

        fake_orchestrator.script = finish("second reply")
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
        fake_orchestrator.script = finish("saw it")
        runner = _runner(partners_root)
        msg = _msg("what is in this image?")
        msg.media = [str(image_path)]

        await runner.process_message(msg)

        context = fake_orchestrator.seen_contexts[-1]
        assert len(context.attachments) == 1
        assert context.attachments[0].type == "image"
        assert context.attachments[0].filename == "image.png"
        records = _shared_store().messages("telegram:42")
        assert records[0]["attachments"][0]["type"] == "image"
        assert records[0]["attachments"][0]["filename"] == "image.png"

    @pytest.mark.asyncio
    async def test_document_media_becomes_attached_source(self, partners_root, fake_orchestrator):
        doc_path = partners_root / "notes.txt"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("Gradient descent uses a learning rate.", encoding="utf-8")
        fake_orchestrator.script = finish("noted")
        runner = _runner(partners_root)
        msg = _msg("summarize this")
        msg.media = [str(doc_path)]

        await runner.process_message(msg)

        context = fake_orchestrator.seen_contexts[-1]
        assert "notes.txt" in context.source_manifest
        source_index = context.metadata["source_index"]
        assert len(source_index) == 1
        assert "Gradient descent" in next(iter(source_index.values()))
        records = _shared_store().messages("telegram:42")
        attachment = records[0]["attachments"][0]
        assert attachment["filename"] == "notes.txt"
        assert "Gradient descent" in attachment["extracted_text"]


class TestBuiltinToolsAndMemory:
    @pytest.mark.asyncio
    async def test_builtin_tools_default_to_no_gating(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("ok")
        runner = _runner(partners_root)  # builtin_tools=None

        await runner.process_message(_msg())

        context = fake_orchestrator.seen_contexts[0]
        # None = no gating: every built-in mounts under its usual condition.
        assert context.allowed_builtin_tools is None

    @pytest.mark.asyncio
    async def test_builtin_tools_whitelist_flows_to_context(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("ok")
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

        fake_orchestrator.script = finish("ok")
        runner = _runner(partners_root)

        await runner.process_message(_msg())

        partner_memory = (get_partner_workspace("ada") / "memory").resolve()
        seen = fake_orchestrator.seen_memory_roots[0].resolve()
        assert seen == partner_memory
        assert "partners" in seen.parts  # the partner's own scope, NOT admin

    @pytest.mark.asyncio
    async def test_memory_override_is_reset_after_turn(self, partners_root, fake_orchestrator):
        from deeptutor.services.memory.paths import memory_root

        fake_orchestrator.script = finish("ok")
        runner = _runner(partners_root)
        before = memory_root()

        await runner.process_message(_msg())

        # The ContextVar override must not leak past the turn.
        assert memory_root() == before

    @pytest.mark.asyncio
    async def test_authenticated_users_get_isolated_session_history(
        self, partners_root, fake_orchestrator
    ):
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import scope_for_user
        from deeptutor.partners.config.paths import get_partner_user_sessions_dir

        alice = CurrentUser("u_alice", "alice", "user", scope_for_user("u_alice", is_admin=False))
        bob = CurrentUser("u_bob", "bob", "user", scope_for_user("u_bob", is_admin=False))
        fake_orchestrator.script = finish("ok")
        runner = _runner(partners_root)

        first = _msg("alice one")
        first.actor = alice
        second = _msg("bob one")
        second.actor = bob
        third = _msg("alice two")
        third.actor = alice

        await runner.process_message(first)
        await runner.process_message(second)
        await runner.process_message(third)

        assert fake_orchestrator.seen_contexts[0].conversation_history == []
        assert fake_orchestrator.seen_contexts[1].conversation_history == []
        assert fake_orchestrator.seen_contexts[2].conversation_history == [
            {"role": "user", "content": "alice one"},
            {"role": "assistant", "content": "ok"},
        ]
        alice_store = session_store_for("ada", alice)
        bob_store = session_store_for("ada", bob)
        assert [m["content"] for m in alice_store.messages("telegram:42")] == [
            "alice one",
            "ok",
            "alice two",
            "ok",
        ]
        assert [m["content"] for m in bob_store.messages("telegram:42")] == ["bob one", "ok"]
        assert _shared_store().list_sessions() == []

    @pytest.mark.asyncio
    async def test_turn_trace_persisted_for_rehydration(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = narration_round("c1", "let me check") + finish("4.")
        runner = _runner(partners_root)

        await runner.process_message(_msg("what is 2+2?"))

        records = _shared_store().messages("telegram:42")
        assistant = next(r for r in records if r["role"] == "assistant")
        events = assistant.get("events")
        assert events, "assistant turn must persist its trace events"
        # done/session are excluded; the narration + finish content survive.
        assert all(e.get("type") != "done" for e in events)
        assert any(e.get("type") == "content" for e in events)

    @pytest.mark.asyncio
    async def test_session_title_is_first_user_message(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("the answer is 4")
        runner = _runner(partners_root)

        await runner.process_message(_msg("what is two plus two?"))

        session = _shared_store().list_sessions()[0]
        assert session["title"] == "what is two plus two?"


class TestSessionStoreOps:
    def test_archive_flag_is_soft_and_reversible(self, partners_root):
        store = _shared_store()
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
        store = _shared_store()
        store.append("web-a", "user", "q1")
        store.append("web-a", "assistant", "a1", events=[{"type": "content"}])
        summary = store.branch("web-a", "web-b")
        assert summary is not None and summary["message_count"] == 2
        assert store.is_archived("web-a") is True
        assert [m["content"] for m in store.messages("web-b")] == ["q1", "a1"]
        # Events ride along so the branched copy rehydrates its trace too.
        assert store.messages("web-b")[1].get("events")

    def test_delete_removes_file_and_index(self, partners_root):
        store = _shared_store()
        store.append("web-a", "user", "hi")
        store.set_archived("web-a", True)
        assert store.delete_session("web-a") is True
        assert store.delete_session("web-a") is False
        assert store.list_sessions() == []


class TestLiveTurn:
    def test_channel_activity_feed_broadcasts_replays_and_isolates_accounts(self):
        from deeptutor.services.partners.manager import PartnerActivityFeed

        feed = PartnerActivityFeed(max_recent=2)
        first = feed.subscribe("alice")
        second = feed.subscribe("alice")
        owner = feed.subscribe_many(("alice", None))
        outsider = feed.subscribe("bob")
        frame = {
            "type": "user_echo",
            "activity_id": "turn-1",
            "external": True,
        }

        feed.publish("alice", frame)

        assert first.get_nowait() == frame
        assert second.get_nowait() == frame
        assert owner.get_nowait() == frame
        assert outsider.empty()
        late = feed.subscribe("alice")
        assert late.get_nowait() == frame

        feed.unsubscribe("alice", first)
        feed.publish("alice", {**frame, "type": "done"})
        assert first.empty()
        assert second.get_nowait()["type"] == "done"
        assert owner.get_nowait()["type"] == "done"

        shared = {**frame, "activity_id": "turn-2"}
        feed.publish(None, shared)
        assert owner.get_nowait() == shared
        assert second.empty()

    def test_owner_activity_history_can_merge_private_and_unlinked_channel_sessions(
        self, partners_root
    ):
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import scope_for_user, user_context
        from deeptutor.services.partners.manager import PartnerManager

        actor = CurrentUser("owner", "owner", "user", scope_for_user("owner", is_admin=False))
        private = session_store_for("ada", actor)
        shared = session_store_for("ada", None)
        private.append("web-1", "user", "from web")
        shared.append("weixin:42", "user", "from weixin")

        with user_context(actor):
            manager = PartnerManager()
            assert [
                item["content"] for item in manager.get_history("ada", include_shared=False)
            ] == ["from web"]
            assert {
                item["content"] for item in manager.get_history("ada", include_shared=True)
            } == {"from web", "from weixin"}

    @pytest.mark.asyncio
    async def test_group_boundary_returns_trace_and_invocation_metadata(
        self, partners_root, fake_orchestrator, monkeypatch
    ):
        from deeptutor.capabilities.partner_group import PartnerGroupCapability
        from deeptutor.capabilities.partner_group.tools import InvokeOtherTool
        import deeptutor.runtime.orchestrator as orchestrator_module
        from deeptutor.services.partners.manager import PartnerManager

        proposal = {
            "target_partner_id": "bob",
            "target_partner_name": "Bob",
            "question": "Which premise should we test?",
        }
        seen_contexts = []

        class CollaborationProtocolOrchestrator:
            async def handle(self, context):
                seen_contexts.append(context)
                capability = PartnerGroupCapability()
                instruction = capability.finish_instruction(context, "Formal answer")
                assert "invoke_other" in instruction
                kwargs = capability.augment_kwargs(
                    "invoke_other",
                    {
                        "target_partner_id": "bob",
                        "question": proposal["question"],
                    },
                    context,
                )
                result = await InvokeOtherTool().execute(**kwargs)
                yield event(
                    StreamEventType.TOOL_RESULT,
                    content=result.content,
                    metadata={"tool_metadata": result.metadata},
                )
                for item in finish("proposal recorded"):
                    yield item

        monkeypatch.setattr(
            orchestrator_module,
            "ChatOrchestrator",
            CollaborationProtocolOrchestrator,
        )
        manager = PartnerManager()
        manager.save_config("ada", PartnerConfig(name="Ada"), auto_start=True)
        await manager.start_partner("ada")
        observed: list[StreamEvent] = []

        async def on_event(item: StreamEvent) -> None:
            observed.append(item)

        try:
            result = await manager.send_group_message(
                "ada",
                "Question",
                session_key="group-panel-session",
                group_id="panel",
                group_name="Panel",
                group_members=[
                    {"partner_id": "ada", "name": "Ada"},
                    {"partner_id": "bob", "name": "Bob"},
                ],
                public_context="Bob: earlier answer",
                actor=None,
                on_event=on_event,
            )
        finally:
            await manager.stop_partner("ada")

        assert result.content == "Formal answer"
        assert result.invocation == proposal
        assert [item["type"] for item in result.events] == [
            "tool_result",
            "content",
            "result",
        ]
        assert any(item.type == StreamEventType.TOOL_RESULT for item in observed)
        context = seen_contexts[0]
        assert context.metadata["partner_group"]["allow_invoke_other"] is True
        assert context.metadata["partner_group"]["members"][1]["partner_id"] == "bob"

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

        fake_orchestrator.script = narration_round("c1", "working") + finish("done!")
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

    @pytest.mark.asyncio
    async def test_manager_captures_authenticated_actor_for_private_history(
        self, partners_root, fake_orchestrator
    ):
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import scope_for_user, user_context
        from deeptutor.partners.config.paths import get_partner_user_sessions_dir
        from deeptutor.services.partners.manager import PartnerManager

        fake_orchestrator.script = finish("private reply")
        mgr = PartnerManager()
        mgr.save_config("ada", PartnerConfig(name="Ada"), auto_start=True)
        await mgr.start_partner("ada")
        actor = CurrentUser("u_alice", "alice", "user", scope_for_user("u_alice", is_admin=False))
        try:
            with user_context(actor):
                assert await mgr.send_message("ada", "private question") == "private reply"
            private = session_store_for("ada", actor)
            assert [item["content"] for item in private.merged_messages()] == [
                "private question",
                "private reply",
            ]
            assert mgr.session_store("ada").list_sessions() == []
        finally:
            await mgr.stop_partner("ada")


class TestPartnerCommands:
    @pytest.mark.asyncio
    async def test_sessions_resume_delete_commands(self, partners_root, fake_orchestrator):
        from deeptutor.services.partners.commands import PartnerCommandHandler

        runner = _runner(partners_root)
        fake_orchestrator.script = finish("ok")
        await runner.process_message(_msg("hello"))  # creates telegram:42

        handler = PartnerCommandHandler(
            partner_id="ada", config=runner.config, store=_shared_store()
        )
        listed = handler.dispatch(_msg("/sessions"))
        assert listed is not None and "telegram_42" in listed.content

        # /delete an existing key, /resume clears an archived flag.
        _shared_store().set_archived("telegram:42", True)
        resumed = handler.dispatch(_msg("/resume telegram:42"))
        assert resumed is not None and not _shared_store().is_archived("telegram:42")
        deleted = handler.dispatch(_msg("/delete telegram:42"))
        assert deleted is not None and "Deleted" in deleted.content
        assert handler.dispatch(_msg("/delete telegram:42")).content.startswith("No conversation")

    @pytest.mark.asyncio
    async def test_stop_command_is_a_noop_on_im(self, partners_root, fake_orchestrator):
        from deeptutor.services.partners.commands import PartnerCommandHandler

        runner = _runner(partners_root)
        handler = PartnerCommandHandler(
            partner_id="ada", config=runner.config, store=_shared_store()
        )
        result = handler.dispatch(_msg("/stop"))
        assert result is not None and "nothing" in result.content.lower()

    @pytest.mark.asyncio
    async def test_new_archives_current_session_without_calling_orchestrator(
        self, partners_root, fake_orchestrator
    ):
        fake_orchestrator.script = finish("first reply")
        runner = _runner(partners_root)
        await runner.process_message(_msg("first question"))
        assert len(fake_orchestrator.seen_contexts) == 1

        reply = await runner.process_message(_msg("/new"))

        assert "Started a new conversation" in reply
        assert len(fake_orchestrator.seen_contexts) == 1
        assert _shared_store().conversation_history("telegram:42") == []
        archived = [session for session in _shared_store().list_sessions() if session["archived"]]
        assert len(archived) == 1
        assert archived[0]["message_count"] == 2
        assert archived[0]["session_key"].startswith("_archived_")

    @pytest.mark.asyncio
    async def test_archived_session_does_not_feed_next_turn(self, partners_root, fake_orchestrator):
        runner = _runner(partners_root)
        fake_orchestrator.script = finish("old reply")
        await runner.process_message(_msg("old question"))
        await runner.process_message(_msg("/new"))

        fake_orchestrator.script = finish("fresh reply")
        await runner.process_message(_msg("fresh question"))

        context = fake_orchestrator.seen_contexts[-1]
        assert context.conversation_history == []

    @pytest.mark.asyncio
    async def test_telegram_bot_command_suffix_is_supported(self, partners_root, fake_orchestrator):
        fake_orchestrator.script = finish("first reply")
        runner = _runner(partners_root)
        await runner.process_message(_msg("first question"))

        reply = await runner.process_message(_msg("/new@DeepTutorBot"))

        assert "Started a new conversation" in reply
        assert len(fake_orchestrator.seen_contexts) == 1
