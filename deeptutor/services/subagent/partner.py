"""Partner backend — consult one of the user's own partners as a subagent.

Unlike the local-CLI backends (Claude Code / Codex) this drives no subprocess:
it puts the question to a running partner through the partner manager's web
entry point, exactly as if the user opened a new session on the partner page.
The partner answers with its own chat loop — its soul, library and skills — and
streams its native trace back, which we map onto the coarse subagent event
channels so the sidebar renders it like any other consulted agent.

Session continuity is the whole point of the design. ``session_id`` here IS the
*partner session key*. The first consult of a DeepTutor chat session has none,
so we mint a fresh ``dt-…`` key and return it; the cross-turn registry
(:mod:`deeptutor.services.subagent.sessions`) remembers it against
(chat session, connection), so every later consult in the same DeepTutor chat —
within one turn or across turns — resumes the SAME partner session. The partner
page then sees one complete history session per DeepTutor chat, titled from the
first consult's question.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
import uuid

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

if TYPE_CHECKING:  # avoid importing the core/partner packages at module load
    from deeptutor.core.stream import StreamEvent

logger = logging.getLogger(__name__)

PARTNER_BACKEND_KIND = "partner"

# Cap on how much of a tool-call's args / a tool result we echo into the trace
# line — keeps the sidebar readable without dropping the event.
_MAX_LINE_CHARS = 600


class PartnerBackend(SubagentBackend):
    """Consult one of the user's partners as a delegate, in-process."""

    kind = PARTNER_BACKEND_KIND
    display_name = "Partner"
    cli_command = ""
    local_cli = False

    async def detect(self) -> DetectResult:
        # Partners are a built-in feature, not a machine-local CLI: ``available``
        # only gates the connect-CLI modal, which this backend deliberately sits
        # out (partners are connected from the partner list instead).
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=False,
            detail="Partners are connected from your partner list, not detected on this machine.",
        )

    async def consult(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None = None,  # noqa: ARG002 — CLI-only; partners have no cwd
        session_id: str | None = None,
        config: BackendConfig | None = None,  # noqa: ARG002 — partner runs its own soul
        images: list[str] | None = None,
        partner_id: str | None = None,
    ) -> ConsultResult:
        pid = str(partner_id or "").strip()
        if not pid:
            return ConsultResult(success=False, error="No partner is bound to this connection.")

        from deeptutor.services.partners import get_partner_manager

        manager = get_partner_manager()
        if not manager.partner_exists(pid):
            return ConsultResult(success=False, error=f"Partner '{pid}' no longer exists.")

        # Bring the partner online if it isn't already (auto-start partners are).
        instance = manager.get_partner(pid)
        if instance is None or not instance.running:
            try:
                await manager.start_partner(pid)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to start partner %s for consult: %s", pid, exc)
                return ConsultResult(success=False, error=f"Could not start partner '{pid}': {exc}")

        # ``session_id`` is the partner session key. None on the first consult of
        # a DeepTutor chat → mint a stable, colon-free key; the registry threads
        # it through every later consult so they all land in one partner session.
        session_key = str(session_id or "").strip() or f"dt-{uuid.uuid4().hex[:12]}"

        events = 0
        # Per-stream state shared across the loop's events:
        # - text/reason: the chat loop streams CONTENT/THINKING as *incremental*
        #   deltas; we accumulate per call_id and emit the running full text (the
        #   CLI backends do the same) so the row grows instead of being wiped by
        #   each chunk.
        # - pending_tools: the loop dispatches tools in PARALLEL — all TOOL_CALL
        #   events, then all TOOL_RESULT events — so a call and its result aren't
        #   adjacent. We hold each call (keyed by its call_id, shared with its
        #   result) and emit it back-to-back with its result, so the trace reads
        #   as call → result pairs.
        state: dict[str, dict[str, str]] = {
            "text": {},
            "reason": {},
            "pending_tools": {},
        }

        async def relay(event: "StreamEvent") -> None:
            nonlocal events
            for out in _to_subagent_events(event, state):
                events += 1
                await on_event(out)

        try:
            reply = await manager.send_message(
                pid,
                question,
                session_key=session_key,
                media=list(images or []),
                on_event=relay,
            )
        except Exception as exc:  # pragma: no cover - defensive: surface, don't crash the turn
            logger.warning("Partner consult failed (%s): %s", pid, exc, exc_info=True)
            return ConsultResult(
                session_id=session_key, success=False, error=str(exc), event_count=events
            )

        # Defensive: surface any tool call that never produced a result event so
        # it isn't silently lost (every tool normally emits one).
        for label in state["pending_tools"].values():
            events += 1
            await on_event(SubagentEvent(EVENT_TOOL, label))

        reply = (reply or "").strip()
        return ConsultResult(
            final_text=reply,
            session_id=session_key,
            success=bool(reply),
            event_count=events,
            error="" if reply else "the partner produced no reply",
        )


def _to_subagent_events(
    event: "StreamEvent",
    state: dict[str, dict[str, str]],
) -> list[SubagentEvent]:
    """Map a partner chat-loop ``StreamEvent`` to zero or more subagent events.

    Renders the partner's run like the CLI backends do — a tool call, its result,
    streamed thinking and the streamed answer — so the sidebar reads as a faithful
    transcript:

    * ``CONTENT`` / ``THINKING`` arrive as incremental deltas, so we accumulate
      per ``call_id`` (in ``state``) and emit the running full text under a
      per-stream ``merge_id`` (the row grows in place, never overwritten by a
      single chunk).
    * A ``TOOL_CALL`` (name + args/query) and its ``TOOL_RESULT`` share a
      ``call_id`` in the loop, but the loop dispatches tools in parallel, so the
      calls and results don't interleave. We hold each call in
      ``state["pending_tools"]`` and emit it immediately before its result, as
      two adjacent rows — so every result sits under the call it belongs to.
    * Pure status/bookkeeping (``PROGRESS`` call-status, ``RESULT`` marker,
      ``DONE``/``SESSION*``) carries no trace value and is dropped.
    """
    from deeptutor.core.stream import StreamEventType

    meta = event.metadata or {}
    call_id = str(meta.get("call_id") or "")
    text = event.content or ""
    etype = event.type
    pending = state["pending_tools"]

    if etype == StreamEventType.CONTENT:
        if not text:
            return []
        running = state["text"][call_id] = state["text"].get(call_id, "") + text
        merge = {"merge_id": f"text:{call_id}"} if call_id else {}
        return [SubagentEvent(EVENT_TEXT, running, meta=merge)]
    if etype == StreamEventType.THINKING:
        if not text.strip():
            return []
        running = state["reason"][call_id] = state["reason"].get(call_id, "") + text
        merge = {"merge_id": f"reason:{call_id}"} if call_id else {}
        return [SubagentEvent(EVENT_REASONING, running, meta=merge)]
    if etype == StreamEventType.TOOL_CALL:
        name = text.strip() or str(meta.get("tool_name") or "tool")
        args = _compact(meta.get("args"))
        label = f"{name} {args}" if args else name
        if call_id:
            # Defer: emit it right before its result so the pair stays adjacent.
            pending[call_id] = label
            return []
        return [SubagentEvent(EVENT_TOOL, label)]
    if etype == StreamEventType.TOOL_RESULT:
        out = _flush_pending_call(pending, call_id)
        body = text.strip()
        if body:
            out.append(SubagentEvent(EVENT_TOOL_RESULT, _truncate(body)))
        return out
    if etype == StreamEventType.ERROR:
        # An error can close out a pending tool call — surface the call first.
        out = _flush_pending_call(pending, call_id)
        if text.strip():
            out.append(SubagentEvent(EVENT_ERROR, text.strip()))
        return out
    # PROGRESS (call-status duplicates the tool rows), RESULT (final answer,
    # returned separately), SOURCES, DONE, SESSION* and WAIT_FOR_INPUT carry no
    # trace value here.
    return []


def _flush_pending_call(pending: dict[str, str], call_id: str) -> list[SubagentEvent]:
    """Emit (and clear) the buffered tool-call row for ``call_id``, if any."""
    label = pending.pop(call_id, "") if call_id else ""
    return [SubagentEvent(EVENT_TOOL, label)] if label else []


def _compact(args: object) -> str:
    if not args:
        return ""
    import json

    try:
        text = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
    except (TypeError, ValueError):
        text = str(args)
    return _truncate(text.strip())


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_LINE_CHARS else text[: _MAX_LINE_CHARS - 1] + "…"


__all__ = ["PARTNER_BACKEND_KIND", "PartnerBackend"]
