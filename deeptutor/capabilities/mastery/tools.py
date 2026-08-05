"""Mastery Path tools — the seam between the chat-loop tutor and the pure
mastery engine (:mod:`deeptutor.learning`).

These five tools are auto-mounted only when a mastery path is active on the
turn (via the chat loop mastery capability). The chat agent loop IS the tutor;
these tools let it read the gate and record outcomes, while the pedagogy —
what to teach, how to question, when to explain — stays the model's job. The
arithmetic (mastery, gate, spaced repetition) stays in the engine.

The active path id is injected server-side by the pipeline as
``_mastery_path_id``; the model never supplies it. Each call constructs a
fresh store + service (matching the REST router) so concurrent turns can't
race on a shared object.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
import uuid

from deeptutor.capabilities.mastery.choices import (
    format_options,
    has_option_bodies,
    parse_options,
    recover_options_from_turn,
    resolve_answer,
)
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

# ``learning.models`` and ``learning.policy`` only depend on pydantic — safe to
# import at module load. ``learning.service`` / ``storage`` / ``scheduler``
# reach the path service (and so the runtime + tool registry), so importing
# them here would close an import cycle through the built-in registry. They
# are imported lazily inside the call paths instead (same pattern as the other
# builtin tools).
from deeptutor.learning.models import (
    AttemptStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    PendingQuestion,
)

_LIVE_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.DRAFT,
        AttemptStatus.COLLECTING,
        AttemptStatus.READY_TO_ASSESS,
    }
)
from deeptutor.learning.policy import (
    QUALITATIVE_TYPES,
    display_mastery,
    find_knowledge_point,
    gate_threshold,
    is_mastered,
    map_summary,
    next_objective,
)

if TYPE_CHECKING:
    from deeptutor.learning.service import LearningService

# Tool names the pipeline mounts together when a mastery path is active. Kept
# here so the mount policy and the registration list can't disagree.
# ``mastery_assess`` is deliberately absent: LRN-03 mounts the Feynman cycle
# tools and keeps ``mastery_assess`` only as a callable legacy path (its class
# stays registered in ``MASTERY_TOOL_TYPES``) — it must never create stable
# mastery.
MASTERY_TOOL_NAMES: tuple[str, ...] = (
    "mastery_status",
    "mastery_cycle_start",
    "mastery_record_evidence",
    "mastery_finalize",
    "mastery_quiz",
    "mastery_grade",
    "mastery_build",
)

_QUESTION_TYPES = ("choice", "short", "open")
_ALLOWED_KP_TYPES = {t.value for t in KnowledgeType}
logger = logging.getLogger(__name__)


def _new_service() -> LearningService:
    from deeptutor.learning.service import LearningService
    from deeptutor.learning.storage import LearningStore

    return LearningService(LearningStore())


def _resolve_path_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_mastery_path_id") or "").strip()


def _resolve_session_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_session_id") or "").strip()


def _resolve_turn_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_turn_id") or "").strip()


def _resolve_message_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_message_id") or "").strip()


def _resolve_user_id(kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("_user_id") or "").strip()


def _question_bank_type(question_type: str) -> str:
    qtype = str(question_type or "").strip().lower()
    if qtype == "choice":
        return "choice"
    if qtype == "open":
        return "written"
    return "short_answer"


async def _resolve_pending_choice(
    pending: PendingQuestion, turn_id: str
) -> tuple[dict[str, str], str]:
    """Resolve a pending choice question's ``({label: body}, expected_label)``.

    Re-parses the bodies stored at registration; for legacy paths that stored
    only ``["A", "B", ...]`` it recovers the real bodies from the turn's
    ``ask_user`` event. The expected answer is normalised to a stable label
    when it resolves, else left as registered.
    """
    options = parse_options(list(pending.options or []))
    if not has_option_bodies(options):
        try:
            from deeptutor.services.session import get_sqlite_session_store

            options = await recover_options_from_turn(
                get_sqlite_session_store(), turn_id, pending.prompt
            )
        except Exception:
            logger.warning("Failed to recover legacy mastery choice options", exc_info=True)
            options = {}
    return options, resolve_answer(pending.expected_answer, options) or pending.expected_answer


async def _sync_mastery_attempt_to_question_bank(
    *,
    session_id: str,
    turn_id: str,
    pending: PendingQuestion,
    user_answer: str,
    is_correct: bool,
    choice_options: dict[str, str] | None = None,
    correct_answer: str | None = None,
) -> None:
    if not session_id:
        return
    item = {
        "turn_id": turn_id,
        "question_id": pending.question_id,
        "question": pending.prompt,
        "question_type": _question_bank_type(pending.question_type),
        "options": choice_options or parse_options(list(pending.options or [])),
        "correct_answer": correct_answer or pending.expected_answer,
        "explanation": "",
        "difficulty": "",
        "user_answer": user_answer,
        "is_correct": is_correct,
    }
    try:
        from deeptutor.services.session import get_sqlite_session_store

        await get_sqlite_session_store().upsert_notebook_entries(session_id, [item])
    except Exception:
        logger.warning(
            "Failed to sync mastery question %s to question bank for session %s",
            pending.question_id,
            session_id,
            exc_info=True,
        )


def _json_result(
    payload: dict[str, Any],
    *,
    meta_key: str,
    success: bool = True,
    refresh: dict[str, Any] | None = None,
) -> ToolResult:
    metadata: dict[str, Any] = {meta_key: payload}
    if refresh:
        # Stable refresh hints ride tool metadata to the WebSocket so the
        # frontend can refresh map/attempt views (§8.4). Only server-trusted
        # ids (path/attempt) are included — never user-supplied identity.
        metadata["refresh"] = refresh
    return ToolResult(
        content=json.dumps(payload, ensure_ascii=False),
        success=success,
        metadata=metadata,
    )


def _feynman_error_result(
    exc: Exception,
    *,
    meta_key: str,
    path_id: str = "",
    attempt_id: str = "",
) -> ToolResult:
    payload: dict[str, Any] = {
        "status": "error",
        "error": str(exc),
        "error_type": type(exc).__name__,
        "path_id": path_id,
    }
    if attempt_id:
        payload["attempt_id"] = attempt_id
    return _json_result(
        payload,
        meta_key=meta_key,
        success=False,
        refresh={"kind": ["map", "attempt"], "path_id": path_id, "attempt_id": attempt_id}
        if path_id
        else None,
    )


def _no_path_result() -> ToolResult:
    return ToolResult(
        content="No mastery path is active on this turn; mastery tools are unavailable.",
        success=False,
    )


class MasteryStatusTool(BaseTool):
    """Read the current objective + map snapshot. Call FIRST every turn."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_status",
            description=(
                "Read the learner's mastery path: the next objective to work on "
                "(decided by a hard mastery gate), any question awaiting an "
                "answer, due reviews, and a map of every objective's status "
                "(new / learning / mastered). Call this FIRST on every mastery "
                "turn — it tells you what to do; never guess the next objective."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        service = _new_service()
        progress = service.get_or_create(path_id)
        if not any(module.knowledge_points for module in progress.modules):
            return _json_result(
                {
                    "status": "empty",
                    "message": (
                        "No mastery path has been built yet. Design one from the "
                        "learner's materials and call mastery_build."
                    ),
                },
                meta_key="mastery_status",
            )
        next_step = next_objective(progress).to_dict()
        payload = {
            "status": "active",
            "next": next_step,
            "map": map_summary(progress),
            "active_attempt": _active_attempt_summary(progress, next_step),
        }
        return _json_result(
            payload,
            meta_key="mastery_status",
            refresh={"kind": ["map"], "path_id": path_id} if payload["active_attempt"] else None,
        )


class MasteryQuizTool(BaseTool):
    """Register an objective-type question; the engine holds the answer."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_quiz",
            description=(
                "Pose a question for a MEMORY or PROCEDURE objective and register "
                "its expected answer with the engine (so grading is deterministic "
                "and you never re-state the answer later). After calling this, "
                "present the question with the ask_user tool so the learner answers "
                "on an interactive card (for choices, give ask_user options short "
                "labels like A/B/C, pass every full option body here, and set the "
                "correct label as expected_answer); "
                "then call mastery_grade with their answer. For CONCEPT / DESIGN "
                "objectives use mastery_assess instead."
            ),
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective id from mastery_status (verbatim).",
                ),
                ToolParameter(
                    name="question",
                    type="string",
                    description="The question text shown to the learner.",
                ),
                ToolParameter(
                    name="expected_answer",
                    type="string",
                    description="The correct answer, used only server-side for grading.",
                ),
                ToolParameter(
                    name="question_type",
                    type="string",
                    description=(
                        "'choice' (exact match), 'short' (exact / fuzzy for ≤30 "
                        "chars), or 'open' (keyword overlap). Default 'short'."
                    ),
                    required=False,
                    default="short",
                    enum=list(_QUESTION_TYPES),
                ),
                ToolParameter(
                    name="options",
                    type="array",
                    description=(
                        "For question_type='choice', every full option in label order, "
                        "for example ['A: first answer', 'B: second answer']. Never "
                        "pass bare labels such as ['A', 'B', 'C', 'D']. Use the same "
                        "bodies as the ask_user option descriptions."
                    ),
                    required=False,
                    items={"type": "string"},
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
        question = str(kwargs.get("question") or "").strip()
        expected = str(kwargs.get("expected_answer") or "").strip()
        if not kp_id or not question or not expected:
            return ToolResult(
                content="mastery_quiz needs knowledge_point_id, question, and expected_answer.",
                success=False,
            )
        q_type = str(kwargs.get("question_type") or "short").strip().lower()
        if q_type not in _QUESTION_TYPES:
            q_type = "short"
        options = [str(o) for o in (kwargs.get("options") or []) if str(o).strip()]
        if q_type == "choice":
            choice_options = parse_options(options)
            if not has_option_bodies(choice_options):
                return ToolResult(
                    content=(
                        "Choice questions need full option bodies in mastery_quiz.options "
                        "(for example ['A: first answer', 'B: second answer']), not only "
                        "the labels A/B/C/D. Retry mastery_quiz with the exact option "
                        "descriptions you will show through ask_user."
                    ),
                    success=False,
                )
            resolved_expected = resolve_answer(expected, choice_options)
            if not resolved_expected:
                return ToolResult(
                    content=(
                        "Choice expected_answer must be an option label such as A/B/C/D, "
                        "or uniquely match one full option body. Retry mastery_quiz with "
                        "the correct label."
                    ),
                    success=False,
                )
            expected = resolved_expected
            options = format_options(choice_options)

        service = _new_service()
        progress = service.get_or_create(path_id)
        kp, module_id, _ = find_knowledge_point(progress, kp_id)
        if kp is None:
            return ToolResult(
                content=f"Unknown objective {kp_id!r}; call mastery_status for valid ids.",
                success=False,
            )
        pending = PendingQuestion(
            question_id=uuid.uuid4().hex,
            knowledge_point_id=kp_id,
            module_id=module_id,
            prompt=question,
            question_type=q_type,
            expected_answer=expected,
            options=options,
        )
        service.set_pending_question(progress, pending)
        return _json_result(
            {
                "status": "registered",
                "knowledge_point_id": kp_id,
                "question": question,
                "options": options,
                "instruction": (
                    "Present this question with the ask_user tool (use its options "
                    "for multiple choice; the option labels must match the "
                    "expected_answer you registered), then call mastery_grade with "
                    "the learner's answer."
                ),
            },
            meta_key="mastery_quiz",
        )


class MasteryGradeTool(BaseTool):
    """Grade the learner's answer to the pending question (deterministic)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_grade",
            description=(
                "Grade the learner's answer to the question you registered with "
                "mastery_quiz. Grading is deterministic against the stored "
                "expected answer; this updates mastery, advances spaced "
                "repetition, and tells you whether the objective's gate is now "
                "cleared. Then give the learner feedback."
            ),
            parameters=[
                ToolParameter(
                    name="answer",
                    type="string",
                    description="The learner's answer, verbatim.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        from deeptutor.learning.scheduler import SpacedRepetitionScheduler

        answer = str(kwargs.get("answer") or "")
        service = _new_service()
        scheduler = SpacedRepetitionScheduler()
        progress = service.get_or_create(path_id)
        pending = progress.pending_question
        if pending is None:
            return ToolResult(
                content="No question is awaiting an answer. Pose one with mastery_quiz first.",
                success=False,
            )
        choice_options: dict[str, str] = {}
        expected_answer = pending.expected_answer
        if pending.question_type == "choice":
            choice_options, expected_answer = await _resolve_pending_choice(
                pending, _resolve_turn_id(kwargs)
            )

        is_correct = service.grade_and_record(
            progress,
            question_id=pending.question_id,
            knowledge_point_id=pending.knowledge_point_id,
            module_id=pending.module_id,
            user_answer=answer,
            expected_answer=expected_answer,
            question_type=pending.question_type,
            scheduler=scheduler,
        )
        await _sync_mastery_attempt_to_question_bank(
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
            pending=pending,
            user_answer=answer,
            is_correct=is_correct,
            choice_options=choice_options,
            correct_answer=expected_answer,
        )
        service.clear_pending_question(progress)
        kp, _, _ = find_knowledge_point(progress, pending.knowledge_point_id)
        mastered = bool(kp and is_mastered(progress, kp))
        payload = {
            "is_correct": is_correct,
            "knowledge_point_id": pending.knowledge_point_id,
            "mastery": round(display_mastery(progress, kp), 3) if kp else 0.0,
            "threshold": round(gate_threshold(kp.type), 3) if kp else 0.0,
            "mastered": mastered,
            "next": next_objective(progress).to_dict(),
        }
        return _json_result(payload, meta_key="mastery_grade")


# ── LRN-03 Feynman cycle tools (spec §8.1) ───────────────────────────────
# These three tools replace ``mastery_assess`` on the mount: the server (not
# the model) owns the attempt lifecycle, evidence binding, and the gate.


def _new_cycle_service():
    from deeptutor.learning.cycles import FeynmanCycleService, production_evaluator_resolver
    from deeptutor.learning.storage import LearningStore

    return FeynmanCycleService(LearningStore(), evaluator_resolver=production_evaluator_resolver())


def _new_evaluator_client():
    """The production evaluator boundary (frozen evaluator runs the rubric).

    Offline tests monkeypatch this module function to inject a fake evaluator.
    """
    from deeptutor.learning.evaluation import RubricEvaluator

    return RubricEvaluator()


def _active_chain_evidence_ids(progress, attempt) -> list[str]:
    """Every evidence id in the attempt's current active chain (§6.1).

    The evaluator grades this exact chain and the server gate validates the ids
    belong to the active chain, so the tool never trusts a model-supplied subset
    that could skip required evidence.
    """
    return [
        item.id
        for item in progress.evidence_items
        if item.attempt_id == attempt.id and item.chain_id == attempt.active_chain_id
    ]


def _client_finalize_payload(
    kwargs: dict[str, Any], attempt_id: str, event_id: str
) -> dict[str, Any]:
    """The model-supplied finalize proposal, normalized for idempotency.

    This is the *client* request identity used to distinguish replay (same
    payload) from conflict (different payload) before the evaluator is invoked.
    It is never the authoritative assessment content.
    """
    citations = sorted(
        (
            {
                "source_snapshot_id": str(entry.get("source_snapshot_id") or ""),
                "anchor": str(entry.get("anchor") or ""),
            }
            for entry in (kwargs.get("source_citations") or [])
            if isinstance(entry, dict) and str(entry.get("source_snapshot_id") or "").strip()
        ),
        key=lambda citation: (citation["source_snapshot_id"], citation["anchor"]),
    )
    return {
        "attempt_id": attempt_id,
        "event_id": event_id,
        "rubric": kwargs.get("rubric"),
        "critical_errors": sorted(str(e) for e in (kwargs.get("critical_errors") or [])),
        "strengths": sorted(str(s) for s in (kwargs.get("strengths") or [])),
        "gaps": sorted(
            (dict(g) for g in (kwargs.get("gaps") or []) if isinstance(g, dict)),
            key=lambda gap: str(gap.get("label") or "") + str(gap.get("description") or ""),
        ),
        "evidence_ids": sorted(str(eid) for eid in (kwargs.get("evidence_ids") or [])),
        "source_citations": citations,
        "challenge_id": str(kwargs.get("challenge_id") or "").strip(),
    }


def _challenge_evaluator_snapshot(progress, challenge_id: str):
    """The explicitly selected configured alternative evaluator for a challenge.

    Returns ``None`` when no alternative was requested — finalize then uses the
    frozen original evaluator (§7.3.1/§9.3). The snapshot is only an *input* to
    the evaluator boundary, which fails closed if it is not actually configured.
    """
    if not challenge_id:
        return None
    from deeptutor.learning.models import ChallengeStatus

    challenge = next(
        (
            record
            for record in progress.challenge_records
            if record.id == challenge_id and record.status == ChallengeStatus.PENDING
        ),
        None,
    )
    if challenge is None or challenge.requested_evaluator_snapshot is None:
        return None
    return challenge.requested_evaluator_snapshot


def _auto_create_stable_card(
    service, progress, *, path_id: str, attempt: Any, user_id: str
) -> dict[str, Any]:
    """§6.6: a newly reached ``stable_mastery`` creates the empty knowledge-card
    shell plus its first queued generation attempt in the *same* durable
    aggregate mutation as the finalize that produced it.

    ``ensure_draft`` runs with ``commit=False``: the caller's single CAS save
    after this returns persists the card + queued attempt atomically with the
    assessment/mastery mutation, so a crash can never leave a stable mastery
    with no card. Provisional mastery never reaches this branch. The card is
    bound to the trusted server user identity and the current latest valid
    stable assessment; nothing is auto-published and no KB write occurs.

    This is **not** best-effort: a missing trusted user identity or any card
    eligibility/ownership failure raises so the caller never commits a stable
    mastery without the required empty card shell and first queued generation
    attempt (finding 2). The caller must propagate the error and skip the CAS
    save, leaving the persisted aggregate pre-finalize.
    """
    from deeptutor.learning.knowledge_cards.errors import KnowledgeCardOwnershipError
    from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
    from deeptutor.learning.storage import LearningStore

    if not user_id:
        raise KnowledgeCardOwnershipError(
            "stable-mastery auto-card requires a trusted server user identity; "
            "finalize is paused until identity is available"
        )
    draft_service = KnowledgeCardDraftService(LearningStore())
    return draft_service.ensure_draft(
        progress,
        user_id=user_id,
        path_id=path_id,
        knowledge_point_id=attempt.knowledge_point_id,
        commit=False,
    )


def _finalize_paused_invocation(service, path_id: str, record_id: str, exc) -> None:
    """Best-effort finalize of a pending evaluation invocation as ``paused``.

    Pausing is idempotent: an already-terminal invocation (a concurrent holder
    finished it) is never re-written. A failure here is logged and must not
    mask the stable paused verdict returned to the learner.
    """
    from deeptutor.learning.models import ModelInvocationStatus
    from deeptutor.learning.storage import find_model_invocation
    from deeptutor.services.model_selection.audit import ModelInvocationRecorder

    if not record_id:
        return
    try:
        progress = service.load(path_id)
        if progress is None:
            return
        latest = find_model_invocation(progress, record_id)
        if latest is None or latest.status != ModelInvocationStatus.PENDING:
            return
        ModelInvocationRecorder().finish(
            progress,
            record_id,
            status=ModelInvocationStatus.PAUSED,
            sanitized_error=exc.sanitized_error,
            error_code=exc.code,
        )
        service.save(progress)
    except Exception:  # noqa: BLE001 - best-effort audit on a paused path
        logger.warning("failed to finalize paused evaluation invocation", exc_info=True)


def _pausable_finalize_error(message: str, code: str):
    """A lightweight ``{sanitized_error, code}`` adapter for paused invocations."""
    from types import SimpleNamespace

    return SimpleNamespace(sanitized_error=message, code=code)


def _commit_evaluated_finalize(
    service,
    *,
    path_id: str,
    attempt_id: str,
    record_id: str,
    event_id: str,
    client_payload: dict[str, Any],
    client_fp: str,
    output: Any,
    challenge_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Apply the already-received evaluator output inside a bounded CAS retry.

    After ``evaluator.invoke`` succeeds, the strictly normalized output exists
    only in this local variable. Instead of a single reload/save (which a
    concurrent version bump can discard, forcing a second provider call on the
    next request), reload current state, recheck committed replay/conflict
    rules, finish the exact pending invocation revision, finalize (including
    the atomic §6.6 auto-card transition), and retry the save on a stale
    aggregate — never calling the evaluator again and never creating a second
    pending record for the same in-flight operation (finding 3).

    A conflicting event payload still fails closed; an already committed
    equivalent result replays. If the bounded retry cannot commit, the store's
    CAS raises and no assessment/mastery is partially persisted.
    """
    from deeptutor.learning.cycles import StaleVersionError
    from deeptutor.learning.models import ModelInvocationStatus
    from deeptutor.services.model_selection.audit import ModelInvocationRecorder

    max_retries = 5
    attempts = 0
    progress = service.load(path_id)
    if progress is None:
        raise StaleVersionError(f"progress for path {path_id!r} disappeared during finalize")
    while True:
        # Recheck committed replay/conflict rules on the reloaded aggregate.
        replay = service.find_finalize_replay(
            progress,
            attempt_id=attempt_id,
            event_id=event_id,
            client_payload=client_payload,
        )
        if replay is not None:
            # A concurrent request committed this exact finalize mid-flight;
            # replay its stored result and leave no dangling PENDING audit.
            _finalize_paused_invocation(
                service,
                path_id,
                record_id,
                _pausable_finalize_error(
                    "finalize replayed by a concurrent holder", "finalize_replayed"
                ),
            )
            return {**replay, "replayed": True}
        attempt = service._attempt(progress, attempt_id)
        current_version = progress.aggregate_versions.attempt
        recorder = ModelInvocationRecorder()
        recorder.finish(
            progress,
            record_id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model=output.reported_model,
            reported_version=output.reported_version,
            usage=output.usage,
        )
        result = service.finalize(
            progress,
            attempt_id=attempt_id,
            rubric=output.rubric,
            critical_errors=output.critical_errors,
            strengths=output.strengths,
            gap_candidates=output.gap_candidates,
            evidence_ids=_active_chain_evidence_ids(progress, attempt),
            source_citations=output.source_citations,
            # The exact evaluation invocation id; a model-supplied public
            # ``model_invocation_id`` / ``_model_invocation_id`` is never
            # promoted (finding 3).
            model_invocation_id=record_id,
            challenge_id=challenge_id,
            client_request_fingerprint=client_fp,
            expected_attempt_version=current_version,
            event_id=event_id,
        )
        # §6.6 automatic transition: a *newly* reached ``stable_mastery``
        # creates exactly one eligible empty card shell + first queued
        # generation attempt in this same CAS save. Provisional mastery creates
        # none. A card error raises here and prevents the save below, so the
        # persisted aggregate stays pre-finalize (finding 2).
        if result.get("mastery_state") == "stable_mastery":
            _auto_create_stable_card(
                service,
                progress,
                path_id=path_id,
                attempt=attempt,
                user_id=user_id,
            )
        try:
            service.save(progress)
        except StaleVersionError:
            attempts += 1
            if attempts > max_retries:
                # Bounded retry exhausted: return a stable recoverable conflict
                # without committing — the aggregate is still internally valid
                # and the committed output is never partially persisted.
                raise StaleVersionError(
                    f"finalize for attempt {attempt_id!r} could not commit after "
                    f"{max_retries} reloads; a concurrent writer is continuously "
                    "advancing the aggregate — reload and retry"
                ) from None
            reloaded = service.load(path_id)
            if reloaded is None:
                raise StaleVersionError(
                    f"progress for path {path_id!r} disappeared during finalize"
                ) from None
            progress = reloaded
            continue
        return result


def _cycle_identity(kwargs: dict[str, Any]) -> dict[str, str]:
    """Server-injected identity for evidence binding (§7.2, requirement 3).

    These come ONLY from the capability loop's ``augment_kwargs``. Model-
    supplied ``session_id`` / ``turn_id`` / ``message_id`` / ``user_id``
    arguments are never read, so a spoofed identity can never be bound.
    """
    return {
        "path_id": _resolve_path_id(kwargs),
        "session_id": _resolve_session_id(kwargs),
        "turn_id": _resolve_turn_id(kwargs),
        "message_id": _resolve_message_id(kwargs),
        "user_id": _resolve_user_id(kwargs),
    }


class MasteryCycleStartTool(BaseTool):
    """Idempotently create or resume a Feynman attempt (§8.1)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_cycle_start",
            description=(
                "Start (or resume) a Feynman learning cycle for a knowledge point. "
                "Call this when the learner begins teaching a knowledge point, "
                "when a delayed reteach is due, or when test-out is requested. "
                "It returns the attempt id, the active chain id, and the required "
                "evidence steps in order. Evidence is then recorded with "
                "mastery_record_evidence and the cycle is closed by "
                "mastery_finalize. cycle_type: 'initial' for a first pass, "
                "'test_out' to test out without teaching, 'delayed_reteach' for "
                "a scheduled review, 'reevaluation' for a cross-model challenge."
            ),
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective id from mastery_status (verbatim).",
                ),
                ToolParameter(
                    name="cycle_type",
                    type="string",
                    description="The kind of Feynman cycle to start.",
                    enum=["initial", "delayed_reteach", "reevaluation", "test_out"],
                    required=False,
                    default="initial",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
        if not kp_id:
            return ToolResult(
                content="mastery_cycle_start needs a knowledge_point_id.", success=False
            )
        cycle_type = str(kwargs.get("cycle_type") or "initial").strip().lower()
        identity = _cycle_identity(kwargs)

        from deeptutor.learning.cycles import FeynmanError

        service = _new_cycle_service()
        progress = service.load(path_id)
        if progress is None:
            return _no_path_result()
        try:
            attempt = service.start_cycle(
                progress,
                knowledge_point_id=kp_id,
                cycle_type=cycle_type,
                session_id=identity["session_id"],
                turn_id=identity["turn_id"],
            )
            service.save(progress)
        except FeynmanError as exc:
            return _feynman_error_result(exc, meta_key="mastery_cycle_start", path_id=path_id)

        from deeptutor.learning.grading import REQUIRED_EVIDENCE_KINDS

        return _json_result(
            {
                "status": "started",
                "attempt_id": attempt.id,
                "chain_id": attempt.active_chain_id,
                "cycle_type": attempt.cycle_type.value,
                "knowledge_point_id": attempt.knowledge_point_id,
                "map_version_id": attempt.map_version_id,
                "attempt_version": progress.aggregate_versions.attempt,
                "required_steps": list(REQUIRED_EVIDENCE_KINDS),
            },
            meta_key="mastery_cycle_start",
            refresh={
                "kind": ["map", "attempt"],
                "path_id": path_id,
                "attempt_id": attempt.id,
            },
        )


class MasteryRecordEvidenceTool(BaseTool):
    """Append one evidence item bound to real session records (§8.1)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_record_evidence",
            description=(
                "Record one piece of Feynman evidence for the active attempt. "
                "The chain must follow the order: explanation (the learner's own "
                "words) -> at least two probe_question/probe_answer pairs (the "
                "learner answers your diagnostic probes) -> transfer_question/"
                "transfer_answer (a novel-situation transfer the learner "
                "completes). Use kind='reteach' after a full_explanation help "
                "level; the server then opens a fresh chain and the learner must "
                "re-teach from scratch. Provide an 'event_id' idempotency key; "
                "replaying the same event_id with the same content returns the "
                "prior result. The real session/turn/message identity is injected "
                "server-side — you cannot supply it."
            ),
            parameters=[
                ToolParameter(
                    name="attempt_id",
                    type="string",
                    description="Attempt id from mastery_cycle_start (verbatim).",
                ),
                ToolParameter(
                    name="kind",
                    type="string",
                    description=(
                        "explanation | probe_question | probe_answer | "
                        "transfer_question | transfer_answer | reteach | "
                        "source_reference."
                    ),
                    enum=[
                        "explanation",
                        "probe_question",
                        "probe_answer",
                        "transfer_question",
                        "transfer_answer",
                        "reteach",
                        "source_reference",
                    ],
                ),
                ToolParameter(
                    name="event_id",
                    type="string",
                    description=(
                        "A stable idempotency key for this evidence event. Reuse "
                        "the same key with the same content to replay; the same "
                        "key with different content is rejected as a conflict."
                    ),
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description=(
                        "The evidence text. For learner evidence (explanation, "
                        "answers) this is the learner's own words verbatim."
                    ),
                ),
                ToolParameter(
                    name="question_evidence_id",
                    type="string",
                    description=(
                        "Required for probe_answer / transfer_answer: the "
                        "evidence id of the question being answered."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="source_citations",
                    type="array",
                    description=(
                        "Optional source references for this evidence: objects "
                        "with source_snapshot_id and anchor. The id must be a "
                        "snapshot already bound to the attempt."
                    ),
                    required=False,
                    items={"type": "object"},
                ),
                ToolParameter(
                    name="input_mode",
                    type="string",
                    description="'text' or 'voice_transcript'.",
                    required=False,
                    default="text",
                    enum=["text", "voice_transcript"],
                ),
                ToolParameter(
                    name="transcript_confirmed",
                    type="boolean",
                    description=(
                        "For voice_transcript learner evidence this must be true "
                        "(the user has edited and confirmed the transcript)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="help_level",
                    type="string",
                    description=(
                        "Optional help level for this item: question | hint | "
                        "source_locator | full_explanation. Using "
                        "full_explanation closes the current chain and forces a "
                        "fresh reteach."
                    ),
                    required=False,
                    enum=["question", "hint", "source_locator", "full_explanation"],
                ),
                ToolParameter(
                    name="expected_attempt_version",
                    type="integer",
                    description=(
                        "Required concurrency guard: the attempt version from the "
                        "last tool result. A stale value is rejected, never "
                        "overwritten."
                    ),
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        attempt_id = str(kwargs.get("attempt_id") or "").strip()
        kind = str(kwargs.get("kind") or "").strip()
        event_id = str(kwargs.get("event_id") or "").strip()
        content = str(kwargs.get("content") or "")
        expected_attempt_version = _optional_int(kwargs.get("expected_attempt_version"))
        if not attempt_id or not kind or not event_id:
            return ToolResult(
                content=("mastery_record_evidence needs attempt_id, kind, and event_id."),
                success=False,
            )
        if expected_attempt_version is None:
            return ToolResult(
                content=(
                    "mastery_record_evidence needs a real expected_attempt_version "
                    "(the attempt version from the last tool result)."
                ),
                success=False,
            )
        identity = _cycle_identity(kwargs)

        from deeptutor.learning.cycles import FeynmanError

        service = _new_cycle_service()
        progress = service.load(path_id)
        if progress is None:
            return _no_path_result()
        try:
            result = service.record_evidence(
                progress,
                attempt_id=attempt_id,
                kind=kind,
                event_id=event_id,
                content=content,
                identity=identity,
                question_evidence_id=str(kwargs.get("question_evidence_id") or ""),
                source_citations=_parse_citations(kwargs.get("source_citations")),
                input_mode=str(kwargs.get("input_mode") or "text"),
                transcript_confirmed=bool(kwargs.get("transcript_confirmed")),
                help_level=str(kwargs.get("help_level") or "") or None,
                expected_attempt_version=expected_attempt_version,
            )
            service.save(progress)
        except FeynmanError as exc:
            return _feynman_error_result(
                exc, meta_key="mastery_record_evidence", path_id=path_id, attempt_id=attempt_id
            )
        return _json_result(
            result,
            meta_key="mastery_record_evidence",
            refresh={
                "kind": ["map", "attempt"],
                "path_id": path_id,
                "attempt_id": attempt_id,
            },
        )


class MasteryFinalizeTool(BaseTool):
    """Server-gated finalize: rubric + evidence → assessment (no ``passed``)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_finalize",
            description=(
                "Close the active Feynman cycle with a rubric assessment. The "
                "frozen evaluator (the learning path's configured evaluation "
                "model) grades the evidence chain against the fixed rubric and "
                "supplies the assessment fields; you do NOT pass 'passed' — the "
                "server computes the hard gate. Your optional rubric/errors/"
                "strengths/gaps/citations are a proposal only and are never "
                "trusted over the evaluator's output. On success the projection "
                "and review queue are updated and the result tells you the new "
                "mastery/review state. A challenge reassessment passes the "
                "challenge_id to append a later revision to the same attempt."
            ),
            parameters=[
                ToolParameter(
                    name="attempt_id",
                    type="string",
                    description="Attempt id from mastery_cycle_start (verbatim).",
                ),
                ToolParameter(
                    name="rubric",
                    type="object",
                    description=(
                        "Optional proposed rubric {correctness: 0|1|2, "
                        "completeness: 0|1|2, causal_clarity: 0|1|2, transfer: "
                        "0|1|2}. The frozen evaluator's rubric is authoritative; "
                        "this value is not trusted over it."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="evidence_ids",
                    type="array",
                    description=(
                        "Optional evidence ids in the attempt's active chain. The "
                        "server grades the full active chain via the frozen "
                        "evaluator; a model-supplied subset is never trusted to "
                        "skip required evidence."
                    ),
                    items={"type": "string"},
                    required=False,
                ),
                ToolParameter(
                    name="critical_errors",
                    type="array",
                    description="Optional critical errors that fail the gate.",
                    required=False,
                    items={"type": "string"},
                ),
                ToolParameter(
                    name="strengths",
                    type="array",
                    description="Optional strengths demonstrated in the evidence.",
                    required=False,
                    items={"type": "string"},
                ),
                ToolParameter(
                    name="gaps",
                    type="array",
                    description=(
                        "Optional gap candidates: {label, description}. The server "
                        "deduplicates and records them as GapRecords."
                    ),
                    required=False,
                    items={"type": "object"},
                ),
                ToolParameter(
                    name="source_citations",
                    type="array",
                    description=(
                        "Source citations for this assessment. Each must resolve "
                        "to a snapshot frozen on the attempt."
                    ),
                    required=False,
                    items={"type": "object"},
                ),
                ToolParameter(
                    name="challenge_id",
                    type="string",
                    description=(
                        "When finalising a challenge reassessment, pass the "
                        "challenge id returned by the challenge API."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="expected_attempt_version",
                    type="integer",
                    description=("Required concurrency guard; a stale value is rejected."),
                ),
                ToolParameter(
                    name="event_id",
                    type="string",
                    description=(
                        "Required finalize idempotency key (paired with the "
                        "attempt_id). Replaying the same event_id with the same "
                        "full payload returns the prior finalize result without "
                        "creating a second assessment; the same event_id with a "
                        "different payload is a stable conflict."
                    ),
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.learning.cycles import FeynmanError
        from deeptutor.learning.evaluation import EvaluatorUnavailableError

        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        if "passed" in kwargs:
            return _feynman_error_result(
                FeynmanError(
                    "mastery_finalize does not accept 'passed'; the server computes "
                    "the gate from evidence and rubric."
                ),
                meta_key="mastery_finalize",
                path_id=path_id,
                attempt_id=str(kwargs.get("attempt_id") or ""),
            )
        attempt_id = str(kwargs.get("attempt_id") or "").strip()
        if not attempt_id:
            return ToolResult(content="mastery_finalize needs an attempt_id.", success=False)
        event_id = str(kwargs.get("event_id") or "").strip()
        if not event_id:
            return ToolResult(
                content="mastery_finalize needs a nonblank event_id idempotency key.",
                success=False,
            )
        expected_attempt_version = _optional_int(kwargs.get("expected_attempt_version"))
        if expected_attempt_version is None:
            return ToolResult(
                content=(
                    "mastery_finalize needs a real expected_attempt_version "
                    "(the attempt version from the last tool result)."
                ),
                success=False,
            )
        challenge_id = str(kwargs.get("challenge_id") or "").strip()
        refresh = {
            "kind": ["map", "attempt", "reviews"],
            "path_id": path_id,
            "attempt_id": attempt_id,
        }

        service = _new_cycle_service()
        progress = service.load(path_id)
        if progress is None:
            return _no_path_result()

        record_id = ""
        result: dict[str, Any] = {}
        try:
            # A committed finalize replays its stored result *before* any
            # evaluator call — a retry must never repeat a provider call or
            # duplicate a completed assessment (§8.3, requirement 2). The same
            # key reused with a *different* client payload stays a conflict.
            from deeptutor.learning.cycles import StaleVersionError, finalize_client_fingerprint
            from deeptutor.learning.knowledge_cards.errors import KnowledgeCardError

            client_payload = _client_finalize_payload(kwargs, attempt_id, event_id)
            client_fp = finalize_client_fingerprint(client_payload)
            replay = service.find_finalize_replay(
                progress,
                attempt_id=attempt_id,
                event_id=event_id,
                client_payload=client_payload,
            )
            if replay is not None:
                return _json_result(replay, meta_key="mastery_finalize", refresh=refresh)

            attempt = service._attempt(progress, attempt_id)

            # Preflight the concurrency token *before* any provider call so a
            # stale token never wastes a provider round-trip (finding 3).
            if expected_attempt_version != progress.aggregate_versions.attempt:
                raise StaleVersionError(
                    f"expected attempt version {expected_attempt_version}, "
                    f"current is {progress.aggregate_versions.attempt}"
                )

            user_id = _resolve_user_id(kwargs)
            # Preflight the trusted server user identity for the only paths that
            # can *newly* reach stable_mastery (a delayed reteach pass, or a
            # challenge re-affirming an already-stable point): the atomic §6.6
            # auto-card transition requires it, so fail closed before spending a
            # provider call instead of after (finding 2).
            projection = progress.projections.get(attempt.knowledge_point_id)
            could_reach_stable = attempt.cycle_type.value == "delayed_reteach" or bool(
                projection is not None and projection.mastery_state.value == "stable_mastery"
            )
            if could_reach_stable and not user_id:
                raise FeynmanError(
                    "mastery_finalize requires a trusted server user identity to "
                    "atomically create the stable-mastery knowledge card; retry "
                    "with the server identity injected"
                )

            challenge_snapshot = _challenge_evaluator_snapshot(progress, challenge_id)

            evaluator = _new_evaluator_client()
            pending = evaluator.append_pending(
                progress,
                attempt,
                snapshot=challenge_snapshot,
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
            record_id = pending.record_id
            # Persist the pending evaluation invocation *before* the provider
            # request so a crash between here and the call still leaves a trace.
            service.save(progress)

            # The frozen evaluator performs the rubric evaluation that supplies
            # the assessment fields; the server still computes ``passed``.
            output, _reported, _response = await evaluator.invoke(
                progress, attempt, snapshot=challenge_snapshot
            )

            # Apply the already-received, strictly normalized evaluator output
            # inside a bounded CAS retry loop. A concurrent version bump never
            # discards the terminal invocation/assessment and never forces a
            # second provider call (finding 3); the same pending record id is
            # reused and no second pending record is ever created.
            result = _commit_evaluated_finalize(
                service,
                path_id=path_id,
                attempt_id=attempt_id,
                record_id=record_id,
                event_id=event_id,
                client_payload=client_payload,
                client_fp=client_fp,
                output=output,
                challenge_id=challenge_id,
                user_id=user_id,
            )
        except EvaluatorUnavailableError as exc:
            # Pause finalize with a stable sanitized outcome: no assessment is
            # written and mastery never advances. The pending invocation is
            # finalized paused on a reload (idempotent to a concurrent holder).
            _finalize_paused_invocation(service, path_id, record_id, exc)
            payload = {
                "status": "paused",
                "reason": "evaluator_unavailable",
                "sanitized_error": exc.sanitized_error,
            }
            return _json_result(
                payload, meta_key="mastery_finalize", success=False, refresh=refresh
            )
        except KnowledgeCardError as exc:
            # §6.6: a card-transition failure must prevent the aggregate mutation
            # from committing — the assessment/mastery never persisted. Finalize
            # the pending invocation paused so the retry starts from a clean
            # audit trail, and return a stable sanitized recoverable outcome
            # instead of swallowing the failure (finding 2).
            from deeptutor.services.model_selection.fingerprint import sanitize_error

            _finalize_paused_invocation(
                service,
                path_id,
                record_id,
                _pausable_finalize_error(str(exc), getattr(exc, "code", "knowledge_card_error")),
            )
            payload = {
                "status": "paused",
                "reason": "auto_card_unavailable",
                "sanitized_error": sanitize_error(str(exc)),
                "error_code": getattr(exc, "code", "knowledge_card_error"),
            }
            return _json_result(
                payload, meta_key="mastery_finalize", success=False, refresh=refresh
            )
        except FeynmanError as exc:
            return _feynman_error_result(
                exc, meta_key="mastery_finalize", path_id=path_id, attempt_id=attempt_id
            )
        return _json_result(result, meta_key="mastery_finalize", refresh=refresh)


def _active_attempt_summary(progress: Any, next_step: dict[str, Any]) -> dict[str, Any] | None:
    """Active attempt + next required evidence for the current objective (§8.1).

    Only server-side ids are surfaced (attempt id / chain id); no user-supplied
    session/turn identity is included.
    """
    kp_id = str(next_step.get("knowledge_point_id") or "")
    if not kp_id:
        return None
    live = next(
        (
            a
            for a in progress.attempts
            if a.knowledge_point_id == kp_id and a.status in _LIVE_ATTEMPT_STATUSES
        ),
        None,
    )
    if live is None:
        return None
    from deeptutor.learning.cycles import FeynmanCycleService

    steps = FeynmanCycleService._missing_steps(progress, live)
    return {
        "attempt_id": live.id,
        "chain_id": live.active_chain_id,
        "status": live.status.value,
        "cycle_type": live.cycle_type.value,
        "next_required_steps": steps,
    }


def _parse_citations(raw: Any) -> list[Any]:
    """Normalise model-supplied source citations into :class:`SourceCitation`."""
    from deeptutor.learning.models import SourceCitation

    citations: list[Any] = []
    if not isinstance(raw, list):
        return citations
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        snapshot_id = str(entry.get("source_snapshot_id") or "").strip()
        if not snapshot_id:
            continue
        citations.append(
            SourceCitation(
                source_snapshot_id=snapshot_id,
                anchor=str(entry.get("anchor") or "").strip(),
            )
        )
    return citations


def _optional_int(raw: Any) -> int | None:
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


class MasteryAssessTool(BaseTool):
    """Record the qualitative (CONCEPT / DESIGN) gate from a Feynman check."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_assess",
            description=(
                "Record your judgement of a CONCEPT or DESIGN objective after the "
                "learner explains it in their own words (a Feynman-style check). "
                "Pass passed=true only when the explanation is correct and "
                "complete enough to count as mastery — this is the gate for these "
                "objective types. For MEMORY / PROCEDURE objectives use "
                "mastery_quiz + mastery_grade instead."
            ),
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective id from mastery_status (verbatim).",
                ),
                ToolParameter(
                    name="passed",
                    type="boolean",
                    description="True if the explanation demonstrates mastery.",
                ),
                ToolParameter(
                    name="feedback",
                    type="string",
                    description="Short note on what was strong or missing (stored as evidence).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
        if not kp_id:
            return ToolResult(content="mastery_assess needs a knowledge_point_id.", success=False)
        passed = bool(kwargs.get("passed"))
        feedback = str(kwargs.get("feedback") or "").strip()

        service = _new_service()
        progress = service.get_or_create(path_id)
        kp, _, _ = find_knowledge_point(progress, kp_id)
        if kp is None:
            return ToolResult(
                content=f"Unknown objective {kp_id!r}; call mastery_status for valid ids.",
                success=False,
            )
        if kp.type not in QUALITATIVE_TYPES:
            return ToolResult(
                content=(
                    f"Objective {kp.name!r} is a {kp.type.value} type — gate it with "
                    "mastery_quiz + mastery_grade, not mastery_assess."
                ),
                success=False,
            )
        service.record_qualitative(progress, kp_id, passed=passed, evidence=feedback)
        payload = {
            "knowledge_point_id": kp_id,
            "passed": passed,
            "mastered": is_mastered(progress, kp),
            "mastery": round(display_mastery(progress, kp), 3),
            "next": next_objective(progress).to_dict(),
        }
        return _json_result(payload, meta_key="mastery_assess")


class MasteryBuildTool(BaseTool):
    """Create / extend the skill map from objectives the tutor designed."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_build",
            description=(
                "Create or extend the learner's mastery path. Design modules and "
                "their knowledge points from the learner's materials (use rag / "
                "read_source first when materials are attached) and pass them "
                "here. Each knowledge point needs a 'type': memory (facts), "
                "procedure (step-by-step skills), concept (ideas to understand), "
                "or design (open-ended judgement). Use mode='replace' to start "
                "fresh or 'append' to add to an existing path."
            ),
            parameters=[
                ToolParameter(
                    name="modules",
                    type="array",
                    description=(
                        "Ordered modules: each {name, knowledge_points: [{name, "
                        "type}]}. type is one of memory/procedure/concept/design."
                    ),
                    items={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "knowledge_points": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "type": {
                                            "type": "string",
                                            "enum": sorted(_ALLOWED_KP_TYPES),
                                        },
                                    },
                                    "required": ["name"],
                                },
                            },
                        },
                        "required": ["name", "knowledge_points"],
                    },
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'replace' (default) starts fresh; 'append' adds modules.",
                    required=False,
                    default="replace",
                    enum=["replace", "append"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        mode = str(kwargs.get("mode") or "replace").strip().lower()
        if mode not in {"replace", "append"}:
            mode = "replace"

        service = _new_service()
        progress = service.get_or_create(path_id)
        offset = len(progress.modules) if mode == "append" else 0
        new_modules, error = _parse_modules(kwargs.get("modules"), path_id, offset)
        if error:
            return ToolResult(content=error, success=False)

        combined = (list(progress.modules) + new_modules) if mode == "append" else new_modules
        service.replace_modules(progress, combined)
        progress.pending_question = None  # a rebuilt map invalidates any open question
        if combined:
            progress.current_module_id = combined[0].id
            progress.current_kp_index = 0
        service.save(progress)
        kp_count = sum(len(m.knowledge_points) for m in new_modules)
        return _json_result(
            {
                "status": "built",
                "mode": mode,
                "modules_added": len(new_modules),
                "knowledge_points_added": kp_count,
                "map": map_summary(progress),
            },
            meta_key="mastery_build",
        )


def _parse_modules(
    raw_modules: Any, path_id: str, offset: int
) -> tuple[list[LearningModule], str | None]:
    """Validate the model-designed module tree into engine models.

    Ids are generated server-side (``<path>_m<i>_kp<j>``) so the model never
    controls storage keys; unknown knowledge types fall back to 'concept'.
    """
    if not isinstance(raw_modules, list) or not raw_modules:
        return [], "mastery_build needs a non-empty 'modules' array."
    modules: list[LearningModule] = []
    for i, raw in enumerate(raw_modules):
        if not isinstance(raw, dict):
            continue
        index = offset + i
        name = str(raw.get("name") or "").strip()[:200]
        if not name:
            continue
        module_id = f"{path_id}_m{index}"
        kps: list[KnowledgePoint] = []
        for j, raw_kp in enumerate(raw.get("knowledge_points") or []):
            if not isinstance(raw_kp, dict):
                continue
            kp_name = str(raw_kp.get("name") or "").strip()[:200]
            if len(kp_name) < 2:
                continue
            kp_type = str(raw_kp.get("type") or "concept").strip().lower()
            if kp_type not in _ALLOWED_KP_TYPES:
                kp_type = "concept"
            kps.append(
                KnowledgePoint(
                    id=f"{module_id}_kp{j}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=module_id,
                )
            )
        if not kps:
            continue
        modules.append(LearningModule(id=module_id, name=name, order=index, knowledge_points=kps))
    if not modules:
        return [], "No valid modules: each module needs a name and at least one knowledge point."
    return modules, None


MASTERY_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MasteryStatusTool,
    MasteryCycleStartTool,
    MasteryRecordEvidenceTool,
    MasteryFinalizeTool,
    MasteryQuizTool,
    MasteryGradeTool,
    MasteryAssessTool,
    MasteryBuildTool,
)


__all__ = [
    "MASTERY_TOOL_NAMES",
    "MASTERY_TOOL_TYPES",
    "MasteryStatusTool",
    "MasteryCycleStartTool",
    "MasteryRecordEvidenceTool",
    "MasteryFinalizeTool",
    "MasteryQuizTool",
    "MasteryGradeTool",
    "MasteryAssessTool",
    "MasteryBuildTool",
]
