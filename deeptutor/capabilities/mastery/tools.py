"""Mastery Path tools — the seam between the chat-loop tutor and the pure
mastery engine (:mod:`deeptutor.learning`).

These tools are auto-mounted only when a mastery path is active on the
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
import random
import re
from typing import TYPE_CHECKING, Any
import uuid

from deeptutor.capabilities.mastery.choices import (
    canonical_labels,
    has_option_bodies,
    labelled_options,
    option_label_intent,
    parse_options,
    read_option_objects,
    recover_options_from_turn,
    resolve_answer,
    resolve_choice_submission,
    strip_echoed_options,
)
from deeptutor.capabilities.mastery.mode import (
    MODES,
    REVIEW,
    admission_error,
    enforced_mode,
    normalize_mode,
    tool_is_allowed,
    wrong_mode_message,
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
    TopicSourceKind,
)
from deeptutor.learning.objective_relations import (
    ObjectiveRelationError,
    RelationRefs,
    normalize_refs,
)
from deeptutor.learning.pending import positional_label, public_pending_question
from deeptutor.learning.policy import (
    QUALITATIVE_TYPES,
    display_mastery,
    find_knowledge_point,
    gate_kind,
    gate_threshold,
    is_mastered,
    learning_stage,
    map_summary,
    next_objective,
    path_display_name,
    visual_achievements,
)
from deeptutor.learning.question_card import (
    QUESTION_CARD_KEY,
    attempt_number,
    build_grade_result,
    build_question_card,
)

if TYPE_CHECKING:
    from deeptutor.learning.models import LearningProgress
    from deeptutor.learning.service import LearningService

# Tool names the pipeline mounts together when a mastery path is active. Kept
# here so the mount policy and the registration list can't disagree.
MASTERY_TOOL_NAMES: tuple[str, ...] = (
    "mastery_prepare_lesson",
    "mastery_status",
    "mastery_quiz",
    "mastery_note_explained",
    "mastery_grade",
    "mastery_skip_question",
    "mastery_repair_question",
    "mastery_defer_objective",
    "mastery_assess",
    "mastery_build",
    "mastery_mode",
    "mastery_profile",
    "mastery_revise",
    "mastery_paths",
    "mastery_switch",
    "mastery_leave",
)

_QUESTION_TYPES = ("choice", "short", "open")
_ALLOWED_KP_TYPES = {t.value for t in KnowledgeType}
_BUILD_SHAPE_ERROR = (
    "mastery_build could not read any objective. Send modules as "
    '\'modules\': [{"name": "<module>", "knowledge_points": '
    '[{"name": "<objective>", "type": "memory|procedure|concept|design"}]}] '
    "— every knowledge point needs a name of at least two characters."
)
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


_DIFFICULTIES = ("easy", "medium", "hard")


def _normalize_difficulty(raw: Any) -> str:
    """Map the model's difficulty onto the bank's badge values, or drop it.

    An unrecognised value is discarded rather than rejected: a mislabelled
    difficulty must never cost the learner a question.
    """
    value = str(raw or "").strip().lower()
    return value if value in _DIFFICULTIES else ""


def _question_bank_type(question_type: str) -> str:
    qtype = str(question_type or "").strip().lower()
    if qtype == "choice":
        return "choice"
    if qtype == "open":
        return "written"
    return "short_answer"


def _duplicate_option_body(options: dict[str, str]) -> str:
    """The first option body that appears twice, ignoring case and spacing.

    A model does occasionally emit the same answer under two labels, and a
    choice card with identical options is unanswerable: the learner picks the
    one they believe is right and is graded wrong for picking the twin. Better
    to reject the registration and let the model write a real distractor.
    """
    seen: set[str] = set()
    for body in options.values():
        key = "".join(str(body or "").split()).casefold()
        if not key:
            continue
        if key in seen:
            return body
        seen.add(key)
    return ""


def _read_choice_options(raw_options: Any) -> list[dict[str, str]]:
    """The options as sent, read into ``[{label, body}]`` order.

    Two ways in. Objects — the shape this contract asks for — are read per
    option, each carrying its own label; ``ask_user``'s key names for the same
    two fields are read too, since a model working one turn sees both tools.
    A list of plain strings is the older, flatter shape: labels are inferred
    for the group by :func:`parse_options`, which is deliberately cautious
    about what counts as a label (``"x - 1 = 0"`` is not option ``X``).
    """
    if raw_options is None:
        return []

    read = read_option_objects(raw_options)
    if read is not None:
        options, unreadable = read
        if unreadable:
            # Naming the entry matters: a model that cannot see which one was
            # unusable rewrites the whole payload the same way and fails again.
            raise ValueError(
                "mastery_quiz.options entries must each be an option — "
                "{'label': 'A', 'body': 'first answer'} or the string "
                f"'A: first answer'; got {unreadable[0]!r}."
            )
        return labelled_options(options)

    if not isinstance(raw_options, (list, tuple)):
        raise ValueError("mastery_quiz.options must be an array of non-empty strings.")
    if any(not option.strip() for option in raw_options):
        raise ValueError("mastery_quiz.options must contain only non-empty strings.")
    texts = [option.strip() for option in raw_options]
    intended_labels = option_label_intent(texts)
    if intended_labels is not None and set(intended_labels) != canonical_labels(
        len(intended_labels)
    ):
        raise ValueError(
            f"Choice option labels must run A, B, C… with one option each; got "
            f"{intended_labels}. Retry mastery_quiz with one full body per label."
        )
    return [{"label": label, "body": body} for label, body in parse_options(texts).items()]


def _normalize_quiz_contract(
    raw_question_type: Any,
    raw_options: Any,
    expected_answer: str,
) -> tuple[str, list[dict[str, str]], str]:
    """Validate and canonicalise the persisted quiz shape.

    A missing question type is inferred from the actual payload: options mean
    ``choice`` and no options mean ``short``. Once a caller explicitly chooses
    ``short`` or ``open``, options are rejected instead of being silently
    discarded. Choice answers are stored as labels so the interactive card and
    deterministic grader always compare the same representation.
    """
    options = _read_choice_options(raw_options)

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

    labels = [option["label"] for option in options]
    if len(set(labels)) != len(labels) or set(labels) != canonical_labels(len(labels)):
        raise ValueError(
            f"Choice option labels must run A, B, C… with one option each; got "
            f"{labels}. Retry mastery_quiz with one full body per label."
        )

    choice_options = {option["label"]: option["body"] for option in options}
    duplicate = _duplicate_option_body(choice_options)
    if duplicate:
        raise ValueError(
            f"Two or more choice options have the same answer ({duplicate!r}), so the "
            "learner would be shown identical choices. Retry mastery_quiz with one "
            "distinct body per option."
        )
    if not has_option_bodies(choice_options):
        raise ValueError(
            "Choice questions need full option bodies in mastery_quiz.options "
            "(for example {'label': 'A', 'body': 'first answer'}), not only "
            "the labels A/B/C/D — the card renders the label itself, so a bare "
            "label leaves the learner with nothing to read."
        )
    normalized_bodies = {" ".join(body.split()).casefold() for body in choice_options.values()}
    if len(normalized_bodies) != len(choice_options):
        raise ValueError(
            "Choice option bodies must be unique; retry mastery_quiz with "
            "distinct answer text for every option."
        )
    resolved_expected = resolve_answer(expected_answer, choice_options)
    if not resolved_expected:
        raise ValueError(
            "Choice expected_answer must be an option label such as A/B/C/D, "
            "or uniquely match one full option body. Retry mastery_quiz with "
            "the correct label."
        )
    return question_type, options, resolved_expected


def _shuffle_choice_options(
    options: list[dict[str, str]], expected: str, rng: random.Random
) -> tuple[list[dict[str, str]], str]:
    """Reorder choice options so the correct answer is not pinned to one label.

    Models put the correct option first the overwhelming majority of the time,
    and the registration order is exactly what the card renders — so an unmixed
    session reads A = correct on quiz after quiz (HKUDS/DeepTutor#1691). The
    shuffle runs after validation and echo stripping, so every contract
    invariant still holds on the payload that gets persisted: bodies stay
    unique, labels are re-issued positionally, and ``expected`` follows its
    body to the new label — the interactive card and the deterministic grader
    keep comparing the same representation.
    """
    if len(options) < 2:
        return options, expected
    expected_body = next(option["body"] for option in options if option["label"] == expected)
    shuffled = list(options)
    rng.shuffle(shuffled)
    remapped = [
        {"label": positional_label(index), "body": option["body"]}
        for index, option in enumerate(shuffled)
    ]
    new_expected = next(option["label"] for option in remapped if option["body"] == expected_body)
    return remapped, new_expected


async def _resolve_pending_choice(
    pending: PendingQuestion, turn_id: str
) -> tuple[dict[str, str], str]:
    """Resolve a pending choice question's ``({label: body}, expected_label)``.

    The persisted options are authoritative. For legacy paths that stored only
    ``["A", "B", ...]`` it recovers the real bodies from the turn's
    ``ask_user`` event. The expected answer is normalised to a stable label
    when it resolves, else left as registered.
    """
    options = pending.choice_map
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
    path_id: str,
    session_id: str,
    turn_id: str,
    pending: PendingQuestion,
    user_answer: str,
    is_correct: bool,
    choice_options: dict[str, str] | None = None,
    correct_answer: str | None = None,
    material_title: str = "",
    section_title: str = "",
    attempt_count: int = 1,
    hints_used: int = 0,
    confidence: float | None = None,
    response_time: float | None = None,
    quality: float | None = None,
    result: str = "",
) -> None:
    if not session_id:
        return
    from deeptutor.learning.assessment import (
        AssessmentRecord,
        RecordAssessmentError,
        is_correct_to_result,
        record_assessment,
    )

    record = AssessmentRecord(
        session_id=session_id,
        turn_id=turn_id,
        question_id=pending.question_id,
        question=pending.prompt,
        question_type=_question_bank_type(pending.question_type),
        options=choice_options or pending.choice_map,
        correct_answer=correct_answer or pending.expected_answer,
        explanation=pending.explanation,
        difficulty=pending.difficulty,
        user_answer=user_answer,
        is_correct=is_correct,
        result=result or is_correct_to_result(is_correct),
        source="mastery_path",
        assessment_type="quiz",
        material_id=path_id,
        material_title=material_title,
        section_id=pending.knowledge_point_id,
        section_title=section_title,
        mastery_path_id=path_id,
        knowledge_point_id=pending.knowledge_point_id,
        attempt_count=attempt_count,
        hints_used=hints_used,
        confidence=confidence,
        response_time=response_time,
        quality=quality,
        visual_context=pending.visual_context,
    )
    try:
        await asyncio.wait_for(record_assessment(record), timeout=5.0)
    except (RecordAssessmentError, Exception):
        logger.warning(
            "Failed to sync mastery question %s to question bank for session %s",
            pending.question_id,
            session_id,
            exc_info=True,
        )


async def _sync_qualitative_to_question_bank(
    *,
    path_id: str,
    session_id: str,
    turn_id: str,
    knowledge_point_id: str,
    knowledge_point_name: str,
    passed: bool,
    evidence: str,
    material_title: str = "",
    quality: float | None = None,
    result: str = "",
) -> None:
    if not session_id:
        return
    from deeptutor.learning.assessment import (
        AssessmentRecord,
        RecordAssessmentError,
        record_assessment,
    )

    record = AssessmentRecord(
        session_id=session_id,
        turn_id=turn_id,
        question_id=f"qual:{knowledge_point_id}",
        question=knowledge_point_name,
        question_type="written",
        user_answer=evidence,
        is_correct=passed,
        result=result or ("correct" if passed else "partial"),
        source="mastery_path",
        assessment_type="qualitative",
        material_id=path_id,
        material_title=material_title,
        section_id=knowledge_point_id,
        section_title=knowledge_point_name,
        mastery_path_id=path_id,
        knowledge_point_id=knowledge_point_id,
        quality=1.0 if passed else 0.2 if quality is None else quality,
    )
    try:
        await asyncio.wait_for(record_assessment(record), timeout=5.0)
    except (RecordAssessmentError, Exception):
        logger.warning(
            "Failed to sync qualitative assessment %s to question bank for session %s",
            knowledge_point_id,
            session_id,
            exc_info=True,
        )


def _unreadable_choice_result(answer: str, options: dict[str, str]) -> ToolResult:
    """Ask for a definite choice rather than recording a guess as wrong."""
    shown = "; ".join(f"{label} = {body}" for label, body in options.items())
    blank = not str(answer or "").strip()
    return ToolResult(
        content=(
            (
                "The learner has not answered this question yet, so there is nothing to grade. "
                if blank
                else f"Could not tell which option {answer!r} picks, so it was NOT graded. "
            )
            + f"The options are: {shown}. Ask the learner which one they choose (or "
            "call mastery_quiz to put the question back in front of them), then call "
            "mastery_grade with the option label. Do not treat this as a wrong answer."
        ),
        success=False,
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


def _load_path(service: LearningService, path_id: str) -> LearningProgress | None:
    """Read a path, or ``None`` when it does not exist yet.

    Reading must not create. ``get_or_create`` is the right entry point for
    building, but as a read it manufactures an empty path — and the id it
    manufactures under is usually the conversation's own scratch id, which is
    how a chat that merely *asked* about its progress left an empty path behind
    each time (#909).
    """
    return service.store.load(path_id)


def _profile_status(
    progress: LearningProgress | None,
    knowledge_point_id: str | None = None,
    *,
    include_teaching_history: bool = False,
) -> dict[str, Any]:
    """The learner profile, and whether intake still has to happen.

    Returned by ``mastery_status`` on every round rather than injected once at
    build time. A profile that only reached the outline generator would be
    forgotten by the thirtieth knowledge point — which is exactly the failure
    intake exists to prevent.
    """
    profile = getattr(progress, "learner_profile", None) if progress is not None else None
    if profile is None or (profile.is_empty() and not profile.teaching_observations):
        return {
            "learner_profile": None,
            "intake_needed": True,
            "intake_instruction": (
                "This learner has not been asked about themselves yet. Before "
                "designing the outline, ask what they can already do, what "
                "'done' looks like for them, how much time they have, and how "
                "they want it taught — then record the answers with "
                "mastery_profile. Ask only what you cannot read off the "
                "materials yourself."
            ),
        }
    from deeptutor.learning.teaching import teaching_guidance

    objective_id = (
        next_objective(progress).knowledge_point_id
        if knowledge_point_id is None
        else knowledge_point_id
    )
    return {
        "learner_profile": {
            "prior_knowledge": profile.prior_knowledge,
            "target_level": profile.target_level,
            "time_budget": profile.time_budget,
            "preferences": profile.preferences,
            "teaching_strategy": profile.teaching_strategy,
            "notes": profile.notes,
            **teaching_guidance(profile, objective_id, include_history=include_teaching_history),
        },
        "intake_needed": profile.is_empty(),
    }


def _review_scope_refusal(
    kwargs: dict[str, Any],
    progress: LearningProgress | None,
    kp_id: str,
) -> ToolResult | None:
    """In review, refuse a knowledge point the learner has not mastered yet.

    This is what separates reviewing from studying, now that a due date no
    longer gates the mode. A due date is a reminder, not a permission — the
    learner may always ask to go back over something — but *revision* means
    re-testing what they have already proven. Letting it examine an untouched
    objective would make it a study session wearing a review label, and the
    frontier would advance in a sitting the learner opened to consolidate.
    """
    if enforced_mode(kwargs.get("_mastery_session_mode")) != REVIEW:
        return None
    if progress is None or not kp_id:
        return None
    kp, _module_id, _module_name = find_knowledge_point(progress, kp_id)
    if kp is None or is_mastered(progress, kp):
        return None
    return ToolResult(
        content=(
            f"{kp.name!r} is not mastered yet, and this conversation is "
            "reviewing. Review re-tests what the learner has already proven; "
            "teaching something new is what 'study' is for. Either pick a "
            "mastered knowledge point, or call mastery_mode with mode='study' "
            "and say why you are switching."
        ),
        success=False,
    )


def _mode_instructions(mode: str) -> str:
    """The prompt block for *mode*, to be handed back inside a tool result.

    The system prompt above the loop was assembled before the turn's first
    round and still frames the mode the turn opened in, so a mid-turn switch
    has to carry its own framing down. Empty on any lookup failure: a mode
    change that lost its wording is still a mode change, and the tools have
    already stopped refusing.
    """
    try:
        from deeptutor.services.prompt import get_prompt_manager
        from deeptutor.services.settings.interface_settings import get_response_language

        pack = (
            get_prompt_manager().load_prompts(
                module_name="mastery",
                agent_name="mastery_loop",
                language=get_response_language(default="en"),
            )
            or {}
        )
    except Exception:
        logger.debug("mastery_mode: prompt pack unreadable", exc_info=True)
        return ""
    section = pack.get("session")
    if not isinstance(section, dict):
        return ""
    return str(section.get(mode) or "").strip()


def _mode_of(kwargs: dict[str, Any]) -> str:
    """The mode this turn is in, as the loop capability injected it."""
    return normalize_mode(kwargs.get("_mastery_session_mode"))


def _wrong_mode_result(tool_name: str, kwargs: dict[str, Any]) -> ToolResult | None:
    """Refuse a tool that does not belong to this conversation's mode.

    Checked here rather than by withholding the tool at mount time, because a
    mode can change inside a turn and a turn's tool schemas cannot — see
    :mod:`deeptutor.capabilities.mastery.mode`. The learner-facing guarantee is
    the same either way: the engine refuses, so an outline sitting cannot
    examine them and a lesson cannot replace their course.
    """
    # The RAW value, never ``_mode_of``: normalising first would turn "this
    # conversation never recorded a mode" into "study", and every pre-modes
    # conversation would lose ``mastery_build`` it has always been able to call.
    raw = kwargs.get("_mastery_session_mode")
    if tool_is_allowed(tool_name, raw):
        return None
    return ToolResult(content=wrong_mode_message(tool_name, raw), success=False)


def _no_built_path_result(tool: str) -> ToolResult:
    return ToolResult(
        content=(
            f"This conversation is not on a built mastery path yet, so {tool} has "
            "nothing to act on. Call mastery_paths to see the learner's existing "
            "paths (mastery_switch to continue one), or mastery_build to design "
            "one here."
        ),
        success=False,
    )


async def _unbuilt_status_message(
    service: LearningService,
    active_path_id: str,
    topic: Any | None = None,
) -> str:
    """What to tell the model when the active path has no objectives.

    Two situations look identical from the map and are opposites in fact.

    A conversation may have resolved to its own **scratch** id while the
    learner's courses live elsewhere. Telling it to build unconditionally is
    what made the tutor answer "no mastery path has been built yet, let me
    create one" to a learner who had several (#909), so those are mentioned
    first — and *which* of them is the learner's to say, because guessing files
    their conversation under a course they never opened.

    Or the conversation may be on a **goal the learner just created**, which
    has a name, a stated goal and chosen materials, and deliberately has no
    outline because designing it is what this conversation is for. Reading that
    as "not on a path" is what made the tutor ignore the goal it was standing
    in and ask the learner to pick from the five they had built before. A
    created goal states a ``goal``; a scratch path never does.
    """
    goal_text = str(getattr(getattr(topic, "metadata", None), "goal", "") or "").strip()
    if goal_text:
        name = str(getattr(topic, "name", "") or "").strip() or active_path_id
        return (
            f"This conversation is on the mastery goal {name!r}, which the learner "
            "created and which has no outline yet. Designing that outline is what "
            "this conversation is for — it is a first draft, not an edit of "
            f"something they already agreed to. In their own words they want: "
            f"{goal_text!r}. The materials they chose for it are listed under "
            "[Topic Materials]; all of them are in play. Do NOT offer to switch to "
            "another goal and do NOT ask which course they mean — they are already "
            "in this one. Read the materials, ask what you cannot read off them, "
            "then call mastery_build."
        )
    overviews = await asyncio.to_thread(service.list_path_overviews)
    elsewhere = [
        overview
        for overview in overviews
        if overview["objectives"] > 0 and overview["path_id"] != active_path_id
    ]
    if not elsewhere:
        return (
            "No mastery path has been built yet. Design one from the learner's "
            "materials and call mastery_build."
        )
    if len(elsewhere) == 1:
        return (
            "This conversation is not on a built path, but the learner has one "
            "built elsewhere. Call mastery_paths for its id and mastery_switch "
            "to continue it — only call mastery_build if they want a new path "
            "here."
        )
    return (
        f"This conversation is not on a built path, but the learner already has "
        f"{len(elsewhere)} built elsewhere. Call mastery_paths, then ask the "
        "learner which one they mean and mastery_switch to the one they name — "
        "do not pick for them. Only call mastery_build if they want a new path "
        "here."
    )


class MasteryStatusTool(BaseTool):
    """Read current state, or refresh a current-turn runtime snapshot."""

    @staticmethod
    def _working_brief(payload: dict, progress: LearningProgress, focus_id: str = "") -> dict:
        """Project relevant state; this never alters the stored path or transcript."""
        from deeptutor.learning.policy import due_reviews

        selected = {payload["next"]["knowledge_point_id"], focus_id} - {""}
        reviews = due_reviews(progress)
        selected.update(task.knowledge_point_id for task in reviews[:3])
        if progress.pending_question is not None:
            selected.add(progress.pending_question.knowledge_point_id)
            selected.update(
                q.knowledge_point_id for q in getattr(progress.pending_question, "questions", ())
            )
        points = {kp.id: kp for module in progress.modules for kp in module.knowledge_points}
        # Preserve the prerequisite closure, even across module boundaries.
        todo = list(selected)
        while todo:
            point = points.get(todo.pop())
            for prerequisite in point.prerequisite_ids if point else ():
                if prerequisite not in selected:
                    selected.add(prerequisite)
                    todo.append(prerequisite)
        overview = payload["map"]
        payload["map"] = {
            **overview,
            "modules": [
                {
                    **module,
                    "knowledge_points": [
                        kp for kp in module["knowledge_points"] if kp["id"] in selected
                    ],
                }
                for module in overview["modules"]
                if any(kp["id"] in selected for kp in module["knowledge_points"])
            ],
        }
        for key in ("learning_stages", "visual_requirements"):
            payload[key] = {kp: value for kp, value in payload[key].items() if kp in selected}
        payload["due_review_ids"] = [task.knowledge_point_id for task in reviews[:3]]
        payload["state_scope"] = "working_brief"
        payload["inspection_instruction"] = (
            "This is the current working brief, not the full outline. Counts describe the whole path; "
            "only the current/focused objective, pending group, prerequisites and first three due "
            "reviews are expanded. Call mastery_status for the full map before selecting an omitted "
            "lesson or editing the outline. "
            "Current learner requests and fresh corrections override historical summaries."
        )
        return payload

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_status",
            description=(
                "Read the learner's mastery path: the next objective to work on "
                "(decided by a hard mastery gate), any question awaiting an "
                "answer, due reviews, and a map of every objective's status "
                "(new / learning / mastered). Use the current-turn runtime snapshot "
                "when supplied; otherwise call this FIRST. Refresh after changing "
                "the path, mode, outline, or progress when updated state is needed. "
                "Never guess the next objective or reuse an earlier turn's snapshot. "
                "The automatic working brief omits unrelated outline details; call this tool "
                "for the full map before selecting another lesson or editing the outline."
            ),
            parameters=[
                ToolParameter(
                    name="include_teaching_history",
                    type="boolean",
                    required=False,
                    description="Read all bounded path teaching notes only for explicit inspection/correction or obsolete-note cleanup. Default returns current objective notes only.",
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        include_history = kwargs.get("include_teaching_history", False)
        if type(include_history) is not bool:
            return ToolResult(content="include_teaching_history must be a boolean.", success=False)
        service = _new_service()
        progress = _load_path(service, path_id)
        # Which goal this is, in the learner's own words. The tutor had no way
        # to see it before: the map carries a name, and the sentence the
        # learner actually wrote when they created the goal lived only in the
        # dashboard — so a conversation standing inside a brand-new goal read
        # as a conversation standing nowhere.
        topic = (
            await asyncio.to_thread(service.store.get_topic, path_id, progress=progress)
            if progress is not None
            else None
        )
        identity = {
            "path_id": path_id,
            "path_name": path_display_name(progress) if progress is not None else "",
            "goal": str(getattr(getattr(topic, "metadata", None), "goal", "") or ""),
            "sources": [
                {
                    "id": source.id,
                    "kind": source.kind.value,
                    "label": source.label,
                    "available": source.available,
                }
                for source in getattr(topic, "sources", [])
                if source.kind != TopicSourceKind.GOAL
            ],
        }
        if progress is None or not any(module.knowledge_points for module in progress.modules):
            return _json_result(
                {
                    "status": "empty",
                    "path_revision": progress.version if progress is not None else 0,
                    **identity,
                    "message": await _unbuilt_status_message(service, path_id, topic),
                    **_profile_status(progress, include_teaching_history=include_history),
                },
                meta_key="mastery_status",
            )
        payload = {
            "status": "active",
            "path_revision": progress.version,
            **identity,
            # What this conversation is for. Reported so the tutor reasons from
            # the same fact its tool surface was narrowed by, rather than
            # inferring the sitting's purpose from what happens to be mounted.
            # What this conversation is doing right now. Reported so the tutor
            # reasons from the same fact its tool calls are checked against.
            "mode": normalize_mode(kwargs.get("_mastery_session_mode")),
            "next": next_objective(progress).to_dict(),
            "map": map_summary(progress),
            **_profile_status(progress, include_teaching_history=include_history),
            "learning_stages": {
                kp.id: learning_stage(progress, kp.id)
                for module in progress.modules
                for kp in module.knowledge_points
            }
            if progress
            else {},
            "visual_requirements": {
                kp.id: {
                    "required": kp.required_visual_tasks,
                    "demonstrated": visual_achievements(progress, kp.id),
                }
                for module in progress.modules
                for kp in module.knowledge_points
            }
            if progress
            else {},
        }
        interaction = service.store.get_active_interaction(path_id)
        if interaction is not None:
            pending_interaction: dict[str, Any] = {
                "question_id": interaction.interaction_id,
                "status": interaction.status.value,
            }
            if interaction.question.questions:
                graded_ids = {
                    result["question_id"] for result in interaction.result.get("results", [])
                }
                pending_interaction["answers"] = dict(interaction.answers)
                pending_interaction["remaining_question_ids"] = [
                    q.question_id
                    for q in interaction.question.questions
                    if q.question_id not in graded_ids
                ]
                pending_interaction["instruction"] = (
                    "Keep committed child replies verbatim. Grade only actual replies; "
                    "unanswered children remain open and earn no score. Continue at the requested "
                    "pace; explain reported gaps, but never infer confusion from an unanswered "
                    "item or invent a missing reply."
                )
            elif interaction.status == InteractionStatus.ANSWERED:
                # The answer is learner-authored state, not the hidden answer
                # key. Returning it lets a restart grade rather than ask twice.
                pending_interaction["learner_answer"] = interaction.user_answer
            else:
                # The card is not the only way in. A learner often answers the
                # question in the composer — that reply never reaches the
                # interaction, so without this the tutor re-posed the same
                # question forever and the path stalled on answer_pending.
                pending_interaction["instruction"] = (
                    "A question is already open. If the learner has answered it "
                    "anywhere in this conversation — on the card or in an ordinary "
                    "message — call mastery_grade with their answer and this "
                    "question_id. If they asked you something instead, answer that "
                    "first and leave the question open; re-posing it over their "
                    "question is how the same card came back four times while it "
                    "went unanswered. Call mastery_quiz to put it back in front of "
                    "them once they are ready — the engine holds the original and "
                    "re-poses it verbatim, so what you pass is ignored, and that "
                    "call ends the turn."
                )
            payload["pending_interaction"] = pending_interaction
        if kwargs.get("_working_brief"):
            payload = self._working_brief(payload, progress)
        return _json_result(payload, meta_key="mastery_status")


class MasteryNoteExplainedTool(BaseTool):
    """Record teaching without pretending that explanation is an assessment."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_note_explained",
            description="After publicly explaining a source-supported slice of an objective, record that delivered explanation with an exact quote. Current source evidence is revalidated. Never record a planned explanation or treat this as complete-objective coverage, assessment or mastery. A quiz is optional until the learner wants practice.",
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Exact objective ID from mastery_status.",
                ),
                ToolParameter(
                    name="summary",
                    type="string",
                    description="What was actually explained, including prerequisites and source limitations.",
                ),
                ToolParameter(
                    name="explanation_quote",
                    type="string",
                    description="Exact 24-2000 character excerpt of explanation already publicly delivered in this turn; not source text, reasoning or a future plan.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_note_explained", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        kp_id = str(kwargs.get("knowledge_point_id") or "")
        summary = str(kwargs.get("summary") or "").strip()[:2000]
        if not summary:
            return ToolResult(content="A teaching summary is required.", success=False)
        quote = kwargs.get("explanation_quote")
        if not isinstance(quote, str) or not 24 <= len(quote.strip()) <= 2000:
            return ToolResult(
                content="Provide an exact 24-2000 character excerpt of the explanation already delivered publicly in this turn.",
                success=False,
            )
        quote = quote.strip()
        read_delivery = kwargs.get("_teaching_delivery")
        delivery = read_delivery() if callable(read_delivery) else None
        expected_scope = {
            "path_id": path_id,
            "session_id": _resolve_session_id(kwargs),
            "turn_id": _resolve_turn_id(kwargs),
        }
        if (
            not isinstance(delivery, dict)
            or not all(expected_scope.values())
            or any(delivery.get(key) != value for key, value in expected_scope.items())
        ):
            return ToolResult(
                content="Teaching must be bound to the active runtime path, session and turn; no explanation was recorded.",
                success=False,
            )
        segments = delivery.get("segments")
        if not isinstance(segments, tuple) or any(
            not isinstance(segment, tuple)
            or len(segment) != 3
            or not isinstance(segment[0], int)
            or not isinstance(segment[1], (int, float))
            or not isinstance(segment[2], str)
            for segment in segments
        ):
            return ToolResult(
                content="Published explanation evidence is unavailable; no explanation was recorded.",
                success=False,
            )
        published = "".join(segment[2] for segment in segments)
        start = published.rfind(quote)
        if start < 0:
            return ToolResult(
                content="That excerpt has not been publicly delivered in this turn. Explain first, then record only what was taught; do not record a future plan.",
                success=False,
            )
        offset = 0
        matched = []
        for segment in segments:
            end = offset + len(segment[2])
            if offset < start + len(quote) and end > start:
                matched.append(segment)
            offset = end
        provenance = {
            **expected_scope,
            "event_seq_range": [matched[0][0], matched[-1][0]],
            "event_timestamp_range": [matched[0][1], matched[-1][1]],
        }
        service = _new_service()
        if _load_path(service, path_id) is None:
            return _no_built_path_result("mastery_note_explained")

        def note(tx):
            import time

            from deeptutor.learning.lesson_evidence import validate_evidence

            if find_knowledge_point(tx.progress, kp_id)[0] is None:
                raise ValueError("Unknown objective; refresh mastery_status.")
            validate_evidence(
                service.store,
                tx.progress,
                kp_id,
                tx.progress.lesson_evidence.get(kp_id, {}),
                allow_partial=True,
            )
            tx.progress.explained_objectives[kp_id] = {
                "summary": summary,
                "explanation_quote": quote,
                "delivery": provenance,
                "coverage": "partial",
                "timestamp": time.time(),
                "session_id": _resolve_session_id(kwargs),
                "turn_id": _resolve_turn_id(kwargs),
            }
            tx.emit(
                "objective.explained",
                {
                    "knowledge_point_id": kp_id,
                    "summary": summary,
                    "explanation_quote": quote,
                    "delivery": provenance,
                    "coverage": "partial",
                },
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )

        try:
            await asyncio.to_thread(service.store.mutate, path_id, note)
        except (ValueError, FileNotFoundError) as exc:
            return ToolResult(content=str(exc), success=False)
        return _json_result(
            {
                "knowledge_point_id": kp_id,
                "stage": "partially_explained",
                "coverage": "partial",
                "mastery_credit": False,
            },
            meta_key="mastery_note_explained",
        )


class MasteryQuizTool(BaseTool):
    """Register an objective-type question; the engine holds the answer."""

    def get_definition(self) -> ToolDefinition:
        definition = ToolDefinition(
            name="mastery_quiz",
            description=(
                "Pose practice cards for all objective types: MEMORY, PROCEDURE, "
                "CONCEPT, or DESIGN, singly or as a questions group. This one "
                "call registers the expected answer with the engine for exact or "
                "semantic grading (you never re-state the answer later) AND "
                "puts the question in front of the learner on its own answer "
                "card — do not call ask_user for it. THE TURN ENDS HERE: unlike "
                "ask_user, this does not wait for a reply inside your turn, so "
                "call it last and plan nothing after it. Their answer arrives as "
                "the next message and you grade it on the next turn with "
                "mastery_grade. CONCEPT / DESIGN cards are practice only: their "
                "qualitative gate still requires the learner's own explanation "
                "assessed through mastery_assess; quiz correctness cannot open it."
            ),
            parameters=[
                ToolParameter(
                    name="visual",
                    type="object",
                    required=False,
                    sensitive=True,
                    description="Optional source-grounded task: {task: identification|relationship|table_graph|comparison, sources:[{kb_name, asset_id OR source_path/page, source_hash?, region?}], reference_quote, accepted_answers: verified equivalent terms (including other languages), key_status: verified|unverified, answer_cues: none|visible|unverified, hints_used}. Retrieve and inspect original pixels first. reference_quote and expected_answer must use the source-grounded canonical terminology; accepted_answers may add verified translations for learner replies. Uncertain or conflicting keys stay ungraded. Visible or unknown cues mean guided practice, not independent mastery. Do not invent masks or regions.",
                ),
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective id from mastery_status (verbatim).",
                ),
                ToolParameter(
                    name="question",
                    type="string",
                    description=(
                        "The question stem shown to the learner — the ask only. "
                        "For a choice question do NOT list the options here: the "
                        "card renders 'options' as its own labelled, clickable "
                        "list, so a stem that repeats them shows every choice "
                        "twice. Naming one option to ask about it is fine."
                        " Make the stem self-contained for later practice: include "
                        "all required code, data, scenario details and diagrams "
                        "(Markdown or Mermaid). Do not refer only to a figure or "
                        "example in an earlier message."
                    ),
                ),
                ToolParameter(
                    name="expected_answer",
                    type="string",
                    description="The correct answer, used only server-side for grading.",
                    # The learner is looking at this question, and the trace
                    # that records the call is theirs to expand.
                    sensitive=True,
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
                        "The choices in label order, as "
                        "{'label': 'A', 'body': 'the full answer text'} objects; "
                        "passing options infers question_type='choice' when the "
                        "type is omitted. Labels run A, B, C…, one option each. "
                        "Every option needs its own 'body': the card renders the "
                        "label itself, so a label with no answer text leaves the "
                        "learner nothing to read, and two options with the same "
                        "body are unanswerable. Never pass options for "
                        "'short'/'open'."
                    ),
                    required=False,
                    items={
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "A, B, C… in order, one per option.",
                            },
                            "body": {
                                "type": "string",
                                "description": "The answer text this choice offers.",
                            },
                        },
                        "required": ["label", "body"],
                    },
                ),
                ToolParameter(
                    name="explanation",
                    type="string",
                    description=(
                        "Why the expected answer is right, in one or two sentences. "
                        "Held server-side like expected_answer — never shown on the "
                        "card the learner is answering — and saved with the attempt "
                        "so a wrong answer is reviewable later in their question "
                        "bank instead of being just a score."
                    ),
                    required=False,
                    # Withheld from the trace for the same reason as
                    # expected_answer: it names the right answer.
                    sensitive=True,
                ),
                ToolParameter(
                    name="difficulty",
                    type="string",
                    description=(
                        "How hard this question is for this learner right now. "
                        "Shown as a badge when they review the attempt later."
                    ),
                    required=False,
                    enum=list(_DIFFICULTIES),
                ),
            ],
        )
        leaf_parameters = {p.name: p.to_schema() for p in definition.parameters}
        from deeptutor.learning.visual_practice import visual_request_schema

        leaf_parameters["visual"].update(visual_request_schema())
        for parameter in definition.parameters:
            if parameter.name in {"knowledge_point_id", "question", "expected_answer"}:
                parameter.required = False
        definition.description += (
            " For several separately graded questions use questions (two to four single-question "
            "objects) in ONE call, not prose or repeated calls. One parent ends the turn. "
            "A pending item is retained unless the learner explicitly requests replacement. "
            "To show the CURRENT pending card again, use pending_action='resume' and "
            "its exact parent resume_question_id only; do not regenerate questions or keys."
        )
        definition.parameters.extend(
            [
                ToolParameter(
                    name="questions",
                    type="array",
                    required=False,
                    sensitive=True,
                    description="Two to four independently answered single-question contracts. Do not concatenate answer keys.",
                    items={
                        "type": "object",
                        "properties": leaf_parameters,
                        "required": ["knowledge_point_id", "question", "expected_answer"],
                        "additionalProperties": False,
                    },
                ),
                ToolParameter(
                    name="pending_action",
                    type="string",
                    required=False,
                    enum=["retain", "replace", "resume"],
                    description="Retain by default; replace only on an explicit learner request; resume re-presents the exact existing card without a new contract.",
                ),
                ToolParameter(
                    name="resume_question_id",
                    type="string",
                    required=False,
                    description="Exact CURRENT pending parent question_id from mastery_status, only with pending_action='resume'. Omit all new-question and replacement parameters.",
                ),
                ToolParameter(
                    name="replace_question_id",
                    type="string",
                    required=False,
                    description="Exact currently pending parent question_id when replacing; a stale id cannot retire a newer card.",
                ),
                ToolParameter(
                    name="replacement_request",
                    type="string",
                    required=False,
                    description="Literal quote from the current learner message requesting replacement, not a paraphrase.",
                ),
            ]
        )
        schema = definition.to_openai_schema()["function"]["parameters"]
        schema["properties"]["visual"].update(visual_request_schema())
        definition.raw_parameters = schema
        return definition

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_quiz", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        service = _new_service()
        progress = _load_path(service, path_id)
        if progress is None:
            return _no_built_path_result("mastery_quiz")
        pending_action = kwargs.get("pending_action", "retain")
        resume_id = kwargs.get("resume_question_id")
        if pending_action == "resume":
            contract_fields = {
                "knowledge_point_id",
                "question",
                "expected_answer",
                "question_type",
                "options",
                "explanation",
                "difficulty",
                "visual",
                "questions",
                "replace_question_id",
                "replacement_request",
            }
            if (
                not isinstance(resume_id, str)
                or not resume_id.strip()
                or any(kwargs.get(field) is not None for field in contract_fields)
            ):
                return ToolResult(
                    content="Resume needs only pending_action='resume' and the exact pending parent resume_question_id; omit new-question and replacement arguments.",
                    success=False,
                )
        elif resume_id is not None:
            return ToolResult(
                content="resume_question_id requires pending_action='resume'.", success=False
            )
        if pending_action == "replace":
            request = kwargs.get("replacement_request")
            learner_message = kwargs.get("_learner_message")
            if (
                not isinstance(request, str)
                or not request.strip()
                or not isinstance(learner_message, str)
                or request not in learner_message
            ):
                return ToolResult(
                    content="Replacement needs a literal request from the current learner message.",
                    success=False,
                )
        raw_questions = kwargs.get("questions")
        if pending_action == "resume":
            pending, echoed_options = None, False
        elif raw_questions is None:
            built = await self._build_question(kwargs, progress)
            if isinstance(built, ToolResult):
                return built
            pending, echoed_options, kp = built
        else:
            if not isinstance(raw_questions, list) or not 2 <= len(raw_questions) <= 4:
                return ToolResult(
                    content="questions must contain two to four independent questions.",
                    success=False,
                )
            fields = {
                "knowledge_point_id",
                "question",
                "expected_answer",
                "question_type",
                "options",
                "explanation",
                "difficulty",
                "visual",
            }
            leaves = []
            echoed_options = False
            # Reject malformed assistance anywhere in the batch before the
            # first leaf performs source/image inspection.
            from deeptutor.learning.visual_practice import visual_hint_count

            try:
                for raw in raw_questions:
                    if isinstance(raw, dict) and isinstance(raw.get("visual"), dict):
                        visual_hint_count(raw["visual"].get("hints_used"))
            except ValueError as exc:
                return ToolResult(content=str(exc), success=False)
            for raw in raw_questions:
                if (
                    not isinstance(raw, dict)
                    or set(raw) - fields
                    or not {"knowledge_point_id", "question", "expected_answer"} <= set(raw)
                ):
                    return ToolResult(
                        content="Group leaves must use the single-question contract, without nested groups.",
                        success=False,
                    )
                built = await self._build_question(
                    {**{key: value for key, value in kwargs.items() if key.startswith("_")}, **raw},
                    progress,
                )
                if isinstance(built, ToolResult):
                    return built
                question, echoed, kp = built
                leaves.append(question)
                echoed_options = echoed_options or echoed
            try:
                pending = PendingQuestion(
                    question_id=uuid.uuid4().hex,
                    knowledge_point_id=leaves[0].knowledge_point_id,
                    module_id=leaves[0].module_id,
                    prompt=str(kwargs.get("question") or ""),
                    question_type="group",
                    questions=leaves,
                )
            except ValueError as exc:
                return ToolResult(content=str(exc), success=False)
        from deeptutor.learning.service import MasteryInteractionError

        if pending is not None:
            from deeptutor.learning.lesson_evidence import LessonUnavailable
            from deeptutor.learning.semantic_assessment import AssessmentUnavailable, bind_questions

            try:
                await bind_questions(service.store, progress, pending.questions or [pending])
            except (AssessmentUnavailable, LessonUnavailable) as exc:
                return ToolResult(content=str(exc), success=False)
        try:
            progress, interaction, created = service.register_question(
                path_id,
                pending,
                pending_action=pending_action,
                replace_question_id=str(kwargs.get("replace_question_id") or ""),
                resume_question_id=str(resume_id or ""),
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        pending = interaction.question
        kp, _, _ = find_knowledge_point(progress, pending.knowledge_point_id)
        public_question = public_pending_question(pending)
        card = build_question_card(
            pending,
            objective_name=kp.name if kp is not None and not pending.questions else "",
            attempt=attempt_number(progress, pending.knowledge_point_id),
        )
        if pending.questions:
            for leaf_card, leaf in zip(card["questions"], pending.questions, strict=True):
                objective, _, _ = find_knowledge_point(progress, leaf.knowledge_point_id)
                leaf_card["objective"]["name"] = objective.name if objective else ""
                leaf_card["attempt"] = attempt_number(progress, leaf.knowledge_point_id)
        # The card is now the learner's to answer, which is the same commit the
        # old pause hook made before parking the turn.
        await asyncio.to_thread(
            service.mark_question_awaiting,
            path_id,
            interaction_id=interaction.interaction_id,
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
        )
        # Diagnostic only. The question itself travels in ``card``, so nothing
        # here restates it.
        payload = {
            "status": "registered" if created else "already_pending",
            "path_revision": progress.version,
            "knowledge_point_id": pending.knowledge_point_id,
            "question_id": pending.question_id,
            "pending_question": public_question.to_dict(),
        }
        end_turn = kwargs.get("_end_turn_on_card")
        if callable(end_turn):
            # Posing the question ends the turn (see
            # ``MasteryLoopCapability.final_text_override``). Signalled from
            # here rather than from the argument binding so a question that
            # failed to register leaves the turn running.
            end_turn()
        if created:
            notice = (
                "The question is on the learner's answer card and this turn ends "
                "here. Their answer arrives as the next message; grade it then "
                "with mastery_grade."
            )
        else:
            # The engine holds one open question per path, so a second call
            # re-presents the existing card instead of posing anything new.
            # Saying so plainly matters: reported verbatim as a fresh question,
            # a model that had already posed one this round could not tell that
            # its extra call did nothing, and kept making it.
            notice = (
                "No new question was posed: the learner already has an open "
                "question on their card, and this call re-presented that same "
                "one. Its parameters were ignored. The turn ends here — their "
                "answer arrives as the next message. Posing a question ends the "
                "turn, so do not call any further tools after mastery_quiz in "
                "the same round; nothing you plan after it will run."
            )
        if echoed_options:
            # Said plainly so the next question is written correctly, rather
            # than silently repairing the same mistake every round.
            notice += (
                " Note: your question text also listed the options, so the card "
                "would have shown each choice twice — once as prose, once as a "
                "button. That list was removed from the stem. Pass the ask in "
                "'question' and the choices only in 'options'."
            )
        qualitative_practice = any(
            point is not None and point.type in QUALITATIVE_TYPES
            for point, _, _ in (
                find_knowledge_point(progress, question.knowledge_point_id)
                for question in pending.questions or [pending]
            )
        )
        if qualitative_practice:
            # The mirror of ``record_qualitative_for_path``, which refuses
            # outright when mastery_assess is aimed at a quantitative
            # objective. This direction stays allowed — a question is a fair
            # way to probe a concept before teaching it — but it must not be
            # silent: the attempt lands in ``mastery_levels``, the qualitative
            # gate never reads it, and a tutor that assumes otherwise poses
            # questions forever at an objective they cannot open.
            notice += (
                " The CONCEPT / DESIGN objectives in this practice are gated qualitatively: "
                "grading their answers will not open their qualitative gate, however right "
                "the answers are. Use the cards to probe, then have the learner explain the idea in "
                "their own words and record that with mastery_assess."
            )

        metadata = {"mastery_quiz": payload, QUESTION_CARD_KEY: card}
        if pending_action == "resume" and pending.questions and interaction.result.get("results"):
            # The original grade message may be outside the current history
            # page. Reuse its public cumulative receipt to restore leaf locks;
            # this is a replay, never another grading call or mastery credit.
            result = {
                key: interaction.result[key]
                for key in (
                    "question_id",
                    "question_type",
                    "complete",
                    "remaining_question_ids",
                    "is_correct",
                    "result",
                )
                if key in interaction.result
            }
            leaf_fields = {
                "question_id",
                "knowledge_point_id",
                "is_correct",
                "learner_answer",
                "correct_label",
                "correct_body",
                "explanation",
                "result",
                "independent",
                "diagnosis",
                "final",
                "needs_clarification",
                "feedback",
                "confidence",
            }
            result["results"] = [
                {key: value for key, value in leaf.items() if key in leaf_fields}
                for leaf in interaction.result["results"]
            ]
            metadata["mastery_grade"] = {
                "question_id": pending.question_id,
                "question_type": "group",
                "complete": False,
                "remaining_question_ids": interaction.result.get("remaining_question_ids", []),
                "replayed": True,
                "result": result,
            }
        return ToolResult(content=notice, metadata=metadata)

    async def _build_question(self, kwargs, progress):
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

        question, echoed_options = strip_echoed_options(
            question, {option["label"]: option["body"] for option in options}
        )

        if q_type == "choice":
            options, expected = _shuffle_choice_options(options, expected, random.Random())

        scope = _review_scope_refusal(kwargs, progress, kp_id)
        if scope is not None:
            return scope
        kp, module_id, _ = find_knowledge_point(progress, kp_id)
        if kp is None:
            return ToolResult(
                content=f"Unknown objective {kp_id!r}; call mastery_status for valid ids.",
                success=False,
            )
        visual_context: dict[str, Any] = {}
        accepted_answers: list[str] = []
        if kwargs.get("visual") is not None:
            from deeptutor.learning.visual_practice import prepare_visual

            if not isinstance(kwargs["visual"], dict):
                return ToolResult(
                    content="visual must be an object with exact source references.", success=False
                )
            try:
                visual_context, accepted_answers = await asyncio.to_thread(
                    prepare_visual,
                    kwargs["visual"],
                    expected_answer=expected,
                    options={option["label"]: option["body"] for option in options},
                    attached_kbs=kwargs.get("_attached_kb_names"),
                    inspected_image_hashes=kwargs.get("_inspected_image_hashes", []),
                )
                from deeptutor.learning.visual_practice import account_for_recent_assistance

                visual_context = account_for_recent_assistance(
                    visual_context, progress.quiz_attempts, kp_id
                )
            except (OSError, ValueError, TypeError) as exc:
                return ToolResult(
                    content=f"Visual practice is unavailable: {exc}. Inspect/clarify the source; no assessment was created.",
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
            explanation=str(kwargs.get("explanation") or "").strip()[:2000],
            difficulty=_normalize_difficulty(kwargs.get("difficulty")),
            visual_context=visual_context,
            accepted_answers=accepted_answers,
        )
        return pending, echoed_options, kp


class MasteryGradeTool(BaseTool):
    """Grade the learner's answer to the pending question (deterministic)."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_grade",
            description=(
                "Grade the learner's answer to the question you registered with "
                "mastery_quiz. Exact answers use the stored key and other answers receive semantic assessment against the stored "
                "expected answer; this updates mastery, advances spaced "
                "repetition, and tells you whether the objective's gate is now "
                "cleared. Then give the learner feedback."
            ),
            parameters=[
                ToolParameter(
                    name="answer",
                    type="string",
                    description="The learner's answer, verbatim.",
                    required=False,
                ),
                ToolParameter(
                    name="answers",
                    type="object",
                    required=False,
                    description="For a group only: one or more exact child question_id to actual learner answer strings. Partial replies are saved and graded independently; unanswered children stay open. Use committed replies verbatim; never invent missing replies or concatenate answers.",
                ),
                ToolParameter(
                    name="question_id",
                    type="string",
                    description=(
                        "Stable question_id from mastery_status. Pass it whenever "
                        "you have it: without one the engine can only grade the "
                        "question it is still holding open, and a question already "
                        "ruled on is not that."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_grade", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        from deeptutor.learning.scheduler import SpacedRepetitionScheduler

        answer = str(
            kwargs.get("_learner_message")
            if "_learner_message" in kwargs
            else kwargs.get("answer") or ""
        )
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
            # reply — unless that commit was unreadable clarifying prose on a
            # choice card (#1004), in which case a later readable answer may
            # still recover the gate.
            from deeptutor.learning.pending import is_readable_choice_answer

            stored = str(interaction.user_answer or "")
            question = interaction.question
            if question.question_type != "choice" or is_readable_choice_answer(
                stored, question.choice_map
            ):
                answer = stored
        progress_before = _load_path(service, path_id)
        if progress_before is None:
            return _no_built_path_result("mastery_grade")
        pending = (
            interaction.question if interaction is not None else progress_before.pending_question
        )
        if pending is not None and pending.questions:
            return await self._grade_group(kwargs, service, scheduler, pending)
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
            answer_for_grading = resolve_choice_submission(answer, choice_options)
            if not answer_for_grading:
                if has_option_bodies(choice_options):
                    # Grading is a permanent, deterministic record. An answer
                    # we cannot map onto exactly one option is not a wrong
                    # answer — it is an unreadable one, and marking it wrong is
                    # how a learner who typed their choice instead of tapping
                    # the card lost mastery for being right.
                    return _unreadable_choice_result(answer, choice_options)
                # Legacy question with no recoverable bodies: the raw reply is
                # the only thing there is to compare.
                answer_for_grading = answer
        from deeptutor.learning.service import MasteryInteractionError

        try:
            progress, interaction, replayed = await service.grade_interaction_semantic(
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
            # The common way to land here now is grading something the runtime
            # already ruled on: an answer sent from a card is graded before the
            # turn starts, and a graded interaction is no longer the open one.
            return ToolResult(
                content=(
                    f"{exc} — if the learner answered on their card, the engine "
                    "graded it when this turn began and the verdict is in your "
                    "briefing above. Give them feedback and carry on; do not "
                    "grade it again."
                ),
                success=False,
            )
        pending = interaction.question
        is_correct = interaction.result.get("is_correct")
        # Upsert on every call, including an idempotent replay: if the first
        # best-effort sync timed out, a safe retry repairs the auxiliary
        # question bank without duplicating the mastery attempt.
        kp, _, _ = find_knowledge_point(progress, pending.knowledge_point_id)
        evidence_items = getattr(progress, "learning_evidence", None) or ()
        evidence = next(
            (
                item
                for item in reversed(evidence_items)
                if getattr(item, "knowledge_point_id", "") == pending.knowledge_point_id
                and getattr(item, "question_id", "") == pending.question_id
            ),
            None,
        )
        await _sync_mastery_attempt_to_question_bank(
            path_id=path_id,
            session_id=interaction.session_id or _resolve_session_id(kwargs),
            turn_id=interaction.turn_id or _resolve_turn_id(kwargs),
            pending=pending,
            # Replays must repair the auxiliary question bank with the
            # committed answer, not whatever a later model round supplied.
            user_answer=interaction.user_answer,
            is_correct=is_correct,
            choice_options=choice_options,
            correct_answer=expected_answer,
            material_title=progress.name,
            section_title=kp.name if kp else "",
            attempt_count=getattr(evidence, "attempt_count", 1) if evidence is not None else 1,
            hints_used=getattr(evidence, "hints_used", 0) if evidence is not None else 0,
            confidence=getattr(evidence, "confidence", None) if evidence is not None else None,
            response_time=getattr(evidence, "response_time", None)
            if evidence is not None
            else None,
            quality=getattr(evidence, "quality", None) if evidence is not None else None,
            result=str(interaction.result.get("result") or ""),
        )
        mastered = bool(kp and is_mastered(progress, kp))
        gate = gate_kind(kp) if kp else ""
        # What to do after the verdict. A qualitative objective needs its own
        # branch: quiz accuracy lands in ``mastery_levels`` without moving that
        # gate — it can even read a full 1.0 against a 1.0 threshold while
        # ``mastered`` stays false — so telling the model to pose another
        # question here is telling it to loop forever on an objective no
        # question can clear. That loop is invisible from the chat, where the
        # tutor narrates progress it never actually recorded, and visible on
        # the outline rail, which correctly never moves.
        if mastered:
            next_move = "going: this objective is mastered, so continue with mastery_status.next."
        elif gate == "qualitative":
            next_move = (
                "going on the same objective — but this one is gated "
                "qualitatively, so more questions cannot clear it however many "
                "the learner gets right. Teach the gap this attempt exposed, "
                "then ask them to explain the idea in their own words and "
                "record your judgement with mastery_assess. That call is the "
                "only thing that opens this gate."
            )
        else:
            next_move = (
                "going on the same objective — teach the gap this attempt "
                "exposed, and when you pose the next question with "
                "mastery_quiz put that call last, since it ends the turn."
            )
        if interaction.result.get("result") == "ungraded":
            next_move = "going with source clarification or an explanation. This was ungraded, created no negative evidence and did not change mastery. Do not turn uncertainty into a wrong answer."
        payload = {
            "is_correct": is_correct,
            "replayed": replayed,
            "path_revision": progress.version,
            "knowledge_point_id": pending.knowledge_point_id,
            "question_id": pending.question_id,
            "mastery": round(display_mastery(progress, kp), 3) if kp else 0.0,
            "threshold": round(gate_threshold(kp.type), 3) if kp else 0.0,
            # Which gate that number is being read against. Without it a
            # qualitative objective reports mastery 1.0 / threshold 1.0 /
            # mastered false, which is not a reading anyone can act on.
            "gate": gate,
            "mastered": mastered,
            "next": next_objective(progress).to_dict(),
            # The answer key, released to the learner's card now that the gate
            # has ruled — see ``build_grade_result``.
            "result": build_grade_result(
                question_id=pending.question_id,
                is_correct=is_correct,
                learner_answer=interaction.user_answer or answer,
                correct_label=expected_answer
                if interaction.result.get("result") != "ungraded"
                else "",
                choice_options=choice_options,
                explanation=(
                    str(
                        interaction.result.get("feedback")
                        or interaction.result.get("diagnosis")
                        or ""
                    )
                    if interaction.result.get("result") == "ungraded"
                    else pending.explanation
                ),
                result=str(interaction.result.get("result") or ""),
                final=interaction.result.get("final", True),
                needs_clarification=interaction.result.get("needs_clarification", False),
                feedback=interaction.result.get("feedback", ""),
                confidence=interaction.result.get("confidence"),
                independent=interaction.result.get("independent"),
            ),
            # A graded card is not an answer to the learner. The verdict and
            # the explanation are now on it, so the model that stops here
            # leaves the turn silent behind a card that only says "correct" —
            # exactly the dead end this instruction exists to prevent.
            "instruction": (
                "The card now shows the verdict, the correct option and your "
                "explanation, so do not restate the answer key. Say what this "
                "attempt tells you about their grasp of the objective, then keep "
                + next_move
                + " Never end the turn without saying anything."
            ),
        }
        return _json_result(payload, meta_key="mastery_grade")

    async def _grade_group(self, kwargs, service, scheduler, pending) -> ToolResult:
        from deeptutor.learning.service import MasteryInteractionError

        path_id = _resolve_path_id(kwargs)
        current = service.store.get_interaction(path_id, pending.question_id)
        submitted = kwargs.get("answers")
        if isinstance(submitted, dict) and "_learner_message" in kwargs:
            actual = str(kwargs.get("_learner_message") or "")
            if any(
                value != (current.answers.get(key) if current else None)
                and (not isinstance(value, str) or value not in actual)
                for key, value in submitted.items()
            ):
                return ToolResult(
                    content="Use the learner's actual committed answers verbatim.", success=False
                )
        try:
            progress, interaction, replayed = await service.grade_interaction_semantic(
                path_id,
                answer="",
                question_id=str(kwargs.get("question_id") or pending.question_id),
                answers=kwargs.get("answers"),
                scheduler=scheduler,
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        group_result = dict(interaction.result)
        group_result["results"] = [dict(result) for result in group_result["results"]]
        leaves = {leaf.question_id: leaf for leaf in interaction.question.questions}
        for result in group_result["results"]:
            leaf = leaves[result["question_id"]]
            kp, _, _ = find_knowledge_point(progress, leaf.knowledge_point_id)
            evidence = next(
                (
                    item
                    for item in reversed(progress.learning_evidence)
                    if item.question_id == leaf.question_id
                ),
                None,
            )
            # Repair auxiliary history on replays as well, using committed data.
            if result["is_correct"] is not None:
                await _sync_mastery_attempt_to_question_bank(
                    path_id=path_id,
                    session_id=interaction.session_id,
                    turn_id=interaction.turn_id,
                    pending=leaf,
                    user_answer=interaction.answers[leaf.question_id],
                    is_correct=result["is_correct"],
                    choice_options=leaf.choice_map,
                    correct_answer=leaf.expected_answer,
                    material_title=progress.name,
                    section_title=kp.name if kp else "",
                    attempt_count=evidence.attempt_count if evidence else 1,
                    hints_used=evidence.hints_used if evidence else 0,
                    confidence=evidence.confidence if evidence else None,
                    response_time=evidence.response_time if evidence else None,
                    quality=evidence.quality if evidence else None,
                    result=str(result.get("result") or ""),
                )
            result.update(
                {
                    "mastery": round(display_mastery(progress, kp), 3) if kp else 0,
                    "gate": gate_kind(kp) if kp else "",
                    "mastered": bool(kp and is_mastered(progress, kp)),
                }
            )
        return _json_result(
            {
                "question_id": pending.question_id,
                "question_type": "group",
                "is_correct": group_result["is_correct"],
                "complete": group_result.get("complete", True),
                "remaining_question_ids": group_result.get("remaining_question_ids", []),
                "replayed": replayed,
                "path_revision": progress.version,
                "result": group_result,
                "next": next_objective(progress).to_dict(),
                "instruction": "Give explanatory feedback only for answered questions. Preserve independent results; the parent grants no extra mastery. If complete=false, unanswered children remain open. Continue at the requested pace and explain reported gaps; do not infer confusion from an unanswered item, invent replies or regrade committed answers. Keep qualitative gates and adapt teaching to the learner's needs.",
            },
            meta_key="mastery_grade",
        )


class MasteryAssessTool(BaseTool):
    """Record the qualitative (CONCEPT / DESIGN) gate from a Feynman check."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_assess",
            description=(
                "Assess a CONCEPT or DESIGN objective after the "
                "learner explains it in their own words (a Feynman-style check). "
                "The server evaluates the actual learner explanation against the objective and current sources; "
                "a model-supplied pass flag cannot grant mastery. This is the gate for these "
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
                    description="Deprecated compatibility hint; ignored. The actual learner explanation is assessed by the server.",
                    required=False,
                ),
                ToolParameter(
                    name="feedback",
                    type="string",
                    description="Optional teaching note; does not replace the actual learner explanation or the server verdict.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_assess", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        from deeptutor.learning.scheduler import SpacedRepetitionScheduler

        kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
        if not kp_id:
            return ToolResult(content="mastery_assess needs a knowledge_point_id.", success=False)
        learner_answer = str(kwargs.get("_learner_message") or "").strip()

        service = _new_service()
        progress = _load_path(service, path_id)
        if progress is None:
            return _no_built_path_result("mastery_assess")
        scope = _review_scope_refusal(kwargs, progress, kp_id)
        if scope is not None:
            return scope
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
            progress, receipt = await service.assess_qualitative_semantic(
                path_id,
                kp_id,
                learner_answer=learner_answer,
                scheduler=SpacedRepetitionScheduler(),
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        if not receipt["final"]:
            return _json_result({"knowledge_point_id": kp_id, **receipt}, meta_key="mastery_assess")
        passed = receipt["result"] == "correct"
        feedback = receipt["feedback"]
        kp, _, _ = find_knowledge_point(progress, kp_id)
        assert kp is not None
        await _sync_qualitative_to_question_bank(
            path_id=path_id,
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
            knowledge_point_id=kp_id,
            knowledge_point_name=kp.name,
            passed=passed,
            evidence=learner_answer,
            result=receipt["result"],
            quality={"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[receipt["result"]],
            material_title=progress.name,
        )
        payload = {
            "knowledge_point_id": kp_id,
            "path_revision": progress.version,
            "passed": passed,
            **receipt,
            "mastered": is_mastered(progress, kp),
            "mastery": round(display_mastery(progress, kp), 3),
            "next": next_objective(progress).to_dict(),
        }
        return _json_result(payload, meta_key="mastery_assess")


class MasterySkipQuestionTool(BaseTool):
    """Abandon the open question without inventing a graded result."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_skip_question",
            description=(
                "Abandon the currently open mastery question without grading "
                "it. This keeps every attempt and mastery level already earned, "
                "but gives no credit for the abandoned question. Use it only "
                "when the learner explicitly asks to skip this question or the "
                "question is unrecoverably stuck; if mastery_status reports an "
                "answered interaction, retry mastery_grade first."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_skip_question", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()

        service = _new_service()
        if _load_path(service, path_id) is None:
            return _no_built_path_result("mastery_skip_question")

        interaction = service.store.get_active_interaction(path_id)
        progress, skipped = service.abandon_active_question(path_id)
        payload = {
            "status": "skipped" if skipped else "no_pending_question",
            "skipped": skipped,
            "path_revision": progress.version,
            "question_id": interaction.interaction_id if interaction is not None else "",
            "next": next_objective(progress).to_dict(),
            "instruction": (
                "The question was abandoned without an attempt or mastery credit. "
                "Continue the objective from mastery_status.next and register a "
                "different question with mastery_quiz."
                if skipped
                else "No question was open; follow mastery_status.next."
            ),
        }
        return _json_result(payload, meta_key="mastery_skip_question")


class MasteryRepairQuestionTool(BaseTool):
    """Void or re-key an invalid question so it cannot keep poisoning mastery."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_repair_question",
            description=(
                "Repair an invalid mastery question or an incorrect answer key. "
                "action='void' removes the attempt from mastery, errors, review, "
                "and the question bank's wrong-answer set. action='correct' "
                "writes the true expected answer and re-grades the stored reply. "
                "Use this when the learner reports a bad question; do not keep "
                "quizzing the same objective on a known-wrong key."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="void | correct",
                    enum=["void", "correct"],
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Why this question or answer key is being repaired.",
                ),
                ToolParameter(
                    name="question_id",
                    type="string",
                    description="Question to repair. Defaults to the active or latest question.",
                    required=False,
                ),
                ToolParameter(
                    name="expected_answer",
                    type="string",
                    description="The corrected answer key. Required when action is correct.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_repair_question", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        from deeptutor.learning.scheduler import SpacedRepetitionScheduler
        from deeptutor.learning.service import MasteryInteractionError

        service = _new_service()
        if _load_path(service, path_id) is None:
            return _no_built_path_result("mastery_repair_question")
        try:
            progress, details = await service.repair_question_semantic(
                path_id,
                str(kwargs.get("question_id") or "").strip(),
                action=str(kwargs.get("action") or ""),
                expected_answer=str(kwargs.get("expected_answer") or ""),
                reason=str(kwargs.get("reason") or ""),
                scheduler=SpacedRepetitionScheduler(),
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)

        kp, _, section_title = find_knowledge_point(progress, details["knowledge_point_id"])
        if details["session_id"] and details["question_id"]:
            pending = PendingQuestion(
                question_id=details["question_id"],
                knowledge_point_id=details["knowledge_point_id"],
                module_id=details["module_id"],
                prompt=details["prompt"],
                question_type=details["question_type"] or "short",
                expected_answer=details["expected_answer"],
                explanation=(
                    f"Voided invalid question: {details['reason']}"
                    if details["action"] == "void"
                    else details["explanation"]
                ),
                difficulty=details["difficulty"],
            )
            await _sync_mastery_attempt_to_question_bank(
                path_id=path_id,
                session_id=details["session_id"],
                turn_id=details["turn_id"],
                pending=pending,
                user_answer=details["user_answer"],
                is_correct=False if details["action"] == "void" else details["is_correct"],
                result="voided" if details["action"] == "void" else details.get("result", ""),
                choice_options=details["options"] or None,
                correct_answer=details["expected_answer"],
                section_title=section_title or (kp.name if kp is not None else ""),
            )
        payload = {
            "status": "repaired",
            "result": details.get("result", ""),
            "feedback": details.get("feedback", ""),
            "action": details["action"],
            "question_id": details["question_id"],
            "knowledge_point_id": details["knowledge_point_id"],
            "path_revision": progress.version,
            "is_correct": details["is_correct"],
            "mastery": round(display_mastery(progress, kp), 3) if kp is not None else 0.0,
            "mastered": is_mastered(progress, kp) if kp is not None else False,
            "next": next_objective(progress).to_dict(),
            "instruction": (
                "The invalid question no longer counts as learner error. "
                "Continue from mastery_status.next."
                if details["action"] == "void"
                else "The answer key was corrected and the stored reply was re-graded. "
                "Continue from mastery_status.next."
            ),
        }
        return _json_result(payload, meta_key="mastery_repair_question")


class MasteryDeferObjectiveTool(BaseTool):
    """Leave the current objective for later without claiming it is mastered."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_defer_objective",
            description=(
                "Temporarily defer the current (or named) objective and continue "
                "with the next eligible one. This does not mark the objective "
                "mastered and does not write a learner override. Use it only when "
                "the learner explicitly asks to move on for now. Skipping a "
                "question is still mastery_skip_question."
            ),
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Objective to defer. Defaults to the current next objective.",
                    required=False,
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Optional note for why this objective is deferred.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_defer_objective", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        from deeptutor.learning.service import MasteryInteractionError

        service = _new_service()
        if _load_path(service, path_id) is None:
            return _no_built_path_result("mastery_defer_objective")
        try:
            progress, details = service.defer_objective(
                path_id,
                str(kwargs.get("knowledge_point_id") or "").strip(),
                note=str(kwargs.get("reason") or ""),
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
            )
        except MasteryInteractionError as exc:
            return ToolResult(content=str(exc), success=False)
        kp, _, _ = find_knowledge_point(progress, details["knowledge_point_id"])
        payload = {
            "status": "deferred",
            "knowledge_point_id": details["knowledge_point_id"],
            "path_revision": progress.version,
            "mastered": is_mastered(progress, kp) if kp is not None else False,
            "abandoned_question": details["abandoned_question"],
            "next": next_objective(progress).to_dict(),
            "map": map_summary(progress),
            "instruction": (
                "The objective is deferred, not mastered. Continue with "
                "mastery_status.next. Do not treat this as clearing the gate."
            ),
        }
        return _json_result(payload, meta_key="mastery_defer_objective")


class MasteryBuildTool(BaseTool):
    """Create / extend the skill map from objectives the tutor designed."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_build",
            description=(
                "Create or extend the learner's mastery goal. Design modules and "
                "their knowledge points from the learner's materials (use rag / "
                "read_source first when materials are attached) and pass them "
                "here, with a short path_name the learner will recognise. Each "
                "module needs an 'objective': one sentence saying what the "
                "learner can do once it is cleared — it is shown beside the "
                "module and is the contract mastery_revise reshapes its "
                "knowledge points against. Each knowledge point needs a 'type': "
                "memory (facts), procedure (step-by-step skills), concept (ideas "
                "to understand), or design (open-ended judgement). Use "
                "mode='replace' to start a new outline — semantically new "
                "objectives get fresh IDs and do not inherit previous mastery — "
                "or 'append' to add to an existing path."
            ),
            parameters=[
                ToolParameter(
                    name="modules",
                    type="array",
                    description=(
                        "Ordered modules: each {name, objective, knowledge_points: "
                        "[{name, type}]}. objective is one sentence naming the "
                        "ability this module delivers. type is one of "
                        "memory/procedure/concept/design."
                    ),
                    items={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "objective": {
                                "type": "string",
                                "description": (
                                    "What the learner can do once this module is "
                                    "cleared, as one sentence."
                                ),
                            },
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
                                        "client_ref": {
                                            "type": "string",
                                            "description": (
                                                "Request-local alias for this new knowledge "
                                                "point. Use it in prerequisite_refs."
                                            ),
                                        },
                                        "prerequisite_refs": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": (
                                                "Required objectives. In append mode use an "
                                                "existing map id or a client_ref from this call."
                                            ),
                                        },
                                        "topic_source_refs": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": (
                                                "Non-goal source ids reported by mastery_status."
                                            ),
                                        },
                                    },
                                    "required": ["name"],
                                },
                            },
                        },
                        "required": ["name", "objective", "knowledge_points"],
                    },
                ),
                ToolParameter(
                    name="path_name",
                    type="string",
                    description=(
                        "What to call this path — a short course title the "
                        "learner will recognise in their dashboard, such as "
                        "'Quadratic equations'. Used only when the path has no "
                        "name yet; rebuilding a named path keeps its name, and "
                        "renaming one is the learner's own call."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'replace' (default) starts a new outline with "
                    "fresh IDs for new objectives; 'append' adds modules.",
                    required=False,
                    default="replace",
                    enum=["replace", "append"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_build", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        mode = str(kwargs.get("mode") or "replace").strip().lower()
        if mode not in {"replace", "append"}:
            mode = "replace"

        service = _new_service()
        new_modules, relation_refs, error = _parse_modules_with_refs(
            kwargs.get("modules"),
            path_id,
            0,
            fallback_module_name=str(kwargs.get("path_name") or "").strip()[:200],
        )
        if error:
            return ToolResult(content=error, success=False)

        try:
            progress = service.replace_modules_for_path(
                path_id,
                new_modules,
                append=mode == "append",
                name=str(kwargs.get("path_name") or ""),
                event_type="path.built",
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
                relation_refs=relation_refs,
                identity_mode="semantic" if mode != "append" else "explicit",
            )
        except ObjectiveRelationError as exc:
            return ToolResult(content=str(exc), success=False)
        kp_count = sum(len(m.knowledge_points) for m in new_modules)
        return _json_result(
            {
                "status": "built",
                "path_revision": progress.version,
                "mode": mode,
                # The name in effect, which is not necessarily the one passed:
                # an already-named path keeps the name the learner sees.
                "path_name": path_display_name(progress),
                "modules_added": len(new_modules),
                "knowledge_points_added": kp_count,
                "map": map_summary(progress),
            },
            meta_key="mastery_build",
        )


class MasteryModeTool(BaseTool):
    """Move this conversation between designing, learning and reviewing.

    The mode is what the sitting is *doing*: it picks the tutor's framing and
    decides which tools will run. It is state on the conversation, not a
    property of it, so nobody has to open a new one to fix a knowledge point
    mid-lesson — and the learner sees the change, because the mode is shown
    above the transcript and they can press it themselves.

    The new mode's instructions come back in the result on purpose. The system
    prompt above was assembled before this turn's first round and still
    describes the mode the turn opened in; a tool result is the only thing that
    can correct that without waiting for the next turn.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_mode",
            description=(
                "Switch what this conversation is doing: 'outline' to design "
                "or change the outline, 'study' to work it forward, 'review' to "
                "re-test what is already mastered. Call it when the learner "
                "asks for something the current mode's tools cannot do — a "
                "refused tool names the mode it needs. Say what you are "
                "switching to and why: the learner sees the mode above the "
                "conversation and can change it themselves."
            ),
            parameters=[
                ToolParameter(
                    name="mode",
                    type="string",
                    description="outline | study | review",
                    enum=list(MODES),
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description=(
                        "One short phrase for why, in the learner's language. "
                        "Shown with the mode change."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()

        requested = str(kwargs.get("mode") or "").strip().lower()
        if requested not in MODES:
            return ToolResult(
                content=(
                    f"{requested!r} is not a mode. Use one of: "
                    f"{', '.join(repr(mode) for mode in MODES)}."
                ),
                success=False,
            )

        current = _mode_of(kwargs)
        service = _new_service()
        progress = _load_path(service, path_id)
        has_outline = progress is not None and any(
            module.knowledge_points for module in progress.modules
        )
        refusal = admission_error(requested, has_outline=has_outline)
        if refusal:
            return ToolResult(content=refusal, success=False)

        bind = kwargs.get("_bind_active_mode")
        if callable(bind):
            bind(requested)
        # Two places, like a path switch: the live turn so the rest of it can
        # use the new mode's tools, and the conversation so the next turn (and
        # a reload) resumes in it.
        from deeptutor.capabilities.mastery.binding import remember_mode_on_session

        await remember_mode_on_session(_resolve_session_id(kwargs), requested)
        return _json_result(
            {
                "status": "unchanged" if requested == current else "switched",
                "previous_mode": current,
                "mode": requested,
                # The framing for the mode just entered: the system prompt
                # still describes the one this turn opened in.
                "instructions": _mode_instructions(requested),
                "reason": str(kwargs.get("reason") or "").strip()[:200],
            },
            meta_key="mastery_mode",
        )


class MasteryProfileTool(BaseTool):
    """Record what the learner said about themselves.

    Intake is not a form and not a moment. The first session asks; later
    sessions correct — "I've done linear algebra since", "我时间变少了" — and
    both go through here, merging rather than replacing so one correction
    never silently wipes the other three answers.

    Deliberately *not* a read tool: ``mastery_status`` returns the profile
    every round, so a second way to read it could only disagree with the first.
    """

    def get_definition(self) -> ToolDefinition:
        from deeptutor.learning.teaching import TeachingUpdate

        return ToolDefinition(
            name="mastery_profile",
            description=(
                "Record what the learner told you about themselves for this "
                "mastery goal: what they can already do, what finishing means "
                "to them, how much time they have, and how they want it "
                "taught. Call it during intake — before designing the outline "
                "— and again whenever they correct one of these. Pass only the "
                "fields they actually spoke to; omitted, null or blank fields keep what they "
                "said before. Never invent an answer they did not give. "
                "For evolving teaching feedback use keyed teaching_updates: explicit "
                "preferences or objective-local difficulties/attempts. Keep attempts "
                "unknown until learner evidence shows helped/not_helped. Reuse a key "
                "to correct it, remove obsolete entries, preserve unrelated keys. "
                "To forget an intake field explicitly requested by the learner, use clear_fields "
                "and quote that current request in clear_request. Global preferences across "
                "unrelated paths belong in write_memory, only when explicitly requested."
            ),
            parameters=[
                ToolParameter(
                    name="prior_knowledge",
                    type="string",
                    description=(
                        "What they can already do in this subject, in their own "
                        "words. Where the outline starts."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="target_level",
                    type="string",
                    description=(
                        "What 'done' means to them — the ability they want, not "
                        "the topics they want covered."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="time_budget",
                    type="string",
                    description=(
                        "How much time they have, as they said it ('两周，每晚一"
                        "小时'). Sizes the outline."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="preferences",
                    type="string",
                    description=(
                        "How they want it taught: language, worked examples over "
                        "prose, intuition before formalism."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="teaching_strategy",
                    type="string",
                    description=(
                        "Use 'teach_first' only when the learner explicitly asks to be taught "
                        "before being quizzed; use 'probe_first' to restore the diagnostic default."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="notes",
                    type="string",
                    description=("Anything else worth carrying that the fields above do not hold."),
                    required=False,
                ),
                ToolParameter(
                    name="teaching_updates",
                    type="array",
                    required=False,
                    description=(
                        "1-6 keyed upsert/remove operations. Preference requires an explicit "
                        "learner_report with evidence. Observation requires a current path "
                        "knowledge_point_id; label inferred difficulties tentative. Strategy "
                        "results require learner_report evidence and strategy. Evidence is a "
                        "literal quote from the current learner message, never silence "
                        "or your own explanation. Upsert supplies the whole entry; remove "
                        "supplies only kind/op/key. Limits: 6 preferences, 12 observations."
                    ),
                    items=TeachingUpdate.model_json_schema(),
                ),
                ToolParameter(
                    name="expected_revision",
                    type="integer",
                    required=False,
                    description="Required with teaching_updates or clear_fields: path_revision from the current mastery snapshot. Refresh after conflict.",
                ),
                ToolParameter(
                    name="clear_fields",
                    type="array",
                    required=False,
                    description="Explicitly forget only the intake fields the learner asked to remove. Blank values never clear a field.",
                    items={
                        "type": "string",
                        "enum": [
                            "prior_knowledge",
                            "target_level",
                            "time_budget",
                            "preferences",
                            "notes",
                        ],
                    },
                ),
                ToolParameter(
                    name="clear_request",
                    type="string",
                    required=False,
                    description="Literal quote from the current learner request authorizing clear_fields. Omit unless clearing.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()

        fields = {
            key: kwargs[key]
            for key in (
                "prior_knowledge",
                "target_level",
                "time_budget",
                "preferences",
                "teaching_strategy",
                "notes",
            )
            if key in kwargs and kwargs[key] is not None and str(kwargs[key]).strip()
        }
        updates = kwargs.get("teaching_updates")
        clear_fields = kwargs.get("clear_fields")
        if not fields and updates is None and not clear_fields:
            return ToolResult(
                content=(
                    "mastery_profile needs at least one of prior_knowledge, "
                    "target_level, time_budget, preferences, teaching_strategy, notes or teaching_updates — pass what "
                    "the learner actually told you."
                ),
                success=False,
            )
        if "teaching_strategy" in fields and fields["teaching_strategy"] not in {
            "probe_first",
            "teach_first",
        }:
            return ToolResult(
                content="teaching_strategy must be probe_first or teach_first.",
                success=False,
            )

        service = _new_service()
        from deeptutor.learning.storage import LearningStoreError

        try:
            progress, changed = service.record_learner_profile(
                path_id,
                fields=fields,
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
                teaching_updates=updates,
                expected_revision=kwargs.get("expected_revision"),
                learner_message=str(kwargs.get("_learner_message") or ""),
                clear_fields=clear_fields,
                clear_request=kwargs.get("clear_request") or "",
            )
        except (ValueError, LearningStoreError) as exc:
            return ToolResult(content=str(exc), success=False)
        except KeyError:
            return ToolResult(
                content="The bound mastery path no longer exists. Refresh the current path.",
                success=False,
            )
        receipt = kwargs.get("_profile_recorded")
        if callable(receipt):
            receipt(
                {"path_id": path_id, "path_revision": progress.version, "updated_fields": changed}
            )
        return _json_result(
            {
                "status": "recorded",
                "path_revision": progress.version,
                # What actually changed, not what was passed: re-sending an
                # unchanged answer must not read back as new information.
                "updated_fields": changed,
                **_profile_status(progress),
            },
            meta_key="mastery_profile",
        )


class MasteryReviseTool(BaseTool):
    """Reshape one module's knowledge points without moving its goalposts.

    ``mastery_build`` is the blunt instrument: it replaces the whole outline,
    which is right when the learner wants a different course and catastrophic
    when they only dislike one waypoint. This tool is the surgical one, and it
    is bounded by the module objective written when the outline was designed —
    the tutor may reword, retype, drop and add knowledge points, but the
    ability the module promises stays fixed. That is what keeps "I don't like
    this one" from quietly turning into a different module.

    Two invariants protect the gate:

    * A rewritten knowledge point gets a **fresh id**, so the evidence that
      cleared the old wording is not silently claimed for the new one. The
      engine drops that point's stale state itself (``replace_modules``); the
      result names what was reset so the tutor can tell the learner.
    * A **mastered** knowledge point is refused, for rewrite and removal
      alike. It is proven work, and erasing it to satisfy a passing dislike
      would delete the one thing the learner cannot re-earn for free.
    """

    def get_definition(self) -> ToolDefinition:
        revise_items = {
            "type": "object",
            "properties": {
                "knowledge_point_id": {"type": "string"},
                "name": {"type": "string"},
                "type": {"type": "string", "enum": sorted(_ALLOWED_KP_TYPES)},
                "prerequisite_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("Omit to inherit; [] explicitly clears required objectives."),
                },
                "topic_source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Omit to inherit; [] explicitly clears sources.",
                },
            },
            "required": ["knowledge_point_id", "name"],
        }
        add_items = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string", "enum": sorted(_ALLOWED_KP_TYPES)},
                "prerequisite_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "topic_source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["name"],
        }
        return ToolDefinition(
            name="mastery_revise",
            description=(
                "Reshape the knowledge points inside ONE module of the current "
                "mastery goal, keeping the module's objective unchanged. Use it "
                "when the learner objects to specific knowledge points — too "
                "easy, too advanced, badly worded, not what they meant, or "
                "something missing. Every revision must still serve the "
                "module's stated objective (read it from mastery_status); when "
                "the learner wants something the objective does not cover, say "
                "so and offer mastery_build instead of quietly widening the "
                "module. Rewriting a knowledge point resets its progress; a "
                "knowledge point the learner has already mastered cannot be "
                "rewritten or removed. When one coordinated adjustment touches "
                "SEVERAL modules, pass them together as modules=[{module_id, "
                "rewrite, add, remove}, ...] in ONE call — they are applied, "
                "validated and reported as a single atomic revision, instead "
                "of one full-outline round per module. For coordinated outline "
                "edits, action=preview returns the exact proposed state changes "
                "without saving. Review them, then use action=commit with only "
                "that preview_id in a later model round. Omit action for the "
                "existing immediate content revision behavior. To change the "
                "displayed module sequence, use action=preview with module_order "
                "containing every existing module ID exactly once; content edits "
                "are optional. Reordering preserves objective IDs and evidence; "
                "it does not abandon an unanswered question or change the active "
                "objective. Never report an order change from a content-only edit "
                "or from an uncommitted preview."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    enum=["preview", "commit"],
                    description="Preview before a reviewed commit; omit for a direct revision.",
                    required=False,
                ),
                ToolParameter(
                    name="preview_id",
                    type="integer",
                    description="Commit only: the identifier returned by the reviewed preview.",
                    required=False,
                ),
                ToolParameter(
                    name="module_order",
                    type="array",
                    items={"type": "string"},
                    description=(
                        "Preview only: complete requested sequence of existing module IDs. "
                        "Omit to keep order unchanged; may be used without content edits. "
                        "Does not rename modules, waive prerequisites, or move the current objective."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="module_id",
                    type="string",
                    description=(
                        "Which module to revise. Copy it verbatim from "
                        "mastery_status's map. Single-module form only; for a "
                        "coordinated multi-module adjustment use 'modules'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="rewrite",
                    type="array",
                    description=(
                        "Knowledge points to restate: each {knowledge_point_id, "
                        "name, type}. type is optional and keeps its current "
                        "value when omitted."
                    ),
                    required=False,
                    items=revise_items,
                ),
                ToolParameter(
                    name="add",
                    type="array",
                    description=("Knowledge points to append to this module: each {name, type}."),
                    required=False,
                    items=add_items,
                ),
                ToolParameter(
                    name="remove",
                    type="array",
                    description="Knowledge point ids to drop from this module.",
                    required=False,
                    items={"type": "string"},
                ),
                ToolParameter(
                    name="modules",
                    type="array",
                    description=(
                        "Coordinated revisions for several modules, applied "
                        "together in one atomic revision: each entry "
                        "{module_id, rewrite, add, remove} with the same item "
                        "shapes as the single-module parameters. Use this "
                        "instead of one mastery_revise call per module when "
                        "the learner's request spans multiple modules."
                    ),
                    required=False,
                    items={
                        "type": "object",
                        "properties": {
                            "module_id": {"type": "string"},
                            "rewrite": {
                                "type": "array",
                                "items": revise_items,
                            },
                            "add": {"type": "array", "items": add_items},
                            "remove": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["module_id"],
                    },
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_revise", kwargs)
        if refusal is not None:
            return refusal
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()

        from deeptutor.learning.storage import LearningConflictError

        action = kwargs.get("action")
        if action not in (None, "preview", "commit"):
            return ToolResult(content="Use action preview or commit, or omit it.", success=False)
        service = _new_service()
        if action == "commit":
            if any(
                kwargs.get(key) is not None
                for key in ("module_id", "modules", "rewrite", "add", "remove", "module_order")
            ):
                return ToolResult(
                    content="Commit takes only preview_id; omit all revision edits.", success=False
                )
            try:
                progress, receipt = service.commit_module_revision(
                    path_id,
                    kwargs.get("preview_id"),
                    session_id=_resolve_session_id(kwargs),
                    turn_id=_resolve_turn_id(kwargs),
                    request_id=str(kwargs.get("_revision_request_id") or ""),
                )
            except (ValueError, TypeError, KeyError, LearningConflictError) as exc:
                return ToolResult(content=f"Revision not saved: {exc}", success=False)
            return _json_result(
                {
                    "status": "committed",
                    **receipt,
                    "path_revision": progress.version,
                    "current_module_order": [module.id for module in progress.modules],
                    "map": map_summary(progress),
                },
                meta_key="mastery_revise",
            )
        if kwargs.get("preview_id") is not None:
            return ToolResult(content="Use preview_id only with action commit.", success=False)

        module_order = kwargs.get("module_order")
        if module_order is not None and action != "preview":
            return ToolResult(
                content="Module reordering requires action preview followed by a reviewed commit.",
                success=False,
            )
        specs: dict[str, dict[str, Any]] = {}
        if module_order is None or any(
            kwargs.get(key) is not None
            for key in ("module_id", "modules", "rewrite", "add", "remove")
        ):
            specs, spec_error = _revise_specs(kwargs)
            if spec_error is not None:
                return ToolResult(content=spec_error, success=False)

        progress = _load_path(service, path_id)
        if progress is None or not progress.modules:
            return _no_built_path_result("mastery_revise")

        try:
            applied, targets, revised_by_module, resets_by_module = _plan_module_revision(
                progress, specs, module_order=module_order
            )
        except (ValueError, TypeError) as exc:
            return ToolResult(content=str(exc), success=False)
        if action == "preview":
            try:
                result, proposed = service.preview_module_revision(
                    path_id,
                    applied,
                    expected_revision=progress.version,
                    session_id=_resolve_session_id(kwargs),
                    request_id=str(kwargs.get("_revision_request_id") or ""),
                )
            except (ValueError, TypeError, KeyError, LearningConflictError) as exc:
                return ToolResult(content=f"Revision not saved: {exc}", success=False)
            return _json_result(
                {
                    "status": "preview_only_not_saved",
                    **result,
                    "proposed_map": map_summary(proposed),
                    "next_step": "Review every change and objective reset. Commit this preview_id in a later model round if coherent and within the learner's request; otherwise correct the edits and preview again.",
                },
                meta_key="mastery_revision_preview",
            )
        try:
            progress = service.replace_modules_for_path(
                path_id,
                applied,
                event_type="path.module_revised",
                session_id=_resolve_session_id(kwargs),
                turn_id=_resolve_turn_id(kwargs),
                identity_mode="explicit",
            )
        except ObjectiveRelationError as exc:
            return ToolResult(content=str(exc), success=False)

        def _module_report(module: LearningModule, points: list[KnowledgePoint]) -> dict[str, Any]:
            return {
                "module_id": module.id,
                "module_name": module.name,
                # Echoed so the tutor reports the revision against the promise
                # it was allowed to keep, not against its own recollection.
                "module_objective": module.objective,
                "knowledge_points": [
                    {
                        "id": kp.id,
                        "name": kp.name,
                        "type": kp.type.value,
                        "prerequisite_ids": kp.prerequisite_ids,
                        "topic_source_ids": kp.topic_source_ids,
                    }
                    for kp in points
                ],
            }

        if len(targets) == 1:
            target = targets[0]
            return _json_result(
                {
                    "status": "revised",
                    "path_revision": progress.version,
                    **_module_report(target, revised_by_module[target.id]),
                    "progress_reset": resets_by_module[target.id],
                    "map": map_summary(progress),
                },
                meta_key="mastery_revise",
            )
        # One payload — one outline map and one report per touched module —
        # instead of a full snapshot per module echoing through later rounds.
        return _json_result(
            {
                "status": "revised",
                "path_revision": progress.version,
                "modules": [
                    _module_report(target, revised_by_module[target.id])
                    | {"progress_reset": resets_by_module[target.id]}
                    for target in targets
                ],
                "map": map_summary(progress),
            },
            meta_key="mastery_revise",
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
                    "Switch with mastery_switch(path_id=...); every later call "
                    "in the turn — including ones issued alongside it — then "
                    "acts on the new path. Call mastery_status after switching."
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
                "Put this conversation on a path the learner has asked for — "
                "by name, or by clearly asking to start or return to it. The "
                "path keeps all of its own progress; the conversation follows "
                "it from now on, including on later turns, and stops being "
                "filed under the path it was on. Because of that, switch only "
                "on what the learner actually asked for: if their request "
                "could mean either of two paths, ask which before switching. "
                "Call mastery_paths first for valid ids, and mastery_status "
                "afterwards to see where the new path stands."
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
                    "later ones — anything else you called in this round acted "
                    "on it too. Call mastery_status to see where it stands."
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


# Ordered by how well each key names the thing for a learner: a real name
# first, a description only when there is nothing better, the raw id last.
_KP_NAME_KEYS = ("name", "title", "label", "objective", "topic", "description", "id")
_MODULE_NAME_KEYS = ("name", "title", "label", "module", "id")
_KP_LIST_KEYS = ("knowledge_points", "objectives", "points", "items")
#: Where a module's one-sentence purpose may arrive. ``objective`` is what the
#: schema asks for; the rest are the substitutions models actually make. Kept
#: in the same spirit as ``_MODULE_NAME_KEYS`` — read the meaning, not the key.
_MODULE_OBJECTIVE_KEYS = ("objective", "goal", "purpose", "summary", "description")
#: One sentence, matching ``topic_generation._MAX_MODULE_OBJECTIVE``.
_MAX_MODULE_OBJECTIVE = 300


def _humanized(value: str) -> str:
    """Turn an identifier-shaped name into a readable one.

    Models that answer with ``{"id": "concept_framework"}`` mean the words,
    not the key. Only reshape when the value really looks like an ASCII
    identifier — CJK names carry no separators and must survive untouched.
    """
    if " " in value or not value.isascii():
        return value
    if "_" not in value and "-" not in value:
        return value
    return re.sub(r"[_-]+", " ", value).strip().title()


def _display_name(raw: Any, keys: tuple[str, ...]) -> str:
    """First readable name *raw* offers under *keys*, or ``""``."""
    if isinstance(raw, str):
        return _humanized(raw.strip())[:200]
    if not isinstance(raw, dict):
        return ""
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _humanized(value.strip())[:200]
    return ""


def _module_objective(raw: Any) -> str:
    """The module's stated purpose, or ``""`` when it declared none.

    Optional by design: an outline built before objectives existed, or by a
    model that ignored the field, must still produce a usable module.
    """
    if not isinstance(raw, dict):
        return ""
    for key in _MODULE_OBJECTIVE_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_MODULE_OBJECTIVE]
    return ""


def _raw_knowledge_points(raw: dict[str, Any]) -> list[Any] | None:
    """The knowledge-point list *raw* declares, or ``None`` if it declares none."""
    for key in _KP_LIST_KEYS:
        value = raw.get(key)
        if isinstance(value, list):
            return value
    return None


def _normalized_module_tree(
    raw_modules: Any, fallback_module_name: str
) -> list[tuple[str, str, list[Any]]]:
    """Reduce whatever the model emitted to ``[(name, objective, knowledge points)]``.

    The tool schema asks for ``[{name, knowledge_points: [{name, type}]}]``, but
    DeepTutor runs on whatever model the learner brings, and smaller ones
    routinely answer with ``objectives`` instead of ``modules``, ``title``
    instead of ``name``, bare strings instead of knowledge-point objects, or a
    flat objective list with no module layer at all (#1019). Every one of those
    used to be dropped silently, leaving an empty path and no error the learner
    could see. Read the meaning instead of rejecting the shape.
    """
    if isinstance(raw_modules, dict):
        for key in ("modules", *_KP_LIST_KEYS):
            value = raw_modules.get(key)
            if isinstance(value, list):
                raw_modules = value
                break
    if not isinstance(raw_modules, list):
        return []

    entries: list[tuple[str, str, list[Any]]] = []
    flat: list[Any] = []
    for raw in raw_modules:
        nested = _raw_knowledge_points(raw) if isinstance(raw, dict) else None
        if nested:
            entries.append((_display_name(raw, _MODULE_NAME_KEYS), _module_objective(raw), nested))
        elif nested is None:
            # No knowledge-point list at all: the model flattened the tree and
            # this entry is itself an objective.
            flat.append(raw)
    if flat:
        # A flattened tree states no module purpose — there was no module layer
        # to state it on.
        entries.append((fallback_module_name, "", flat))
    return entries


#: Waypoints one module may hold, matching
#: ``topic_generation._MAX_OBJECTIVES_PER_MODULE``. A module the tutor keeps
#: adding to stops being a module.
_MAX_POINTS_PER_MODULE = 7


def _revised_point_id(module_id: str, taken: set[str]) -> str:
    """A knowledge point id not already used anywhere on this path.

    Rewrites and additions both need one. Ids are never reused: a retired id's
    attempts, errors and repetition state are dropped by the engine, and
    handing that id to a *different* objective would resurrect them as
    evidence for something the learner never answered.
    """
    index = 0
    while True:
        candidate = f"{module_id}_kp{index}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        index += 1


def _plan_module_revision(
    progress: LearningProgress,
    specs: dict[str, dict[str, Any]],
    *,
    module_order: list[str] | None = None,
):
    """Shared planner for direct and reviewed revisions; never mutates stored state."""
    known_modules = {m.id: m for m in progress.modules}
    targets: list[LearningModule] = []
    for module_id in specs:
        target = known_modules.get(module_id)
        if target is None:
            known = ", ".join(f"{m.id!r} ({m.name})" for m in progress.modules)
            raise ValueError(
                f"No module {module_id!r} in this mastery goal. Revise one of: {known}."
            )
        targets.append(target)

    removals = {
        str(raw or "").strip() for spec in specs.values() for raw in (spec.get("remove") or [])
    }
    blocked_by = [
        f"{point.name!r} ({point.id})"
        for module in progress.modules
        for point in module.knowledge_points
        if point.id not in removals and any(ref in removals for ref in point.prerequisite_ids)
    ]
    if blocked_by:
        raise ValueError(
            "Those knowledge points are still required by: "
            + ", ".join(blocked_by)
            + ". Remove or change those prerequisites first."
        )

    taken = {kp.id for m in progress.modules for kp in m.knowledge_points}
    revised_by_module: dict[str, list[KnowledgePoint]] = {}
    resets_by_module: dict[str, list[str]] = {}
    rewrite_ids: dict[str, str] = {}
    for target in targets:
        revised, error, resets, rewrites = _revise_points(
            progress, target, specs[target.id], taken=taken
        )
        if error:
            # First rejection refuses the whole request: a coordinated
            # edit must not half-apply because its third module was bad.
            raise ValueError(error)
        revised_by_module[target.id] = revised
        resets_by_module[target.id] = resets
        rewrite_ids.update(rewrites)

    applied = [
        module.model_copy(deep=True, update={"knowledge_points": revised_by_module[module.id]})
        if module.id in revised_by_module
        else module.model_copy(deep=True)
        for module in sorted(progress.modules, key=lambda m: m.order)
    ]
    for module in applied:
        for point in module.knowledge_points:
            point.prerequisite_ids = [rewrite_ids.get(ref, ref) for ref in point.prerequisite_ids]
    if module_order is not None:
        from deeptutor.learning.outline_revision import reorder_modules

        applied = reorder_modules(applied, module_order)
    return applied, targets, revised_by_module, resets_by_module


def _revise_specs(kwargs: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Read one revise request into ``{module_id: spec}``, or say why not.

    Two doors into the same contract: the single-module form (``module_id``
    with ``rewrite`` / ``add`` / ``remove`` beside it) and the coordinated
    form (``modules`` holding those per module). Keeping them one shape here
    is what lets one execution path validate and apply both identically —
    and refuses mixing the two, because a half-half request has no single
    meaning to report back.
    """
    batch = kwargs.get("modules")
    single_id = str(kwargs.get("module_id") or "").strip()
    if batch is not None and not isinstance(batch, list):
        return {}, "'modules' must be a list of {module_id, rewrite, add, remove} objects."
    if batch:
        if single_id:
            return {}, (
                "Pass either module_id (one module) or modules (several), not both — "
                "put every coordinated change in its modules entry instead."
            )
        specs: dict[str, dict[str, Any]] = {}
        for raw in batch:
            if not isinstance(raw, dict):
                return {}, "Each modules entry must be an object with a module_id."
            module_id = str(raw.get("module_id") or "").strip()
            if not module_id:
                return {}, "Each modules entry needs the module_id it revises."
            if module_id in specs:
                return {}, (
                    f"Module {module_id!r} appears twice in modules. Merge its "
                    "rewrite / add / remove changes into one entry."
                )
            spec = {key: raw.get(key) for key in ("rewrite", "add", "remove")}
            if not any(spec.get(key) for key in ("rewrite", "add", "remove")):
                return {}, (
                    f"The modules entry for {module_id!r} needs at least one of "
                    "rewrite, add or remove."
                )
            specs[module_id] = spec
        return specs, None
    if not single_id:
        return {}, (
            "mastery_revise needs a module_id (one module) or a modules list "
            "(several) saying what to revise."
        )
    has_changes = any(kwargs.get(key) for key in ("rewrite", "add", "remove"))
    if not has_changes:
        return {}, "mastery_revise needs at least one of rewrite, add or remove."
    return {single_id: {key: kwargs.get(key) for key in ("rewrite", "add", "remove")}}, None


def _revise_points(
    progress: LearningProgress,
    module: LearningModule,
    spec: dict[str, Any],
    taken: set[str] | None = None,
) -> tuple[list[KnowledgePoint], str | None, list[str], dict[str, str]]:
    """Apply one module's rewrite / add / remove instructions.

    Returns ``(points, error, reset_names, rewrite_ids)``. ``error`` is a sentence for the
    model — every rejection says what was wrong *and* what to do instead,
    because a tool that only says "no" is one the model retries verbatim.
    ``reset_names`` are the knowledge points whose progress this revision
    clears, so the tutor can tell the learner before they notice it themselves.
    ``taken`` is the id space new points are minted into; a coordinated
    multi-module revision passes one shared set so fresh ids stay unique
    across the whole batch.
    """
    rewrites: dict[str, dict[str, Any]] = {}
    for raw in spec.get("rewrite") or []:
        if not isinstance(raw, dict):
            continue
        kp_id = str(raw.get("knowledge_point_id") or "").strip()
        if kp_id:
            rewrites[kp_id] = raw
    removals = {str(raw).strip() for raw in (spec.get("remove") or []) if str(raw or "").strip()}
    additions = [raw for raw in (spec.get("add") or []) if isinstance(raw, (dict, str))]
    if not rewrites and not removals and not additions:
        return (
            [],
            "mastery_revise needs at least one of rewrite, add or remove.",
            [],
            {},
        )

    known = {kp.id for kp in module.knowledge_points}
    unknown = sorted((set(rewrites) | removals) - known)
    if unknown:
        listed = ", ".join(f"{kp.id!r} ({kp.name})" for kp in module.knowledge_points)
        return (
            [],
            f"Module {module.id!r} has no knowledge point {unknown[0]!r}. Its "
            f"knowledge points are: {listed}.",
            [],
            {},
        )

    protected = sorted(
        kp.name
        for kp in module.knowledge_points
        if kp.id in (set(rewrites) | removals) and is_mastered(progress, kp)
    )
    if protected:
        return (
            [],
            f"{protected[0]!r} is already mastered, so it cannot be rewritten or "
            "removed — that would erase proof the learner has earned. Leave it "
            "in place and add a new knowledge point if they want to go further.",
            [],
            {},
        )

    if taken is None:
        taken = {kp.id for m in progress.modules for kp in m.knowledge_points}
    points: list[KnowledgePoint] = []
    reset_names: list[str] = []
    rewrite_ids: dict[str, str] = {}

    def relation_values(raw: dict[str, Any], key: str, current: list[str]) -> list[str]:
        if key not in raw or raw[key] is None:
            return list(current)
        return normalize_refs(raw[key], label=key)

    for kp in module.knowledge_points:
        if kp.id in removals:
            continue
        raw = rewrites.get(kp.id)
        if raw is None:
            points.append(kp)
            continue
        name = _display_name(raw, _KP_NAME_KEYS)
        if len(name) < 2:
            return (
                [],
                f"The rewrite for {kp.name!r} needs a 'name' of at least two characters.",
                [],
                {},
            )
        # An unrecognised type keeps the current one: a targeted edit that
        # silently retyped a waypoint would change which gate it has to clear.
        kp_type = str(raw.get("type") or "").strip().lower()
        resolved = KnowledgeType(kp_type) if kp_type in _ALLOWED_KP_TYPES else kp.type
        points.append(
            KnowledgePoint(
                id=_revised_point_id(module.id, taken),
                name=name,
                type=resolved,
                module_id=module.id,
                prerequisite_ids=relation_values(raw, "prerequisite_ids", kp.prerequisite_ids),
                topic_source_ids=relation_values(raw, "topic_source_ids", kp.topic_source_ids),
                required_visual_tasks=raw.get("required_visual_tasks", kp.required_visual_tasks),
            )
        )
        rewrite_ids[kp.id] = points[-1].id
        reset_names.append(kp.name)

    for raw in additions:
        name = _display_name(raw, _KP_NAME_KEYS)
        if len(name) < 2:
            continue
        kp_type = "concept"
        if isinstance(raw, dict):
            kp_type = str(raw.get("type") or "concept").strip().lower()
            if kp_type not in _ALLOWED_KP_TYPES:
                kp_type = "concept"
        points.append(
            KnowledgePoint(
                id=_revised_point_id(module.id, taken),
                name=name,
                type=KnowledgeType(kp_type),
                module_id=module.id,
                prerequisite_ids=(
                    normalize_refs(raw.get("prerequisite_ids"), label="prerequisite")
                    if isinstance(raw, dict)
                    else []
                ),
                topic_source_ids=(
                    normalize_refs(raw.get("topic_source_ids"), label="topic source")
                    if isinstance(raw, dict)
                    else []
                ),
                required_visual_tasks=(raw.get("required_visual_tasks") or [])
                if isinstance(raw, dict)
                else [],
            )
        )

    if not points:
        return (
            [],
            f"That would leave module {module.name!r} with no knowledge points. A "
            "module needs at least one; remove the module with mastery_build if "
            "the learner wants it gone entirely.",
            [],
            {},
        )
    if len(points) > _MAX_POINTS_PER_MODULE:
        return (
            [],
            f"A module may hold at most {_MAX_POINTS_PER_MODULE} knowledge points; "
            f"this revision would give {module.name!r} {len(points)}. Drop some, or "
            "split the material across modules with mastery_build.",
            [],
            {},
        )
    return points, None, reset_names, rewrite_ids


def _parse_modules_with_refs(
    raw_modules: Any, path_id: str, offset: int, fallback_module_name: str = ""
) -> tuple[list[LearningModule], dict[str, RelationRefs], str | None]:
    """Validate the model-designed module tree into engine models.

    Ids are generated server-side (``<path>_m<i>_kp<j>``) so the model never
    controls storage keys; unknown knowledge types fall back to 'concept'.
    """
    entries = _normalized_module_tree(raw_modules, fallback_module_name or "Objectives")
    if not entries:
        return [], {}, _BUILD_SHAPE_ERROR
    modules: list[LearningModule] = []
    relation_refs: dict[str, RelationRefs] = {}
    for i, (raw_name, raw_objective, raw_kps) in enumerate(entries):
        index = offset + len(modules)
        module_id = f"{path_id}_m{index}"
        name = raw_name or fallback_module_name or f"Module {index + 1}"
        kps: list[KnowledgePoint] = []
        for raw_kp in raw_kps:
            kp_name = _display_name(raw_kp, _KP_NAME_KEYS)
            if len(kp_name) < 2:
                continue
            kp_type = "concept"
            prerequisite_refs: list[str] = []
            topic_source_refs: list[str] = []
            client_ref = ""
            if isinstance(raw_kp, dict):
                kp_type = str(raw_kp.get("type") or "concept").strip().lower()
                if kp_type not in _ALLOWED_KP_TYPES:
                    kp_type = "concept"
                prerequisite_refs = normalize_refs(
                    raw_kp.get("prerequisite_refs"), label="prerequisite"
                )
                topic_source_refs = normalize_refs(
                    raw_kp.get("topic_source_refs"), label="topic source"
                )
                client_ref = str(raw_kp.get("client_ref") or "").strip()
            kps.append(
                KnowledgePoint(
                    id=f"{module_id}_kp{len(kps)}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=module_id,
                    required_visual_tasks=(raw_kp.get("required_visual_tasks") or [])
                    if isinstance(raw_kp, dict)
                    else [],
                )
            )
            relation_refs[kps[-1].id] = RelationRefs(
                client_ref=client_ref,
                prerequisite_refs=prerequisite_refs,
                topic_source_refs=topic_source_refs,
            )
        if not kps:
            continue
        modules.append(
            LearningModule(
                id=module_id,
                name=name,
                order=index,
                objective=raw_objective,
                knowledge_points=kps,
            )
        )
    if not modules:
        return [], {}, _BUILD_SHAPE_ERROR
    return modules, relation_refs, None


def _parse_modules(
    raw_modules: Any, path_id: str, offset: int, fallback_module_name: str = ""
) -> tuple[list[LearningModule], str | None]:
    modules, _relation_refs, error = _parse_modules_with_refs(
        raw_modules, path_id, offset, fallback_module_name
    )
    return modules, error


MASTERY_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MasteryStatusTool,
    MasteryNoteExplainedTool,
    MasteryQuizTool,
    MasteryGradeTool,
    MasterySkipQuestionTool,
    MasteryRepairQuestionTool,
    MasteryDeferObjectiveTool,
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryModeTool,
    MasteryProfileTool,
    MasteryReviseTool,
    MasteryPathsTool,
    MasterySwitchTool,
    MasteryLeaveTool,
)


__all__ = [
    "MASTERY_TOOL_NAMES",
    "MASTERY_TOOL_TYPES",
    "MasteryAssessTool",
    "MasteryBuildTool",
    "MasteryDeferObjectiveTool",
    "MasteryGradeTool",
    "MasteryLeaveTool",
    "MasteryPathsTool",
    "MasteryModeTool",
    "MasteryNoteExplainedTool",
    "MasteryProfileTool",
    "MasteryQuizTool",
    "MasteryRepairQuestionTool",
    "MasteryReviseTool",
    "MasterySkipQuestionTool",
    "MasteryStatusTool",
    "MasterySwitchTool",
]


class MasteryPrepareLessonTool(BaseTool):
    """Demand-driven preparation; the loop only delivers validated cached pages."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_prepare_lesson",
            description="Privately prepare source evidence for the next teaching or practice step within an objective; this does not display source pages to the learner. To intentionally show a teaching image, use rag with an exact source view and presentation=teaching; use presentation=reveal after an answer. Reuses validated evidence. A partial packet supports teaching only its covered material; use a specific focus to resolve the evidence needed for a question and its key. For requested exam questions, focus on actual questions and solutions in the selected question bank, not merely topic summaries. Administrative discussion does not require preparation. Uses only the path's selected materials.",
            parameters=[
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Stable objective ID from mastery_status.",
                ),
                ToolParameter(
                    name="focus",
                    type="string",
                    required=False,
                    sensitive=True,
                    description="Optional next teaching step or assessment task within this objective, at most 600 characters. Include the requested source/task when relevant. Do not widen the objective or invent examination requirements.",
                ),
                ToolParameter(
                    name="refresh",
                    type="boolean",
                    required=False,
                    description="Explicit targeted retry of this focus after new retrieval information or a learner request to retry. Do not repeat unchanged preparation on every model round.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.learning.lesson_evidence import (
            LessonUnavailable,
            lesson_context,
            prepare_lesson,
        )
        from deeptutor.services.llm.config import get_llm_config

        service = _new_service()
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()
        try:
            from deeptutor.runtime.stream_bus import get_bus

            evidence = await prepare_lesson(
                service.store,
                path_id,
                str(kwargs.get("knowledge_point_id") or ""),
                get_llm_config(),
                stream=get_bus(_resolve_turn_id(kwargs)),
                language=kwargs.get("_language") or "en",
                focus=kwargs.get("focus") or "",
                learner_request=str(kwargs.get("_learner_message") or "")[:1500],
                refresh=kwargs.get("refresh", False),
            )
        except LessonUnavailable as exc:
            return ToolResult(content=str(exc), success=False)
        bind = kwargs.get("_bind_lesson_objective")
        if callable(bind):
            bind(str(kwargs.get("knowledge_point_id") or ""))
        return ToolResult(
            content=lesson_context(evidence)
            if evidence
            else "This objective has no selected PDF materials.",
            public_result={"content": "Lesson source evidence prepared privately."},
        )
