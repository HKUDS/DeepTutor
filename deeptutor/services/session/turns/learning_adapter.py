"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.trace import build_trace_metadata

if TYPE_CHECKING:
    from deeptutor.learning.storage import MasteryPathLease
    from deeptutor.services.session.protocol import SessionStoreProtocol

    from .._turn_runtime_shared import _TurnExecution


logger = logging.getLogger(__name__)


def _turn_taught_this_point(
    events: list[dict[str, Any]], knowledge_point_id: str
) -> bool:
    """Whether the turn actually taught or cleared this objective.

    Two things count, and both are already in the turn's own event trace: the
    gate was cleared for this point, or an explanation for it was recorded.
    Merely mentioning the point does not — a reply that says "let's move on to
    X" must not produce a lecture for X out of nothing.
    """
    point = str(knowledge_point_id or "").strip()
    if not point:
        return False
    for event in events:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            continue
        tool_metadata = metadata.get("tool_metadata")
        containers = [metadata] + ([tool_metadata] if isinstance(tool_metadata, dict) else [])
        for container in containers:
            grade = container.get("mastery_grade")
            if isinstance(grade, dict) and grade.get("mastered"):
                if str(grade.get("knowledge_point_id") or "") in {"", point}:
                    return True
            assess = container.get("mastery_assess")
            if isinstance(assess, dict) and assess.get("mastered"):
                if str(assess.get("knowledge_point_id") or "") in {"", point}:
                    return True
            noted = container.get("mastery_note_explained")
            if isinstance(noted, dict):
                if str(noted.get("knowledge_point_id") or "") in {"", point}:
                    return True
    return False


class LearningTurnAdapter:
    if TYPE_CHECKING:
        store: SessionStoreProtocol
        _lock: asyncio.Lock
        _executions: dict[str, _TurnExecution]

        async def _publish_live_event(
            self,
            execution: _TurnExecution,
            event: StreamEvent,
        ) -> dict[str, Any]: ...

        async def cancel_turn(self, turn_id: str) -> bool: ...

    async def _is_awaiting_user_reply(self, turn_id: str) -> bool:
        async with self._lock:
            execution = self._executions.get(turn_id)
            return execution is not None and execution.awaiting_user_reply

    async def _release_superseded_lease(self, path_id: str, lease: MasteryPathLease) -> None:
        """Free ``lease`` when its turn can no longer be working on the path.

        Three cases release it. A turn that is no longer live (finished) is
        simply gone. A turn whose worker died left a ``running`` row and no
        owner: reading only the durable row would call it busy forever, which
        is how one crashed turn locks the whole path. A turn parked inside
        ``ask_user`` is alive but idle — it holds the lease for as long as the
        learner takes to answer, which may be forever. Since the posed question
        is persisted on the path itself, the arriving turn resumes exactly
        where the parked one stopped, so handing the path over loses nothing;
        the parked turn is cancelled rather than left to mutate a path it no
        longer owns. Only a turn that is actively generating keeps the lease.
        """
        from deeptutor.learning.storage import LearningStore
        from deeptutor.services.session.orphan_turns import reap_orphaned_turn

        leased_turn = await self.store.get_turn(lease.turn_id)
        status = str((leased_turn or {}).get("status") or "")
        # A live row is only proof of a live worker while some worker still
        # holds that turn's own lease. A restart leaves the row behind and
        # drops the lease, and nothing else would ever move it off ``running``
        # for this path: the recovery pass only fails rows it can see expired,
        # and this lease outlives every one of those passes.
        if status in {"running", "waiting_input"} and self.coordinator is not None:
            if await self.coordinator.get_lease(lease.turn_id) is None:
                await reap_orphaned_turn(self.store, self.coordinator, lease.turn_id)
                leased_turn = await self.store.get_turn(lease.turn_id)
                status = str((leased_turn or {}).get("status") or "")

        # ``waiting_input`` is the durable shape of a parked ``ask_user`` turn.
        # It is alive but not generating, so it is the one live status this may
        # take over — and the in-memory flag covers turns parked before the row
        # was moved.
        parked = status == "waiting_input" or await self._is_awaiting_user_reply(
            lease.turn_id
        )
        if status in {"running", "waiting_input"}:
            if not parked:
                # Genuinely busy — leave the lease, and let the store report
                # the conflict to the caller.
                return
            if not await self.cancel_turn(lease.turn_id) and not await self._stop_remote_turn(
                lease.turn_id
            ):
                # The parked turn belongs to another worker that would not
                # stop. Handing the path over would let it resume and write to
                # a path it no longer holds, so the conflict is the honest
                # answer here.
                raise RuntimeError(
                    "mastery_path_busy: "
                    f"path {path_id!r} is already active in session {lease.session_id!r}"
                )
        # Scoped to the superseded turn id, so a lease already re-taken by
        # someone else survives.
        await asyncio.to_thread(
            LearningStore().release_path_lease,
            path_id,
            turn_id=lease.turn_id,
        )

    async def _stop_remote_turn(self, turn_id: str, *, timeout_seconds: float = 5.0) -> bool:
        """Cancel a turn owned by another worker and wait for it to settle.

        A parked turn's worker is the only thing that can unwind it, and it
        unwinds through the coordinator's command queue. Waiting matters: the
        caller releases a path lease on the strength of this answer, so
        returning before the row has left the live set would hand the path to a
        turn that is still about to wake up.
        """
        if self.coordinator is None:
            return False
        with contextlib.suppress(Exception):
            await self.coordinator.submit_command(turn_id, "cancel", {})
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            turn = await self.store.get_turn(turn_id)
            if turn is None or str(turn.get("status") or "") not in {
                "queued",
                "running",
                "waiting_input",
            }:
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def _commit_mastery_card_answer(
        self,
        *,
        path_id: str,
        session_id: str,
        turn_id: str,
        question_id: str,
        answer: str,
        answers: dict[str, str] | None = None,
    ) -> None:
        """Record an answer submitted from a card that outlived its turn.

        Posing a question ends the turn, so the answer comes back as the next
        turn's message rather than through a parked turn's reply queue.
        Committing it here — before the tutor's first token — is what lets
        ``mastery_status`` report the interaction as ``answered`` carrying the
        learner's own words, so the model grades what they actually picked
        instead of having to pair a bare "C" with a question from scrollback.

        Best-effort by design: the answer is also in the message the learner
        sent and the tutor can still grade it from there, so a stale card or a
        storage hiccup must not sink the turn.
        """
        from deeptutor.learning.service import LearningService

        def _commit() -> None:
            LearningService().record_question_answer(
                path_id,
                answer,
                interaction_id=question_id,
                session_id=session_id,
                turn_id=turn_id,
                **({"answers": answers} if answers is not None else {}),
            )

        try:
            await asyncio.to_thread(_commit)
        except Exception:
            logger.warning(
                "Failed to commit mastery card answer for path %s question %s",
                path_id,
                question_id,
                exc_info=True,
            )

    async def _grade_submitted_card_answer(
        self,
        execution: _TurnExecution,
        *,
        path_id: str,
        mode: str,
        knowledge_point_id: str,
        answer: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Rule on a card answer now, before the tutor writes a word.

        Everything the card needs to show a verdict is already server-side:
        the expected label and the explanation were registered when the
        question was posed. Waiting for the tutor to call ``mastery_grade``
        left the learner looking at their own pick for as long as a full LLM
        round took — half a minute, for a ruling that takes milliseconds and
        was never the model's to make.

        The verdict is published as the ``mastery_grade`` tool result the card
        already reads, so it renders with no client change and persists with
        the turn (a reload still shows it). The tutor's own grade call later in
        the turn replays the same committed attempt rather than scoring twice.

        Best-effort: an answer that cannot be graded — a stale card, an
        unreadable pick — leaves the interaction as it was for the tutor to
        sort out, and never sinks the turn.
        """
        question_id = str((answer or {}).get("question_id") or "").strip()
        text = str((answer or {}).get("text") or "")
        answers = (answer or {}).get("answers")
        if not path_id or not question_id or (not text and answers is None):
            return None
        # Grading is one deterministic engine operation and this tool is its
        # only entry point; calling it here keeps that logic in one place
        # rather than growing a second copy on the runtime side.
        from deeptutor.capabilities.mastery.tools import MasteryGradeTool

        try:
            result = await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                _session_id=execution.session_id,
                _turn_id=execution.turn_id,
                # The placed objective, so a card belonging to a different
                # objective is refused rather than clearing the wrong gate.
                _mastery_session_mode=mode,
                _mastery_knowledge_point_id=knowledge_point_id,
                question_id=question_id,
                **({"answers": answers} if answers is not None else {"answer": text}),
            )
        except Exception:
            logger.warning(
                "Failed to grade mastery card answer for path %s question %s",
                path_id,
                question_id,
                exc_info=True,
            )
            await self._publish_mastery_group_rejection(execution, question_id)
            return None
        payload = (result.metadata or {}).get("mastery_grade")
        if not result.success or not isinstance(payload, dict):
            foreign = (result.metadata or {}).get("mastery_foreign_question")
            await self._publish_mastery_group_rejection(
                execution,
                question_id,
                message=(
                    "This question belongs to another section of the course. "
                    "Open that section's session to answer it."
                    if isinstance(foreign, dict)
                    else ""
                ),
            )
            return None
        # One complete trace group, the same shape the dispatcher emits for a
        # tool the model called: a lone result with no terminal status renders
        # as a row that never stops running.
        call_id = f"mastery-grade-{execution.turn_id}-{question_id}"
        trace_meta = build_trace_metadata(
            call_id=call_id,
            phase="grading",
            label="Mastery Grade",
            call_kind="tool_call",
            trace_id=call_id,
            tool="mastery_grade",
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source="mastery",
                stage="grading",
                content=result.content,
                metadata={
                    **trace_meta,
                    "trace_kind": "tool_result",
                    "tool_metadata": {"mastery_grade": payload},
                },
            ),
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source="mastery",
                stage="grading",
                content="",
                metadata={
                    **trace_meta,
                    "trace_kind": "call_status",
                    "call_state": "complete",
                },
            ),
        )
        return payload

    async def _publish_mastery_group_rejection(
        self, execution: _TurnExecution, question_id: str, *, message: str = ""
    ) -> None:
        """Reopen an optimistically submitted card without fabricating a verdict.

        *message* replaces the generic "could not be submitted" line when the
        caller knows why — a card from another objective is not a submission
        failure, and telling the learner to retry it would be wrong.
        """
        call_id = f"mastery-grade-{execution.turn_id}-{question_id}"
        trace = build_trace_metadata(
            call_id=call_id,
            phase="grading",
            label="Mastery Grade",
            call_kind="tool_call",
            trace_id=call_id,
            tool="mastery_grade",
        )
        message = message or "These answers could not be submitted. Please review or retry."
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source="mastery",
                stage="grading",
                content=message,
                metadata={
                    **trace,
                    "trace_kind": "tool_result",
                    "tool_metadata": {
                        "mastery_answer_rejected": {"question_id": question_id, "message": message}
                    },
                },
            ),
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source="mastery",
                stage="grading",
                content="",
                metadata={**trace, "trace_kind": "call_status", "call_state": "error"},
            ),
        )

    async def _skip_card_question(
        self,
        execution: _TurnExecution,
        *,
        path_id: str,
        skip: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Drop the question the learner declined, before the tutor starts.

        A posed question ends its turn and stays open on the path, so a learner
        who does not want to answer it had no way past it: the engine holds one
        open question, and the tutor's next ``mastery_quiz`` simply re-presents
        the same card. Abandoning it here — the same place a card answer is
        graded — means the tutor's first ``mastery_status`` already sees a path
        with nothing pending, and can move on without being told to.

        Scoped to the question the card named: by the time this runs, an open
        question that is *not* the one on the learner's card is one they never
        declined.

        Best-effort, like grading: a stale card must not sink the turn.
        """
        question_id = str((skip or {}).get("question_id") or "").strip()
        if not path_id or not question_id:
            return None
        from deeptutor.capabilities.mastery.tools import MasterySkipQuestionTool
        from deeptutor.learning.service import LearningService

        try:
            service = await asyncio.to_thread(LearningService)
            active = await asyncio.to_thread(service.store.get_active_interaction, path_id)
            if active is None or active.interaction_id != question_id:
                # Already answered, already skipped, or superseded. Nothing to
                # drop, and nothing the card can be told that it does not
                # already show.
                return None
            result = await MasterySkipQuestionTool().execute(
                _mastery_path_id=path_id,
                _session_id=execution.session_id,
                _turn_id=execution.turn_id,
            )
        except Exception:
            logger.warning(
                "Failed to skip mastery card question for path %s question %s",
                path_id,
                question_id,
                exc_info=True,
            )
            return None
        payload = (result.metadata or {}).get("mastery_skip_question")
        if not result.success or not isinstance(payload, dict):
            return None
        # The tool reports the interaction it dropped; the card matches on the
        # id it was posed with, which is the same value. Stated explicitly so
        # the card can find its own verdict without trusting that.
        payload = {**payload, "question_id": question_id}
        call_id = f"mastery-skip-{execution.turn_id}-{question_id}"
        trace_meta = build_trace_metadata(
            call_id=call_id,
            phase="grading",
            label="Mastery Skip",
            call_kind="tool_call",
            trace_id=call_id,
            tool="mastery_skip_question",
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source="mastery",
                stage="grading",
                content=result.content,
                metadata={
                    **trace_meta,
                    "trace_kind": "tool_result",
                    "tool_metadata": {"mastery_skip_question": payload},
                },
            ),
        )
        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source="mastery",
                stage="grading",
                content="",
                metadata={
                    **trace_meta,
                    "trace_kind": "call_status",
                    "call_state": "complete",
                },
            ),
        )
        return payload

    async def _roll_mastery_lecture_draft(
        self,
        execution: _TurnExecution,
        *,
        path_id: str,
        mode: str,
        knowledge_point_id: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Keep a study point's lecture draft in step with what was just taught.

        Deliberately server-side and deterministic rather than another tool the
        model has to remember. A tutor that has just spent a long turn teaching
        is exactly the model least likely to end by summarising itself, and the
        failure is silent: review simply has nothing to show. So the condition
        is a comparison the engine can make — did this turn clear the point's
        gate, or add teaching past the draft's watermark — not a request.

        The draft is *unconfirmed* by construction. Confirming it here would
        remove the learner's only chance to read the summary before review
        treats it as settled.

        Best-effort: a lecture is a convenience next to the turn's answer, and
        an LLM failure writing one must never fail a turn that already
        succeeded.
        """
        if mode != "study" or not path_id or not knowledge_point_id:
            return None
        if not _turn_taught_this_point(events, knowledge_point_id):
            return None
        from deeptutor.learning.placement import write_lecture_draft

        try:
            status = await write_lecture_draft(path_id, knowledge_point_id)
        except Exception:
            logger.warning(
                "Could not roll the lecture draft for path %s point %s",
                path_id,
                knowledge_point_id,
                exc_info=True,
            )
            return None
        draft = status.get("draft")
        if not isinstance(draft, dict) or not draft.get("body"):
            return None
        # No event is published for this. The client's confirm card reads the
        # lecture from the API, and it has to — a card driven by a stream event
        # is one a reloaded page never shows, which is exactly when a learner
        # comes back to check what was written.
        _ = execution
        return status

    async def _acquire_mastery_path_lease(
        self,
        *,
        path_id: str,
        session_id: str,
        turn_id: str,
        owns_path: bool,
    ) -> None:
        """Bind a session to its path and take over from any superseded turn."""
        from deeptutor.learning.storage import LearningStore, PathLeaseConflictError

        learning_store = LearningStore()
        await asyncio.to_thread(
            learning_store.bind_session,
            path_id,
            session_id,
            owns_path=owns_path,
        )
        lease = await asyncio.to_thread(learning_store.get_path_lease, path_id)
        if lease is not None and lease.turn_id != turn_id and lease.session_id != "__path_api__":
            await self._release_superseded_lease(path_id, lease)
        try:
            await asyncio.to_thread(
                learning_store.acquire_path_lease,
                path_id,
                session_id,
                turn_id,
            )
        except PathLeaseConflictError as exc:
            raise RuntimeError(
                "mastery_path_busy: "
                f"path {path_id!r} is already active in session {exc.lease.session_id!r}"
            ) from exc

    @staticmethod
    async def _validate_mastery_session_topic(
        *,
        session_id: str,
        requested_path_id: str,
        remembered_path_id: str,
    ) -> None:
        """Reject a topic URL paired with a conversation held on another path.

        A conversation is on exactly one path, so this is a comparison against
        one value: the membership the store holds, or — for a conversation
        that predates memberships — the path remembered on the session. A
        conversation with neither is new and may start anywhere.

        An in-chat ``mastery_switch`` moves the membership itself, so a
        legitimate move is never seen here as a mismatch.
        """

        from deeptutor.learning.storage import LearningStore

        learning_store = LearningStore()
        current = await asyncio.to_thread(
            learning_store.path_id_for_session,
            session_id,
        )
        expected = current or str(remembered_path_id or "").strip()
        if expected and requested_path_id != expected:
            raise RuntimeError(
                "mastery_session_topic_mismatch: "
                f"session {session_id!r} is on path {expected!r}, not {requested_path_id!r}"
            )
