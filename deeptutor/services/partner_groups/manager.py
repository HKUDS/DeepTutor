"""Application service coordinating Group storage, routing and Partner turns."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import re
import time
from typing import Any, Awaitable, Callable
from uuid import uuid4

from deeptutor.core.stream import StreamEventType
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.partner_access import can_use_partner
from deeptutor.services.partner_groups.memory import shared_memory_registry
from deeptutor.services.partner_groups.models import (
    GroupMessage,
    GroupTurnResult,
    PartnerGroupConfig,
    PartnerInvocation,
    utc_now,
)
from deeptutor.services.partner_groups.modes import DiscussionContext, discussion_mode_registry
from deeptutor.services.partner_groups.store import (
    GroupTranscriptStore,
    PartnerGroupStore,
    PartnerInvocationStore,
)
from deeptutor.services.partners import (
    PartnerGroupTurnResponse,
    get_partner_manager,
    slugify_partner_id,
)

GroupEmitter = Callable[[dict[str, Any]], Awaitable[None]]

_LIVE_REPLAY_MAX_FRAMES = 512
_LIVE_REPLAY_MAX_TURNS = 64
_MENTION_PATTERN = re.compile(r"(?<![\w@])@([^\s@,，:：;；!?！？。.]+)")
_ROUND_CONTEXT_HEADING = "Messages already produced this round:"
_ROUND_SUMMARY_INSTRUCTION = (
    "Summarize only the completed round in the public context. Produce exactly three "
    "clearly labeled sections: Consensus, Disagreements, and Recommendation for the user. "
    "Use the user's language, distinguish genuine agreement from unresolved differences, "
    "and make the recommendation actionable."
)


async def _noop_emit(frame: dict[str, Any]) -> None:
    _ = frame


def _append_round_context(public_context: str, extra_context: str) -> str:
    extra_context = str(extra_context or "").strip()
    if not extra_context:
        return public_context
    return f"{public_context}\n\n{_ROUND_CONTEXT_HEADING}\n{extra_context}"


def _append_partner_instruction(content: str, partner_id: str, instruction: str) -> str:
    instruction = str(instruction or "").strip()
    if not instruction:
        return content
    return (
        f"{content}\n\n"
        f'<upcoming_partner_turn_requirement partner_id="{partner_id}">\n'
        f"This requirement applies only to @{partner_id}'s upcoming turn:\n"
        f"{instruction}\n"
        "</upcoming_partner_turn_requirement>"
    )


@dataclass(slots=True)
class LiveGroupTurn:
    """A public Group turn that survives its initiating WebSocket."""

    content: str = ""
    mentions: tuple[str, ...] | None = None
    operation: str = "message"
    invocation_id: str = ""
    turn_id: str = ""
    partner_id: str = ""
    frames: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set, repr=False)
    done: bool = False
    task: asyncio.Task | None = field(default=None, repr=False)
    started_at: float = field(default_factory=time.monotonic)

    async def emit(self, frame: dict[str, Any]) -> None:
        self._record(frame)

    def _record(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)
        if len(self.frames) > _LIVE_REPLAY_MAX_FRAMES:
            del self.frames[: len(self.frames) - _LIVE_REPLAY_MAX_FRAMES]
        if frame.get("type") in {"done", "error", "cancelled"}:
            self.done = True
        for queue in tuple(self.subscribers):
            queue.put_nowait(frame)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        for frame in self.frames:
            queue.put_nowait(frame)
        if not self.done:
            self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)


@dataclass(frozen=True, slots=True)
class GroupMemberSnapshot:
    """One turn's immutable view of member configs and mention aliases."""

    members: tuple[dict[str, str], ...]
    configs: dict[str, Any]
    aliases: dict[str, str]


@dataclass(frozen=True, slots=True)
class MentionResolution:
    targets: tuple[str, ...]
    unknown_mentions: tuple[str, ...]


class PartnerGroupManager:
    def __init__(self) -> None:
        self.store = PartnerGroupStore()
        self._live_turns: dict[tuple[str, str, str, str], LiveGroupTurn] = {}
        self._completed_turns: OrderedDict[tuple[str, str, str, str], LiveGroupTurn] = OrderedDict()

    def list_groups(self) -> list[dict[str, Any]]:
        return [self.describe_group(group) for group in self.store.list()]

    def get_group(self, group_id: str) -> PartnerGroupConfig | None:
        try:
            return self.store.get(group_id)
        except ValueError:
            return None

    def create_group(
        self,
        *,
        name: str,
        member_ids: list[str],
        description: str = "",
        discussion_mode: str = "panel_parallel",
        shared_memory: str = "whiteboard",
        emoji: str = "👥",
        color: str = "#6366f1",
    ) -> PartnerGroupConfig:
        members = self._validate_members(member_ids)
        discussion_mode_registry.get(discussion_mode)
        # Type validation must not construct storage against a non-group path;
        # otherwise an implementation with eager I/O can pollute every group.
        shared_memory_registry.validate(shared_memory)
        base = slugify_partner_id(name) or "group"
        group_id = base
        while self.store.get(group_id) is not None:
            group_id = f"{base}-{uuid4().hex[:6]}"
        now = utc_now()
        group = PartnerGroupConfig(
            group_id=group_id,
            owner_id=get_current_user().id,
            name=str(name).strip()[:80],
            description=str(description).strip()[:500],
            member_ids=members,
            discussion_mode=discussion_mode,
            shared_memory=shared_memory,
            emoji=str(emoji or "👥").strip()[:16],
            color=self._color(color),
            created_at=now,
            updated_at=now,
        )
        if not group.name:
            raise ValueError("A Partner Group needs a name.")
        self.store.save(group)
        return group

    def update_group(self, group_id: str, changes: dict[str, Any]) -> PartnerGroupConfig:
        group = self._require(group_id)
        if "name" in changes:
            name = str(changes["name"] or "").strip()[:80]
            if not name:
                raise ValueError("A Partner Group needs a name.")
            group.name = name
        if "description" in changes:
            group.description = str(changes["description"] or "").strip()[:500]
        if "member_ids" in changes:
            group.member_ids = self._validate_members(list(changes["member_ids"] or []))
        if "discussion_mode" in changes:
            mode = str(changes["discussion_mode"])
            discussion_mode_registry.get(mode)
            group.discussion_mode = mode
        if "shared_memory" in changes:
            memory = str(changes["shared_memory"])
            shared_memory_registry.validate(memory)
            group.shared_memory = memory
        if "emoji" in changes:
            group.emoji = str(changes["emoji"] or "👥").strip()[:16]
        if "color" in changes:
            group.color = self._color(changes["color"])
        group.updated_at = utc_now()
        self.store.save(group)
        return group

    def delete_group(self, group_id: str) -> bool:
        self._require(group_id)
        return self.store.delete(group_id)

    def history(self, group_id: str, session_key: str, *, limit: int = 200) -> list[dict]:
        group = self._require(group_id)
        group_dir = self.store.group_dir(group.group_id)
        transcript = GroupTranscriptStore(group_dir)
        invocations = PartnerInvocationStore(group_dir)
        messages = transcript.messages(_normalize_session_key(session_key), limit=limit)
        for message in messages:
            if message.invocation_id:
                invocation = invocations.get(message.invocation_id)
                if invocation is not None:
                    message.invocation = invocation.to_dict()
        return [message.to_dict() for message in messages]

    def invocations(
        self,
        group_id: str,
        session_key: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        group = self._require(group_id)
        store = PartnerInvocationStore(self.store.group_dir(group.group_id))
        return [
            invocation.to_dict()
            for invocation in store.list(_normalize_session_key(session_key), limit=limit)
        ]

    def create_invocation(
        self,
        group_id: str,
        *,
        session_key: str,
        requester_partner_id: str,
        target_partner_id: str,
        question: str,
    ) -> PartnerInvocation:
        """Create a user-originated proposal for the existing approval flow."""
        group = self._require(group_id)
        members = self._member_snapshot(group).members
        (
            requester_id,
            requester_name,
            target_id,
            target_name,
            normalized_question,
        ) = self._validate_invocation_request(
            group=group,
            requester_partner_id=requester_partner_id,
            target_partner_id=target_partner_id,
            question=question,
            members=members,
        )
        return self._save_invocation(
            PartnerInvocationStore(self.store.group_dir(group.group_id)),
            group=group,
            session_key=_normalize_session_key(session_key),
            parent_turn_id="",
            requester_partner_id=requester_id,
            requester_partner_name=requester_name,
            target_partner_id=target_id,
            target_partner_name=target_name,
            question=normalized_question,
        )

    def whiteboard(self, group_id: str, *, limit: int = 200) -> list[dict]:
        group = self._require(group_id)
        memory = shared_memory_registry.create(
            group.shared_memory, self.store.group_dir(group.group_id)
        )
        return memory.entries(limit=limit)

    def pin_whiteboard(self, group_id: str, event_id: str) -> dict[str, Any]:
        group = self._require(group_id)
        group_dir = self.store.group_dir(group.group_id)
        message = GroupTranscriptStore(group_dir).find_event(event_id)
        if message is None:
            raise LookupError("Partner Group transcript message not found")
        if message.error or not message.content.strip():
            raise ValueError("Only a completed public transcript message can be pinned.")
        memory = shared_memory_registry.create(group.shared_memory, group_dir)
        entry, created = memory.pin(message, pinned_at=utc_now())
        return {"entry": entry, "created": created}

    def unpin_whiteboard(self, group_id: str, event_id: str) -> bool:
        group = self._require(group_id)
        memory = shared_memory_registry.create(
            group.shared_memory, self.store.group_dir(group.group_id)
        )
        return memory.unpin(str(event_id or "").strip(), unpinned_at=utc_now())

    def list_sessions(self, group_id: str) -> list[dict[str, Any]]:
        group = self._require(group_id)
        transcript = GroupTranscriptStore(self.store.group_dir(group.group_id))
        return [session.to_dict() for session in transcript.list_sessions()]

    def create_session(self, group_id: str) -> dict[str, Any]:
        group = self._require(group_id)
        transcript = GroupTranscriptStore(self.store.group_dir(group.group_id))
        session = transcript.create_session(f"pg-{uuid4().hex}")
        return session.to_dict()

    def delete_session(self, group_id: str, session_key: str) -> bool:
        group = self._require(group_id)
        session_key = _normalize_session_key(session_key)
        prefix = (get_current_user().id, group.group_id, session_key)
        if any(key[:3] == prefix for key in self._live_turns):
            raise ValueError("A Partner Group turn is still running in this session.")
        group_dir = self.store.group_dir(group.group_id)
        transcript = GroupTranscriptStore(group_dir)
        if not transcript.delete_session(session_key):
            return False
        PartnerInvocationStore(group_dir).delete_session(session_key)
        return True

    def referenced_transcript(
        self,
        group_id: str,
        session_key: str,
        *,
        language: str = "en",
    ) -> tuple[str, str]:
        """Return a bounded public transcript suitable for home-chat sources."""
        group = self._require(group_id)
        session_key = _normalize_session_key(session_key)
        transcript = GroupTranscriptStore(self.store.group_dir(group.group_id))
        sessions = {item.session_key: item for item in transcript.list_sessions()}
        summary = sessions.get(session_key)
        if summary is None or summary.message_count == 0:
            return "", ""
        lang = "zh" if str(language or "").lower().startswith("zh") else "en"
        header = (
            f"〔以下是 Partner Group「{group.name}」中的另一段公开讨论，由用户附带进来供你参考。"
            "这不是当前对话；请区分各位发言者，不要把他们的发言当成你自己的经历。〕"
            if lang == "zh"
            else (
                f"[The following is a separate public discussion from Partner Group "
                f"{group.name!r}, attached by the user for reference. It is not the current "
                "conversation; keep the speakers distinct and do not claim their statements "
                "as your own.]"
            )
        )
        body_budget = max(1, 16_000 - len(header) - 2)
        body = transcript.render(session_key, max_chars=body_budget)
        if not body:
            return "", ""
        title = summary.title or group.name
        return f"{header}\n\n{body}", f"{group.name}: {title}"

    async def send_message(
        self,
        group_id: str,
        *,
        content: str,
        session_key: str,
        mentions: list[str] | None = None,
        emit: GroupEmitter = _noop_emit,
        turn_id: str = "",
    ) -> GroupTurnResult:
        group = self._require(group_id)
        content = str(content or "").strip()
        if not content:
            raise ValueError("Group message cannot be empty.")
        session_key = _normalize_session_key(session_key)
        member_snapshot = self._member_snapshot(group)
        mention_resolution = self.resolve_mentions(
            group,
            content,
            mentions,
            member_snapshot=member_snapshot,
        )
        targets = list(mention_resolution.targets)
        turn_id = str(turn_id or uuid4().hex)
        now = utc_now()
        actor = get_current_user()
        user_message = GroupMessage(
            event_id=uuid4().hex,
            turn_id=turn_id,
            session_key=session_key,
            role="user",
            content=content,
            author_id=actor.id,
            author_name=actor.username or "User",
            mentions=targets,
            created_at=now,
        )
        group_dir = self.store.group_dir(group.group_id)
        transcript = GroupTranscriptStore(group_dir)
        previous_transcript = transcript.render(session_key)
        transcript.append(user_message)
        await emit({"type": "user_message", "message": user_message.to_dict()})

        public_context = self._render_public_context(
            group,
            members=member_snapshot.members,
            previous_transcript=previous_transcript,
            shared_memory=self._render_shared_memory(group),
        )
        invocation_store = PartnerInvocationStore(group_dir)

        pending_messages: dict[str, GroupMessage] = {}

        async def respond(
            partner_id: str,
            *,
            extra_context: str = "",
            instruction: str = "",
            allow_invoke_other: bool = True,
        ) -> GroupMessage:
            message = await self._run_partner_reply(
                group=group,
                partner_id=partner_id,
                content=content,
                session_key=session_key,
                turn_id=turn_id,
                member_snapshot=member_snapshot,
                public_context=public_context,
                invocation_store=invocation_store,
                emit=emit,
                actor=actor,
                extra_context=extra_context,
                instruction=instruction,
                allow_invoke_other=allow_invoke_other,
            )
            pending_messages[message.event_id] = message
            return message

        async def mode_emit(frame: dict[str, Any]) -> None:
            if frame.get("type") == "partner_message":
                payload = frame.get("message")
                event_id = str(payload.get("event_id") or "") if isinstance(payload, dict) else ""
                message = pending_messages.pop(event_id, None)
                if message is not None:
                    transcript.append(message)
            await emit(frame)

        mode = discussion_mode_registry.get(group.discussion_mode)
        replies = await mode.run(
            DiscussionContext(group=group, targets=targets, respond=respond, emit=mode_emit)
        )
        group.updated_at = utc_now()
        self.store.save(group)
        result = GroupTurnResult(
            turn_id,
            targets,
            user_message,
            replies,
            list(mention_resolution.unknown_mentions),
        )
        await emit({"type": "done", "result": result.to_dict()})
        return result

    async def summarize_round(
        self,
        group_id: str,
        turn_id: str,
        *,
        session_key: str,
        partner_id: str,
        emit: GroupEmitter = _noop_emit,
    ) -> GroupMessage:
        """Ask one member to synthesize a completed public Group round."""
        group = self._require(group_id)
        session_key = _normalize_session_key(session_key)
        turn_id = str(turn_id or "").strip()
        partner_id = str(partner_id or "").strip()
        group_dir = self.store.group_dir(group.group_id)
        transcript = GroupTranscriptStore(group_dir)
        round_messages = self._require_summary_round(
            group,
            transcript,
            session_key=session_key,
            turn_id=turn_id,
            partner_id=partner_id,
        )
        member_snapshot = self._member_snapshot(group)
        public_context = self._render_public_context(
            group,
            members=member_snapshot.members,
            previous_transcript=transcript.render_before_turn(session_key, turn_id),
            shared_memory=self._render_shared_memory(group),
        )
        extra_context = "\n\n".join(
            f"{message.author_name}: {message.content}" for message in round_messages
        )
        await emit(
            {
                "type": "partner_started",
                "turn_id": turn_id,
                "partner_id": partner_id,
            }
        )
        message = await self._run_partner_reply(
            group=group,
            partner_id=partner_id,
            content="Summarize this completed Partner Group round.",
            session_key=session_key,
            turn_id=turn_id,
            member_snapshot=member_snapshot,
            public_context=public_context,
            invocation_store=PartnerInvocationStore(group_dir),
            emit=emit,
            actor=get_current_user(),
            extra_context=extra_context,
            instruction=_ROUND_SUMMARY_INSTRUCTION,
            kind="round_summary",
            allow_invoke_other=False,
        )
        transcript.append(message)
        await emit({"type": "partner_message", "message": message.to_dict()})
        group.updated_at = utc_now()
        self.store.save(group)
        await emit(
            {
                "type": "done",
                "result": {
                    "operation": "summarize_round",
                    "turn_id": turn_id,
                    "partner_id": partner_id,
                    "message": message.to_dict(),
                },
            }
        )
        return message

    async def retry_partner(
        self,
        group_id: str,
        turn_id: str,
        partner_id: str,
        *,
        session_key: str,
        emit: GroupEmitter = _noop_emit,
    ) -> GroupMessage:
        """Re-run one failed panel seat against its original public snapshot."""
        group = self._require(group_id)
        session_key = _normalize_session_key(session_key)
        group_dir = self.store.group_dir(group.group_id)
        transcript = GroupTranscriptStore(group_dir)
        user_message, failed_message = self._require_retry_target(
            transcript,
            session_key=session_key,
            turn_id=turn_id,
            partner_id=partner_id,
        )
        member_snapshot = self._member_snapshot(group)
        public_context = self._render_public_context(
            group,
            members=member_snapshot.members,
            previous_transcript=transcript.render_before_turn(session_key, turn_id),
            shared_memory=self._render_shared_memory(group),
        )
        await emit(
            {
                "type": "partner_started",
                "turn_id": turn_id,
                "partner_id": partner_id,
                "retry": True,
            }
        )
        replacement = await self._run_partner_reply(
            group=group,
            partner_id=partner_id,
            content=user_message.content,
            session_key=session_key,
            turn_id=turn_id,
            member_snapshot=member_snapshot,
            public_context=public_context,
            invocation_store=PartnerInvocationStore(group_dir),
            emit=emit,
            actor=get_current_user(),
            event_id=failed_message.event_id,
            retry=True,
        )
        if not transcript.replace(replacement):
            raise LookupError("Failed Partner seat no longer exists")
        await emit({"type": "partner_message", "message": replacement.to_dict(), "retry": True})
        group.updated_at = utc_now()
        self.store.save(group)
        await emit(
            {
                "type": "done",
                "result": {
                    "operation": "retry_partner",
                    "turn_id": turn_id,
                    "partner_id": partner_id,
                    "message": replacement.to_dict(),
                },
            }
        )
        return replacement

    async def approve_invocation(
        self,
        group_id: str,
        invocation_id: str,
        *,
        session_key: str,
        emit: GroupEmitter = _noop_emit,
    ) -> GroupMessage:
        """Publish the approved question and run one non-chainable target turn."""
        group = self._require(group_id)
        session_key = _normalize_session_key(session_key)
        group_dir = self.store.group_dir(group.group_id)
        invocations = PartnerInvocationStore(group_dir)
        pending = self._require_invocation(
            invocations,
            group=group,
            invocation_id=invocation_id,
            session_key=session_key,
        )
        now = utc_now()
        invocation = invocations.transition(
            pending.invocation_id,
            # ``approved`` is accepted for recovery after a process restart:
            # the live task is in memory, while the durable approval is not.
            allowed={"pending", "approved"},
            status="approved",
            updated_at=now,
        )
        await emit({"type": "invocation_updated", "invocation": invocation.to_dict()})

        transcript = GroupTranscriptStore(group_dir)
        previous_transcript = transcript.render(session_key)
        member_snapshot = self._member_snapshot(group)
        followup_turn_id = uuid4().hex
        question_message = next(
            (
                message
                for message in transcript.messages(session_key, limit=500)
                if invocation.question_event_id and message.event_id == invocation.question_event_id
            ),
            None,
        )
        if question_message is None:
            question_message = GroupMessage(
                event_id=uuid4().hex,
                turn_id=followup_turn_id,
                session_key=session_key,
                role="partner",
                content=invocation.question,
                author_id=invocation.requester_partner_id,
                author_name=invocation.requester_partner_name,
                created_at=utc_now(),
                mentions=[invocation.target_partner_id],
                kind="invocation_question",
                invocation_id=invocation.invocation_id,
                invocation=invocation.to_dict(),
            )
            transcript.append(question_message)
            invocation = invocations.transition(
                invocation.invocation_id,
                allowed={"approved"},
                status="approved",
                updated_at=utc_now(),
                question_event_id=question_message.event_id,
            )
        await emit({"type": "partner_message", "message": question_message.to_dict()})

        partners = get_partner_manager()
        target_id = invocation.target_partner_id
        cfg = member_snapshot.configs.get(target_id)
        target_name = cfg.name if cfg else invocation.target_partner_name or target_id
        public_context = self._render_public_context(
            group,
            members=member_snapshot.members,
            previous_transcript=previous_transcript,
            shared_memory=self._render_shared_memory(group),
        )
        await emit(
            {
                "type": "partner_started",
                "partner_id": target_id,
                "invocation_id": invocation.invocation_id,
            }
        )

        status = "completed"
        error = ""
        try:
            if cfg is None or not can_use_partner(target_id):
                raise RuntimeError("Partner is unavailable")
            instance = partners.get_partner(target_id)
            if instance is None or not instance.running:
                instance = await partners.start_partner(target_id, cfg)

            async def forward_trace(event: Any) -> None:
                if event.type in {StreamEventType.DONE, StreamEventType.SESSION}:
                    return
                await emit(
                    {
                        "type": "partner_trace",
                        "turn_id": followup_turn_id,
                        "partner_id": target_id,
                        "partner_name": target_name,
                        "invocation_id": invocation.invocation_id,
                        "event": event.to_dict(),
                    }
                )

            turn = await partners.send_group_message(
                target_id,
                (
                    f"{invocation.requester_partner_name} asks you directly in the Group: "
                    f"{invocation.question}"
                ),
                session_key=f"group-{group.group_id}-{session_key}",
                group_id=group.group_id,
                group_name=group.name,
                group_members=[dict(member) for member in member_snapshot.members],
                public_context=public_context,
                actor=get_current_user(),
                # One hop only: an invoked answer cannot propose another call.
                allow_invoke_other=False,
                on_event=forward_trace,
            )
            if isinstance(turn, str):
                turn = PartnerGroupTurnResponse(content=turn)
            reply = GroupMessage(
                event_id=uuid4().hex,
                turn_id=followup_turn_id,
                session_key=session_key,
                role="partner",
                content=turn.content,
                author_id=target_id,
                author_name=target_name,
                created_at=utc_now(),
                kind="invocation_reply",
                events=turn.events,
                invocation_id=invocation.invocation_id,
            )
        except asyncio.CancelledError:
            cancelled = invocations.transition(
                invocation.invocation_id,
                allowed={"approved"},
                status="cancelled",
                updated_at=utc_now(),
                error="Cancelled by user.",
            )
            await emit({"type": "invocation_updated", "invocation": cancelled.to_dict()})
            raise
        except Exception as exc:
            status = "failed"
            error = str(exc)[:500] or "Partner failed to answer."
            reply = GroupMessage(
                event_id=uuid4().hex,
                turn_id=followup_turn_id,
                session_key=session_key,
                role="partner",
                content=error,
                author_id=target_id,
                author_name=target_name,
                created_at=utc_now(),
                kind="invocation_reply",
                error=True,
                invocation_id=invocation.invocation_id,
            )

        transcript.append(reply)
        await emit({"type": "partner_message", "message": reply.to_dict()})
        invocation = invocations.transition(
            invocation.invocation_id,
            allowed={"approved"},
            status=status,
            updated_at=utc_now(),
            reply_event_id=reply.event_id,
            error=error,
        )
        await emit({"type": "invocation_updated", "invocation": invocation.to_dict()})
        group.updated_at = utc_now()
        self.store.save(group)
        await emit(
            {
                "type": "done",
                "result": {
                    "operation": "invoke_other",
                    "invocation": invocation.to_dict(),
                    "reply": reply.to_dict(),
                },
            }
        )
        return reply

    def reject_invocation(
        self,
        group_id: str,
        invocation_id: str,
        *,
        session_key: str,
    ) -> PartnerInvocation:
        group = self._require(group_id)
        invocations = PartnerInvocationStore(self.store.group_dir(group.group_id))
        pending = self._require_invocation(
            invocations,
            group=group,
            invocation_id=invocation_id,
            session_key=_normalize_session_key(session_key),
        )
        return invocations.transition(
            pending.invocation_id,
            allowed={"pending"},
            status="rejected",
            updated_at=utc_now(),
        )

    def start_live_turn(
        self,
        group_id: str,
        *,
        content: str,
        session_key: str,
        mentions: list[str] | None = None,
    ) -> LiveGroupTurn:
        """Start or reattach to one in-flight turn for a Group session."""
        group_id = self._require(group_id).group_id
        session_key = _normalize_session_key(session_key)
        content = str(content or "").strip()
        normalized_mentions = (
            tuple(str(value).strip() for value in mentions) if mentions is not None else None
        )
        key = self._live_key(group_id, session_key, "message")
        previous = self._live_turns.get(key)
        if previous is not None:
            if previous.content != content or previous.mentions != normalized_mentions:
                raise ValueError("A Partner Group turn is already in progress for this session.")
            return previous
        live = LiveGroupTurn(
            content=content,
            mentions=normalized_mentions,
            operation="message",
            turn_id=uuid4().hex,
        )

        async def run() -> None:
            try:
                await self.send_message(
                    group_id,
                    content=content,
                    session_key=session_key,
                    mentions=mentions,
                    emit=live.emit,
                    turn_id=live.turn_id,
                )
            except asyncio.CancelledError:
                await live.emit(
                    {
                        "type": "cancelled",
                        "operation": "message",
                        "content": "Partner Group turn cancelled.",
                    }
                )
                raise
            except Exception as exc:  # preserve a stable public failure frame
                await live.emit({"type": "error", "content": str(exc)[:500]})

        live.task = asyncio.create_task(run(), name=f"partner-group:{group_id}:{session_key}")
        self._track_live_turn(key, live)
        return live

    def start_live_invocation(
        self,
        group_id: str,
        *,
        invocation_id: str,
        session_key: str,
    ) -> LiveGroupTurn:
        """Start or reattach to an approved one-hop collaboration turn."""
        group = self._require(group_id)
        group_id = group.group_id
        session_key = _normalize_session_key(session_key)
        invocations = PartnerInvocationStore(self.store.group_dir(group.group_id))
        proposal = self._require_invocation(
            invocations,
            group=group,
            invocation_id=invocation_id,
            session_key=session_key,
        )
        key = self._live_key(group_id, session_key, f"invocation:{proposal.invocation_id}")
        previous = self._live_turns.get(key)
        if previous is not None:
            return previous
        if proposal.status not in {"pending", "approved"}:
            raise ValueError(f"Partner invocation is already {proposal.status}.")

        live = LiveGroupTurn(
            content=proposal.question,
            operation="invocation",
            invocation_id=proposal.invocation_id,
        )

        async def run() -> None:
            try:
                await self.approve_invocation(
                    group_id,
                    proposal.invocation_id,
                    session_key=session_key,
                    emit=live.emit,
                )
            except asyncio.CancelledError:
                await live.emit(
                    {
                        "type": "cancelled",
                        "operation": "invoke_other",
                        "invocation_id": proposal.invocation_id,
                        "content": "Partner invocation cancelled.",
                    }
                )
                raise
            except Exception as exc:
                await live.emit({"type": "error", "content": str(exc)[:500]})

        live.task = asyncio.create_task(
            run(),
            name=f"partner-group-invoke:{group_id}:{proposal.invocation_id}",
        )
        self._track_live_turn(key, live)
        return live

    def start_live_retry(
        self,
        group_id: str,
        *,
        turn_id: str,
        partner_id: str,
        session_key: str,
    ) -> LiveGroupTurn:
        """Start or reattach to one failed seat's retry operation."""
        group = self._require(group_id)
        group_id = group.group_id
        session_key = _normalize_session_key(session_key)
        transcript = GroupTranscriptStore(self.store.group_dir(group_id))
        self._require_retry_target(
            transcript,
            session_key=session_key,
            turn_id=turn_id,
            partner_id=partner_id,
        )
        operation_id = f"retry:{turn_id}:{partner_id}"
        key = self._live_key(group_id, session_key, operation_id)
        previous = self._live_turns.get(key)
        if previous is not None:
            return previous
        live = LiveGroupTurn(
            operation="retry_partner",
            turn_id=turn_id,
            partner_id=partner_id,
        )

        async def run() -> None:
            try:
                await self.retry_partner(
                    group_id,
                    turn_id,
                    partner_id,
                    session_key=session_key,
                    emit=live.emit,
                )
            except asyncio.CancelledError:
                await live.emit(
                    {
                        "type": "cancelled",
                        "operation": "retry_partner",
                        "turn_id": turn_id,
                        "partner_id": partner_id,
                        "content": "Partner retry cancelled.",
                    }
                )
                raise
            except Exception as exc:
                await live.emit({"type": "error", "content": str(exc)[:500]})

        live.task = asyncio.create_task(
            run(),
            name=f"partner-group-retry:{group_id}:{turn_id}:{partner_id}",
        )
        self._track_live_turn(key, live)
        return live

    def start_live_summary(
        self,
        group_id: str,
        *,
        turn_id: str,
        partner_id: str,
        session_key: str,
    ) -> LiveGroupTurn:
        """Start or reattach to one member's summary of a completed round."""
        group = self._require(group_id)
        group_id = group.group_id
        session_key = _normalize_session_key(session_key)
        turn_id = str(turn_id or "").strip()
        partner_id = str(partner_id or "").strip()
        self._require_summary_round(
            group,
            GroupTranscriptStore(self.store.group_dir(group_id)),
            session_key=session_key,
            turn_id=turn_id,
            partner_id=partner_id,
        )
        operation_id = f"summary:{turn_id}:{partner_id}"
        key = self._live_key(group_id, session_key, operation_id)
        previous = self._live_turns.get(key)
        if previous is not None:
            return previous
        live = LiveGroupTurn(
            operation="summarize_round",
            turn_id=turn_id,
            partner_id=partner_id,
        )

        async def run() -> None:
            try:
                await self.summarize_round(
                    group_id,
                    turn_id,
                    session_key=session_key,
                    partner_id=partner_id,
                    emit=live.emit,
                )
            except asyncio.CancelledError:
                await live.emit(
                    {
                        "type": "cancelled",
                        "operation": "summarize_round",
                        "turn_id": turn_id,
                        "partner_id": partner_id,
                        "content": "Partner Group round summary cancelled.",
                    }
                )
                raise
            except Exception as exc:
                await live.emit({"type": "error", "content": str(exc)[:500]})

        live.task = asyncio.create_task(
            run(),
            name=f"partner-group-summary:{group_id}:{turn_id}:{partner_id}",
        )
        self._track_live_turn(key, live)
        return live

    def subscribe_live_turn(self, group_id: str, session_key: str) -> LiveGroupTurn | None:
        """Compatibility accessor for the session's primary message turn."""
        group_id = self._require(group_id).group_id
        key = self._live_key(group_id, session_key, "message")
        return self._live_turns.get(key) or self._completed_turns.get(key)

    def subscribe_live_turns(self, group_id: str, session_key: str) -> list[LiveGroupTurn]:
        """Return all active operations, or the newest bounded replay."""
        group_id = self._require(group_id).group_id
        prefix = (get_current_user().id, group_id, _normalize_session_key(session_key))
        active = [live for key, live in self._live_turns.items() if key[:3] == prefix]
        if active:
            return sorted(active, key=lambda item: item.started_at)
        completed = [live for key, live in self._completed_turns.items() if key[:3] == prefix]
        return completed[-1:]

    def cancel_live_turn(
        self,
        group_id: str,
        session_key: str,
        *,
        invocation_id: str = "",
    ) -> LiveGroupTurn:
        """Cancel the selected or most recently started operation in a session."""
        group = self._require(group_id)
        group_id = group.group_id
        session_key = _normalize_session_key(session_key)
        prefix = (get_current_user().id, group_id, session_key)
        candidates = [
            live
            for key, live in self._live_turns.items()
            if key[:3] == prefix
            and (not invocation_id or live.invocation_id == invocation_id)
            and live.task is not None
            and not live.task.done()
            and not live.task.cancelling()
        ]
        if not candidates:
            raise LookupError("No Partner Group turn is currently running.")
        live = max(candidates, key=lambda item: item.started_at)
        assert live.task is not None
        if not live.task.cancel():
            raise LookupError("No Partner Group turn is currently running.")
        if live.operation == "message":
            marker = GroupMessage(
                event_id=uuid4().hex,
                turn_id=live.turn_id,
                session_key=session_key,
                role="system",
                content="",
                author_id="system",
                author_name="System",
                created_at=utc_now(),
                kind="round_stopped",
            )
            GroupTranscriptStore(self.store.group_dir(group_id)).append(marker)
            group.updated_at = marker.created_at
            self.store.save(group)
        return live

    def _live_key(
        self,
        group_id: str,
        session_key: str,
        operation_id: str,
    ) -> tuple[str, str, str, str]:
        return (
            get_current_user().id,
            group_id,
            _normalize_session_key(session_key),
            operation_id,
        )

    def _track_live_turn(
        self,
        key: tuple[str, str, str, str],
        live: LiveGroupTurn,
    ) -> None:
        """Move terminal turns out of the active map into a bounded replay LRU."""
        self._completed_turns.pop(key, None)
        self._live_turns[key] = live
        assert live.task is not None

        def archive(_task: asyncio.Task) -> None:
            if self._live_turns.get(key) is not live:
                return
            # Cancellation can win before the coroutine executes its handler.
            # Record a terminal frame synchronously so subscribers never hang.
            if _task.cancelled() and not live.done:
                live._record(
                    {
                        "type": "cancelled",
                        "operation": live.operation,
                        "invocation_id": live.invocation_id,
                        "content": "Partner Group turn cancelled.",
                    }
                )
            self._live_turns.pop(key, None)
            self._completed_turns[key] = live
            self._completed_turns.move_to_end(key)
            while len(self._completed_turns) > _LIVE_REPLAY_MAX_TURNS:
                self._completed_turns.popitem(last=False)

        live.task.add_done_callback(archive)

    def resolve_mentions(
        self,
        group: PartnerGroupConfig,
        content: str,
        mentions: list[str] | None,
        *,
        member_snapshot: GroupMemberSnapshot | None = None,
    ) -> MentionResolution:
        snapshot = member_snapshot or self._member_snapshot(group)

        if mentions is not None:
            raw_mentions = [_normalize_mention(value) for value in mentions]
        else:
            raw_mentions = [
                _normalize_mention(value) for value in _MENTION_PATTERN.findall(content)
            ]
        raw_mentions = [value for value in raw_mentions if value]
        if not raw_mentions:
            return MentionResolution(tuple(group.member_ids), ())

        all_aliases = {"all", "所有人", "全部"}
        unknown = tuple(
            dict.fromkeys(
                f"@{value}"
                for value in raw_mentions
                if value not in snapshot.aliases and value not in all_aliases
            )
        )
        if any(value in all_aliases for value in raw_mentions):
            targets = tuple(group.member_ids)
        else:
            targets = tuple(
                dict.fromkeys(
                    snapshot.aliases[value] for value in raw_mentions if value in snapshot.aliases
                )
            )
            # A typo should not discard the message. When nothing resolves, the
            # established no-mention behavior (@all) is the safest fallback.
            if not targets:
                targets = tuple(group.member_ids)
        return MentionResolution(targets, unknown)

    async def _run_partner_reply(
        self,
        *,
        group: PartnerGroupConfig,
        partner_id: str,
        content: str,
        session_key: str,
        turn_id: str,
        member_snapshot: GroupMemberSnapshot,
        public_context: str,
        invocation_store: PartnerInvocationStore,
        emit: GroupEmitter,
        actor: Any,
        event_id: str = "",
        retry: bool = False,
        extra_context: str = "",
        instruction: str = "",
        kind: str = "message",
        allow_invoke_other: bool = True,
    ) -> GroupMessage:
        """Run one seat while keeping trace forwarding and failure folding uniform."""
        partners = get_partner_manager()
        cfg = member_snapshot.configs.get(partner_id)
        name = cfg.name if cfg else partner_id
        turn_public_context = _append_round_context(public_context, extra_context)
        turn_content = _append_partner_instruction(content, partner_id, instruction)
        try:
            if cfg is None or not can_use_partner(partner_id):
                raise RuntimeError("Partner is unavailable")
            instance = partners.get_partner(partner_id)
            if instance is None or not instance.running:
                instance = await partners.start_partner(partner_id, cfg)

            async def forward_trace(event: Any) -> None:
                if event.type in {StreamEventType.DONE, StreamEventType.SESSION}:
                    return
                frame = {
                    "type": "partner_trace",
                    "turn_id": turn_id,
                    "partner_id": partner_id,
                    "partner_name": name,
                    "event": event.to_dict(),
                }
                if retry:
                    frame["retry"] = True
                await emit(frame)

            turn = await partners.send_group_message(
                partner_id,
                turn_content,
                session_key=f"group-{group.group_id}-{session_key}",
                group_id=group.group_id,
                group_name=group.name,
                group_members=[dict(member) for member in member_snapshot.members],
                public_context=turn_public_context,
                actor=actor,
                allow_invoke_other=allow_invoke_other,
                on_event=forward_trace,
            )
            if isinstance(turn, str):
                turn = PartnerGroupTurnResponse(content=turn)
            invocation = self._create_invocation(
                invocation_store,
                group=group,
                session_key=session_key,
                turn_id=turn_id,
                requester_partner_id=partner_id,
                proposal=turn.invocation,
                members=member_snapshot.members,
            )
            return GroupMessage(
                event_id=event_id or uuid4().hex,
                turn_id=turn_id,
                session_key=session_key,
                role="partner",
                content=turn.content,
                author_id=partner_id,
                author_name=name,
                created_at=utc_now(),
                kind=kind,
                events=turn.events,
                invocation_id=invocation.invocation_id if invocation else "",
                invocation=invocation.to_dict() if invocation else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # one panel member must not cancel the rest
            return GroupMessage(
                event_id=event_id or uuid4().hex,
                turn_id=turn_id,
                session_key=session_key,
                role="partner",
                content=str(exc)[:500] or "Partner failed to answer.",
                author_id=partner_id,
                author_name=name,
                created_at=utc_now(),
                error=True,
                kind=kind,
            )

    @staticmethod
    def _require_retry_target(
        transcript: GroupTranscriptStore,
        *,
        session_key: str,
        turn_id: str,
        partner_id: str,
    ) -> tuple[GroupMessage, GroupMessage]:
        messages = transcript.messages_for_turn(session_key, turn_id)
        user_message = next(
            (row for row in messages if row.turn_id == turn_id and row.role == "user"),
            None,
        )
        partner_message = next(
            (
                row
                for row in reversed(messages)
                if row.turn_id == turn_id and row.role == "partner" and row.author_id == partner_id
            ),
            None,
        )
        if user_message is None or partner_message is None:
            raise LookupError("Partner Group turn or seat not found")
        if not partner_message.error:
            raise ValueError("Only a failed Partner seat can be retried.")
        return user_message, partner_message

    def _require_summary_round(
        self,
        group: PartnerGroupConfig,
        transcript: GroupTranscriptStore,
        *,
        session_key: str,
        turn_id: str,
        partner_id: str,
    ) -> list[GroupMessage]:
        if partner_id not in group.member_ids:
            raise ValueError("Summary Partner is not a current Group member.")
        messages = transcript.messages_for_turn(session_key, turn_id)
        if not any(message.role == "user" for message in messages):
            raise LookupError("Partner Group round not found")
        owner_id = get_current_user().id
        if any(
            key[:3] == (owner_id, group.group_id, session_key)
            and live.operation == "message"
            and live.turn_id == turn_id
            and live.task is not None
            and not live.task.done()
            for key, live in self._live_turns.items()
        ):
            raise ValueError("Partner Group round is still in progress.")
        return [
            message
            for message in messages
            if message.kind not in {"round_summary", "round_stopped"}
        ]

    def _create_invocation(
        self,
        store: PartnerInvocationStore,
        *,
        group: PartnerGroupConfig,
        session_key: str,
        turn_id: str,
        requester_partner_id: str,
        proposal: dict[str, Any] | None,
        members: tuple[dict[str, str], ...],
    ) -> PartnerInvocation | None:
        """Validate tool metadata again at the orchestration trust boundary."""
        if not isinstance(proposal, dict):
            return None
        try:
            (
                requester_id,
                requester_name,
                target_id,
                target_name,
                question,
            ) = self._validate_invocation_request(
                group=group,
                requester_partner_id=requester_partner_id,
                target_partner_id=str(proposal.get("target_partner_id") or ""),
                question=str(proposal.get("question") or ""),
                members=members,
            )
        except ValueError:
            return None
        return self._save_invocation(
            store,
            group=group,
            session_key=session_key,
            parent_turn_id=turn_id,
            requester_partner_id=requester_id,
            requester_partner_name=requester_name,
            target_partner_id=target_id,
            target_partner_name=target_name,
            question=question,
        )

    @staticmethod
    def _validate_invocation_request(
        *,
        group: PartnerGroupConfig,
        requester_partner_id: str,
        target_partner_id: str,
        question: str,
        members: tuple[dict[str, str], ...],
    ) -> tuple[str, str, str, str, str]:
        requester_id = str(requester_partner_id or "").strip()
        target_id = str(target_partner_id or "").strip()
        normalized_question = str(question or "").strip()
        if requester_id not in group.member_ids:
            raise ValueError("Requester Partner is not a current Group member.")
        if target_id not in group.member_ids:
            raise ValueError("Target Partner is not a current Group member.")
        if requester_id == target_id:
            raise ValueError("Requester and target Partners must differ.")
        if not normalized_question:
            raise ValueError("Invocation question is required.")
        if len(normalized_question) > 2_000:
            raise ValueError("Invocation question must be at most 2000 characters.")
        names = {
            member["partner_id"]: member["name"] for member in members if member.get("partner_id")
        }
        return (
            requester_id,
            names.get(requester_id, requester_id),
            target_id,
            names.get(target_id, target_id),
            normalized_question,
        )

    @staticmethod
    def _save_invocation(
        store: PartnerInvocationStore,
        *,
        group: PartnerGroupConfig,
        session_key: str,
        parent_turn_id: str,
        requester_partner_id: str,
        requester_partner_name: str,
        target_partner_id: str,
        target_partner_name: str,
        question: str,
    ) -> PartnerInvocation:
        now = utc_now()
        invocation = PartnerInvocation(
            invocation_id=uuid4().hex,
            group_id=group.group_id,
            session_key=session_key,
            parent_turn_id=parent_turn_id,
            requester_partner_id=requester_partner_id,
            requester_partner_name=requester_partner_name,
            target_partner_id=target_partner_id,
            target_partner_name=target_partner_name,
            question=question,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        store.save(invocation)
        return invocation

    @staticmethod
    def _require_invocation(
        store: PartnerInvocationStore,
        *,
        group: PartnerGroupConfig,
        invocation_id: str,
        session_key: str,
    ) -> PartnerInvocation:
        try:
            invocation = store.get(invocation_id)
        except ValueError as exc:
            raise LookupError("Partner invocation not found") from exc
        if (
            invocation is None
            or invocation.group_id != group.group_id
            or invocation.session_key != session_key
        ):
            raise LookupError("Partner invocation not found")
        return invocation

    def _member_snapshot(self, group: PartnerGroupConfig) -> GroupMemberSnapshot:
        manager = get_partner_manager()
        members: list[dict[str, str]] = []
        configs: dict[str, Any] = {}
        aliases: dict[str, str] = {}
        for partner_id in group.member_ids:
            cfg = manager.load_config(partner_id)
            configs[partner_id] = cfg
            name = cfg.name if cfg else partner_id
            members.append(
                {
                    "partner_id": partner_id,
                    "name": name,
                    "description": cfg.description if cfg else "",
                }
            )
            aliases[partner_id.casefold()] = partner_id
            if name:
                aliases[name.casefold()] = partner_id
        return GroupMemberSnapshot(tuple(members), configs, aliases)

    def _render_public_context(
        self,
        group: PartnerGroupConfig,
        *,
        members: tuple[dict[str, str], ...],
        previous_transcript: str,
        shared_memory: str,
    ) -> str:
        roster = []
        for member in members:
            line = f"- {member['name']} (@{member['partner_id']})"
            if member.get("description"):
                line += f": {member['description']}"
            roster.append(line)
        context = (
            f"Group: {group.name}\nParallel panel members and positioning:\n"
            + "\n".join(roster)
            + "\n\n"
            "Public transcript before the current message:\n" + (previous_transcript or "(empty)")
        )
        if shared_memory:
            context += "\n\nUser-curated shared whiteboard:\n" + shared_memory
        return context

    def _render_shared_memory(self, group: PartnerGroupConfig) -> str:
        memory = shared_memory_registry.create(
            group.shared_memory, self.store.group_dir(group.group_id)
        )
        return memory.render()

    def describe_group(self, group: PartnerGroupConfig) -> dict[str, Any]:
        """Public config plus the currently visible member identity cards."""
        manager = get_partner_manager()
        members = []
        for partner_id in group.member_ids:
            cfg = manager.load_config(partner_id)
            if cfg is not None and can_use_partner(partner_id):
                members.append(
                    {
                        "partner_id": partner_id,
                        "name": cfg.name,
                        "description": cfg.description,
                        "emoji": cfg.emoji,
                        "color": cfg.color,
                        "avatar": cfg.avatar,
                        "running": bool(
                            manager.get_partner(partner_id)
                            and manager.get_partner(partner_id).running
                        ),
                    }
                )
        return {**group.to_dict(), "members": members}

    def _require(self, group_id: str) -> PartnerGroupConfig:
        group = self.get_group(group_id)
        if group is None:
            raise LookupError("Partner Group not found")
        return group

    @staticmethod
    def _validate_members(member_ids: list[str]) -> list[str]:
        manager = get_partner_manager()
        members = list(dict.fromkeys(str(item).strip() for item in member_ids if str(item).strip()))
        if len(members) < 2:
            raise ValueError("A Partner Group needs at least two members.")
        for partner_id in members:
            if not manager.partner_exists(partner_id) or not can_use_partner(partner_id):
                raise ValueError(f"Partner is unavailable: {partner_id}")
        return members

    @staticmethod
    def _color(value: Any) -> str:
        color = str(value or "#6366f1").strip()
        return color.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#6366f1"


# This singleton owns only process-local scheduling/replay state. Durable data
# always resolves through the request's user-scoped PathService; every live key
# includes owner id, and every public operation revalidates group ownership.
_manager = PartnerGroupManager()


def _normalize_session_key(value: str) -> str:
    return str(value or "default").strip()[:120] or "default"


def _normalize_mention(value: Any) -> str:
    return str(value or "").strip().lstrip("@").rstrip(".,，。:：;；!?！？").strip().casefold()


def get_partner_group_manager() -> PartnerGroupManager:
    """Return the process scheduler; request context remains the security boundary."""
    return _manager


__all__ = ["PartnerGroupManager", "get_partner_group_manager"]
