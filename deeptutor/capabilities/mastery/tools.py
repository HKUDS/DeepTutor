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

import asyncio
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
    resolve_choice_submission,
)
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

# ``learning.models`` and ``learning.policy`` only depend on pydantic — safe to
# import at module load. ``learning.service`` / ``storage`` / ``scheduler``
# reach the path service (and so the runtime + tool registry), so importing
# them here would close an import cycle through the built-in registry. They
# are imported lazily inside the call paths instead (same pattern as the other
# builtin tools).
from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    PendingQuestion,
)
from deeptutor.learning.pending import public_pending_question
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
MASTERY_TOOL_NAMES: tuple[str, ...] = (
    "mastery_status",
    "mastery_quiz",
    "mastery_grade",
    "mastery_assess",
    "mastery_build",
    "mastery_paths",
    "mastery_switch",
    "mastery_leave",
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


def _question_bank_type(question_type: str) -> str:
    qtype = str(question_type or "").strip().lower()
    if qtype == "choice":
        return "choice"
    if qtype == "open":
        return "written"
    return "short_answer"


def _normalize_quiz_contract(
    raw_question_type: Any,
    raw_options: Any,
    expected_answer: str,
) -> tuple[str, list[str], str]:
    """Validate and canonicalise the persisted quiz shape.

    A missing question type is inferred from the actual payload: options mean
    ``choice`` and no options mean ``short``. Once a caller explicitly chooses
    ``short`` or ``open``, options are rejected instead of being silently
    discarded. Choice answers are stored as labels so the interactive card and
    deterministic grader always compare the same representation.
    """
    if raw_options is None:
        options: list[str] = []
    elif not isinstance(raw_options, list):
        raise ValueError("mastery_quiz.options must be an array of non-empty strings.")
    elif any(not isinstance(option, str) or not option.strip() for option in raw_options):
        raise ValueError("mastery_quiz.options must contain only non-empty strings.")
    else:
        options = [option.strip() for option in raw_options]

    supplied_type = str(raw_question_type or "").strip().lower()
    if supplied_type and supplied_type not in _QUESTION_TYPES:
        allowed = ", ".join(_QUESTION_TYPES)
        raise ValueError(f"mastery_quiz.question_type must be one of: {allowed}.")

    question_type = supplied_type or ("choice" if options else "short")
    if question_type != "choice":
        if options:
            raise ValueError(
                f"mastery_quiz.options cannot be used with question_type={question_type!r}; "
                "omit options or use question_type='choice'."
            )
        return question_type, [], expected_answer

    choice_options = parse_options(options)
    if len(choice_options) != len(options):
        raise ValueError(
            "Choice option labels must be unique; retry mastery_quiz with one full body "
            "for each label."
        )
    if not has_option_bodies(choice_options):
        raise ValueError(
            "Choice questions need full option bodies in mastery_quiz.options "
            "(for example ['A: first answer', 'B: second answer']), not only "
            "the labels A/B/C/D. Retry mastery_quiz with the exact option "
            "descriptions you will show through ask_user."
        )

    resolved_expected = resolve_answer(expected_answer, choice_options)
    if not resolved_expected:
        raise ValueError(
            "Choice expected_answer must be an option label such as A/B/C/D, "
            "or uniquely match one full option body. Retry mastery_quiz with "
            "the correct label."
        )
    return question_type, format_options(choice_options), resolved_expected


async def _resolve_pending_choice(
    pending: PendingQuestion, turn_id: str
) -> tuple[dict[str, str], str]:
    """Resolve a pending choice question's ``({label: body}, expected_label)``.

    The persisted options are authoritative. For legacy paths that stored only
    ``["A", "B", ...]`` it recovers the real bodies from the turn's
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

        await asyncio.wait_for(
            get_sqlite_session_store().upsert_notebook_entries(session_id, [item]),
            timeout=5.0,
        )
    except Exception:
        logger.warning(
            "Failed to sync mastery question %s to question bank for session %s",
            pending.question_id,
            session_id,
            exc_info=True,
        )


def _json_result(payload: dict[str, Any], *, meta_key: str, success: bool = True) -> ToolResult:
    return ToolResult(
        content=json.dumps(payload, ensure_ascii=False),
        success=success,
        metadata={meta_key: payload},
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
                    "path_revision": progress.version,
                    "message": (
                        "No mastery path has been built yet. Design one from the "
                        "learner's materials and call mastery_build."
                    ),
                },
                meta_key="mastery_status",
            )
        payload = {
            "status": "active",
            "path_revision": progress.version,
            "next": next_objective(progress).to_dict(),
            "map": map_summary(progress),
        }
        interaction = service.store.get_active_interaction(path_id)
        if interaction is not None:
            pending_interaction = {
                "question_id": interaction.interaction_id,
                "status": interaction.status.value,
            }
            if interaction.status == InteractionStatus.ANSWERED:
                # The answer is learner-authored state, not the hidden answer
                # key. Returning it lets a restart grade rather than ask twice.
                pending_interaction["learner_answer"] = interaction.user_answer
            payload["pending_interaction"] = pending_interaction
        return _json_result(payload, meta_key="mastery_status")


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
                        "chars), or 'open' (keyword overlap). When omitted, options "
                        "infer 'choice'; otherwise the default is 'short'."
                    ),
                    required=False,
                    default="short",
                    enum=list(_QUESTION_TYPES),
                ),
                ToolParameter(
                    name="options",
                    type="array",
                    description=(
                        "Every full choice option in label order; providing options "
                        "infers question_type='choice' when the type is omitted. "
                        "for example ['A: first answer', 'B: second answer']. Never "
                        "pass options for 'short'/'open' or bare labels such as "
                        "['A', 'B', 'C', 'D']. Use the same bodies as the ask_user "
                        "option descriptions."
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
        try:
            q_type, options, expected = _normalize_quiz_contract(
                kwargs.get("question_type"), kwargs.get("options"), expected
            )
        except ValueError as exc:
            return ToolResult(content=str(exc), success=False)

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
        from deeptutor.learning.service import MasteryInteractionError

        try:
            progress, interaction, created = service.register_question(
                path_id,
                pending,
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        pending = interaction.question
        public_question = public_pending_question(pending)
        return _json_result(
            {
                "status": "registered" if created else "already_pending",
                "path_revision": progress.version,
                "knowledge_point_id": pending.knowledge_point_id,
                "question_id": pending.question_id,
                "question_type": pending.question_type,
                "question": pending.prompt,
                "options": pending.options,
                "pending_question": public_question.to_dict(),
                "ask_user": {"questions": [public_question.to_ask_user_dict()]},
                "instruction": (
                    "Pass ask_user.questions through unchanged: its question id and "
                    "option labels are bound to the persisted question. Then call "
                    "mastery_grade with the learner's answer and this question_id."
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
                ToolParameter(
                    name="question_id",
                    type="string",
                    description=(
                        "Stable question_id from mastery_quiz or mastery_status. "
                        "Optional only for legacy pending questions."
                    ),
                    required=False,
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
        submitted_question_id = str(kwargs.get("question_id") or "").strip()
        interaction = (
            service.store.get_interaction(path_id, submitted_question_id)
            if submitted_question_id
            else service.store.get_active_interaction(path_id)
        )
        if interaction is not None and interaction.status == InteractionStatus.ANSWERED:
            # The pause/resume boundary already committed the learner's exact
            # reply. Never let a later model round paraphrase the graded input.
            answer = interaction.user_answer
        progress_before = service.get_or_create(path_id)
        pending = (
            interaction.question if interaction is not None else progress_before.pending_question
        )
        choice_options: dict[str, str] = {}
        expected_answer = pending.expected_answer if pending is not None else ""
        answer_for_grading = answer
        if (
            pending is not None
            and pending.question_type == "choice"
            and (interaction is None or interaction.status != InteractionStatus.GRADED)
        ):
            choice_options, expected_answer = await _resolve_pending_choice(
                pending, _resolve_turn_id(kwargs)
            )
            answer_for_grading = resolve_choice_submission(answer, choice_options) or answer
        from deeptutor.learning.service import MasteryInteractionError

        try:
            progress, interaction, replayed = service.grade_interaction(
                path_id,
                answer=answer,
                question_id=submitted_question_id,
                answer_for_grading=answer_for_grading,
                expected_answer=expected_answer if pending is not None else None,
                resolved_choice_options=choice_options or None,
                scheduler=scheduler,
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        pending = interaction.question
        is_correct = bool(interaction.result.get("is_correct"))
        # Upsert on every call, including an idempotent replay: if the first
        # best-effort sync timed out, a safe retry repairs the auxiliary
        # question bank without duplicating the mastery attempt.
        await _sync_mastery_attempt_to_question_bank(
            session_id=interaction.session_id or _resolve_session_id(kwargs),
            turn_id=interaction.turn_id or _resolve_turn_id(kwargs),
            pending=pending,
            # Replays must repair the auxiliary question bank with the
            # committed answer, not whatever a later model round supplied.
            user_answer=interaction.user_answer,
            is_correct=is_correct,
            choice_options=choice_options,
            correct_answer=expected_answer,
        )
        kp, _, _ = find_knowledge_point(progress, pending.knowledge_point_id)
        mastered = bool(kp and is_mastered(progress, kp))
        payload = {
            "is_correct": is_correct,
            "replayed": replayed,
            "path_revision": progress.version,
            "knowledge_point_id": pending.knowledge_point_id,
            "mastery": round(display_mastery(progress, kp), 3) if kp else 0.0,
            "threshold": round(gate_threshold(kp.type), 3) if kp else 0.0,
            "mastered": mastered,
            "next": next_objective(progress).to_dict(),
        }
        return _json_result(payload, meta_key="mastery_grade")


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
        from deeptutor.learning.scheduler import SpacedRepetitionScheduler

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
        from deeptutor.learning.service import MasteryInteractionError

        try:
            progress = service.record_qualitative_for_path(
                path_id,
                kp_id,
                passed=passed,
                evidence=feedback,
                scheduler=SpacedRepetitionScheduler(),
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        kp, _, _ = find_knowledge_point(progress, kp_id)
        assert kp is not None
        payload = {
            "knowledge_point_id": kp_id,
            "path_revision": progress.version,
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
        new_modules, error = _parse_modules(kwargs.get("modules"), path_id, 0)
        if error:
            return ToolResult(content=error, success=False)

        progress = service.replace_modules_for_path(
            path_id,
            new_modules,
            append=mode == "append",
            event_type="path.built",
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
        )
        kp_count = sum(len(m.knowledge_points) for m in new_modules)
        return _json_result(
            {
                "status": "built",
                "path_revision": progress.version,
                "mode": mode,
                "modules_added": len(new_modules),
                "knowledge_points_added": kp_count,
                "map": map_summary(progress),
            },
            meta_key="mastery_build",
        )


class MasteryPathsTool(BaseTool):
    """List every path the learner owns and which one this turn is on."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_paths",
            description=(
                "List every mastery path this learner has — name, how many "
                "objectives are mastered vs still being learned, reviews due, "
                "and which one this conversation is currently on. Use it when "
                "the learner asks what they are studying or what is finished, "
                "or before mastery_switch, to find the id to switch to."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        service = _new_service()
        active = _resolve_path_id(kwargs)
        overviews = await asyncio.to_thread(service.list_path_overviews)
        # A path with no objectives is one nobody has built yet; listing it
        # would offer the model an id that teaches nothing.
        paths = [
            {**overview, "active": overview["path_id"] == active}
            for overview in overviews
            if overview["objectives"] > 0
        ]
        return _json_result(
            {
                "active_path_id": active,
                "paths": paths,
                "instruction": (
                    "Switch with mastery_switch(path_id=...) — it takes effect "
                    "from your next round, so call mastery_status afterwards."
                ),
            },
            meta_key="mastery_paths",
        )


class MasterySwitchTool(BaseTool):
    """Point this conversation at a different mastery path."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_switch",
            description=(
                "Put this conversation on a different mastery path — use it to "
                "enter a path the learner names, or to move from the current "
                "one to another. The path keeps all of its own progress; the "
                "conversation simply follows it from now on, including on "
                "later turns. Call mastery_paths first for valid ids, and "
                "mastery_status afterwards to see where the new path stands."
            ),
            parameters=[
                ToolParameter(
                    name="path_id",
                    type="string",
                    description="Path id from mastery_paths (verbatim).",
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.capabilities.mastery.binding import (
            PathBindingError,
            rebind_active_path,
        )

        requested = str(kwargs.get("path_id") or "").strip()
        if not requested:
            return ToolResult(
                content="mastery_switch needs a path_id; call mastery_paths for the ids.",
                success=False,
            )
        previous = _resolve_path_id(kwargs)
        try:
            active = await rebind_active_path(
                path_id=requested,
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
                bind_turn=kwargs.get("_bind_active_path"),
            )
        except PathBindingError as exc:
            return ToolResult(content=str(exc), success=False)
        return _json_result(
            {
                "status": "switched",
                "previous_path_id": previous,
                "active_path_id": active,
                "instruction": (
                    "This conversation now follows that path, on this turn and "
                    "later ones. Call mastery_status to see where it stands."
                ),
            },
            meta_key="mastery_switch",
        )


class MasteryLeaveTool(BaseTool):
    """Detach this conversation from the named path it was following."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_leave",
            description=(
                "Stop following the current mastery path in this conversation. "
                "The path keeps every bit of its progress and can be resumed "
                "any time with mastery_switch; this conversation falls back to "
                "a scratch path of its own, so the learner can start something "
                "new here. Use it when the learner says they are done with the "
                "course for now, or wants to work on something unrelated."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.capabilities.mastery.binding import (
            PathBindingError,
            leave_active_path,
        )

        previous = _resolve_path_id(kwargs)
        try:
            active = await leave_active_path(
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
                bind_turn=kwargs.get("_bind_active_path"),
            )
        except PathBindingError as exc:
            return ToolResult(content=str(exc), success=False)
        return _json_result(
            {
                "status": "left",
                "previous_path_id": previous,
                "active_path_id": active,
                "instruction": (
                    "That path is untouched and resumable with mastery_switch. "
                    "This conversation is now on its own scratch path."
                ),
            },
            meta_key="mastery_leave",
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
    MasteryQuizTool,
    MasteryGradeTool,
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryPathsTool,
    MasterySwitchTool,
    MasteryLeaveTool,
)


__all__ = [
    "MASTERY_TOOL_NAMES",
    "MASTERY_TOOL_TYPES",
    "MasteryAssessTool",
    "MasteryBuildTool",
    "MasteryGradeTool",
    "MasteryLeaveTool",
    "MasteryPathsTool",
    "MasteryQuizTool",
    "MasteryStatusTool",
    "MasterySwitchTool",
]
