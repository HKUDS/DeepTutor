"""QuestionPipeline — agentic-engine-based replacement for ``AgentCoordinator``.

Phase shape:

* **Phase 1 (Explore)** — one agentic loop over ``THINK`` / ``TOOL`` /
  ``FINISH``, using the same tool composition as chat. The ``FINISH``
  text streams live into the chat bubble as a brief, user-facing preface
  (e.g., "I researched X; now let me generate N questions"). Prior quiz
  history (if any) is fed in so the model articulates avoidance and
  weak-spot coverage.
* **Phase 2 (Plan)** — one ``PLAN`` labeled step emits a JSON plan with
  per-question templates ``[{question_id, topic, question_type,
  difficulty}, ...]``. No tools, no loop. Streams into the trace panel.
* **Phase 3 (Quiz)** — for each template, one agentic loop over the
  three ``THINK`` / ``TOOL`` / ``FINISH`` labels. ``FINISH`` is a strict
  JSON payload describing one question; the pipeline parses it (with
  one-shot repair on schema violation) and emits a structured
  ``quiz_question_emitted`` event so the frontend can render the
  question card the moment it's ready.

The orchestrator owns control flow (per-question iteration, repair pass,
incremental emission) and prompt assembly; everything else is delegated
to :mod:`deeptutor.core.agentic` and the shared tool-composition policy.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import StrEnum
import json
import logging
import re
from typing import Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.agents._shared.tool_composition import (
    ToolMountFlags,
    compose_enabled_tools,
    default_optional_tools,
    user_has_memory,
    user_has_notebooks,
)
from deeptutor.core.agentic import (
    DispatchOutcome,
    LabeledStepResult,
    LabelProtocol,
    LLMClientConfig,
    UsageTracker,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    dispatch_tool_calls,
    run_agentic_loop,
    run_labeled_step,
)
from deeptutor.core.agentic.labels import find_inline_labels
from deeptutor.core.agentic.tool_dispatch import MAX_PARALLEL_TOOL_CALLS
from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.config import parse_language
from deeptutor.services.llm import get_llm_config, prepare_multimodal_messages
from deeptutor.services.path_service import get_path_service
from deeptutor.services.prompt import get_prompt_manager
from deeptutor.services.prompt.language import append_language_directive
from deeptutor.services.sandbox import exec_capability_available
from deeptutor.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)


SOURCE = "deep_question"
FEATURE = "deep_question"

STAGE_EXPLORING = "exploring"
STAGE_PLANNING = "planning"
STAGE_QUIZZING = "quizzing"

LABEL_THINK = "THINK"
LABEL_TOOL = "TOOL"
LABEL_FINISH = "FINISH"
LABEL_PLAN = "PLAN"

# Sub-trace metadata that the frontend renders as a "Question" card.
# Pairs with TracePanels.tsx's getTraceHeader extension (call_kind/role).
CALL_KIND_QUIZ_QUESTION = "quiz_question_emitted"
TRACE_ROLE_QUIZ_QUESTION = "quiz_question"
TRACE_GROUP_QUIZ = "quiz"

_PROTOCOL_EXPLORE = LabelProtocol(
    allowed=(LABEL_THINK, LABEL_TOOL, LABEL_FINISH),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset({LABEL_THINK}),
    final=frozenset({LABEL_FINISH}),
    tool_label=LABEL_TOOL,
)
_PROTOCOL_PLAN = LabelProtocol(
    allowed=(LABEL_PLAN,),
    terminal=frozenset({LABEL_PLAN}),
    intermediate=frozenset(),
    final=frozenset(),
    tool_label=None,
)
_PROTOCOL_QUIZ = LabelProtocol(
    allowed=(LABEL_THINK, LABEL_TOOL, LABEL_FINISH),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset({LABEL_THINK}),
    final=frozenset({LABEL_FINISH}),
    tool_label=LABEL_TOOL,
)
_PROTOCOL_REPAIR = LabelProtocol(
    allowed=(LABEL_FINISH,),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset(),
    final=frozenset({LABEL_FINISH}),
    tool_label=None,
)

DEFAULT_MAX_EXPLORE_ITERATIONS = 8
DEFAULT_MAX_QUIZ_ITERATIONS_PER_QUESTION = 5
DEFAULT_MAX_TOKENS = 4000
EXPLORE_FINISH_MAX_TOKENS = 3000
PLAN_MAX_TOKENS = 2000
QUIZ_FINISH_MAX_TOKENS = 3000
REPAIR_MAX_TOKENS = 2500
FINALIZATION_REPAIR_ATTEMPTS = 2
# Tool-result summarizer (Phase 1 reflection step). The summarizer runs
# after every tool_result returned during Explore; its compressed output
# replaces the raw tool message in the loop's buffer so subsequent
# iterations — and the exploration_trace passed downstream — see only the
# distilled version. Cost: one extra main-model LLM call per tool result.
DEFAULT_TOOL_SUMMARIZER_MAX_TOKENS = 800
TOOL_SUMMARIZER_TEMPERATURE = 0.2


class QuestionType(StrEnum):
    """Canonical question-type taxonomy. Source of truth for the planner,
    quiz-step prompt schema, and the normalizer / validator below."""

    CHOICE = "choice"
    CONCEPT = "concept"
    FILL_IN_BLANK = "fill_in_blank"
    SHORT_ANSWER = "short_answer"
    WRITTEN = "written"
    CODING = "coding"


_VALID_QUESTION_TYPES: frozenset[str] = frozenset(qt.value for qt in QuestionType)
_TYPES_WITH_OPTIONS: frozenset[str] = frozenset({QuestionType.CHOICE.value})
_VALID_DIFFICULTIES = ("easy", "medium", "hard")
_CHOICE_KEYS = ("A", "B", "C", "D")
_FILL_IN_BLANK_TOKEN = "____"
_CONCEPT_ANSWERS: frozenset[str] = frozenset({"true", "false"})


# ---------------------------------------------------------------------------
# Question-type whitelist helpers (used by ``run`` / ``_explore`` / ``_plan``).
#
# The pipeline accepts an optional ``question_types`` allow-list and an
# optional ``per_type_counts`` distribution so callers can constrain the
# planner to a subset of the canonical taxonomy (or fix the per-type
# breakdown). Both inputs are tolerant: anything outside the canonical set
# is silently dropped; non-positive counts are removed.
# ---------------------------------------------------------------------------


def _normalize_type_list(types: list[str] | None) -> list[str]:
    """Filter / dedup a caller-supplied ``question_types`` list.

    Returns an ordered list of canonical type names. Unknown entries are
    dropped silently; ``None`` and ``[]`` both yield ``[]`` which downstream
    treats as "any canonical type is fair game".
    """
    if not types:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in types:
        if not isinstance(raw, str):
            continue
        normalized = raw.strip().lower()
        if normalized in _VALID_QUESTION_TYPES and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _normalize_per_type_counts(counts: dict[str, int] | None, allowed: list[str]) -> dict[str, int]:
    """Validate and clamp a per-type count map.

    Keys outside the canonical taxonomy — or outside ``allowed`` when
    non-empty — are dropped. Non-positive values are dropped. Returns an
    empty dict when there's nothing usable, in which case the planner is
    free to distribute the requested total however it sees fit.
    """
    if not counts:
        return {}
    allowed_set = frozenset(allowed) if allowed else _VALID_QUESTION_TYPES
    cleaned: dict[str, int] = {}
    for key, value in counts.items():
        if not isinstance(key, str):
            continue
        normalized = key.strip().lower()
        if normalized not in allowed_set:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            cleaned[normalized] = count
    return cleaned


def _format_allowed_types(types: list[str]) -> str:
    """Render ``allowed_types`` for prompt injection. ``[]`` collapses to
    ``"auto"`` so the model knows it can pick freely."""
    return ", ".join(types) if types else "auto"


def _format_per_type_counts(counts: dict[str, int]) -> str:
    """Render ``per_type_counts`` for prompt injection. ``{}`` collapses to
    ``"auto"`` so the model knows the breakdown is its call."""
    if not counts:
        return "auto"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _normalize_type_list(raw: list[str] | None) -> list[str]:
    """Coerce a user-supplied type list into the canonical taxonomy.

    Unknown values are dropped; duplicates collapse; order preserved
    relative to first appearance. Empty list means "any type".
    """
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip().lower()
        if value in _VALID_QUESTION_TYPES and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _normalize_per_type_counts(
    raw: dict[str, int] | None,
    allowed_types: list[str],
) -> dict[str, int]:
    """Coerce per-type quantity targets into the canonical taxonomy.

    Drops counts for types not in ``allowed_types`` (when non-empty) or
    not in the canonical taxonomy (when allowed_types is empty). Negative
    or non-integer values become 0. Empty dict means "let the planner
    distribute".
    """
    if not raw:
        return {}
    accepted: frozenset[str] = frozenset(allowed_types) if allowed_types else _VALID_QUESTION_TYPES
    out: dict[str, int] = {}
    for key, value in raw.items():
        canonical = str(key or "").strip().lower()
        if canonical not in accepted:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[canonical] = count
    return out


def _format_allowed_types(allowed_types: list[str]) -> str:
    """Prompt-side rendering of the allowed-types directive."""
    if not allowed_types:
        return "any (planner picks per question)"
    return ", ".join(f"``{t}``" for t in allowed_types)


def _format_per_type_counts(per_type_counts: dict[str, int]) -> str:
    """Prompt-side rendering of the per-type quantity directive."""
    if not per_type_counts:
        return "no per-type targets (planner distributes freely)"
    return ", ".join(f"{t}={n}" for t, n in per_type_counts.items())


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuizTemplate:
    question_id: str
    topic: str
    question_type: str
    difficulty: str
    # ``source`` distinguishes templates the planner invents from templates
    # lifted out of an exam paper. ``mimic`` templates carry the original
    # text so the quiz step can shadow / paraphrase rather than invent.
    source: str = "custom"
    reference_question: str | None = None
    reference_answer: str | None = None


@dataclass(frozen=True)
class QuizPlan:
    analysis: str
    templates: list[QuizTemplate] = field(default_factory=list)


@dataclass(frozen=True)
class QuizHistoryEntry:
    """One prior quiz item the learner attempted in this session."""

    question: str
    question_type: str
    correct_answer: str
    user_answer: str
    is_correct: bool | None
    turn_id: str = ""


@dataclass
class QuizPair:
    """Final shape one question takes when emitted to the frontend.

    Mirrors the legacy ``QAPair`` shape so ``QuizViewer`` keeps rendering.
    """

    question_id: str
    question: str
    question_type: str
    correct_answer: str
    explanation: str
    options: dict[str, str] | None = None
    topic: str = ""
    difficulty: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# QuestionPipeline
# ---------------------------------------------------------------------------


class QuestionPipeline:
    """One-shot orchestrator: instantiate per turn, call :meth:`run` once."""

    def __init__(
        self,
        *,
        language: str = "en",
        kb_name: str | None = None,
        enabled_tools: list[str] | None = None,
        max_explore_iterations: int = DEFAULT_MAX_EXPLORE_ITERATIONS,
        max_quiz_iterations_per_question: int = DEFAULT_MAX_QUIZ_ITERATIONS_PER_QUESTION,
        runtime_config: dict[str, Any] | None = None,
    ) -> None:
        self.language = parse_language(language)
        self.kb_name = (kb_name or "").strip() or None
        self.enabled_tools = list(enabled_tools or [])
        self.runtime_config: dict[str, Any] = dict(runtime_config or {})

        # Pull the exploring sub-config. Direct kwargs win for callers that
        # don't go through ``build_question_runtime_config``; runtime_config
        # is the path the capability wires up.
        exploring_cfg = (
            self.runtime_config.get("exploring")
            if isinstance(self.runtime_config.get("exploring"), dict)
            else {}
        )
        cfg_max_iter = exploring_cfg.get("max_iterations")
        if isinstance(cfg_max_iter, int) and cfg_max_iter > 0:
            self.max_explore_iterations = max(1, int(cfg_max_iter))
        else:
            self.max_explore_iterations = max(1, int(max_explore_iterations))

        summarizer_cfg = (
            exploring_cfg.get("tool_summarizer")
            if isinstance(exploring_cfg.get("tool_summarizer"), dict)
            else {}
        )
        summarizer_tokens = summarizer_cfg.get("max_tokens")
        if isinstance(summarizer_tokens, int) and summarizer_tokens > 0:
            self.tool_summarizer_max_tokens = int(summarizer_tokens)
        else:
            self.tool_summarizer_max_tokens = DEFAULT_TOOL_SUMMARIZER_MAX_TOKENS
        self.tool_summarizer_enabled = bool(summarizer_cfg.get("enabled", True))

        self.max_quiz_iterations_per_question = max(1, int(max_quiz_iterations_per_question))

        self.llm_config = get_llm_config()
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.model = getattr(self.llm_config, "model", None)
        self.reasoning_effort = getattr(self.llm_config, "reasoning_effort", None)
        self.client_config = LLMClientConfig(
            binding=self.binding,
            model=self.model,
            api_key=getattr(self.llm_config, "api_key", None),
            base_url=getattr(self.llm_config, "base_url", None),
            api_version=getattr(self.llm_config, "api_version", None),
            extra_headers=getattr(self.llm_config, "extra_headers", None) or None,
            reasoning_effort=self.reasoning_effort,
        )

        self.registry = get_tool_registry()
        self.usage = UsageTracker(model=self.model)
        self._optional_tools = default_optional_tools()
        self._temperature = 0.4

        try:
            self._prompts: dict[str, Any] = (
                get_prompt_manager().load_prompts(
                    module_name="question",
                    agent_name="pipeline",
                    language=self.language,
                )
                or {}
            )
        except Exception as exc:
            logger.warning("Failed to load question pipeline prompts: %s", exc)
            self._prompts = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(
        self,
        *,
        context: UnifiedContext,
        user_message: str,
        num_questions: int,
        difficulty: str = "",
        question_types: list[str] | None = None,
        per_type_counts: dict[str, int] | None = None,
        conversation_context: str = "",
        attachments: list[Attachment] | None = None,
        quiz_history: list[QuizHistoryEntry] | None = None,
        templates_override: list[QuizTemplate] | None = None,
        stream: StreamBus,
    ) -> dict[str, Any]:
        """Drive the pipeline. ``templates_override`` is the mimic-mode hook:
        when caller supplies pre-built templates (e.g., extracted from an
        uploaded exam paper), Phase 1 (Explore) and Phase 2 (Plan) are
        skipped — we jump straight to per-question quizzing with the
        provided templates.

        ``question_types`` is the allowed-types whitelist (empty = any
        type). ``per_type_counts`` optionally pins how many questions of
        each type to produce; when supplied, it must sum to
        ``num_questions`` (caller's responsibility).
        """
        attachments = list(attachments or [])
        image_attachments = [a for a in attachments if getattr(a, "type", "") == "image"]
        quiz_history = list(quiz_history or [])
        requested = max(1, int(num_questions or 1))

        allowed_types = _normalize_type_list(question_types)
        counts = _normalize_per_type_counts(per_type_counts, allowed_types)

        client = build_openai_client(self.client_config)

        try:
            return await self._run_inner(
                context=context,
                user_message=user_message,
                num_questions=requested,
                difficulty=str(difficulty or "").strip().lower(),
                allowed_types=allowed_types,
                per_type_counts=counts,
                conversation_context=conversation_context.strip(),
                attachments=attachments,
                image_attachments=image_attachments,
                quiz_history=quiz_history,
                templates_override=list(templates_override) if templates_override else None,
                stream=stream,
                client=client,
            )
        except Exception as exc:
            logger.exception("QuestionPipeline.run failed: %s", exc)
            await self._emit_visible_failure(stream, exc)
            raise

    async def _run_inner(
        self,
        *,
        context: UnifiedContext,
        user_message: str,
        num_questions: int,
        difficulty: str,
        allowed_types: list[str],
        per_type_counts: dict[str, int],
        conversation_context: str,
        attachments: list[Attachment],
        image_attachments: list[Attachment],
        quiz_history: list[QuizHistoryEntry],
        templates_override: list[QuizTemplate] | None,
        stream: StreamBus,
        client: Any,
    ) -> dict[str, Any]:
        is_mimic = templates_override is not None
        logger.info(
            "QuestionPipeline.run: lang=%s kb=%s tools=%s requested=%d "
            "explore_iter=%d quiz_iter/q=%d history=%d mode=%s",
            self.language,
            self.kb_name,
            self.enabled_tools,
            num_questions,
            self.max_explore_iterations,
            self.max_quiz_iterations_per_question,
            len(quiz_history),
            "mimic" if is_mimic else "custom",
        )

        finish_text = ""
        if is_mimic:
            # Mimic mode: templates come from an exam paper. We skip explore
            # + plan and synthesize a minimal Plan envelope so downstream
            # rendering / result code paths stay identical. ``exploration_trace``
            # is the empty marker so quiz prompts render a coherent section.
            exploration_trace = self._t("empty.no_exploration_trace")
            plan = QuizPlan(analysis="", templates=list(templates_override or []))
        else:
            # ----- Phase 1: Explore -----
            async with stream.stage(STAGE_EXPLORING, source=SOURCE):
                finish_text, exploration_trace = await self._explore(
                    context=context,
                    user_message=user_message,
                    num_questions=num_questions,
                    difficulty=difficulty,
                    allowed_types=allowed_types,
                    per_type_counts=per_type_counts,
                    conversation_context=conversation_context,
                    attachments=attachments,
                    image_attachments=image_attachments,
                    quiz_history=quiz_history,
                    stream=stream,
                    client=client,
                )

            # ----- Phase 2: Plan -----
            async with stream.stage(STAGE_PLANNING, source=SOURCE):
                plan = await self._plan(
                    user_message=user_message,
                    exploration_trace=exploration_trace,
                    num_questions=num_questions,
                    difficulty=difficulty,
                    allowed_types=allowed_types,
                    per_type_counts=per_type_counts,
                    stream=stream,
                    client=client,
                )

            if not plan.templates:
                await stream.progress(
                    self._t("notices.plan_count_mismatch", got=0, requested=num_questions),
                    source=SOURCE,
                    stage=STAGE_PLANNING,
                    metadata={"trace_kind": "warning"},
                )

        # ----- Phase 3: Quiz (per-question) -----
        qa_pairs: list[QuizPair] = []
        async with stream.stage(STAGE_QUIZZING, source=SOURCE):
            for index, template in enumerate(plan.templates):
                qa_pair = await self._quiz_one(
                    template=template,
                    question_number=index + 1,
                    total_questions=len(plan.templates),
                    exploration_trace=exploration_trace,
                    plan=plan,
                    previous_pairs=qa_pairs,
                    image_attachments=image_attachments,
                    context=context,
                    stream=stream,
                    client=client,
                )
                await self._emit_quiz_question(
                    stream=stream,
                    qa_pair=qa_pair,
                    index=index,
                    total=len(plan.templates),
                )
                qa_pairs.append(qa_pair)

        # ----- Result envelope -----
        result_payload = self._build_result_payload(
            plan, qa_pairs, is_mimic=is_mimic, finish_text=finish_text
        )
        await emit_capability_result(stream, result_payload, source=SOURCE, usage=self.usage)
        return result_payload

    # ------------------------------------------------------------------
    # Phase 1: Explore
    # ------------------------------------------------------------------
    async def _explore(
        self,
        *,
        context: UnifiedContext,
        user_message: str,
        num_questions: int,
        difficulty: str,
        allowed_types: list[str],
        per_type_counts: dict[str, int],
        conversation_context: str,
        attachments: list[Attachment],
        image_attachments: list[Attachment],
        quiz_history: list[QuizHistoryEntry],
        stream: StreamBus,
        client: Any,
    ) -> tuple[str, str]:
        """Drive Phase 1 and return a ``(finish_text, exploration_trace)`` pair.

        ``finish_text`` is the user-facing exploration preface (already
        streamed to ``stream.content`` during the loop via
        ``stream_body_live=True``). It is **not** consumed by downstream
        phases. ``exploration_trace`` is the full reasoning + tool-call
        history serialized for the plan / quiz prompts; tool results
        embedded in it have already been replaced by the Tool Summarizer
        step's compressed output.
        """
        system_prompt = self._t(
            "explore.system",
            kb_note=self._kb_system_note(),
            tool_list=self._tool_list_text(context),
            num_questions=num_questions,
        )
        system_prompt = append_language_directive(system_prompt, self.language)
        user_prompt = self._t(
            "explore.user_template",
            user_message=user_message,
            num_questions=num_questions,
            allowed_types=_format_allowed_types(allowed_types),
            per_type_counts=_format_per_type_counts(per_type_counts),
            difficulty=difficulty or "auto",
            attachments_summary=self._render_attachments_summary(attachments),
            conversation_context=conversation_context or self._t("empty.no_conversation"),
            quiz_history=self._render_quiz_history(quiz_history),
        )
        messages = self._build_system_user_messages(
            system_prompt, user_prompt, image_attachments=image_attachments
        )
        # Capture the initial-message count so the trace renderer can skip
        # them: only post-system+user iteration messages constitute the
        # exploration trace passed downstream.
        initial_message_count = len(messages)

        tool_schemas = (
            self._build_llm_tool_schemas(context) if self._use_native_tools(context) else None
        )

        host = _ExploreLoopHost(pipeline=self, stream=stream, context=context, client=client)
        outcome = await run_agentic_loop(
            initial_messages=messages,
            protocol=_PROTOCOL_EXPLORE,
            client=client,
            model=self.model,
            completion_kwargs=self._completion_kwargs(DEFAULT_MAX_TOKENS),
            binding=self.binding,
            tool_schemas=tool_schemas,
            stream=stream,
            source=SOURCE,
            stage=STAGE_EXPLORING,
            max_iterations=self.max_explore_iterations,
            host=host,
            usage=self.usage,
            stream_body_live=True,
            eager_sub_trace=True,
        )
        finish_text = (outcome.final_text or "").strip()
        exploration_trace = self._render_exploration_trace(
            outcome.messages[initial_message_count:],
            finish_text=finish_text,
        )
        return finish_text, exploration_trace

    # ------------------------------------------------------------------
    # Phase 2: Plan
    # ------------------------------------------------------------------
    async def _plan(
        self,
        *,
        user_message: str,
        exploration_trace: str,
        num_questions: int,
        difficulty: str,
        allowed_types: list[str],
        per_type_counts: dict[str, int],
        stream: StreamBus,
        client: Any,
    ) -> QuizPlan:
        system_prompt = self._t("plan.system", num_questions=num_questions)
        system_prompt = append_language_directive(system_prompt, self.language)
        user_prompt = self._t(
            "plan.user_template",
            user_message=user_message,
            exploration_trace=exploration_trace or self._t("empty.no_exploration_trace"),
            num_questions=num_questions,
            allowed_types=_format_allowed_types(allowed_types),
            per_type_counts=_format_per_type_counts(per_type_counts),
            difficulty=difficulty or "auto",
        )
        messages = self._build_system_user_messages(system_prompt, user_prompt)
        iter_meta = self._build_simple_trace_meta(
            call_id_root="quiz-plan",
            label=self._t("labels.plan", default="Plan"),
            stage=STAGE_PLANNING,
            call_kind="llm_planning",
            trace_role="plan",
            trace_group="plan",
        )
        step = await self._run_labeled_step(
            client=client,
            messages=messages,
            tool_schemas=None,
            protocol=_PROTOCOL_PLAN,
            stream=stream,
            stage=STAGE_PLANNING,
            iter_meta=iter_meta,
            max_tokens=PLAN_MAX_TOKENS,
        )
        plan = self._parse_plan(
            step.text,
            requested=num_questions,
            allowed_types=allowed_types,
            target_difficulty=difficulty,
        )
        if len(plan.templates) != num_questions:
            await stream.progress(
                self._t(
                    "notices.plan_count_mismatch",
                    got=len(plan.templates),
                    requested=num_questions,
                ),
                source=SOURCE,
                stage=STAGE_PLANNING,
                metadata={"trace_kind": "warning"},
            )
        return plan

    def _parse_plan(
        self,
        raw: str,
        *,
        requested: int,
        allowed_types: list[str],
        target_difficulty: str,
    ) -> QuizPlan:
        data = parse_json_response(raw, logger_instance=logger, fallback={})
        if not isinstance(data, dict) or not data:
            return QuizPlan(analysis="", templates=[])
        analysis = str(data.get("analysis", "") or "")

        raw_items: list[Any]
        if isinstance(data.get("templates"), list):
            raw_items = list(data["templates"])
        elif isinstance(data.get("ideas"), list):
            raw_items = list(data["ideas"])
        else:
            raw_items = []

        # If the caller restricted types, the plan must only use that set.
        # Otherwise fall back to the full canonical taxonomy.
        allowed_set: frozenset[str] = (
            frozenset(allowed_types) if allowed_types else _VALID_QUESTION_TYPES
        )
        # The chosen fallback when the planner emits an out-of-set type:
        # prefer SHORT_ANSWER (concept-style Q&A) when allowed, else first
        # allowed type, else WRITTEN as a global default.
        if QuestionType.SHORT_ANSWER.value in allowed_set:
            fallback_type = QuestionType.SHORT_ANSWER.value
        elif allowed_set:
            fallback_type = next(iter(allowed_set))
        else:
            fallback_type = QuestionType.WRITTEN.value

        templates: list[QuizTemplate] = []
        seen_topics: set[str] = set()
        for idx, item in enumerate(raw_items, 1):
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic") or item.get("concentration") or "").strip()
            if not topic or topic.lower() in seen_topics:
                continue
            seen_topics.add(topic.lower())

            qtype_raw = str(item.get("question_type", "")).strip().lower()
            qtype = qtype_raw if qtype_raw in allowed_set else fallback_type

            diff_raw = str(item.get("difficulty", "")).strip().lower()
            diff = target_difficulty or diff_raw
            diff = diff if diff in _VALID_DIFFICULTIES else "medium"

            templates.append(
                QuizTemplate(
                    question_id=f"q_{len(templates) + 1}",
                    topic=topic,
                    question_type=qtype,
                    difficulty=diff,
                )
            )
            if len(templates) >= requested:
                break
        return QuizPlan(analysis=analysis, templates=templates)

    # ------------------------------------------------------------------
    # Phase 3: Quiz (one question)
    # ------------------------------------------------------------------
    async def _quiz_one(
        self,
        *,
        template: QuizTemplate,
        question_number: int,
        total_questions: int,
        exploration_trace: str,
        plan: QuizPlan,
        previous_pairs: list[QuizPair],
        image_attachments: list[Attachment],
        context: UnifiedContext,
        stream: StreamBus,
        client: Any,
    ) -> QuizPair:
        system_prompt = self._t(
            "quiz_step.system",
            question_number=question_number,
            total_questions=total_questions,
            kb_note=self._kb_system_note(),
            tool_list=self._tool_list_text(context),
        )
        system_prompt = append_language_directive(system_prompt, self.language)
        user_prompt = self._t(
            "quiz_step.user_template",
            question_id=template.question_id,
            topic=template.topic,
            question_type=template.question_type,
            difficulty=template.difficulty,
            exploration_trace=exploration_trace or self._t("empty.no_exploration_trace"),
            plan_summary=self._render_plan_summary(plan),
            previous_questions=self._render_previous_questions(previous_pairs),
            reference_block=self._render_reference_block(template),
        )
        messages = self._build_system_user_messages(
            system_prompt, user_prompt, image_attachments=image_attachments
        )

        tool_schemas = (
            self._build_llm_tool_schemas(context) if self._use_native_tools(context) else None
        )
        host = _QuizLoopHost(
            pipeline=self,
            template=template,
            stream=stream,
            context=context,
            client=client,
        )
        outcome = await run_agentic_loop(
            initial_messages=messages,
            protocol=_PROTOCOL_QUIZ,
            client=client,
            model=self.model,
            completion_kwargs=self._completion_kwargs(QUIZ_FINISH_MAX_TOKENS),
            binding=self.binding,
            tool_schemas=tool_schemas,
            stream=stream,
            source=SOURCE,
            stage=STAGE_QUIZZING,
            max_iterations=self.max_quiz_iterations_per_question,
            host=host,
            usage=self.usage,
            stream_body_live=False,
            eager_sub_trace=True,
        )
        payload = self._parse_quiz_payload(outcome.final_text)
        normalized = self._normalize_quiz_payload(template, payload)
        issues = self._collect_quiz_issues(template, normalized)
        if issues:
            await stream.progress(
                self._t("notices.repair_attempted"),
                source=SOURCE,
                stage=STAGE_QUIZZING,
                metadata={"trace_kind": "warning"},
            )
            repaired = await self._repair_quiz_payload(
                template=template,
                payload=normalized,
                issues=issues,
                stream=stream,
                client=client,
            )
            if repaired:
                normalized = self._normalize_quiz_payload(template, repaired)
                issues = self._collect_quiz_issues(template, normalized)
            if issues:
                await stream.progress(
                    self._t("notices.repair_failed"),
                    source=SOURCE,
                    stage=STAGE_QUIZZING,
                    metadata={"trace_kind": "warning"},
                )
        return self._payload_to_qa_pair(template, normalized, issues=issues)

    async def _repair_quiz_payload(
        self,
        *,
        template: QuizTemplate,
        payload: dict[str, Any],
        issues: list[str],
        stream: StreamBus,
        client: Any,
    ) -> dict[str, Any] | None:
        system_prompt = append_language_directive(
            self._t("repair.system"),
            self.language,
        )
        user_prompt = self._t(
            "repair.user_template",
            question_id=template.question_id,
            topic=template.topic,
            question_type=template.question_type,
            difficulty=template.difficulty,
            invalid_payload=json.dumps(payload, ensure_ascii=False, indent=2),
            issues=json.dumps(issues, ensure_ascii=False),
        )
        messages = self._build_system_user_messages(system_prompt, user_prompt)
        iter_meta = self._build_simple_trace_meta(
            call_id_root=f"quiz-repair-{template.question_id}",
            label=self._t("labels.repair", default="Repair question format"),
            stage=STAGE_QUIZZING,
            call_kind="llm_reasoning",
            trace_role="thought",
            trace_group=TRACE_GROUP_QUIZ,
            question_id=template.question_id,
        )
        # Repair uses a FINISH-only protocol so the host's existing parser
        # path can re-use ``_parse_quiz_payload`` on the buffered text.
        step = await self._run_labeled_step(
            client=client,
            messages=messages,
            tool_schemas=None,
            protocol=_PROTOCOL_REPAIR,
            stream=stream,
            stage=STAGE_QUIZZING,
            iter_meta=iter_meta,
            max_tokens=REPAIR_MAX_TOKENS,
        )
        return self._parse_quiz_payload(step.text)

    # ------------------------------------------------------------------
    # Tool Summarizer (Phase 1 reflection over a single tool_result)
    # ------------------------------------------------------------------
    async def _summarize_tool_result(
        self,
        *,
        tool_name: str,
        tool_result: str,
        iteration: int,
        stream: StreamBus,
        client: Any,
    ) -> str | None:
        """Run one main-model LLM call that compresses ``tool_result`` into a
        lossless summary. The summary is streamed live to the trace panel
        under a "Reflecting..." sub-trace node and returned to the caller,
        which then substitutes it for the raw result in the loop's message
        buffer.

        Returns ``None`` on failure / empty input so the caller can keep the
        raw result instead.
        """
        text = (tool_result or "").strip()
        if not text:
            return None

        system_prompt = self._t("tool_summarizer.system")
        system_prompt = append_language_directive(system_prompt, self.language)
        user_prompt = self._t("tool_summarizer.user_template", tool_result=text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        call_id = new_call_id(f"quiz-reflect-iter-{iteration}-{tool_name or 'tool'}")
        meta = build_trace_metadata(
            call_id=call_id,
            phase=STAGE_EXPLORING,
            label=self._t("labels.reflecting", default="DeepTutor Reflecting..."),
            call_kind="tool_result_reflection",
            trace_id=call_id,
            trace_role="reflection",
            trace_group="reflection",
            tool=tool_name,
            iteration=iteration,
        )
        # Open the sub-trace card before the LLM stream starts so the panel
        # registers the "Reflecting..." node immediately.
        await stream.progress(
            self._t("labels.reflecting", default="DeepTutor Reflecting..."),
            source=SOURCE,
            stage=STAGE_EXPLORING,
            metadata=merge_trace_metadata(
                meta, {"trace_kind": "call_status", "call_state": "running"}
            ),
        )

        # ``build_completion_kwargs`` returns generation/provider kwargs;
        # ``model``/``messages``/``stream`` must be added explicitly
        # (mirrors how ``run_labeled_step`` composes its create call).
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            **build_completion_kwargs(
                temperature=TOOL_SUMMARIZER_TEMPERATURE,
                model=self.model,
                max_tokens=self.tool_summarizer_max_tokens,
                binding=self.binding,
                reasoning_effort=self.reasoning_effort,
            ),
        }
        try:
            kwargs["stream_options"] = {"include_usage": True}
        except Exception:
            pass

        chunks: list[str] = []
        try:
            response_stream = await client.chat.completions.create(**kwargs)
            async for chunk in response_stream:
                # Usage frames have no choices; surface them to the usage
                # tracker so the cost summary reflects the summarizer too.
                usage_frame = getattr(chunk, "usage", None)
                if usage_frame and self.usage is not None:
                    try:
                        self.usage.add_from_response(usage_frame)
                    except Exception:
                        logger.debug("usage recording failed for summarizer", exc_info=True)
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                text_chunk = getattr(delta, "content", None) or ""
                if not text_chunk:
                    continue
                chunks.append(text_chunk)
                await stream.thinking(
                    text_chunk,
                    source=SOURCE,
                    stage=STAGE_EXPLORING,
                    metadata=merge_trace_metadata(meta, {"trace_kind": "llm_chunk"}),
                )
        except Exception as exc:
            logger.warning("Tool summarizer failed for %s: %s", tool_name, exc)
            await stream.progress(
                self._t("notices.tool_summarizer_failed"),
                source=SOURCE,
                stage=STAGE_EXPLORING,
                metadata=merge_trace_metadata(
                    meta, {"trace_kind": "warning", "call_state": "error"}
                ),
            )
            return None
        finally:
            await stream.progress(
                "",
                source=SOURCE,
                stage=STAGE_EXPLORING,
                metadata=merge_trace_metadata(
                    meta, {"trace_kind": "call_status", "call_state": "complete"}
                ),
            )

        summary = "".join(chunks).strip()
        return summary or None

    # ------------------------------------------------------------------
    # Exploration trace serialization (Phase 1 → Phase 2/3 hand-off)
    # ------------------------------------------------------------------
    def _render_exploration_trace(
        self,
        loop_messages: list[dict[str, Any]],
        *,
        finish_text: str,
    ) -> str:
        """Serialize the explore loop's post-initial messages into a
        markdown blob consumed by the plan + quiz prompts.

        Tool results in ``loop_messages`` have already been replaced by the
        Tool Summarizer's output (the explore host substitutes them inside
        ``dispatch_tools``), so this renderer never has to compress anything
        — it just lays the buffer out in a readable form.

        The final FINISH assistant message is included as a labeled "final
        exploration preface" block so the planner can read the same closing
        synthesis the user saw, while still having every preceding tool
        result + thought to draw on.
        """
        if not loop_messages and not finish_text:
            return self._t("empty.no_exploration_trace")

        blocks: list[str] = []
        iteration = 0
        # Map tool_call_id → invoked function name so tool messages can
        # surface a human-readable label even though the role=tool message
        # itself only carries the id.
        tool_call_names: dict[str, str] = {}

        for message in loop_messages:
            role = message.get("role")
            content = (message.get("content") or "").strip()

            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    iteration += 1
                    for tc in tool_calls:
                        function = tc.get("function") or {}
                        name = function.get("name") or "tool"
                        tc_id = tc.get("id") or ""
                        if tc_id:
                            tool_call_names[tc_id] = name
                        raw_args = function.get("arguments") or "{}"
                        try:
                            parsed_args = json.loads(raw_args)
                            args_display = json.dumps(parsed_args, ensure_ascii=False, indent=2)
                        except Exception:
                            args_display = str(raw_args)
                        header = self._t(
                            "trace.iteration_tool_call",
                            n=iteration,
                            tool=name,
                            default=f"Iteration {iteration} — Tool call: {name}",
                        )
                        body_parts: list[str] = []
                        if content:
                            body_parts.append(content)
                        body_parts.append(f"Arguments:\n```json\n{args_display}\n```")
                        blocks.append(f"### {header}\n\n" + "\n\n".join(body_parts))
                    continue

                # Plain assistant content = a THINK iteration. Strip the
                # leading protocol label so downstream consumers don't have
                # to.
                if not content:
                    continue
                iteration += 1
                stripped = self._strip_protocol_label(content)
                header = self._t(
                    "trace.iteration_thought",
                    n=iteration,
                    default=f"Iteration {iteration} — Thought",
                )
                blocks.append(f"### {header}\n\n{stripped}")

            elif role == "tool":
                tc_id = message.get("tool_call_id") or ""
                name = tool_call_names.get(tc_id, "tool")
                header = self._t(
                    "trace.iteration_tool_result",
                    n=iteration,
                    tool=name,
                    default=f"Iteration {iteration} — Tool result (summarized): {name}",
                )
                blocks.append(f"### {header}\n\n{content or '(empty)'}")

            elif role == "user":
                # User-role messages inside the loop are protocol-repair
                # nudges or force-finish prompts injected by the host —
                # noise that downstream readers don't need.
                continue

        finish_label = self._t(
            "trace.finish_note", default="Final exploration preface (also shown to the user)"
        )
        if finish_text:
            blocks.append(f"### {finish_label}\n\n{finish_text.strip()}")

        return "\n\n".join(blocks) if blocks else self._t("empty.no_exploration_trace")

    @staticmethod
    def _strip_protocol_label(text: str) -> str:
        """Drop a leading ``THINK`` / ``TOOL`` / ``FINISH`` label so the trace
        rendering doesn't double up on protocol noise."""
        stripped = text.lstrip()
        for label in ("``THINK``", "``TOOL``", "``FINISH``"):
            if stripped.startswith(label):
                return stripped[len(label) :].lstrip("\n").lstrip()
        return text

    # ------------------------------------------------------------------
    # Incremental emission (per question)
    # ------------------------------------------------------------------
    async def _emit_quiz_question(
        self,
        *,
        stream: StreamBus,
        qa_pair: QuizPair,
        index: int,
        total: int,
    ) -> None:
        meta = build_trace_metadata(
            call_id=new_call_id(f"quiz-question-{index + 1}"),
            phase=STAGE_QUIZZING,
            label=f"{self._t('labels.quiz_step', default='Question')} {index + 1}",
            call_kind=CALL_KIND_QUIZ_QUESTION,
            trace_id=qa_pair.question_id,
            trace_role=TRACE_ROLE_QUIZ_QUESTION,
            trace_group=TRACE_GROUP_QUIZ,
            question_index=index,
            total_questions=total,
            qa_pair=self._qa_pair_to_dict(qa_pair),
        )
        await stream.content(
            self._render_question_markdown(qa_pair, index + 1),
            source=SOURCE,
            stage=STAGE_QUIZZING,
            metadata=merge_trace_metadata(meta, {"trace_kind": "llm_output"}),
        )

    # ------------------------------------------------------------------
    # Final result envelope
    # ------------------------------------------------------------------
    def _build_result_payload(
        self,
        plan: QuizPlan,
        qa_pairs: list[QuizPair],
        *,
        is_mimic: bool = False,
        finish_text: str = "",
    ) -> dict[str, Any]:
        """Compose the terminal envelope.

        On result-event arrival the frontend overwrites the chat bubble's
        body with ``response``. The QuizViewer renders the per-question
        cards from ``summary.results`` independently, **above** which it
        now stacks the response body — so we put ONLY the explore FINISH
        preface in ``response`` (no per-question markdown). Mimic mode
        has no Phase 1, so ``finish_text`` is empty and ``response``
        falls back to the rendered question summary so something still
        shows in the bubble even though the QuizViewer carries the same
        content.
        """
        results = [
            {
                "qa_pair": self._qa_pair_to_dict(qa_pair),
                "metadata": dict(qa_pair.metadata),
            }
            for qa_pair in qa_pairs
        ]
        successful = sum(1 for qa in qa_pairs if not qa.metadata.get("error"))
        markdown = self._render_summary_markdown(qa_pairs)
        finish_block = finish_text.strip()
        if finish_block:
            # Custom mode: the user already watched FINISH stream into the
            # bubble. Keep that as the bubble's body so it doesn't disappear
            # when QuizViewer mounts. Question markdown lives in QuizViewer
            # — duplicating it here would render every question twice.
            response_body = finish_block
        else:
            # Mimic mode: no Phase 1 ran, so there's no streamed preface
            # to preserve. Fall back to the legacy summary markdown.
            response_body = markdown or "No questions generated."
        payload: dict[str, Any] = {
            "response": response_body,
            "summary": {
                "success": successful == len(qa_pairs) and bool(qa_pairs),
                "source": "exam" if is_mimic else "topic",
                "requested": len(plan.templates),
                "template_count": len(plan.templates),
                "completed": successful,
                "failed": len(qa_pairs) - successful,
                "templates": [self._template_to_dict(t) for t in plan.templates],
                "results": results,
                "analysis": plan.analysis,
            },
            "mode": "mimic" if is_mimic else "custom",
        }
        return payload

    # ------------------------------------------------------------------
    # Quiz payload parsing / validation / normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_quiz_payload(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        # Strip a single fenced block if the model wrapped the JSON
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            obj = re.search(r"\{[\s\S]*\}", text)
            if obj is None:
                return {}
            try:
                parsed = json.loads(obj.group(0))
            except json.JSONDecodeError:
                return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _normalize_quiz_payload(
        cls, template: QuizTemplate, payload: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(payload or {})
        expected_type = template.question_type
        normalized["question_type"] = expected_type
        normalized["question"] = str(normalized.get("question", "") or "").strip()
        normalized["correct_answer"] = str(normalized.get("correct_answer", "") or "").strip()
        normalized["explanation"] = str(normalized.get("explanation", "") or "").strip()

        raw_options = normalized.get("options")
        if expected_type == QuestionType.CHOICE.value:
            clean: dict[str, str] = {}
            if isinstance(raw_options, dict):
                for key, value in raw_options.items():
                    k = str(key or "").strip().upper()[:1]
                    v = str(value or "").strip()
                    if k in _CHOICE_KEYS and v:
                        clean[k] = v
            normalized["options"] = clean or None
            if clean and normalized["correct_answer"]:
                ans = normalized["correct_answer"].upper().strip()
                if ans in clean:
                    normalized["correct_answer"] = ans
                else:
                    for key, value in clean.items():
                        if normalized["correct_answer"].lower() == value.lower():
                            normalized["correct_answer"] = key
                            break
        elif expected_type == QuestionType.CONCEPT.value:
            # Concept (T/F) answers ride through correct_answer as the lowercase
            # literal "true"/"false". Coerce any Chinese / casing variants the
            # model might emit before the rest of the pipeline sees them.
            normalized["options"] = None
            raw_ans = normalized["correct_answer"].lower()
            if raw_ans in {"true", "t", "对", "正确", "yes", "y", "1"}:
                normalized["correct_answer"] = "true"
            elif raw_ans in {"false", "f", "错", "错误", "no", "n", "0"}:
                normalized["correct_answer"] = "false"
        else:
            normalized["options"] = None
        return normalized

    @classmethod
    def _collect_quiz_issues(cls, template: QuizTemplate, payload: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        question = str(payload.get("question") or "").strip()
        correct = str(payload.get("correct_answer") or "").strip()
        explanation = str(payload.get("explanation") or "").strip()
        options = payload.get("options")

        if not question:
            issues.append("missing_question")
        if not correct:
            issues.append("missing_correct_answer")
        if not explanation:
            issues.append("missing_explanation")

        qtype = template.question_type
        if qtype == QuestionType.CHOICE.value:
            if not isinstance(options, dict) or set(options.keys()) != set(_CHOICE_KEYS):
                issues.append("choice_options_must_be_a_to_d")
            if correct.upper() not in _CHOICE_KEYS:
                issues.append("choice_correct_answer_must_be_option_key")
        elif qtype == QuestionType.CONCEPT.value:
            if isinstance(options, dict) and options:
                issues.append("concept_must_not_have_options")
            if correct.lower() not in _CONCEPT_ANSWERS:
                issues.append("concept_correct_answer_must_be_true_or_false")
        elif qtype == QuestionType.FILL_IN_BLANK.value:
            if isinstance(options, dict) and options:
                issues.append("fill_in_blank_must_not_have_options")
            if question and _FILL_IN_BLANK_TOKEN not in question:
                issues.append("fill_in_blank_question_must_contain_blank_token")
        else:
            if isinstance(options, dict) and options:
                issues.append("non_choice_must_not_have_options")
            if correct.upper() in _CHOICE_KEYS and len(correct) == 1:
                issues.append("non_choice_correct_answer_looks_like_option_key")
        return issues

    def _payload_to_qa_pair(
        self,
        template: QuizTemplate,
        payload: dict[str, Any],
        *,
        issues: list[str],
    ) -> QuizPair:
        question = str(payload.get("question") or "").strip()
        if not question:
            question = f"[Generation failed] {template.topic}"
        return QuizPair(
            question_id=template.question_id,
            question=question,
            question_type=template.question_type,
            correct_answer=str(payload.get("correct_answer") or "").strip() or "N/A",
            explanation=str(payload.get("explanation") or "").strip() or "N/A",
            options=payload.get("options") if isinstance(payload.get("options"), dict) else None,
            topic=template.topic,
            difficulty=template.difficulty,
            metadata={"issues": issues} if issues else {},
        )

    # ------------------------------------------------------------------
    # Forced-finish (max-iter recovery) — shared by explore + quiz
    # ------------------------------------------------------------------
    async def _force_finish(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        stream: StreamBus,
        stage: str,
        trace_root: str,
        trace_extras: dict[str, Any],
        stream_body_live: bool,
    ) -> tuple[str, bool, int]:
        messages.append({"role": "user", "content": self._t("protocol.force_finish")})
        await stream.progress(
            self._t("notices.max_iterations_reached"),
            source=SOURCE,
            stage=stage,
            metadata={"trace_kind": "warning"},
        )
        calls = 0
        for attempt in range(FINALIZATION_REPAIR_ATTEMPTS):
            iter_meta = self._build_simple_trace_meta(
                call_id_root=f"{trace_root}-force-{attempt}",
                label=self._t("labels.reasoning", default="Reasoning"),
                stage=stage,
                **trace_extras,
            )
            final_meta = None
            if stream_body_live:
                final_call_id = new_call_id(f"{trace_root}-force-final-{attempt}")
                final_meta = build_trace_metadata(
                    call_id=final_call_id,
                    phase=stage,
                    label=self._t("labels.explore", default="Explore"),
                    call_kind="llm_final_response",
                    trace_id=final_call_id,
                    trace_role="response",
                    trace_group="stage",
                )
            step = await self._run_labeled_step(
                client=client,
                messages=messages,
                tool_schemas=None,
                protocol=_PROTOCOL_REPAIR,
                stream=stream,
                stage=stage,
                iter_meta=iter_meta,
                max_tokens=DEFAULT_MAX_TOKENS,
                final_meta=final_meta,
            )
            calls += 1
            if step.label == LABEL_FINISH and not find_inline_labels(
                step.text, allowed_labels=_PROTOCOL_EXPLORE.allowed
            ):
                return step.text, True, calls
            messages.append({"role": "assistant", "content": step.text[:500]})
            messages.append({"role": "user", "content": self._t("protocol.force_finish_repair")})
        return self._t("protocol.fallback_final"), False, calls

    # ------------------------------------------------------------------
    # Tool integration (mirrors chat's policy)
    # ------------------------------------------------------------------
    def _mount_flags(self, context: UnifiedContext) -> ToolMountFlags:
        return ToolMountFlags(
            has_kb=bool(self.kb_name),
            has_sources=bool(self._source_index(context)),
            has_memory=user_has_memory(),
            has_notebooks=user_has_notebooks(),
            has_code=exec_capability_available(),
        )

    def _resolved_tools(self, context: UnifiedContext) -> list[str]:
        return compose_enabled_tools(
            registry=self.registry,
            requested_tools=self.enabled_tools,
            optional_whitelist=self._optional_tools,
            mount_flags=self._mount_flags(context),
        )

    def _use_native_tools(self, context: UnifiedContext) -> bool:
        """Native tool calling is only worth enabling when (a) the binding /
        model actually supports it and (b) we have at least one tool to
        mount. Returning True with no tools would make the model improvise
        text-based "tool calls" since the prompt still mentions tools."""
        return bool(self._resolved_tools(context)) and can_use_native_tool_calling(
            binding=self.binding, model=self.model
        )

    def _build_llm_tool_schemas(self, context: UnifiedContext) -> list[dict[str, Any]]:
        schemas = self.registry.build_openai_schemas(self._resolved_tools(context))
        kb_choices = [self.kb_name] if self.kb_name else []
        source_ids = sorted((self._source_index(context) or {}).keys())
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if not isinstance(function, dict):
                continue
            parameters = function.get("parameters") or {}
            if not isinstance(parameters, dict):
                continue
            properties = parameters.get("properties") or {}
            name = function.get("name")
            if name == "rag" and isinstance(properties, dict):
                query_schema = properties.get("query")
                if isinstance(query_schema, dict):
                    query_schema.setdefault("minLength", 1)
                kb_schema = properties.get("kb_name")
                if isinstance(kb_schema, dict) and kb_choices:
                    kb_schema["enum"] = kb_choices
            if name == "read_source" and isinstance(properties, dict):
                sid_schema = properties.get("source_id")
                if isinstance(sid_schema, dict) and source_ids:
                    sid_schema["enum"] = source_ids
            parameters["additionalProperties"] = False
        return schemas

    def _augment_tool_kwargs(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        kwargs = dict(args)
        turn_id = str(context.metadata.get("turn_id", "") or "").strip()
        task_dir = None
        if turn_id:
            task_dir = get_path_service().get_task_workspace(FEATURE, turn_id)
        if tool_name == "rag":
            kwargs.setdefault("mode", "hybrid")
            if self.kb_name:
                kwargs.setdefault("kb_name", self.kb_name)
        elif tool_name == "code_execution":
            from deeptutor.services.sandbox import Mount

            if task_dir is not None:
                code_dir = task_dir / "code_runs"
                code_dir.mkdir(parents=True, exist_ok=True)
                kwargs["_sandbox_workdir"] = str(code_dir)
                kwargs["_sandbox_mounts"] = (
                    Mount(host_path=str(code_dir), sandbox_path=str(code_dir), read_only=False),
                )
        elif tool_name in {"reason", "brainstorm"}:
            kwargs.setdefault("context", context.user_message)
        elif tool_name == "web_search":
            kwargs.setdefault("query", context.user_message)
            if task_dir is not None:
                kwargs.setdefault("output_dir", str(task_dir / "web_search"))
        elif tool_name == "paper_search":
            kwargs.setdefault("max_results", 3)
            kwargs.setdefault("years_limit", 3)
            kwargs.setdefault("sort_by", "relevance")
        elif tool_name == "read_source":
            kwargs["source_index"] = self._source_index(context)
        elif tool_name == "write_note":
            kwargs["conversation_history"] = list(context.conversation_history or [])
            kwargs["current_user_message"] = context.user_message or ""
        return kwargs

    def _retrieve_trace_metadata(
        self,
        tool_meta: dict[str, Any],
        *,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        if tool_name != "rag":
            return None
        return derive_trace_metadata(
            tool_meta,
            label=self._t("labels.retrieve", default="Retrieve"),
            call_kind="rag_retrieval",
            trace_role="retrieve",
            trace_group="retrieve",
            query=str(tool_args.get("query", "") or ""),
        )

    @staticmethod
    def _source_index(context: UnifiedContext) -> dict[str, str]:
        idx = context.metadata.get("source_index")
        return idx if isinstance(idx, dict) and idx else {}

    def _tool_list_text(self, context: UnifiedContext) -> str:
        text = self.registry.build_prompt_text(
            self._resolved_tools(context),
            format="list_with_usage",
            language=self.language,
        )
        return text or self._fallback_empty_tool_list()

    def _fallback_empty_tool_list(self) -> str:
        return "- 无" if self.language == "zh" else "- none"

    def _kb_system_note(self) -> str:
        if not self.kb_name:
            return ""
        if self.language == "zh":
            return f"用户已挂载知识库：{self.kb_name}。调用 rag 时，kb_name 必须填这个名称。"
        return (
            f"Attached knowledge bases: {self.kb_name}. When calling rag, kb_name "
            f"must be {self.kb_name!r}."
        )

    # ------------------------------------------------------------------
    # LLM call helpers
    # ------------------------------------------------------------------
    def _completion_kwargs(self, max_tokens: int) -> dict[str, Any]:
        return build_completion_kwargs(
            temperature=self._temperature,
            model=self.model,
            max_tokens=max_tokens,
            binding=self.binding,
            reasoning_effort=self.reasoning_effort,
        )

    async def _run_labeled_step(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]] | None,
        protocol: LabelProtocol,
        stream: StreamBus,
        stage: str,
        iter_meta: dict[str, Any],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        final_meta: dict[str, Any] | None = None,
        eager_sub_trace: bool = True,
    ) -> LabeledStepResult:
        return await run_labeled_step(
            client=client,
            model=self.model,
            messages=messages,
            completion_kwargs=self._completion_kwargs(max_tokens),
            tool_schemas=tool_schemas,
            allowed_labels=protocol.allowed,
            final_labels=protocol.final,
            tool_label=protocol.tool_label,
            stream=stream,
            source=SOURCE,
            stage=stage,
            iter_meta=iter_meta,
            binding=self.binding,
            usage=self.usage,
            final_meta=final_meta,
            eager_sub_trace=eager_sub_trace,
        )

    # ------------------------------------------------------------------
    # Message + trace assembly
    # ------------------------------------------------------------------
    def _build_system_user_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        image_attachments: list[Attachment] | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if image_attachments:
            mm_result = prepare_multimodal_messages(
                messages, image_attachments, binding=self.binding, model=self.model
            )
            return mm_result.messages
        return messages

    def _build_simple_trace_meta(
        self,
        *,
        call_id_root: str,
        label: str,
        stage: str,
        call_kind: str = "llm_reasoning",
        trace_role: str = "thought",
        trace_group: str = "stage",
        **extra: Any,
    ) -> dict[str, Any]:
        call_id = new_call_id(call_id_root)
        return build_trace_metadata(
            call_id=call_id,
            phase=stage,
            label=label,
            call_kind=call_kind,
            trace_id=call_id,
            trace_role=trace_role,
            trace_group=trace_group,
            **extra,
        )

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------
    def _render_attachments_summary(self, attachments: list[Attachment]) -> str:
        if not attachments:
            return self._t("empty.no_attachments")
        lines = []
        for att in attachments:
            name = getattr(att, "filename", "") or getattr(att, "type", "attachment")
            kind = getattr(att, "type", "")
            lines.append(f"- {name} ({kind})")
        return "\n".join(lines)

    def _render_quiz_history(self, history: list[QuizHistoryEntry]) -> str:
        if not history:
            return self._t("empty.no_quiz_history")
        lines = [
            (
                f"- ({entry.turn_id or '?'}) [{self._correctness_label(entry.is_correct)}] "
                f"{entry.question[:160]}"
                + (
                    f" — learner answer: {entry.user_answer[:80]}; "
                    f"reference: {entry.correct_answer[:80]}"
                    if entry.user_answer or entry.correct_answer
                    else ""
                )
            )
            for entry in history
        ]
        return "\n".join(lines)

    def _correctness_label(self, is_correct: bool | None) -> str:
        if is_correct is True:
            return "correct" if self.language != "zh" else "做对"
        if is_correct is False:
            return "incorrect" if self.language != "zh" else "做错"
        return "unknown" if self.language != "zh" else "未知"

    def _render_plan_summary(self, plan: QuizPlan) -> str:
        if not plan.templates:
            return "(empty plan)"
        lines = []
        if plan.analysis:
            lines.append(f"Analysis: {plan.analysis}")
        for template in plan.templates:
            lines.append(
                f"  - [{template.question_id}] ({template.question_type}/"
                f"{template.difficulty}) {template.topic}"
            )
        return "\n".join(lines)

    def _render_previous_questions(self, qa_pairs: list[QuizPair]) -> str:
        if not qa_pairs:
            return self._t("empty.no_previous_questions")
        return "\n".join(f"{i}. {qa.question}" for i, qa in enumerate(qa_pairs, 1))

    def _render_reference_block(self, template: QuizTemplate) -> str:
        """Mimic-mode reference block injected into ``quiz_step.user_template``.

        For ``custom`` templates this is the YAML-supplied empty marker so
        the LLM treats this as a generative task; for ``mimic`` templates
        we surface the original exam-paper question (and reference answer
        when present) so the LLM shadows the source's style and difficulty
        rather than inventing a fresh stem.
        """
        if template.source != "mimic":
            return self._t("empty.no_reference")
        reference_q = (template.reference_question or "").strip()
        reference_a = (template.reference_answer or "").strip()
        if not reference_q and not reference_a:
            return self._t("empty.no_reference")
        lines: list[str] = []
        if reference_q:
            lines.append(f"Reference question:\n{reference_q}")
        if reference_a:
            lines.append(f"Reference answer:\n{reference_a}")
        return "\n\n".join(lines)

    def _render_question_markdown(self, qa: QuizPair, ordinal: int) -> str:
        header = "题目" if self.language == "zh" else "Question"
        lines = [f"### {header} {ordinal}\n", qa.question]
        if isinstance(qa.options, dict) and qa.options:
            for key in _CHOICE_KEYS:
                if key in qa.options:
                    lines.append(f"- {key}. {qa.options[key]}")
        if qa.correct_answer:
            answer_label = "答案" if self.language == "zh" else "Answer"
            lines.append(f"\n**{answer_label}:** {qa.correct_answer}")
        if qa.explanation:
            expl_label = "解析" if self.language == "zh" else "Explanation"
            lines.append(f"\n**{expl_label}:** {qa.explanation}")
        return "\n".join(lines).strip()

    def _render_summary_markdown(self, qa_pairs: list[QuizPair]) -> str:
        return "\n\n".join(
            self._render_question_markdown(qa, i + 1) for i, qa in enumerate(qa_pairs)
        )

    @staticmethod
    def _qa_pair_to_dict(qa: QuizPair) -> dict[str, Any]:
        return {
            "question_id": qa.question_id,
            "question": qa.question,
            "question_type": qa.question_type,
            "options": qa.options,
            "correct_answer": qa.correct_answer,
            "explanation": qa.explanation,
            "difficulty": qa.difficulty,
            "concentration": qa.topic,
        }

    @staticmethod
    def _template_to_dict(template: QuizTemplate) -> dict[str, Any]:
        return {
            "question_id": template.question_id,
            "topic": template.topic,
            "question_type": template.question_type,
            "difficulty": template.difficulty,
            "source": template.source,
            "reference_question": template.reference_question,
            "reference_answer": template.reference_answer,
        }

    # ------------------------------------------------------------------
    # Visible failure
    # ------------------------------------------------------------------
    async def _emit_visible_failure(self, stream: StreamBus, exc: BaseException) -> None:
        call_id = new_call_id("quiz-failure")
        meta = build_trace_metadata(
            call_id=call_id,
            phase=STAGE_QUIZZING,
            label=self._t("labels.quiz_step", default="Question"),
            call_kind="llm_final_response",
            trace_id=call_id,
            trace_role="response",
            trace_group="stage",
        )
        message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        await stream.error(
            message,
            source=SOURCE,
            stage=STAGE_QUIZZING,
            metadata=merge_trace_metadata(meta, {"trace_kind": "error"}),
        )
        prefix = "⚠️ " if self.language == "zh" else "⚠ "
        await stream.content(
            f"{prefix}{message}",
            source=SOURCE,
            stage=STAGE_QUIZZING,
            metadata=merge_trace_metadata(meta, {"trace_kind": "llm_output"}),
        )

    # ------------------------------------------------------------------
    # YAML lookup
    # ------------------------------------------------------------------
    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        value: Any = self._prompts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        if not isinstance(value, str):
            return default
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        return value


# ---------------------------------------------------------------------------
# LoopHosts
# ---------------------------------------------------------------------------


class _BaseLoopHost:
    """Common LoopHost wiring shared by explore + quiz hosts.

    Subclasses customize the iteration trace metadata, the final-emission
    behavior, and the force-finalize copy.
    """

    def __init__(
        self,
        *,
        pipeline: QuestionPipeline,
        stream: StreamBus,
        context: UnifiedContext,
        client: Any,
    ) -> None:
        self._pipeline = pipeline
        self._stream = stream
        self._context = context
        self._client = client

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        # v1 doesn't run an in-loop trimmer for the quiz pipeline. Per-phase
        # message buffers are bounded by max_iterations × per-call size.
        return

    async def dispatch_tools(
        self,
        *,
        iteration: int,
        tool_calls: list[dict[str, Any]],
    ) -> DispatchOutcome:
        too_many = None
        if len(tool_calls) > MAX_PARALLEL_TOOL_CALLS:
            too_many = self._pipeline._t(
                "notices.too_many_tool_calls",
                requested=len(tool_calls),
                limit=MAX_PARALLEL_TOOL_CALLS,
            )
        return await dispatch_tool_calls(
            tool_calls=tool_calls,
            context=self._context,
            stream=self._stream,
            source=SOURCE,
            stage=self._stage,
            iteration_index=iteration,
            registry=self._pipeline.registry,
            kwarg_augmenter=self._pipeline._augment_tool_kwargs,
            retrieve_meta_factory=lambda meta, tn, ta: self._pipeline._retrieve_trace_metadata(
                meta, tool_name=tn, tool_args=ta
            ),
            tool_call_label=self._pipeline._t("labels.tool_call", default="Tool call"),
            retrieve_label=self._pipeline._t("labels.retrieve", default="Retrieve"),
            empty_tool_result_message=self._pipeline._t("notices.empty_tool_result"),
            start_retrieval_message=self._pipeline._t(
                "notices.start_retrieval", default="Starting retrieval"
            ),
            too_many_tool_calls_message=too_many,
            unknown_error_message_factory=lambda tn: self._pipeline._t(
                "notices.tool_unknown_error",
                tool=tn,
                default=f"Error executing {tn}.",
            ),
            trace_id_prefix=self._trace_id_prefix,
        )

    async def resolve_pause(self, dispatch: DispatchOutcome) -> bool:
        # ``ask_user`` would pause the turn — quiz pipeline v1 doesn't wire up
        # the wait/resume path. Terminate the loop so the turn closes cleanly.
        return False

    async def emit_terminator(self, payload: dict[str, Any] | None) -> None:
        # No quiz tool is wired to terminate the loop with content.
        return

    def assistant_message_with_tool_calls(
        self,
        *,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc.get("arguments") or "{}",
                    },
                }
                for tc in tool_calls
            ],
        }

    def protocol_retry_notice(self) -> str:
        return self._pipeline._t(
            "notices.protocol_retry",
            default="The model violated the action-label protocol; retrying.",
        )

    def protocol_repair_message(self, violation: str) -> str:
        return self._pipeline._t(
            f"protocol.{violation}",
            default=f"Protocol violation: {violation}.",
        )

    # The two attributes below are set by each subclass.
    _stage: str = ""
    _trace_id_prefix: str = "iter"


class _ExploreLoopHost(_BaseLoopHost):
    """Drives the Explore phase. FINISH streams live to the chat bubble.

    Layers a Tool Summarizer over the base ``dispatch_tools``: after the
    parent dispatch returns, this host fires one main-model LLM call per
    ``role=tool`` message to compress the raw result into a concise summary,
    streams that summary to a "Reflecting..." trace node, and substitutes it
    back into the loop's message buffer. Downstream phases see only the
    summarized version via the exploration_trace.
    """

    _stage = STAGE_EXPLORING
    _trace_id_prefix = "quiz-explore-iter"

    async def dispatch_tools(
        self,
        *,
        iteration: int,
        tool_calls: list[dict[str, Any]],
    ) -> DispatchOutcome:
        outcome = await super().dispatch_tools(iteration=iteration, tool_calls=tool_calls)
        if not self._pipeline.tool_summarizer_enabled or not outcome.tool_messages:
            return outcome

        # Build a tool_call_id → name map so the reflection node carries a
        # human-readable tool label.
        name_by_id: dict[str, str] = {}
        for tc in tool_calls:
            tc_id = tc.get("id") or ""
            if tc_id:
                name_by_id[tc_id] = str(tc.get("name") or "tool")

        summarized: list[dict[str, Any]] = []
        for message in outcome.tool_messages:
            new_message = dict(message)
            content = str(message.get("content") or "")
            tc_id = str(message.get("tool_call_id") or "")
            tool_name = name_by_id.get(tc_id, "tool")
            summary = await self._pipeline._summarize_tool_result(
                tool_name=tool_name,
                tool_result=content,
                iteration=iteration,
                stream=self._stream,
                client=self._client,
            )
            if summary:
                new_message["content"] = summary
            summarized.append(new_message)

        return DispatchOutcome(
            sources=outcome.sources,
            tool_messages=summarized,
            terminate=outcome.terminate,
            terminate_payload=outcome.terminate_payload,
            pause=outcome.pause,
            pause_payload=outcome.pause_payload,
            pause_tool_call_id=outcome.pause_tool_call_id,
        )

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        iter_call_id = new_call_id(f"quiz-explore-iter-{iteration}")
        iter_meta = build_trace_metadata(
            call_id=iter_call_id,
            phase=STAGE_EXPLORING,
            label=self._pipeline._t("labels.reasoning", default="Reasoning"),
            call_kind="llm_reasoning",
            trace_id=iter_call_id,
            trace_role="thought",
            trace_group="stage",
        )
        final_call_id = new_call_id("quiz-explore-final")
        final_meta = build_trace_metadata(
            call_id=final_call_id,
            phase=STAGE_EXPLORING,
            label=self._pipeline._t("labels.explore", default="Explore"),
            call_kind="llm_final_response",
            trace_id=final_call_id,
            trace_role="response",
            trace_group="stage",
        )
        return iter_meta, final_meta

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        # Reached when ``stream_body_live=False`` would have been set; the
        # explore loop runs with ``stream_body_live=True`` so the
        # ``run_agentic_loop`` skips this. Kept for protocol compliance.
        if not text:
            return
        await self._stream.content(
            text,
            source=SOURCE,
            stage=STAGE_EXPLORING,
            metadata=merge_trace_metadata(final_meta, {"trace_kind": "llm_output"}),
        )

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        return await self._pipeline._force_finish(
            client=self._client,
            messages=messages,
            stream=self._stream,
            stage=STAGE_EXPLORING,
            trace_root="quiz-explore",
            trace_extras={
                "call_kind": "llm_reasoning",
                "trace_role": "thought",
                "trace_group": "stage",
            },
            stream_body_live=True,
        )


class _QuizLoopHost(_BaseLoopHost):
    """Drives one quiz question's loop.

    FINISH text is buffered (``stream_body_live=False``); the pipeline
    parses + repairs + emits a structured ``quiz_question_emitted`` event
    after the loop returns. This host's ``emit_final`` is a deliberate
    no-op so the loop doesn't drop the raw JSON into the chat bubble.
    """

    _stage = STAGE_QUIZZING

    def __init__(
        self,
        *,
        pipeline: QuestionPipeline,
        template: QuizTemplate,
        stream: StreamBus,
        context: UnifiedContext,
        client: Any,
    ) -> None:
        super().__init__(pipeline=pipeline, stream=stream, context=context, client=client)
        self._template = template
        self._trace_id_prefix = f"quiz-{template.question_id}-iter"

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        iter_call_id = new_call_id(f"quiz-{self._template.question_id}-iter-{iteration}")
        iter_meta = build_trace_metadata(
            call_id=iter_call_id,
            phase=STAGE_QUIZZING,
            label=self._pipeline._t("labels.reasoning", default="Reasoning"),
            call_kind="llm_reasoning",
            trace_id=iter_call_id,
            trace_role="thought",
            trace_group=TRACE_GROUP_QUIZ,
            question_id=self._template.question_id,
        )
        # The visible "Question" card is emitted by the pipeline after the
        # loop returns (with the structured qa_pair). ``final_meta`` is
        # never consumed because ``stream_body_live=False`` AND
        # ``emit_final`` is a no-op for this host.
        return iter_meta, iter_meta

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        # Intentional no-op. See class docstring.
        return

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        return await self._pipeline._force_finish(
            client=self._client,
            messages=messages,
            stream=self._stream,
            stage=STAGE_QUIZZING,
            trace_root=f"quiz-{self._template.question_id}",
            trace_extras={
                "call_kind": "llm_reasoning",
                "trace_role": "thought",
                "trace_group": TRACE_GROUP_QUIZ,
                "question_id": self._template.question_id,
            },
            stream_body_live=False,
        )


# Awaitable re-export so host return types resolve cleanly when callers
# type-check this module in isolation (mirrors solve/pipeline.py).
_ = Awaitable  # type: ignore[assignment]
