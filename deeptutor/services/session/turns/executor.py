"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from contextvars import Token
import logging
from typing import TYPE_CHECKING, Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.artifact_attachments import (
    artifact_attachments,
    fill_preview_text,
)
from deeptutor.services.session.provider_response_state import (
    normalize_provider_response_state,
)
from deeptutor.services.session.workspace_preferences import (
    WORKSPACE_MODE_MASTERY,
    WORKSPACE_MODE_READING,
)

from .._turn_runtime_shared import (
    _assemble_persisted_answer,
    _build_question_bank_context,
    _clip_text,
    _count_branch_user_turns,
    _extract_followup_question_context,
    _extract_memory_references,
    _extract_selection_tutor_context,
    _format_followup_question_context,
    _format_selection_tutor_context,
    _mastery_action_context,
    _mastery_path_id,
    _narration_marker_call_id,
    _partner_group_references,
    _reading_action_context,
    _reading_material_id,
    _reading_material_revision,
    _reading_references,
    _reading_viewport,
    _reading_workspace_id,
    _repair_chinese_emphasis_for_persistence,
    _request_snapshot_metadata,
    _resolve_selection_tutor_context,
    _resolve_turn_outcome,
    _should_capture_assistant_content,
    _stamp_ask_user_content_offset,
    _timed_media_id,
    _timed_media_viewport,
    _topic_material_manifest,
    _TurnExecution,
    _workspace_mode,
)

if TYPE_CHECKING:
    from deeptutor.runtime.coordination import RuntimeCoordinator
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.session.protocol import SessionStoreProtocol

logger = logging.getLogger(__name__)


class TurnExecutor:
    if TYPE_CHECKING:
        store: SessionStoreProtocol
        coordinator: RuntimeCoordinator | None
        turn_engine: Any
        _lock: asyncio.Lock
        _executions: dict[str, _TurnExecution]
        _reply_queues: dict[str, asyncio.Queue[dict[str, Any] | None]]

        def _create_context_builder(self) -> Any: ...

        async def _publish_live_event(
            self,
            execution: _TurnExecution,
            event: StreamEvent,
        ) -> dict[str, Any]: ...

        async def _publish_mastery_path_change(
            self,
            execution: _TurnExecution,
            *,
            capability_name: str,
            started_on: str,
            ended_on: str,
            mastery_mode: bool = False,
        ) -> None: ...

        async def _flush_buffered_events(self, execution: _TurnExecution) -> None: ...

        async def _transition_execution(
            self,
            execution: _TurnExecution,
            status: str,
            error: str = "",
            *,
            failure_code: str = "",
            retryable: bool = False,
        ) -> bool: ...

        async def _maybe_generate_session_title(
            self,
            *,
            execution: _TurnExecution,
            session_id: str,
            ui_language: str,
        ) -> None: ...

    async def _run_turn(self, execution: _TurnExecution) -> None:
        payload = execution.payload
        session_id = execution.session_id
        capability_name = execution.capability
        workspace_mode = _workspace_mode(payload.get("workspace_mode"), capability=capability_name)
        mastery_lease_managed = bool(payload.get("mastery_path_lease_managed"))
        turn_id = execution.turn_id
        attachments = []
        attachment_records = []
        assistant_events: list[dict[str, Any]] = []
        assistant_content = ""
        provider_response_state: dict[str, Any] | None = None
        # Per-round content segments + narration call_ids: a chat-loop round's
        # text is captured live but a round that resolves as narration is
        # dropped from the persisted answer (mirrors the frontend bubble).
        content_segments: list[tuple[str | None, str]] = []
        narration_call_ids: set[str] = set()

        def _persisted_answer() -> str:
            # clean_thinking_tags is a second line of defence: providers that
            # inline <think> in the content channel are split at streaming
            # time by the agent loop, but anything that slips through must
            # never be persisted as the user-facing answer.
            return _assemble_persisted_answer(content_segments, narration_call_ids)

        # Files the model generated this turn (exec/code_execution artifacts),
        # persisted as assistant-message attachments so the UI shows openable
        # cards. Deduped by URL across the turn's SOURCES events.
        generated_attachments: list[dict[str, Any]] = []
        seen_artifact_urls: set[str] = set()
        stream_done_sent = False
        llm_scope_token: Token[LLMConfig | None] | None = None
        reset_active_llm_selection: Callable[[Token[LLMConfig | None] | None], None] | None = None
        # One queue per turn for ``ask_user`` style pause-resume.
        # Created here (BEFORE the orchestrator runs) so the pipeline can
        # await on the awaitable we publish into ``context.metadata``.
        # Cleaned up unconditionally in the outer ``finally``.
        reply_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._reply_queues[turn_id] = reply_queue

        async def _wait_for_user_reply() -> dict[str, Any] | None:
            # Publish the pause so a turn that wants the same mastery path can
            # tell "busy generating" apart from "parked, learner walked away".
            entered_waiting = await self.store.transition_turn(
                execution.turn_id,
                "waiting_input",
                expected_status="running",
                fencing_token=(
                    execution.lease.fencing_token if execution.lease is not None else None
                ),
            )
            if not entered_waiting:
                execution.lease_lost = self.coordinator is not None
                raise asyncio.CancelledError
            execution.awaiting_user_reply = True
            try:
                return await reply_queue.get()
            finally:
                execution.awaiting_user_reply = False
                # Restore the active execution state before the loop resumes or
                # the outer cancellation handler performs its terminal CAS.
                # A stale fencing token is rejected by the repository.
                with contextlib.suppress(Exception):
                    await asyncio.shield(
                        self.store.transition_turn(
                            execution.turn_id,
                            "running",
                            expected_status="waiting_input",
                            fencing_token=(
                                execution.lease.fencing_token
                                if execution.lease is not None
                                else None
                            ),
                        )
                    )

        try:
            from deeptutor.agents.notebook import NotebookAnalysisAgent
            from deeptutor.book.context import build_book_context
            from deeptutor.core.context import Attachment, TurnRuntimeContext, UnifiedContext
            from deeptutor.services.memory import get_memory_store
            from deeptutor.services.model_selection.runtime import (
                activate_llm_selection,
            )
            from deeptutor.services.model_selection.runtime import (
                reset_llm_selection as reset_active_llm_selection,
            )
            from deeptutor.services.notebook import get_notebook_manager
            from deeptutor.services.skill import get_skill_service

            request_config = dict(payload.get("config", {}) or {})
            followup_question_context = _extract_followup_question_context(
                {"followup_question_context": payload.get("followup_question_context")}
            )
            selection_tutor_context = _extract_selection_tutor_context(
                {"selection_tutor_context": payload.get("selection_tutor_context")}
            )
            if selection_tutor_context:
                selection_tutor_context = await _resolve_selection_tutor_context(
                    self.store,
                    selection_tutor_context,
                )
            persist_user_message = bool(payload.get("persist_user_message", True))
            is_regenerate = bool(payload.get("regenerate", False))
            raw_user_content = str(payload.get("content", "") or "")
            # Edit-branching tip: when the FE includes ``parent_message_id``
            # (even as ``null``), the new user message attaches at that
            # exact parent — creating a sibling of any existing children
            # and forcing LLM context to come from that parent's ancestor
            # chain only. When the key is absent (legacy callers), the
            # store auto-appends to the latest message in the session.
            branch_parent_explicit = "parent_message_id" in payload
            branch_parent_raw = payload.get("parent_message_id")
            branch_parent_id: int | None
            if branch_parent_explicit:
                try:
                    branch_parent_id = (
                        int(branch_parent_raw) if branch_parent_raw is not None else None
                    )
                except (TypeError, ValueError):
                    branch_parent_id = None
                    branch_parent_explicit = False
            else:
                branch_parent_id = None
            notebook_references = payload.get("notebook_references", []) or []
            history_references = payload.get("history_references", []) or []
            partner_group_references = _partner_group_references(
                payload.get("partner_group_references")
            )
            question_notebook_references = payload.get("question_notebook_references", []) or []
            book_context_result = build_book_context(payload.get("book_references", []) or [])
            book_references = book_context_result.references
            reading_references = _reading_references(payload.get("reading_references"))
            memory_references = _extract_memory_references(payload)
            notebook_context = ""
            history_context = ""
            question_bank_context = ""
            book_context = book_context_result.text

            import base64 as _b64
            import uuid as _uuid

            from deeptutor.services.storage import get_attachment_store

            for item in payload.get("attachments", []):
                record = {
                    "type": item.get("type", "file"),
                    "url": item.get("url", ""),
                    "base64": item.get("base64", ""),
                    "filename": item.get("filename", ""),
                    "mime_type": item.get("mime_type", ""),
                    "id": item.get("id", "") or _uuid.uuid4().hex[:12],
                }
                attachment_records.append(record)

            # Persist original bytes to the attachment store before extraction
            # so the frontend preview drawer can fetch the file later. The
            # extractor will clear base64 on documents to keep DB rows lean,
            # but the URL we record here outlives that pruning. Upload errors
            # are non-fatal — extraction still runs from the in-memory base64.
            attachment_store = get_attachment_store()
            for record in attachment_records:
                if record.get("url"):
                    continue  # already hosted (e.g. legacy URL)
                b64 = record.get("base64") or ""
                if not b64:
                    continue
                try:
                    raw_bytes = _b64.b64decode(b64, validate=False)
                except Exception as exc:
                    logger.warning(
                        "skipping attachment upload for %r: invalid base64 (%s)",
                        record.get("filename"),
                        exc,
                    )
                    continue
                try:
                    record["url"] = await attachment_store.put(
                        session_id=session_id,
                        attachment_id=record["id"],
                        filename=record.get("filename", "") or "file",
                        data=raw_bytes,
                        mime_type=record.get("mime_type", "") or "",
                    )
                except Exception as exc:
                    logger.warning(
                        "attachment store rejected %r: %s",
                        record.get("filename"),
                        exc,
                    )

            from deeptutor.utils.document_extractor import extract_documents_from_records

            document_texts, attachment_records = extract_documents_from_records(attachment_records)
            attachments = [
                Attachment(
                    type=r.get("type", "file"),
                    url=r.get("url", ""),
                    base64=r.get("base64", ""),
                    filename=r.get("filename", ""),
                    mime_type=r.get("mime_type", ""),
                    id=r.get("id", ""),
                    extracted_text=r.get("extracted_text", ""),
                )
                for r in attachment_records
            ]
            # DB persistence copy: drop base64 unconditionally now that the
            # original bytes live in the attachment store. Image attachments
            # used to keep base64 here (which bloated message rows); the URL
            # is now the stable source for previews.
            persisted_attachment_records = [
                {
                    **{k: v for k, v in r.items() if k != "base64"},
                    "base64": "",
                }
                for r in attachment_records
            ]

            sidebar_system_context = ""
            if selection_tutor_context:
                sidebar_system_context = _format_selection_tutor_context(
                    selection_tutor_context,
                    language=str(payload.get("language", "en") or "en"),
                )

            # Quiz follow-up context is part of the child session's durable
            # history and is inserted exactly once. Selection tutoring is
            # intentionally different: its source passage remains a per-turn
            # sidebar context and must not be copied into chat history.
            if followup_question_context:
                existing_messages = await self.store.get_messages_for_context(
                    session_id, leaf_message_id=branch_parent_id
                )
                if not existing_messages:
                    await self.store.add_message(
                        session_id=session_id,
                        role="system",
                        content=_format_followup_question_context(
                            followup_question_context,
                            language=str(payload.get("language", "en") or "en"),
                        ),
                        capability=capability_name or "chat",
                    )

            llm_config, llm_scope_token = activate_llm_selection(payload.get("llm_selection"))
            builder = self._create_context_builder()

            async def _emit_context_event(event: StreamEvent) -> None:
                if event.source in {"context", "context_builder"}:
                    return
                await self._publish_live_event(execution, event)

            history_result = await builder.build(
                session_id=session_id,
                llm_config=llm_config,
                language=payload.get("language", "en"),
                on_event=_emit_context_event,
                leaf_message_id=branch_parent_id,
            )
            memory_store = get_memory_store()
            memory_context = memory_store.read_l3_concat() if memory_references else ""

            # Persona: at most one behaviour preset per turn, eagerly
            # injected (a persona must shape the voice from the first
            # token). Resolution: the user's own workspace first; non-admin
            # users fall back to admin-authored presets (personas carry no
            # privileged workflow, so no grant gate applies).
            from deeptutor.multi_user.context import get_current_user
            from deeptutor.multi_user.paths import get_admin_path_service
            from deeptutor.multi_user.skill_access import assigned_skill_ids
            from deeptutor.services.persona import PersonaService, get_persona_service
            from deeptutor.services.skill.service import SkillService, render_skills_manifest

            current_user = get_current_user()
            learner_profile_prompt = ""
            if not current_user.is_admin:
                from deeptutor.multi_user.identity import get_user_by_id
                from deeptutor.multi_user.learner_profile import prompt_block

                account = get_user_by_id(current_user.id)
                if account and str(account[1].get("preset") or "standard") == "learner":
                    learner_profile_prompt = prompt_block(account[1].get("learner_profile"))
            requested_persona = str(payload.get("persona") or "").strip()
            persona_context = ""
            if requested_persona:
                persona_context = get_persona_service().load_for_context(requested_persona)
                if not persona_context and not current_user.is_admin:
                    persona_context = PersonaService(
                        root=get_admin_path_service().get_workspace_dir() / "personas"
                    ).load_for_context(requested_persona)
            active_persona = requested_persona if persona_context else ""

            # Skills: never user-selected per turn. The model sees a
            # one-line manifest of every skill visible to this user (own +
            # builtin, plus admin-assigned for non-admin users) and pulls
            # full content on demand via ``read_skill``. ``always`` skills
            # are the exception — their bodies are injected eagerly.
            user_skill_service = get_skill_service()
            skill_entries = user_skill_service.summary_entries()
            always_blocks = [user_skill_service.load_always_for_context()]
            if not current_user.is_admin:
                assigned_service = SkillService(
                    root=get_admin_path_service().get_workspace_dir() / "skills",
                    builtin_root=None,
                )
                allowed_skills = assigned_skill_ids(current_user.id)
                assigned_entries = [
                    e for e in assigned_service.summary_entries() if e.name in allowed_skills
                ]
                skill_entries = skill_entries + assigned_entries
                always_blocks.append(
                    assigned_service.load_for_context(
                        [e.name for e in assigned_entries if e.always and e.available]
                    )
                )
            skills_manifest = "\n\n".join(
                part for part in (*always_blocks, render_skills_manifest(skill_entries)) if part
            )

            # Chat capability uses the lightweight manifest + read_source
            # affordance (no upstream LLM call, no wholesale-dump into the
            # user message). All other capabilities keep the legacy concat
            # path because their internal pipelines consume the named blocks
            # (``[Notebook Context]`` etc.) directly.
            is_chat_capability = (capability_name or "") in {"", "chat"}

            source_manifest_text = ""
            source_index: dict[str, str] = {}

            if is_chat_capability:
                from deeptutor.services.session.source_inventory import (
                    build_inventory,
                    render_manifest,
                )

                resolved_notebook_records = (
                    get_notebook_manager().get_records_by_references(notebook_references)
                    if notebook_references
                    else []
                )
                # Current turn ordinal = (#user messages on this branch's
                # ancestor chain) + 1. ``_count_branch_user_turns`` walks
                # the same lineage the inventory builder uses, so we agree
                # on what "turn N" means for the historical labels.
                current_turn_ordinal = (
                    await _count_branch_user_turns(self.store, session_id, branch_parent_id) + 1
                )
                inventory = await build_inventory(
                    self.store,
                    session_id=session_id,
                    leaf_message_id=branch_parent_id,
                    current_turn_ordinal=current_turn_ordinal,
                    fresh_attachment_records=attachment_records,
                    fresh_notebook_records=resolved_notebook_records,
                    fresh_book_context_text=book_context,
                    fresh_book_references=book_references,
                    fresh_history_session_ids=history_references,
                    fresh_question_entry_ids=question_notebook_references,
                    fresh_partner_group_references=partner_group_references,
                    fresh_reading_references=reading_references,
                    language=str(payload.get("language", "en") or "en"),
                )
                source_manifest_text, source_index = render_manifest(inventory)
                effective_user_message = raw_user_content
            else:
                if notebook_references:
                    referenced_records = get_notebook_manager().get_records_by_references(
                        notebook_references
                    )
                    if referenced_records:
                        analysis_agent = NotebookAnalysisAgent(
                            language=str(payload.get("language", "en") or "en")
                        )
                        notebook_context = await analysis_agent.analyze(
                            user_question=raw_user_content,
                            records=referenced_records,
                            emit=_emit_context_event,
                        )

                if history_references:
                    from deeptutor.services.session.source_inventory import (
                        serialize_referenced_transcript,
                    )

                    history_records: list[dict[str, Any]] = []
                    for session_ref in history_references:
                        history_session_id = str(session_ref or "").strip()
                        if not history_session_id:
                            continue

                        history_session = await self.store.get_session(history_session_id)
                        if not history_session:
                            continue

                        history_messages = await self.store.get_messages_for_context(
                            history_session_id
                        )
                        transcript = serialize_referenced_transcript(
                            history_session,
                            history_messages,
                            language=str(payload.get("language", "en") or "en"),
                        )
                        if not transcript:
                            continue

                        history_summary = str(
                            history_session.get("compressed_summary", "") or ""
                        ).strip()
                        if not history_summary:
                            history_summary = _clip_text(
                                " ".join(
                                    str(message.get("content", "") or "").strip()
                                    for message in history_messages[-4:]
                                    if str(message.get("content", "") or "").strip()
                                ),
                                limit=400,
                            )
                        if not history_summary:
                            history_summary = f"{len(history_messages)} messages"

                        history_records.append(
                            {
                                "id": history_session_id,
                                "notebook_id": "__history__",
                                "notebook_name": "History",
                                "title": str(
                                    history_session.get("title", "") or "Untitled session"
                                ),
                                "summary": history_summary,
                                "output": transcript,
                                "metadata": {
                                    "session_id": history_session_id,
                                    "source": "history",
                                },
                            }
                        )

                    if history_records:
                        analysis_agent = NotebookAnalysisAgent(
                            language=str(payload.get("language", "en") or "en")
                        )
                        history_context = await analysis_agent.analyze(
                            user_question=raw_user_content,
                            records=history_records,
                            emit=_emit_context_event,
                        )
                        if not history_context.strip():
                            MAX_FALLBACK_CHARS = 8000
                            parts: list[str] = []
                            total = 0
                            for record in history_records:
                                output = record.get("output")
                                if not output:
                                    continue
                                part = f"## Session: {record.get('title', 'Untitled')}\n{output}"
                                if total + len(part) > MAX_FALLBACK_CHARS:
                                    remaining = MAX_FALLBACK_CHARS - total
                                    if remaining > 100:
                                        parts.append(part[:remaining] + "\n...(truncated)")
                                    break
                                parts.append(part)
                                total += len(part)
                            history_context = "\n\n".join(parts)

                if question_notebook_references:
                    question_bank_context = await _build_question_bank_context(
                        self.store, question_notebook_references
                    )

                effective_user_message = raw_user_content
                context_parts: list[str] = []
                if document_texts:
                    context_parts.append("[Attached Documents]\n" + "\n\n".join(document_texts))
                if book_context:
                    context_parts.append(f"[Book Context]\n{book_context}")
                if notebook_context:
                    context_parts.append(f"[Notebook Context]\n{notebook_context}")
                if history_context:
                    context_parts.append(f"[History Context]\n{history_context}")
                if question_bank_context:
                    context_parts.append(f"[Question Bank Context]\n{question_bank_context}")
                if context_parts:
                    context_parts.append(f"[User Question]\n{raw_user_content}")
                    effective_user_message = "\n\n".join(context_parts)

            # A mastery topic carries materials the learner chose once, in the
            # create-topic wizard. They grounded the outline and were then never
            # seen again: the tutor taught the learner's own book from parametric
            # memory while its prompt claimed to teach *from* it.
            #
            # Deliberately NOT fed into ``source_index``: that key is what wakes
            # the explore_context pre-pass, which forces a bounded "read
            # everything relevant" investigation before the tutor's first LLM
            # call — the right posture for chat, wrong for tutoring, where the
            # model should decide for itself, turn by turn, whether a knowledge
            # point needs the source text at all. Mastery instead gets its own
            # index (``mastery_topic_source_index``) that only
            # ``MasteryLoopCapability`` wires to ``read_source``, so the manifest
            # (rendered into ``context.source_manifest`` below) is the only thing
            # every turn pays for; reading a material is the tutor's own call.
            #
            # Guarded on an empty chat-path index so materials the learner
            # attached to *this turn* (which took the chat path above) always win.
            mastery_topic_source_index: dict[str, str] = {}
            if workspace_mode == WORKSPACE_MODE_MASTERY and not source_index:
                topic_path_id = _mastery_path_id(payload.get("mastery_path_id"))
                if topic_path_id:
                    source_manifest_text, mastery_topic_source_index = await asyncio.to_thread(
                        _topic_material_manifest, topic_path_id
                    )

            # Agentic actions receive workspace behavior through loop
            # capabilities and tools. Standalone pipelines (Quiz, Research,
            # Visualize) cannot call those hooks, so give them a bounded,
            # explicit snapshot of the same workspace instead.
            if not is_chat_capability and capability_name not in {
                "ask_questions",
                "deep_solve",
                "immersive_reading",
                "mastery_path",
                "course_study",
            }:
                workspace_context = ""
                if workspace_mode == WORKSPACE_MODE_READING:
                    workspace_context = await asyncio.to_thread(
                        _reading_action_context,
                        _reading_material_id(payload.get("reading_material_id")),
                        _reading_viewport(payload.get("reading_viewport")),
                        raw_user_content,
                    )
                elif workspace_mode == WORKSPACE_MODE_MASTERY:
                    workspace_context = await asyncio.to_thread(
                        _mastery_action_context,
                        _mastery_path_id(payload.get("mastery_path_id")),
                        source_manifest_text,
                        mastery_topic_source_index,
                    )
                if workspace_context:
                    effective_user_message = (
                        f"[Workspace Context]\n{workspace_context}\n\n"
                        f"[User Question]\n{effective_user_message}"
                    )

            conversation_history = list(history_result.conversation_history)
            conversation_context_text = history_result.context_text

            # SQLite returns integer rowids; PocketBase returns its string
            # record ids. Both are opaque to this layer — they only flow into
            # ``parent_message_id`` chaining and the DONE reconcile metadata.
            new_user_message_id: int | str | None = None
            if persist_user_message:
                # Pass parent explicitly only when the FE pinned it (covers
                # both branched edits with a positive id and root edits
                # with explicit null). Otherwise let the store auto-append.
                parent_kwargs: dict[str, Any] = (
                    {"parent_message_id": branch_parent_id} if branch_parent_explicit else {}
                )
                new_user_message_id = await self.store.add_message(
                    session_id=session_id,
                    role="user",
                    content=raw_user_content,
                    capability=capability_name,
                    attachments=persisted_attachment_records,
                    metadata=_request_snapshot_metadata(
                        payload=payload,
                        content=raw_user_content,
                        capability=capability_name,
                        config=request_config,
                        attachments=persisted_attachment_records,
                        notebook_references=notebook_references,
                        history_references=history_references,
                        partner_group_references=partner_group_references,
                        question_notebook_references=question_notebook_references,
                        book_references=book_references,
                        reading_references=reading_references,
                        persona=active_persona,
                        memory_references=memory_references,
                        llm_selection=payload.get("llm_selection"),
                    ),
                    **parent_kwargs,
                )

            context = UnifiedContext(
                session_id=session_id,
                user_message=effective_user_message,
                conversation_history=conversation_history,
                enabled_tools=payload.get("tools"),
                # Selected-text tutoring must stay isolated from global
                # memory and every other auto-mounted built-in.
                allowed_builtin_tools=[] if selection_tutor_context else None,
                active_capability=payload.get("capability"),
                knowledge_bases=payload.get("knowledge_bases", []),
                attachments=attachments,
                config_overrides=request_config,
                language=payload.get("language", "en"),
                memory_context=memory_context,
                persona_context=persona_context,
                sidebar_context=sidebar_system_context,
                skills_manifest=skills_manifest,
                source_manifest=source_manifest_text,
                runtime=TurnRuntimeContext(
                    turn_id=turn_id,
                    wait_for_user_reply=_wait_for_user_reply,
                    subagent_consult_budget=payload.get("subagent_consult_budget"),
                ),
                metadata={
                    "conversation_summary": history_result.conversation_summary,
                    "conversation_context_text": conversation_context_text,
                    "history_token_count": history_result.token_count,
                    "history_budget": history_result.budget,
                    "turn_id": turn_id,
                    "question_followup_context": followup_question_context or {},
                    "selection_tutor_context": selection_tutor_context or {},
                    "notebook_references": notebook_references,
                    "history_references": history_references,
                    "partner_group_references": partner_group_references,
                    "question_notebook_references": question_notebook_references,
                    "book_references": book_references,
                    "course_id": str(payload.get("course_id") or ""),
                    "course_conventions": str(payload.get("course_conventions") or ""),
                    "reading_references": reading_references,
                    "learner_profile_prompt": learner_profile_prompt,
                    "mastery_path_id": _mastery_path_id(payload.get("mastery_path_id")),
                    "mastery_mode": workspace_mode == WORKSPACE_MODE_MASTERY,
                    "mastery_path_lease_managed": mastery_lease_managed,
                    # Immersive reading: the open material activates the reading
                    # capability and binds its tools; the viewport tells the
                    # model where the user is actually looking.
                    "reading_material_id": _reading_material_id(payload.get("reading_material_id")),
                    "reading_material_revision": _reading_material_revision(
                        payload.get("reading_material_revision")
                    ),
                    "reading_workspace_id": _reading_workspace_id(
                        payload.get("reading_workspace_id")
                    ),
                    "immersive_reading_mode": workspace_mode == WORKSPACE_MODE_READING,
                    "reading_viewport": _reading_viewport(payload.get("reading_viewport")),
                    "timed_media_id": _timed_media_id(payload.get("timed_media_id")),
                    "timed_media_viewport": _timed_media_viewport(
                        payload.get("timed_media_viewport")
                    ),
                    "book_context": book_context,
                    "book_context_warnings": book_context_result.warnings,
                    "memory_references": memory_references,
                    "question_bank_context": question_bank_context,
                    "memory_context": memory_context,
                    "active_persona": active_persona,
                    "llm_selection": payload.get("llm_selection") or {},
                    "llm_model": str(getattr(llm_config, "model", "") or ""),
                    "llm_provider": str(getattr(llm_config, "provider_name", "") or ""),
                    "llm_reasoning_effort": str(getattr(llm_config, "reasoning_effort", "") or ""),
                    "capability_route": payload.get("capability_route"),
                    # Per-turn full-text payload for read_source. Empty when
                    # the manifest is empty (non-chat capabilities, or chat
                    # turns with no attached sources). Consumed by the chat
                    # pipeline's tool kwargs injector, and — a non-empty value
                    # here specifically — by the explore_context pre-pass.
                    "source_index": source_index,
                    # A mastery topic's materials, read on demand by the
                    # tutor's own read_source calls (see
                    # ``MasteryLoopCapability.augment_kwargs``). Kept separate
                    # from ``source_index`` so topic materials never trigger
                    # explore_context's forced pre-pass.
                    "mastery_topic_source_index": mastery_topic_source_index,
                },
            )

            pending_done_event: StreamEvent | None = None
            async for event in self.turn_engine.execute(context):
                if event.type == StreamEventType.SESSION:
                    continue
                if event.type == StreamEventType.DONE:
                    pending_done_event = event
                    capability_route = payload.get("capability_route")
                    if isinstance(capability_route, dict):
                        pending_done_event.metadata = {
                            **pending_done_event.metadata,
                            "capability_route": dict(capability_route),
                        }
                    continue
                payload_event = await self._publish_live_event(execution, event)
                if payload_event.get("type") not in {"done", "session"}:
                    # A card reply lives inside this assistant row. Persist
                    # the exact user-facing answer boundary so future context
                    # can replay assistant -> user -> assistant in order.
                    _stamp_ask_user_content_offset(payload_event, _persisted_answer())
                    assistant_events.append(payload_event)
                if _should_capture_assistant_content(event):
                    call_id = (event.metadata or {}).get("call_id")
                    content_segments.append((str(call_id) if call_id else None, event.content))
                narration_call_id = _narration_marker_call_id(event)
                if narration_call_id:
                    narration_call_ids.add(narration_call_id)
                for attachment in artifact_attachments(event):
                    if attachment["url"] not in seen_artifact_urls:
                        seen_artifact_urls.add(attachment["url"])
                        generated_attachments.append(attachment)

            provider_response_state = normalize_provider_response_state(
                context.runtime.provider_response_state
            )
            assistant_provider_metadata = (
                {"provider_response_state": provider_response_state}
                if provider_response_state is not None
                else None
            )

            # A mastery turn may have changed which path it is on
            # (``mastery_switch`` / ``mastery_leave``). The conversation's
            # stored preference already followed it; tell the open client too,
            # so what it shows as "currently mastering" is not the path the
            # turn merely started on.
            await self._publish_mastery_path_change(
                execution,
                capability_name=capability_name,
                started_on=_mastery_path_id(payload.get("mastery_path_id")),
                ended_on=str(context.metadata.get("mastery_path_id") or ""),
                mastery_mode=mastery_lease_managed,
            )

            # Office binaries the browser cannot render need their text pulled
            # out now, while the files are still on disk, or their preview card
            # opens empty. Skipped on the cancelled path below: that one is
            # already unwinding and must not start new blocking work.
            await fill_preview_text(generated_attachments)

            # The persisted answer is the captured content minus any narration
            # rounds (their text stayed in the trace, never the answer). Apply
            # the CJK Markdown repair only after every streamed segment has
            # arrived, so no incomplete response is ever rewritten.
            assistant_content = _repair_chinese_emphasis_for_persistence(
                _persisted_answer(),
                str(payload.get("language", "en") or "en"),
            )

            # Assistant continues the same branch as the user message it
            # answers. If we just persisted a new user row we chain off
            # that; if we did not (regenerate path) and the caller pinned a
            # parent, we use it; otherwise we let the store auto-append
            # (legacy behavior).
            if new_user_message_id is not None:
                assistant_message_id = await self.store.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    capability=capability_name,
                    events=[],
                    attachments=generated_attachments or None,
                    parent_message_id=new_user_message_id,
                    metadata=assistant_provider_metadata,
                )
            elif branch_parent_explicit:
                assistant_message_id = await self.store.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    capability=capability_name,
                    events=[],
                    attachments=generated_attachments or None,
                    parent_message_id=branch_parent_id,
                    metadata=assistant_provider_metadata,
                )
            else:
                assistant_message_id = await self.store.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    capability=capability_name,
                    events=[],
                    attachments=generated_attachments or None,
                    metadata=assistant_provider_metadata,
                )
            await self.store.link_turn_message(turn_id, assistant_message_id)
            turn_status, turn_error = _resolve_turn_outcome(
                assistant_events,
                pending_done_event,
            )
            if pending_done_event is None:
                pending_done_event = StreamEvent(
                    type=StreamEventType.DONE,
                    source=capability_name,
                    metadata={"status": turn_status},
                )
            else:
                pending_done_event.metadata = {
                    **pending_done_event.metadata,
                    "status": turn_status,
                }
            # Attach the persisted row ids so the frontend can reconcile its
            # optimistic (negative) message ids with a targeted in-place swap
            # instead of refetching and re-rendering the whole session.
            persisted_ids = {
                key: value
                for key, value in (
                    ("user_message_id", new_user_message_id),
                    ("assistant_message_id", assistant_message_id),
                )
                if value
            }
            if persisted_ids:
                pending_done_event.metadata = {**pending_done_event.metadata, **persisted_ids}
            # Commit all non-terminal events and the terminal row before DONE
            # becomes visible. The DONE envelope itself is then appended and
            # synchronously flushed, so a reconnect can never observe a
            # terminal row with a missing durable event prefix.
            await self._flush_buffered_events(execution)
            transitioned = await self._transition_execution(execution, turn_status, turn_error)
            if not transitioned:
                execution.lease_lost = True
                raise asyncio.CancelledError
            await self._publish_live_event(execution, pending_done_event)
            stream_done_sent = True
            await self._flush_buffered_events(execution)
            if not is_regenerate and turn_status == "completed":
                # Title generation is post-turn metadata. Keep it after DONE
                # so the composer and duration clock stop as soon as the
                # assistant answer is saved; the frontend keeps this socket
                # open briefly so the later ``session_meta`` title update can
                # still arrive.
                try:
                    await self._maybe_generate_session_title(
                        execution=execution,
                        session_id=session_id,
                        ui_language=str(payload.get("language", "en") or "en"),
                    )
                except Exception:
                    # Not debug: this step is the only thing that names a
                    # conversation, and it has no other error surface. Hiding
                    # its failures below the default log level is what let a
                    # broken title path go unnoticed.
                    logger.warning(
                        "Session title generation failed for turn %s", turn_id, exc_info=True
                    )
            # Flush once every terminal/post-turn event (DONE, and the title
            # ``session_meta`` above) has been published, not before: a
            # client that reconnects after this task's ``finally`` pops
            # ``execution`` from ``_executions`` falls back entirely to this
            # persisted backlog, and ``subscribe_turn`` synthesises an
            # id-less DONE when it finds none there -- permanently orphaning
            # the just-persisted assistant reply from that client's
            # reconcile path (it can still see the message after a full
            # session reload, since the row itself is fine; only the
            # targeted in-place swap is unreachable).
            await self._flush_buffered_events(execution)
        except asyncio.CancelledError:
            if execution.lease_lost:
                # The owner can no longer prove it holds the fencing token.
                # Do not publish or persist anything else; leader recovery
                # preserves the shared stream and writes worker_lost.
                raise
            terminal_status = "failed" if execution.shutdown_requested else "cancelled"
            terminal_error = (
                "Server shutdown interrupted this turn"
                if execution.shutdown_requested
                else "Turn cancelled"
            )
            failure_code = "server_shutdown" if execution.shutdown_requested else ""
            retryable = execution.shutdown_requested
            if not stream_done_sent:
                await self._publish_live_event(
                    execution,
                    StreamEvent(
                        type=StreamEventType.ERROR,
                        source=capability_name,
                        content=terminal_error,
                        metadata={
                            "turn_terminal": True,
                            "status": terminal_status,
                            "error_code": failure_code,
                            "retryable": retryable,
                        },
                    ),
                )
            with contextlib.suppress(Exception):
                await self._flush_buffered_events(execution)
            # Best-effort: persist what the turn already produced (streamed
            # answer text, trace events, generated files) so cancelling a
            # turn does not erase visible work — files the model created are
            # on disk either way and must stay reachable. Shielded because
            # we are already unwinding a cancellation. Every step is
            # suppressed separately so the status update below always runs —
            # a turn left "running" gets mislabelled as a restart orphan.
            partial_content = _persisted_answer()
            if partial_content or generated_attachments or assistant_events:
                with contextlib.suppress(Exception):
                    await asyncio.shield(
                        assistant_message_id=await self.store.add_message(
                            session_id=session_id,
                            role="assistant",
                            content=partial_content,
                            capability=capability_name,
                            events=[],
                            attachments=generated_attachments or None,
                            metadata=(
                                {"provider_response_state": provider_response_state}
                                if provider_response_state is not None
                                else None
                            ),
                        )
                    )
                    with contextlib.suppress(Exception):
                        await asyncio.shield(
                            self.store.link_turn_message(turn_id, assistant_message_id)
                        )
            transitioned = False
            with contextlib.suppress(Exception):
                transitioned = await self._transition_execution(
                    execution,
                    terminal_status,
                    terminal_error,
                    failure_code=failure_code,
                    retryable=retryable,
                )
            if not stream_done_sent and transitioned:
                await self._publish_live_event(
                    execution,
                    StreamEvent(
                        type=StreamEventType.DONE,
                        source=capability_name,
                        metadata={
                            "status": terminal_status,
                            "error_code": failure_code,
                            "retryable": retryable,
                        },
                    ),
                )
                stream_done_sent = True
                with contextlib.suppress(Exception):
                    await self._flush_buffered_events(execution)
            raise
        except Exception as exc:
            if stream_done_sent:
                logger.error(
                    "Post-stream persistence for turn %s failed: %s",
                    turn_id,
                    exc,
                    exc_info=True,
                )
                # Suppress each step separately: a flush failure must not
                # also skip the status update, or the turn stays "running"
                # forever and gets mislabelled as a server-restart orphan.
                with contextlib.suppress(Exception):
                    await self._flush_buffered_events(execution)
                with contextlib.suppress(Exception):
                    await self._transition_execution(
                        execution,
                        "failed",
                        str(exc),
                        failure_code="internal_error",
                        retryable=True,
                    )
            else:
                logger.error("Turn %s failed: %s", turn_id, exc, exc_info=True)
                await self._publish_live_event(
                    execution,
                    StreamEvent(
                        type=StreamEventType.ERROR,
                        source=capability_name,
                        content=str(exc),
                        metadata={"turn_terminal": True, "status": "failed"},
                    ),
                )
                await self._publish_live_event(
                    execution,
                    StreamEvent(
                        type=StreamEventType.DONE,
                        source=capability_name,
                        metadata={"status": "failed"},
                    ),
                )
                with contextlib.suppress(Exception):
                    await self._flush_buffered_events(execution)
                await self._transition_execution(
                    execution,
                    "failed",
                    str(exc),
                    failure_code="internal_error",
                    retryable=True,
                )
        finally:
            if llm_scope_token is not None and reset_active_llm_selection is not None:
                reset_active_llm_selection(llm_scope_token)
            # Drop the reply queue first — any in-flight ``submit_user_reply``
            # that finds the queue gone will return ``False`` rather than
            # accumulating on a dead turn.
            self._reply_queues.pop(turn_id, None)
            if bool(payload.get("mastery_path_lease_managed")):
                from deeptutor.learning.storage import LearningStore

                # By turn, not by the path the turn started on: mastery_switch
                # can move a turn onto a different path mid-flight, and freeing
                # the original id would release someone else's lease while
                # leaking the one this turn actually holds.
                with contextlib.suppress(Exception):
                    await asyncio.shield(
                        asyncio.to_thread(LearningStore().release_leases_for_turn, turn_id)
                    )
            async with self._lock:
                current = self._executions.get(turn_id)
                if current is not None:
                    for subscriber in current.subscribers:
                        with contextlib.suppress(asyncio.QueueFull):
                            subscriber.queue.put_nowait(None)
                    self._executions.pop(turn_id, None)
            coordination_task = execution.coordination_task
            if (
                coordination_task is not None
                and coordination_task is not asyncio.current_task()
                and not coordination_task.done()
            ):
                coordination_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await coordination_task
            if execution.lease is not None and self.coordinator is not None:
                with contextlib.suppress(Exception):
                    await self.coordinator.release_turn(execution.lease)
            # A turn may have parsed large attachments or built substantial
            # temporary prompts/results. Reclaim after this coroutine returns,
            # outside the user-visible streaming path.
            from deeptutor.runtime.memory_reclaim import schedule_memory_reclaim

            schedule_memory_reclaim()
