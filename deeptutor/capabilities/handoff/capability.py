"""Hand the turn over: a partner or a connected agent answers it, not DeepTutor.

Consulting (``deeptutor.capabilities.subagent``) keeps DeepTutor in charge: its
own chat loop calls the agent as a tool, then answers in its own voice, and the
agent's run is shown in a side panel. Handing over is the other choice a
learner can make — "let them answer this". The user's message goes to the
partner or agent unchanged, their reply *is* the answer, and their work is
written into the conversation the way DeepTutor's own is: each stretch of
writing a round, each tool a row between rounds, the last round the finish.

The two kinds of target arrive differently:

* A **partner** runs DeepTutor's chat loop under its own soul, library and
  memory, so its events are already in this protocol. They are forwarded as
  they are, minus the frames that belong to its own turn (stages, its result,
  its done), and tagged with who wrote them.
* A **connected agent** (Claude Code, Codex, …) speaks the subagent channel
  protocol: running text under merge ids, tool lines, results. That is turned
  into rounds and tool rows here.

Continuity reuses the consult registry: one partner session, or one agent
session, per DeepTutor conversation — shared with consulting, so switching
between asking and handing over keeps a single thread on their side.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field, replace
import logging
from typing import Any
import uuid

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata

logger = logging.getLogger(__name__)

SOURCE = "handoff"
STAGE = "responding"

# The partner's own turn frames: its stages would nest inside ours, and its
# result and done would end our turn early. Everything else is its work.
_PARTNER_DROPPED = frozenset(
    {
        StreamEventType.STAGE_START,
        StreamEventType.STAGE_END,
        StreamEventType.RESULT,
        StreamEventType.DONE,
        StreamEventType.SESSION,
    }
)

# Instruction for an agent answering in the learner's conversation, when the
# user has not written their own in /settings. The consult default tells the
# agent it is being questioned by DeepTutor; here it is talking to the user.
_HANDOFF_INSTRUCTION = (
    "You are answering the user directly inside their DeepTutor conversation, "
    "not in an interactive terminal. Your reply is shown to them as the answer. "
    "Work the request through, then answer clearly and completely. Do not wait "
    "for input; if something is ambiguous, state your assumption and proceed."
)


class HandoffError(RuntimeError):
    """The target could not take the turn; the message says why."""

    error_code = "handoff_failed"
    retryable = True


def parse_answer_by(value: str | None) -> tuple[str, str] | None:
    """``"partner:<id>"`` / ``"subagent:<connection>"`` → ``(kind, id)``."""
    kind, _, target = str(value or "").partition(":")
    target = target.strip()
    if kind in {"partner", "subagent"} and target:
        return kind, target
    return None


def _delegate(kind: str, target_id: str, name: str, **look: Any) -> dict[str, str]:
    """Who answers, as the transcript shows them: identity plus the small
    things that draw their mark (a partner's emoji and colour, an agent's
    kind). Never an uploaded picture — it rides on every event of the turn."""
    card = {"kind": kind, "id": target_id, "name": name or target_id}
    card.update({key: str(value) for key, value in look.items() if value})
    return card


def _delegate_meta(delegate: dict[str, str]) -> dict[str, str]:
    return {f"delegate_{key}": value for key, value in delegate.items()}


@dataclass
class _Writer:
    """Writes a delegate's run as rounds and tool rows on the turn's stream.

    A round is one stretch of writing. It opens with the first text or
    reasoning after a tool (or at the start) and closes as ``narration`` when a
    tool interrupts it, or as ``finish`` at the end — the shape the chat loop
    produces, so the transcript folds and persists it the same way.
    """

    stream: Any
    delegate: dict[str, str]
    round_id: str = ""
    rounds: int = 0
    wrote: bool = False
    answer: list[str] = field(default_factory=list)

    def _meta(self, call_id: str, **extra: Any) -> dict[str, Any]:
        return build_trace_metadata(
            call_id=call_id,
            phase=STAGE,
            label=self.delegate["name"],
            call_kind="agent_loop_round",
            trace_id=call_id,
            trace_role="response",
            trace_group="stage",
            **_delegate_meta(self.delegate),
            **extra,
        )

    async def _open(self) -> str:
        if not self.round_id:
            self.rounds += 1
            self.round_id = f"{SOURCE}-{uuid.uuid4().hex[:10]}"
            await self.stream.progress(
                self.delegate["name"],
                source=SOURCE,
                stage=STAGE,
                metadata=self._meta(self.round_id, trace_kind="call_status", call_state="running"),
            )
        return self.round_id

    async def close(self, role: str) -> None:
        if not self.round_id:
            return
        call_id, self.round_id = self.round_id, ""
        await self.stream.progress(
            self.delegate["name"],
            source=SOURCE,
            stage=STAGE,
            metadata=self._meta(
                call_id,
                trace_kind="call_status",
                call_state="complete",
                call_role=role,
                answer_visible=True,
            ),
        )

    async def text(self, delta: str) -> None:
        if not delta:
            return
        call_id = await self._open()
        self.wrote = True
        self.answer.append(delta)
        await self.stream.content(delta, source=SOURCE, stage=STAGE, metadata=self._meta(call_id))

    async def thinking(self, delta: str) -> None:
        if not delta.strip():
            return
        call_id = await self._open()
        await self.stream.thinking(delta, source=SOURCE, stage=STAGE, metadata=self._meta(call_id))

    async def tool(self, call_id: str, name: str, args: dict[str, Any]) -> None:
        await self.close("narration")
        meta = build_trace_metadata(
            call_id=call_id,
            phase=STAGE,
            label=name,
            call_kind="tool_planning",
            trace_id=call_id,
            trace_role="tool",
            trace_group="tool_call",
            tool_name=name,
            tool_call_id=call_id,
            **_delegate_meta(self.delegate),
        )
        await self.stream.tool_call(name, args, source=SOURCE, stage=STAGE, metadata=meta)
        await self.stream.progress(
            name,
            source=SOURCE,
            stage=STAGE,
            metadata=merge_trace_metadata(
                meta, {"trace_kind": "call_status", "call_state": "running"}
            ),
        )

    async def tool_result(self, call_id: str, name: str, body: str) -> None:
        meta = build_trace_metadata(
            call_id=call_id,
            phase=STAGE,
            label=name,
            call_kind="tool_planning",
            trace_id=call_id,
            trace_role="tool",
            trace_group="tool_call",
            tool_name=name,
            tool_call_id=call_id,
        )
        await self.stream.tool_result(name, body, source=SOURCE, stage=STAGE, metadata=meta)
        await self.stream.progress(
            name,
            source=SOURCE,
            stage=STAGE,
            metadata=merge_trace_metadata(
                meta, {"trace_kind": "call_status", "call_state": "complete"}
            ),
        )


class HandoffCapability(TurnCapability):
    manifest = CapabilityManifest(
        name=SOURCE,
        description="A partner or a connected agent answers the turn in DeepTutor's place.",
        stages=[STAGE],
    )

    async def run(self, context: UnifiedContext, stream: Any) -> None:
        target = parse_answer_by(context.runtime.answer_by)
        if target is None:
            raise HandoffError(f"Nobody to hand this turn to: {context.runtime.answer_by!r}")
        kind, target_id = target
        async with stream.stage(STAGE, source=SOURCE):
            if kind == "partner":
                writer, reply = await self._partner(context, stream, target_id)
            else:
                writer, reply = await self._subagent(context, stream, target_id)
            if reply and not writer.wrote:
                # Nothing streamed as text (a degenerate run): the reply is
                # still the answer, so it is written as the finishing round.
                await writer.text(reply)
            await writer.close("finish")
        await emit_capability_result(
            stream,
            {
                "response": reply or "".join(writer.answer),
                "metadata": {"answered_by": dict(writer.delegate)},
            },
            source=SOURCE,
        )

    # ── Partner ──────────────────────────────────────────────────────────

    async def _partner(
        self, context: UnifiedContext, stream: Any, partner_id: str
    ) -> tuple[_Writer, str]:
        from deeptutor.multi_user.partner_access import (
            assert_partner_allowed,
            visible_partner_cards,
        )
        from deeptutor.services.partners import get_partner_manager

        try:
            assert_partner_allowed(partner_id)
        except Exception as exc:
            raise HandoffError(str(getattr(exc, "detail", None) or exc)) from exc
        card = next((p for p in visible_partner_cards() if p["partner_id"] == partner_id), None)
        card = card or {}
        writer = _Writer(
            stream,
            _delegate(
                "partner",
                partner_id,
                str(card.get("name") or ""),
                emoji=card.get("emoji"),
                color=card.get("color"),
            ),
        )
        manager = get_partner_manager()
        if not manager.partner_exists(partner_id):
            raise HandoffError(f"Partner '{partner_id}' no longer exists.")
        instance = manager.get_partner(partner_id)
        if instance is None or not instance.running:
            try:
                await manager.start_partner(partner_id)
            except Exception as exc:
                raise HandoffError(f"Could not start partner '{partner_id}': {exc}") from exc

        registry_key, session_key = _session(context, f"partner:{partner_id}")
        session_key = session_key or f"dt-{uuid.uuid4().hex[:12]}"
        if registry_key:
            from deeptutor.services.subagent.sessions import remember_session

            remember_session(registry_key, session_key, kind="partner")

        # A reply the learner is still waiting on in the partner's own chat must
        # finish first; this message would otherwise be mistaken for its answer.
        existing = manager.subscribe_web_turn(partner_id, session_key)
        if existing is not None and existing.task is not None:
            with suppress(asyncio.CancelledError):
                await asyncio.shield(existing.task)

        image_dir, images = _stage_images(context)
        live = manager.start_web_turn(partner_id, session_key, context.user_message, media=images)
        queue = live.subscribe()
        reply = ""
        try:
            while True:
                frame = await queue.get()
                kind = frame.get("type")
                if kind == "stream_event":
                    await self._relay_partner(writer, stream, frame["event"])
                elif kind == "content":
                    reply = str(frame.get("content") or "")
                elif kind == "error":
                    raise HandoffError(str(frame.get("content") or "The partner could not answer."))
                elif kind == "stopped":
                    raise HandoffError("The partner stopped before answering.")
                elif kind == "done":
                    break
        except asyncio.CancelledError:
            if live.task is not None and not live.task.done():
                live.task.cancel()
                with suppress(asyncio.CancelledError):
                    await live.task
            raise
        finally:
            live.subscribers.discard(queue)
            _drop_images(image_dir)
        return writer, reply.strip()

    async def _relay_partner(self, writer: _Writer, stream: Any, raw: dict[str, Any]) -> None:
        """Forward one of the partner's own events, as its own work."""
        try:
            etype = StreamEventType(raw.get("type"))
        except ValueError:
            return
        if etype in _PARTNER_DROPPED:
            return
        metadata = dict(raw.get("metadata") or {})
        metadata.update(_delegate_meta(writer.delegate))
        content = str(raw.get("content") or "")
        if etype == StreamEventType.CONTENT and metadata.get("call_kind") in {
            "agent_loop_round",
            "llm_final_response",
        }:
            writer.wrote = True
            writer.answer.append(content)
        if etype == StreamEventType.ERROR:
            # The partner's turn reports its own failure through the frame
            # stream; a mid-run error event here is part of its trace.
            metadata.pop("turn_terminal", None)
        await stream.emit(
            StreamEvent(
                type=etype,
                source=SOURCE,
                stage=STAGE,
                content=content,
                metadata=metadata,
            )
        )

    # ── Connected agent ──────────────────────────────────────────────────

    async def _subagent(
        self, context: UnifiedContext, stream: Any, connection: str
    ) -> tuple[_Writer, str]:
        from deeptutor.knowledge.kb_types import SUBAGENT_KB_TYPE
        from deeptutor.multi_user.knowledge_access import resolve_kb_metadata
        from deeptutor.services.subagent import get_backend, load_subagent_settings
        from deeptutor.services.subagent.sessions import remember_session

        meta = resolve_kb_metadata(connection)
        if not meta or meta.get("type") != SUBAGENT_KB_TYPE:
            raise HandoffError(f"'{connection}' is not a connected agent you can use.")
        kind = str(meta.get("agent_kind") or "").strip()
        backend = get_backend(kind) if kind and kind != "partner" else None
        if backend is None:
            raise HandoffError(f"No agent backend for '{connection}' ({kind or 'unknown'}).")
        name = str(meta.get("name") or connection)
        cwd = str(meta.get("cwd") or "").strip()
        writer = _Writer(stream, _delegate("subagent", connection, name, agent=kind))

        settings = load_subagent_settings()
        config = settings.backend(kind)
        if not config.system_prompt.strip():
            config = replace(config, system_prompt=_HANDOFF_INSTRUCTION)
        registry_key, session_id = _session(context, name)
        image_dir, images = (
            _stage_images(context) if getattr(config, "forward_images", False) else (None, [])
        )
        relay = _AgentRelay(writer)
        try:
            result = await backend.consult(
                context.user_message,
                on_event=relay,
                cwd=cwd or None,
                session_id=session_id,
                config=config,
                images=images or None,
            )
        finally:
            _drop_images(image_dir)
        await relay.flush()
        if result.session_id and registry_key:
            remember_session(registry_key, result.session_id, kind=kind, cwd=cwd)
        reply = (result.final_text or "").strip()
        if not reply and not writer.wrote:
            raise HandoffError(result.error or f"{name} produced no answer.")
        return writer, reply


class _AgentRelay:
    """Turns subagent channel events into rounds and tool rows.

    Text and reasoning arrive as the running full text of one block (keyed by
    ``merge_id``); only what is new is written. Tool lines are rows; a result
    belongs to the oldest call still waiting for one.
    """

    def __init__(self, writer: _Writer) -> None:
        self.writer = writer
        self.seen: dict[str, str] = {}
        self.open_tools: list[tuple[str, str]] = []
        self.tool_names: dict[str, str] = {}
        self.blocks = 0

    async def __call__(self, event: Any) -> None:
        from deeptutor.services.subagent.types import (
            EVENT_ERROR,
            EVENT_REASONING,
            EVENT_TEXT,
            EVENT_TOOL,
            EVENT_TOOL_RESULT,
        )

        text = str(getattr(event, "text", "") or "")
        kind = getattr(event, "kind", "")
        merge = str((getattr(event, "meta", None) or {}).get("merge_id") or "")
        if kind in {EVENT_TEXT, EVENT_REASONING}:
            delta = self._delta(f"{kind}:{merge}" if merge else "", text)
            if kind == EVENT_TEXT:
                await self.writer.text(delta)
            else:
                await self.writer.thinking(delta)
        elif kind == EVENT_TOOL and text.strip():
            if merge and any(key == merge for key, _ in self.open_tools):
                return  # a start/finish pair of one call: the row exists
            name, _, rest = text.strip().partition(" ")
            name = name.rstrip(":") or "tool"
            call_id = f"{SOURCE}-tool-{uuid.uuid4().hex[:10]}"
            self.open_tools.append((merge or call_id, call_id))
            self.tool_names[call_id] = name
            await self.writer.tool(call_id, name, {"input": rest.strip()} if rest.strip() else {})
        elif kind == EVENT_TOOL_RESULT:
            if not self.open_tools:
                return
            _, call_id = self.open_tools.pop(0)
            await self.writer.tool_result(call_id, self.tool_names.pop(call_id, "tool"), text)
        elif kind == EVENT_ERROR and text.strip():
            await self.writer.stream.error(
                text.strip(),
                source=SOURCE,
                stage=STAGE,
                metadata=_delegate_meta(self.writer.delegate),
            )

    def _delta(self, key: str, running: str) -> str:
        """What ``running`` adds to what this block already wrote."""
        if not key:
            # No block identity: each event is a block of its own.
            self.blocks += 1
            key = f"block:{self.blocks}"
        previous = self.seen.get(key)
        self.seen[key] = running
        if previous is None:
            # A new block after earlier writing starts a new paragraph.
            return ("\n\n" if self.writer.wrote and running else "") + running
        if running.startswith(previous):
            return running[len(previous) :]
        return ""

    async def flush(self) -> None:
        """Close calls the agent never reported a result for."""
        while self.open_tools:
            _, call_id = self.open_tools.pop(0)
            await self.writer.tool_result(call_id, self.tool_names.pop(call_id, "tool"), "")


def _session(context: UnifiedContext, connection: str) -> tuple[str, str | None]:
    """The cross-turn registry key for this conversation, and its session id."""
    from deeptutor.services.subagent.sessions import get_session, session_key

    chat_sid = str(getattr(context, "session_id", "") or "")
    if not chat_sid:
        return "", None
    key = session_key(chat_sid, connection)
    return key, get_session(key)


def _stage_images(context: UnifiedContext) -> tuple[str | None, list[str]]:
    from deeptutor.capabilities.subagent.tools import _stage_images as stage

    images = [a for a in (context.attachments or []) if getattr(a, "type", "") == "image"]
    return stage(images)


def _drop_images(directory: str | None) -> None:
    if directory:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)


__all__ = ["HandoffCapability", "HandoffError", "parse_answer_by"]
