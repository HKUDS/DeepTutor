"""Partner agent runtime — drives the chat agent loop from IM messages.

This replaces the deleted TutorBot engine. A partner has NO engine of its
own: every inbound message becomes one chat turn executed by
``ChatOrchestrator`` → ``AgenticChatPipeline`` (the exact loop the product
chat uses), run inside the partner's synthetic user scope so rag / skills /
notebook tools read the partner workspace natively.

Event → IM mapping:

* ``RESULT`` (``metadata.response``)            → the reply message
* ``CONTENT`` with ``call_kind=llm_final_response`` → terminator/ask_user
  text (the loop's RESULT is empty for an unresolved ask_user pause — the
  pending question IS the reply, and the user's next IM message simply
  starts the next turn)
* narration rounds (``call_role=narration``)     → optional ``_progress``
  messages (``send_progress`` channel flag)
* ``TOOL_CALL``                                  → optional ``_tool_hint``
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any, Awaitable, Callable
import uuid

from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.multi_user.paths import user_context
from deeptutor.partners.bus.events import InboundMessage, OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.helpers import detect_image_mime
from deeptutor.services.partners.commands import PartnerCommandHandler
from deeptutor.services.partners.scope import partner_user
from deeptutor.services.partners.sessions import PartnerSessionStore
from deeptutor.services.partners.workspace import ensure_partner_workspace, read_soul

logger = logging.getLogger(__name__)

EventCallback = Callable[[StreamEvent], Awaitable[None]]

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_MEDIA_BYTES = 10 * 1024 * 1024
_TOOL_HINT_MAX_CHARS = 120


def _format_tool_hint(tool_name: str, args: Any) -> str:
    """One-line IM rendering of a tool call: ``⚙ rag(query="…")``."""
    rendered = ""
    if isinstance(args, dict) and args:
        parts = []
        for key, value in args.items():
            if str(key).startswith("_"):
                continue
            text = str(value)
            if len(text) > 40:
                text = text[:37] + "…"
            parts.append(f"{key}={text!r}" if isinstance(value, str) else f"{key}={text}")
        rendered = ", ".join(parts)
    hint = f"⚙ {tool_name}({rendered})"
    if len(hint) > _TOOL_HINT_MAX_CHARS:
        hint = hint[: _TOOL_HINT_MAX_CHARS - 1] + "…"
    return hint


class PartnerRunner:
    """Consume a partner's inbound bus and answer with the chat agent loop."""

    def __init__(
        self,
        partner_id: str,
        config: Any,
        bus: MessageBus,
        store: PartnerSessionStore,
        save_config: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.partner_id = partner_id
        self.config = config
        self.bus = bus
        self.store = store
        self.save_config = save_config
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()

    # ── inbound loop ──────────────────────────────────────────────

    async def run(self) -> None:
        """Long-running consumer: one task per message, serialised per session."""
        try:
            while True:
                msg = await self.bus.consume_inbound()
                task = asyncio.create_task(
                    self._handle_inbound(msg),
                    name=f"partner:{self.partner_id}:turn",
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except asyncio.CancelledError:
            for task in list(self._tasks):
                task.cancel()
            raise

    async def _handle_inbound(self, msg: InboundMessage) -> None:
        delivery_meta: dict[str, Any] = {}
        try:
            final = await self.process_message(msg, delivery_meta=delivery_meta)
        except Exception as exc:
            logger.exception(
                "Partner %s failed to process message on %s", self.partner_id, msg.channel
            )
            final = f"Sorry, something went wrong while processing your message: {exc}"
        if final:
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=final,
                    metadata=delivery_meta,
                )
            )

    # ── one turn ──────────────────────────────────────────────────

    def _lock_for(self, session_key: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_key] = lock
        return lock

    async def process_message(
        self,
        msg: InboundMessage,
        *,
        on_event: EventCallback | None = None,
        delivery_meta: dict[str, Any] | None = None,
    ) -> str:
        """Run one chat turn for *msg* and return the final reply text.

        *delivery_meta*, when given, is filled with metadata the caller
        should attach to the final outbound message (e.g. ``_streamed``
        when the reply was already delivered live via stream deltas).
        """
        session_key = msg.session_key
        async with self._lock_for(session_key):
            command = PartnerCommandHandler(
                partner_id=self.partner_id,
                config=self.config,
                store=self.store,
                save_config=self.save_config,
            ).dispatch(msg)
            if command is not None:
                return command.content

            final, turn_events = await self._run_turn(
                msg, on_event=on_event, delivery_meta=delivery_meta
            )
            self.store.append(
                session_key,
                "user",
                msg.content,
                channel=msg.channel,
                sender_id=msg.sender_id,
                attachments=list((msg.metadata or {}).get("_attachment_records") or []),
            )
            if final:
                self.store.append(
                    session_key,
                    "assistant",
                    final,
                    channel=msg.channel,
                    events=turn_events or None,
                )
            return final

    async def _run_turn(
        self,
        msg: InboundMessage,
        *,
        on_event: EventCallback | None = None,
        delivery_meta: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        ensure_partner_workspace(self.partner_id)
        primary = getattr(self.config, "llm_selection", None) or None
        backup = getattr(self.config, "backup_llm_selection", None) or None

        final_text, errors, events = await self._execute_turn(
            msg, selection=primary, on_event=on_event, delivery_meta=delivery_meta
        )
        if not final_text and errors and backup and backup != primary:
            logger.warning(
                "Partner %s turn failed on primary model (%s); retrying with backup",
                self.partner_id,
                errors[-1][:200],
            )
            if delivery_meta is not None:
                delivery_meta.pop("_streamed", None)
            final_text, errors, events = await self._execute_turn(
                msg, selection=backup, on_event=on_event, delivery_meta=delivery_meta
            )

        if not final_text and errors:
            final_text = f"Sorry, the turn failed: {errors[-1]}"
        return final_text, events

    async def _execute_turn(
        self,
        msg: InboundMessage,
        *,
        selection: dict[str, str] | None,
        on_event: EventCallback | None = None,
        delivery_meta: dict[str, Any] | None = None,
    ) -> tuple[str, list[str], list[dict[str, Any]]]:
        """Run one chat turn with *selection* active; returns (final, errors, events).

        ``events`` is the turn's trace (every StreamEvent except done/session,
        as ``to_dict()`` — the exact shape the web socket forwards live), so the
        web chat can rehydrate its collapsible "Done" activity after a refresh.

        A failed turn is ``("", [error, …], events)`` — the caller decides
        whether a backup model gets a second attempt. Exceptions are folded into
        the error list so the retry policy sees them too.

        When the inbound message asks for streaming (``_wants_stream``, set
        by channels whose config enables it), every loop round's text is
        published live as ``_stream_delta`` messages keyed by
        ``_stream_id = {turn_id}:{call_id}`` — narration rounds freeze into
        their own IM message when they complete, and the finish round
        becomes the reply (the final outbound is then marked ``_streamed``
        so the channel doesn't send it twice).
        """
        from deeptutor.runtime.orchestrator import ChatOrchestrator
        from deeptutor.services.model_selection.runtime import (
            activate_llm_selection,
            reset_llm_selection,
        )

        final_text = ""
        terminator_text = ""
        turn_id = ""
        round_buffers: dict[str, list[str]] = {}
        streamed_rounds: dict[str, str] = {}  # call_id → accumulated streamed text
        ended_rounds: set[str] = set()
        errors: list[str] = []
        turn_events: list[dict[str, Any]] = []

        # Turn setup (context assembly + LLM-selection resolution) runs INSIDE
        # the try so a setup failure folds into the error list instead of
        # propagating as an opaque crash. The common one is a missing active
        # LLM model: get_llm_config() raises LLMConfigError (a plain Exception,
        # not RuntimeError), which previously escaped _execute_turn and surfaced
        # as a bare "Internal error" on the web socket — masking the real
        # message and skipping the backup-model retry. Folding it here keeps the
        # actual reason ("No active LLM model is configured…") and lets
        # _run_turn fall back to the backup selection.
        #
        # activate_llm_selection still runs BEFORE the partner scope is entered:
        # the model catalog lives in the admin workspace, and the scoped config
        # rides the same async context into the orchestrator task.
        llm_token = None
        try:
            context = self._build_context(msg)
            turn_id = str(context.metadata.get("turn_id") or "")
            send_progress = self._channel_delivery_flag(msg.channel, "send_progress", default=True)
            send_tool_hints = self._channel_delivery_flag(
                msg.channel, "send_tool_hints", default=True
            )
            is_im = msg.channel != "web"
            # Streaming requires send_progress: narration rounds stream live as
            # they happen, so with progress muted we keep buffered delivery.
            wants_stream = is_im and send_progress and bool(msg.metadata.get("_wants_stream"))

            _config, llm_token = activate_llm_selection(selection)
            # Everything — rag / skills / notebooks AND memory — resolves to the
            # partner's own synthetic workspace. The partner-only memory tools
            # (partner_read / partner_memorize / partner_search, force-mounted by
            # the pipeline) own the split-memory model: partner_read folds in the
            # owner's shared L3 on top of the partner's own, partner_memorize
            # writes only the partner's own. Chat's read_memory / write_memory
            # are suppressed on partner turns, so no admin memory override is
            # needed here (and the partner can never write the owner's memory).
            with user_context(partner_user(self.partner_id, name=self.config.name)):
                orchestrator = ChatOrchestrator()
                async for event in orchestrator.handle(context):
                    if on_event is not None:
                        await on_event(event)
                    meta = event.metadata or {}

                    # Capture the trace for rehydration — mirror product chat's
                    # persisted ``assistant_events`` (everything but done/session).
                    if event.type not in (StreamEventType.DONE, StreamEventType.SESSION):
                        turn_events.append(event.to_dict())

                    if event.type == StreamEventType.CONTENT:
                        call_id = str(meta.get("call_id") or "")
                        round_buffers.setdefault(call_id, []).append(event.content or "")
                        if meta.get("call_kind") == "llm_final_response":
                            terminator_text += event.content or ""
                        if wants_stream and event.content:
                            streamed_rounds[call_id] = (
                                streamed_rounds.get(call_id, "") + event.content
                            )
                            await self._publish_stream_delta(msg, turn_id, call_id, event.content)

                    elif event.type == StreamEventType.TOOL_CALL:
                        if is_im and send_tool_hints and event.content:
                            hint = _format_tool_hint(event.content, meta.get("args"))
                            await self._publish_hint(msg, hint, tool_hint=True)

                    elif event.type == StreamEventType.PROGRESS:
                        if (
                            meta.get("trace_kind") == "call_status"
                            and meta.get("call_state") == "complete"
                            and meta.get("call_role") == "narration"
                        ):
                            call_id = str(meta.get("call_id") or "")
                            text = "".join(round_buffers.pop(call_id, [])).strip()
                            if call_id in streamed_rounds:
                                # Already streamed live — freeze the segment.
                                ended_rounds.add(call_id)
                                await self._publish_stream_end(msg, turn_id, call_id)
                            elif is_im and send_progress and text:
                                await self._publish_hint(msg, text, tool_hint=False)

                    elif event.type == StreamEventType.RESULT and event.source == "chat":
                        final_text = str(meta.get("response") or "")

                    elif event.type == StreamEventType.ERROR and event.content:
                        errors.append(event.content)
        except Exception as exc:
            logger.exception("Partner %s turn crashed", self.partner_id)
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            reset_llm_selection(llm_token)

        if not final_text.strip():
            final_text = terminator_text.strip()
        final_text = final_text.strip()

        # Close any stream segments still open (the finish round, or partial
        # rounds after a crash) so channels can flush their edit buffers.
        for call_id in streamed_rounds:
            if call_id not in ended_rounds:
                await self._publish_stream_end(msg, turn_id, call_id)
                # The reply is "already delivered" only when the live-streamed
                # text matches what the caller is about to send.
                if (
                    delivery_meta is not None
                    and final_text
                    and streamed_rounds[call_id].strip() == final_text
                ):
                    delivery_meta["_streamed"] = True

        return final_text, errors, turn_events

    # ── context assembly ──────────────────────────────────────────

    def _build_context(self, msg: InboundMessage) -> UnifiedContext:
        session_key = msg.session_key
        turn_id = f"partner-{self.partner_id}-{uuid.uuid4().hex[:12]}"
        history = self.store.conversation_history(session_key)
        attachments, attachment_records = self._attachments_from_media(msg.media)
        source_manifest, source_index = self._source_manifest_from_records(
            session_key,
            fresh_records=attachment_records,
        )
        msg.metadata["_attachment_records"] = attachment_records

        # Partner-scope context blocks (soul / skills / KBs) are assembled
        # inside the partner scope so the same service locators the chat
        # turn-runtime uses resolve to the partner workspace.
        with user_context(partner_user(self.partner_id, name=self.config.name)):
            skills_manifest = self._build_skills_manifest()
            kb_names = self._list_kb_names()

        metadata: dict[str, Any] = {
            "turn_id": turn_id,
            "source": "partner",
            "partner_id": self.partner_id,
            "channel": msg.channel,
            "chat_id": msg.chat_id,
            "sender_id": msg.sender_id,
            "session_key": session_key,
            # Swaps the system prompt's product identity ("You are DeepTutor")
            # for the partner's user-given identity; the Soul does the rest.
            "agent_identity": {
                "name": self.config.name,
                "description": getattr(self.config, "description", "") or "",
            },
            # NOTE: no ``wait_for_user_reply`` — an ask_user pause makes
            # the pending question the turn's reply (IM semantics).
        }
        channel_meta: dict[str, Any] = {}
        for key, value in (msg.metadata or {}).items():
            key_text = str(key)
            if key_text.startswith("_"):
                continue
            try:
                json.dumps(value)
                channel_meta[key_text] = value
            except TypeError:
                channel_meta[key_text] = str(value)
        if channel_meta:
            metadata["channel_metadata"] = channel_meta
        if source_index:
            metadata["source_index"] = source_index
        cron_job_id = str((msg.metadata or {}).get("_cron_job_id") or "").strip()
        if cron_job_id:
            metadata["cron_job_id"] = cron_job_id
        mcp_tools = getattr(self.config, "mcp_tools", None)
        if isinstance(mcp_tools, list):
            metadata["mcp_tools_filter"] = [str(name) for name in mcp_tools]

        return UnifiedContext(
            session_id=f"partner:{self.partner_id}:{session_key}",
            user_message=msg.content,
            conversation_history=history,
            enabled_tools=self._resolved_enabled_tools(),
            allowed_builtin_tools=self._resolved_builtin_tools(),
            active_capability="chat",
            knowledge_bases=kb_names,
            attachments=attachments,
            language=self._language(),
            persona_context=read_soul(self.partner_id).strip(),
            skills_manifest=skills_manifest,
            source_manifest=source_manifest,
            metadata=metadata,
        )

    def _resolved_enabled_tools(self) -> list[str]:
        """The partner's user-toggleable tool whitelist.

        ``None`` in config means "everything the user could toggle on in
        chat" — partners default to fully equipped; an explicit list (or
        ``[]``) is the owner's selection.
        """
        configured = getattr(self.config, "enabled_tools", None)
        if configured is None:
            from deeptutor.agents._shared.tool_composition import default_optional_tools

            return default_optional_tools()
        return [str(name) for name in configured]

    def _resolved_builtin_tools(self) -> list[str] | None:
        """The partner's allowed built-in (auto-mounted) tools.

        ``None`` in config means "no gating" — every built-in mounts under its
        usual context condition, exactly like the product chat (partners
        default to fully equipped). An explicit list (or ``[]``) restricts the
        built-in surface so an owner can deny e.g. memory access to an
        IM-facing partner. Flows to ``UnifiedContext.allowed_builtin_tools``.
        """
        configured = getattr(self.config, "builtin_tools", None)
        if configured is None:
            return None
        return [str(name) for name in configured]

    def _build_skills_manifest(self) -> str:
        try:
            from deeptutor.services.skill.service import (
                get_skill_service,
                render_skills_manifest,
            )

            service = get_skill_service()
            entries = service.summary_entries()
            always_block = service.load_always_for_context()
            return "\n\n".join(
                part for part in (always_block, render_skills_manifest(entries)) if part
            )
        except Exception:
            logger.warning(
                "Failed to build skills manifest for partner %s", self.partner_id, exc_info=True
            )
            return ""

    def _list_kb_names(self) -> list[str]:
        try:
            from deeptutor.knowledge.manager import KnowledgeBaseManager
            from deeptutor.services.path_service import get_path_service

            kb_root = get_path_service().get_knowledge_bases_root()
            if not kb_root.is_dir():
                return []
            return KnowledgeBaseManager(base_dir=str(kb_root)).list_knowledge_bases()
        except Exception:
            logger.warning("Failed to list KBs for partner %s", self.partner_id, exc_info=True)
            return []

    def _language(self) -> str:
        lang = str(getattr(self.config, "language", "") or "").strip().lower()
        return "zh" if lang.startswith("zh") else "en"

    def _channel_delivery_flag(self, channel_name: str, name: str, *, default: bool) -> bool:
        channels = getattr(self.config, "channels", None) or {}
        if not isinstance(channels, dict):
            return default
        section = channels.get(channel_name)
        if not isinstance(section, dict):
            return default
        value = section.get(name)
        if value is None:
            camel = "sendProgress" if name == "send_progress" else "sendToolHints"
            value = section.get(camel)
        return value if isinstance(value, bool) else default

    @staticmethod
    def _attachment_id_for_path(path: Path) -> str:
        try:
            seed = str(path.resolve())
        except OSError:
            seed = str(path)
        return hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]

    def _attachments_from_media(self, media: list[str]) -> tuple[list[Attachment], list[dict]]:
        attachments: list[Attachment] = []
        records: list[dict[str, Any]] = []
        document_records: list[dict[str, Any]] = []
        for raw_path in media or []:
            try:
                path = Path(raw_path)
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if size > _MAX_MEDIA_BYTES:
                    continue
                data = path.read_bytes()
                attachment_id = self._attachment_id_for_path(path)
                mime_type = mimetypes.guess_type(path.name)[0] or ""
                mime = detect_image_mime(data)
                if mime and size <= _MAX_IMAGE_BYTES:
                    encoded = base64.b64encode(data).decode("ascii")
                    attachments.append(
                        Attachment(
                            type="image",
                            base64=encoded,
                            filename=path.name,
                            mime_type=mime,
                            id=attachment_id,
                        )
                    )
                    records.append(
                        {
                            "id": attachment_id,
                            "type": "image",
                            "filename": path.name,
                            "mime_type": mime,
                            "path": str(path),
                            "size": size,
                        }
                    )
                    continue

                document_records.append(
                    {
                        "id": attachment_id,
                        "type": "pdf" if path.suffix.lower() == ".pdf" else "file",
                        "filename": path.name,
                        "mime_type": mime_type,
                        "base64": base64.b64encode(data).decode("ascii"),
                        "path": str(path),
                        "size": size,
                    }
                )
            except OSError:
                logger.warning("Skipping unreadable media file: %s", raw_path, exc_info=True)

        if document_records:
            try:
                from deeptutor.utils.document_extractor import extract_documents_from_records

                _document_texts, updated_records = extract_documents_from_records(document_records)
            except Exception:
                logger.warning(
                    "Failed to extract partner media documents for %s",
                    self.partner_id,
                    exc_info=True,
                )
                updated_records = [
                    {**record, "base64": "", "extracted_chars": 0} for record in document_records
                ]

            for record in updated_records:
                cleaned = {k: v for k, v in record.items() if k != "base64"}
                records.append(cleaned)
                if str(cleaned.get("extracted_text", "") or "").strip():
                    attachments.append(
                        Attachment(
                            type=str(cleaned.get("type") or "file"),
                            filename=str(cleaned.get("filename") or ""),
                            mime_type=str(cleaned.get("mime_type") or ""),
                            id=str(cleaned.get("id") or ""),
                            extracted_text=str(cleaned.get("extracted_text") or ""),
                        )
                    )

        return attachments, records

    def _source_manifest_from_records(
        self,
        session_key: str,
        *,
        fresh_records: list[dict[str, Any]],
    ) -> tuple[str, dict[str, str]]:
        try:
            from deeptutor.services.session.source_inventory import (
                SourceEntry,
                SourceInventory,
                render_manifest,
            )
        except Exception:
            logger.warning("Failed to import source inventory helpers", exc_info=True)
            return "", {}

        inv = SourceInventory()
        turn_ordinal = 1
        historical_messages = self.store.messages(session_key, limit=200)
        for message in historical_messages:
            if message.get("role") == "user":
                turn_ordinal += 1
                for record in message.get("attachments") or []:
                    self._add_attachment_source(
                        inv,
                        record,
                        fresh=False,
                        first_seen_turn=turn_ordinal - 1,
                        source_entry_cls=SourceEntry,
                    )

        for record in fresh_records:
            self._add_attachment_source(
                inv,
                record,
                fresh=True,
                first_seen_turn=turn_ordinal,
                source_entry_cls=SourceEntry,
            )
        return render_manifest(inv)

    @staticmethod
    def _add_attachment_source(
        inv: Any,
        record: dict[str, Any],
        *,
        fresh: bool,
        first_seen_turn: int,
        source_entry_cls: Any,
    ) -> None:
        if str(record.get("type", "")).lower() == "image":
            return
        mime = str(record.get("mime_type", "") or "").lower()
        if mime.startswith("image/"):
            return
        text = str(record.get("extracted_text", "") or "")
        attachment_id = str(record.get("id", "") or "").strip()
        if not text.strip() or not attachment_id:
            return
        inv.add(
            source_entry_cls(
                sid=f"at-{attachment_id}",
                kind="attachment",
                name=str(record.get("filename") or "Untitled file"),
                full_text=text,
                fresh=fresh,
                first_seen_turn=first_seen_turn,
            )
        )

    async def _publish_hint(self, msg: InboundMessage, text: str, *, tool_hint: bool) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=text,
                metadata={"_progress": True, "_tool_hint": tool_hint},
            )
        )

    async def _publish_stream_delta(
        self, msg: InboundMessage, turn_id: str, call_id: str, delta: str
    ) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=delta,
                metadata={"_stream_delta": True, "_stream_id": f"{turn_id}:{call_id}"},
            )
        )

    async def _publish_stream_end(self, msg: InboundMessage, turn_id: str, call_id: str) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="",
                metadata={"_stream_end": True, "_stream_id": f"{turn_id}:{call_id}"},
            )
        )


__all__ = ["PartnerRunner"]
