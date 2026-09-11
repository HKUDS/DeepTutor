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
    path_display_name,
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
    "mastery_status",
    "mastery_quiz",
    "mastery_grade",
    "mastery_skip_question",
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
) -> None:
    if not session_id:
        return
    item = {
        "turn_id": turn_id,
        "question_id": pending.question_id,
        "question": pending.prompt,
        "question_type": _question_bank_type(pending.question_type),
        "options": choice_options or pending.choice_map,
        "correct_answer": correct_answer or pending.expected_answer,
        # Carried from mastery_quiz. Without these the bank held a bare
        # right/wrong for every mastery attempt — reviewable only as a score.
        "explanation": pending.explanation,
        "difficulty": pending.difficulty,
        "user_answer": user_answer,
        "is_correct": is_correct,
        "source": "mastery_path",
        "material_id": path_id,
        "material_title": material_title,
        "section_id": pending.knowledge_point_id,
        "section_title": section_title,
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


def _profile_status(progress: LearningProgress | None) -> dict[str, Any]:
    """The learner profile, and whether intake still has to happen.

    Returned by ``mastery_status`` on every round rather than injected once at
    build time. A profile that only reached the outline generator would be
    forgotten by the thirtieth knowledge point — which is exactly the failure
    intake exists to prevent.
    """
    profile = getattr(progress, "learner_profile", None) if progress is not None else None
    if profile is None or profile.is_empty():
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
    return {
        "learner_profile": {
            "prior_knowledge": profile.prior_knowledge,
            "target_level": profile.target_level,
            "time_budget": profile.time_budget,
            "preferences": profile.preferences,
            "notes": profile.notes,
        },
        "intake_needed": False,
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
        }
        if progress is None or not any(module.knowledge_points for module in progress.modules):
            return _json_result(
                {
                    "status": "empty",
                    "path_revision": progress.version if progress is not None else 0,
                    **identity,
                    "message": await _unbuilt_status_message(service, path_id, topic),
                    **_profile_status(progress),
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
            **_profile_status(progress),
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
        return _json_result(payload, meta_key="mastery_status")


class MasteryQuizTool(BaseTool):
    """Register an objective-type question; the engine holds the answer."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_quiz",
            description=(
                "Pose a question for a MEMORY or PROCEDURE objective. This one "
                "call registers the expected answer with the engine (so grading "
                "is deterministic and you never re-state the answer later) AND "
                "puts the question in front of the learner on its own answer "
                "card — do not call ask_user for it. THE TURN ENDS HERE: unlike "
                "ask_user, this does not wait for a reply inside your turn, so "
                "call it last and plan nothing after it. Their answer arrives as "
                "the next message and you grade it on the next turn with "
                "mastery_grade. For CONCEPT / DESIGN objectives use "
                "mastery_assess instead."
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
                    description=(
                        "The question stem shown to the learner — the ask only. "
                        "For a choice question do NOT list the options here: the "
                        "card renders 'options' as its own labelled, clickable "
                        "list, so a stem that repeats them shows every choice "
                        "twice. Naming one option to ask about it is fine."
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

    async def execute(self, **kwargs: Any) -> ToolResult:
        refusal = _wrong_mode_result("mastery_quiz", kwargs)
        if refusal is not None:
            return refusal
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

        question, echoed_options = strip_echoed_options(
            question, {option["label"]: option["body"] for option in options}
        )

        service = _new_service()
        progress = _load_path(service, path_id)
        if progress is None:
            return _no_built_path_result("mastery_quiz")
        scope = _review_scope_refusal(kwargs, progress, kp_id)
        if scope is not None:
            return scope
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
            explanation=str(kwargs.get("explanation") or "").strip()[:2000],
            difficulty=_normalize_difficulty(kwargs.get("difficulty")),
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
        card = build_question_card(
            pending,
            objective_name=kp.name,
            attempt=attempt_number(progress, pending.knowledge_point_id),
        )
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

        return ToolResult(
            content=notice,
            metadata={"mastery_quiz": payload, QUESTION_CARD_KEY: card},
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
        is_correct = bool(interaction.result.get("is_correct"))
        # Upsert on every call, including an idempotent replay: if the first
        # best-effort sync timed out, a safe retry repairs the auxiliary
        # question bank without duplicating the mastery attempt.
        kp, _, _ = find_knowledge_point(progress, pending.knowledge_point_id)
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
        )
        mastered = bool(kp and is_mastered(progress, kp))
        payload = {
            "is_correct": is_correct,
            "replayed": replayed,
            "path_revision": progress.version,
            "knowledge_point_id": pending.knowledge_point_id,
            "question_id": pending.question_id,
            "mastery": round(display_mastery(progress, kp), 3) if kp else 0.0,
            "threshold": round(gate_threshold(kp.type), 3) if kp else 0.0,
            "mastered": mastered,
            "next": next_objective(progress).to_dict(),
            # The answer key, released to the learner's card now that the gate
            # has ruled — see ``build_grade_result``.
            "result": build_grade_result(
                question_id=pending.question_id,
                is_correct=is_correct,
                learner_answer=interaction.user_answer or answer,
                correct_label=expected_answer,
                choice_options=choice_options,
                explanation=pending.explanation,
            ),
            # A graded card is not an answer to the learner. The verdict and
            # the explanation are now on it, so the model that stops here
            # leaves the turn silent behind a card that only says "correct" —
            # exactly the dead end this instruction exists to prevent.
            "instruction": (
                "The card now shows the verdict, the correct option and your "
                "explanation, so do not restate the answer key. Say what this "
                "attempt tells you about their grasp of the objective, then keep "
                + (
                    "going: this objective is mastered, so continue with mastery_status.next."
                    if mastered
                    else "going on the same objective — teach the gap this "
                    "attempt exposed, and when you pose the next question with "
                    "mastery_quiz put that call last, since it ends the turn."
                )
                + " Never end the turn without saying anything."
            ),
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
        passed = bool(kwargs.get("passed"))
        feedback = str(kwargs.get("feedback") or "").strip()

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
                "mode='replace' to start fresh or 'append' to add to an "
                "existing path."
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
                    description="'replace' (default) starts fresh; 'append' adds modules.",
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
        new_modules, error = _parse_modules(
            kwargs.get("modules"),
            path_id,
            0,
            fallback_module_name=str(kwargs.get("path_name") or "").strip()[:200],
        )
        if error:
            return ToolResult(content=error, success=False)

        progress = service.replace_modules_for_path(
            path_id,
            new_modules,
            append=mode == "append",
            name=str(kwargs.get("path_name") or ""),
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
        return ToolDefinition(
            name="mastery_profile",
            description=(
                "Record what the learner told you about themselves for this "
                "mastery goal: what they can already do, what finishing means "
                "to them, how much time they have, and how they want it "
                "taught. Call it during intake — before designing the outline "
                "— and again whenever they correct one of these. Pass only the "
                "fields they actually spoke to; omitted fields keep what they "
                "said before. Never invent an answer they did not give."
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
                    name="notes",
                    type="string",
                    description=("Anything else worth carrying that the fields above do not hold."),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_id = _resolve_path_id(kwargs)
        if not path_id:
            return _no_path_result()

        fields = {
            key: kwargs[key]
            for key in ("prior_knowledge", "target_level", "time_budget", "preferences", "notes")
            if key in kwargs and kwargs[key] is not None
        }
        if not fields:
            return ToolResult(
                content=(
                    "mastery_profile needs at least one of prior_knowledge, "
                    "target_level, time_budget, preferences or notes — pass what "
                    "the learner actually told you."
                ),
                success=False,
            )

        service = _new_service()
        progress, changed = service.record_learner_profile(
            path_id,
            fields=fields,
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
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
                "rewritten or removed."
            ),
            parameters=[
                ToolParameter(
                    name="module_id",
                    type="string",
                    description=(
                        "Which module to revise. Copy it verbatim from mastery_status's map."
                    ),
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
                    items={
                        "type": "object",
                        "properties": {
                            "knowledge_point_id": {"type": "string"},
                            "name": {"type": "string"},
                            "type": {"type": "string", "enum": sorted(_ALLOWED_KP_TYPES)},
                        },
                        "required": ["knowledge_point_id", "name"],
                    },
                ),
                ToolParameter(
                    name="add",
                    type="array",
                    description=("Knowledge points to append to this module: each {name, type}."),
                    required=False,
                    items={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "enum": sorted(_ALLOWED_KP_TYPES)},
                        },
                        "required": ["name"],
                    },
                ),
                ToolParameter(
                    name="remove",
                    type="array",
                    description="Knowledge point ids to drop from this module.",
                    required=False,
                    items={"type": "string"},
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

        service = _new_service()
        progress = _load_path(service, path_id)
        if progress is None or not progress.modules:
            return _no_built_path_result("mastery_revise")

        module_id = str(kwargs.get("module_id") or "").strip()
        target = next((m for m in progress.modules if m.id == module_id), None)
        if target is None:
            known = ", ".join(f"{m.id!r} ({m.name})" for m in progress.modules)
            return ToolResult(
                content=(f"No module {module_id!r} in this mastery goal. Revise one of: {known}."),
                success=False,
            )

        revised, error, reset_names = _revise_points(progress, target, kwargs)
        if error:
            return ToolResult(content=error, success=False)

        applied = [
            module.model_copy(deep=True, update={"knowledge_points": revised})
            if module.id == target.id
            else module.model_copy(deep=True)
            for module in sorted(progress.modules, key=lambda m: m.order)
        ]
        progress = service.replace_modules_for_path(
            path_id,
            applied,
            event_type="path.module_revised",
            session_id=_resolve_session_id(kwargs),
            turn_id=_resolve_turn_id(kwargs),
        )
        return _json_result(
            {
                "status": "revised",
                "path_revision": progress.version,
                "module_id": target.id,
                "module_name": target.name,
                # Echoed so the tutor reports the revision against the promise
                # it was allowed to keep, not against its own recollection.
                "module_objective": target.objective,
                "knowledge_points": [
                    {"id": kp.id, "name": kp.name, "type": kp.type.value} for kp in revised
                ],
                "progress_reset": reset_names,
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


def _revise_points(
    progress: LearningProgress,
    module: LearningModule,
    kwargs: dict[str, Any],
) -> tuple[list[KnowledgePoint], str | None, list[str]]:
    """Apply one module's rewrite / add / remove instructions.

    Returns ``(points, error, reset_names)``. ``error`` is a sentence for the
    model — every rejection says what was wrong *and* what to do instead,
    because a tool that only says "no" is one the model retries verbatim.
    ``reset_names`` are the knowledge points whose progress this revision
    clears, so the tutor can tell the learner before they notice it themselves.
    """
    rewrites: dict[str, dict[str, Any]] = {}
    for raw in kwargs.get("rewrite") or []:
        if not isinstance(raw, dict):
            continue
        kp_id = str(raw.get("knowledge_point_id") or "").strip()
        if kp_id:
            rewrites[kp_id] = raw
    removals = {str(raw).strip() for raw in (kwargs.get("remove") or []) if str(raw or "").strip()}
    additions = [raw for raw in (kwargs.get("add") or []) if isinstance(raw, (dict, str))]
    if not rewrites and not removals and not additions:
        return (
            [],
            "mastery_revise needs at least one of rewrite, add or remove.",
            [],
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
        )

    taken = {kp.id for m in progress.modules for kp in m.knowledge_points}
    points: list[KnowledgePoint] = []
    reset_names: list[str] = []
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
            )
        )
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
            )
        )

    if not points:
        return (
            [],
            f"That would leave module {module.name!r} with no knowledge points. A "
            "module needs at least one; remove the module with mastery_build if "
            "the learner wants it gone entirely.",
            [],
        )
    if len(points) > _MAX_POINTS_PER_MODULE:
        return (
            [],
            f"A module may hold at most {_MAX_POINTS_PER_MODULE} knowledge points; "
            f"this revision would give {module.name!r} {len(points)}. Drop some, or "
            "split the material across modules with mastery_build.",
            [],
        )
    return points, None, reset_names


def _parse_modules(
    raw_modules: Any, path_id: str, offset: int, fallback_module_name: str = ""
) -> tuple[list[LearningModule], str | None]:
    """Validate the model-designed module tree into engine models.

    Ids are generated server-side (``<path>_m<i>_kp<j>``) so the model never
    controls storage keys; unknown knowledge types fall back to 'concept'.
    """
    entries = _normalized_module_tree(raw_modules, fallback_module_name or "Objectives")
    if not entries:
        return [], _BUILD_SHAPE_ERROR
    modules: list[LearningModule] = []
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
            if isinstance(raw_kp, dict):
                kp_type = str(raw_kp.get("type") or "concept").strip().lower()
                if kp_type not in _ALLOWED_KP_TYPES:
                    kp_type = "concept"
            kps.append(
                KnowledgePoint(
                    id=f"{module_id}_kp{len(kps)}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=module_id,
                )
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
        return [], _BUILD_SHAPE_ERROR
    return modules, None


MASTERY_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MasteryStatusTool,
    MasteryQuizTool,
    MasteryGradeTool,
    MasterySkipQuestionTool,
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
    "MasteryGradeTool",
    "MasteryLeaveTool",
    "MasteryPathsTool",
    "MasteryModeTool",
    "MasteryProfileTool",
    "MasteryQuizTool",
    "MasteryReviseTool",
    "MasterySkipQuestionTool",
    "MasteryStatusTool",
    "MasterySwitchTool",
]
