"""ResearchPipeline — agentic-engine-based replacement for the legacy
multi-agent ``ResearchPipeline``.

Phase shape:

* **Phase 1 (Rephrase)** — a mini agentic loop over ``THINK`` / ``TOOL``
  / ``FINISH`` whose only available tool is ``ask_user``. Up to 3
  ask_user rounds (each with 1-4 questions on one card). FINISH text
  is the refined research topic. May FINISH early when the user is
  unambiguous.
* **Phase 2 (Decompose)** — one ``OUTLINE`` labeled step turning the
  refined topic into N sub-topics. When ``confirmed_outline=None``
  ResearchPipeline returns the outline and exits so the capability can
  surface it as a preview; the same pipeline is invoked again with
  ``confirmed_outline`` once the user confirms.
* **Phase 3 (Research blocks)** — for each ``TopicBlock`` in the
  dynamic queue, one ``run_agentic_loop`` over ``THINK`` / ``TOOL`` /
  ``APPEND`` / ``FINISH``. ``APPEND`` is an intermediate label that
  mutates the queue (via ``_BlockLoopHost.on_intermediate``). The outer
  scheduler drains the queue in series or parallel; APPEND-added
  blocks naturally get picked up by subsequent batches.
* **Phase 4 (Reporting)** — sequence of one-shot labeled steps:
  ``OUTLINE`` (report structure) → ``INTRO`` → for each section
  ``SECTION`` → ``CONCLUSION`` → assemble. Each emits its own trace
  card and pulls evidence from :class:`CitationManager` for anchor
  injection.

Citations and the dynamic topic queue — the two features that make
deep research distinct — are preserved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
import html
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
from deeptutor.agents.research.data_structures import (
    DynamicTopicQueue,
    ToolTrace,
    TopicBlock,
    TopicStatus,
)
from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.core.agentic import (
    DispatchOutcome,
    LabeledStepResult,
    LabelProtocol,
    LLMClientConfig,
    UsageTracker,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    classify_label,
    dispatch_tool_calls,
    run_agentic_loop,
    run_labeled_step,
)
from deeptutor.core.agentic.tool_dispatch import (
    MAX_PARALLEL_TOOL_CALLS,
)
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


SOURCE = "deep_research"

# Per-block research uses the same shared composition policy as chat
# (``compose_enabled_tools``), then narrows the result to tools that can
# produce evidence for a block-level research summary.
RESEARCH_OPTIONAL_TOOLS: list[str] = default_optional_tools()
RESEARCH_BLOCK_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {"rag", "web_search", "paper_search", "code_execution"}
)

# ---------------------------------------------------------------------------
# Label vocabulary
# ---------------------------------------------------------------------------
LABEL_THINK = "THINK"
LABEL_TOOL = "TOOL"
LABEL_APPEND = "APPEND"
LABEL_FINISH = "FINISH"
LABEL_OUTLINE = "OUTLINE"
LABEL_INTRO = "INTRO"
LABEL_SECTION = "SECTION"
LABEL_CONCLUSION = "CONCLUSION"

# Rephrase loop: agent talks to the user through ``ask_user`` and then
# FINISHes with a refined topic statement.
_PROTOCOL_REPHRASE = LabelProtocol(
    allowed=(LABEL_THINK, LABEL_TOOL, LABEL_FINISH),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset({LABEL_THINK}),
    final=frozenset({LABEL_FINISH}),
    tool_label=LABEL_TOOL,
)

# Decompose: one-shot ``OUTLINE`` payload (JSON list of sub-topics).
_PROTOCOL_DECOMPOSE = LabelProtocol(
    allowed=(LABEL_OUTLINE,),
    terminal=frozenset({LABEL_OUTLINE}),
    intermediate=frozenset(),
    final=frozenset({LABEL_OUTLINE}),
    tool_label=None,
)

# Per-block research: the headline agentic loop. ``APPEND`` is the
# intermediate label that extends the dynamic queue (handled by the
# host's ``on_intermediate`` hook).
_PROTOCOL_BLOCK = LabelProtocol(
    allowed=(LABEL_THINK, LABEL_TOOL, LABEL_APPEND, LABEL_FINISH),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset({LABEL_THINK, LABEL_APPEND}),
    final=frozenset({LABEL_FINISH}),
    tool_label=LABEL_TOOL,
)

# Reporting sub-phases — each is one labeled step with one terminal
# label. Distinct names so the LLM and the trace UI both recognise
# which phase the call belongs to.
_PROTOCOL_REPORT_OUTLINE = LabelProtocol(
    allowed=(LABEL_OUTLINE,),
    terminal=frozenset({LABEL_OUTLINE}),
    intermediate=frozenset(),
    final=frozenset({LABEL_OUTLINE}),
    tool_label=None,
)
_PROTOCOL_REPORT_INTRO = LabelProtocol(
    allowed=(LABEL_INTRO,),
    terminal=frozenset({LABEL_INTRO}),
    intermediate=frozenset(),
    final=frozenset({LABEL_INTRO}),
    tool_label=None,
)
_PROTOCOL_REPORT_SECTION = LabelProtocol(
    allowed=(LABEL_SECTION,),
    terminal=frozenset({LABEL_SECTION}),
    intermediate=frozenset(),
    final=frozenset({LABEL_SECTION}),
    tool_label=None,
)
_PROTOCOL_REPORT_CONCLUSION = LabelProtocol(
    allowed=(LABEL_CONCLUSION,),
    terminal=frozenset({LABEL_CONCLUSION}),
    intermediate=frozenset(),
    final=frozenset({LABEL_CONCLUSION}),
    tool_label=None,
)
_PROTOCOL_ANSWER_NOW = LabelProtocol(
    allowed=(LABEL_FINISH,),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset(),
    final=frozenset({LABEL_FINISH}),
    tool_label=None,
)

# Note Agent — single ``FINISH`` labeled step that compresses a raw tool
# result into a short dense summary for the citation sidecar.
_PROTOCOL_NOTE = LabelProtocol(
    allowed=(LABEL_FINISH,),
    terminal=frozenset({LABEL_FINISH}),
    intermediate=frozenset(),
    final=frozenset({LABEL_FINISH}),
    tool_label=None,
)

# Tools whose results get summarised + recorded in the citation manager.
# Any tool whose results carry source documents / external evidence
# should be added here.
CITABLE_TOOLS: frozenset[str] = frozenset({"rag", "web_search", "paper_search", "code_execution"})

# Token budget for the note summarization sidecar.
DEFAULT_NOTE_MAX_TOKENS = 1500
# How much of the raw tool output we feed into the note summarizer.
NOTE_RAW_INPUT_TRUNCATE_CHARS = 8000

# ---------------------------------------------------------------------------
# Defaults — preserved from the legacy presets so refactor is config-stable.
# ---------------------------------------------------------------------------
DEFAULT_REPHRASE_MAX_ITERATIONS = (
    8  # Inner loop iter cap; ask_user round cap is enforced separately.
)
DEFAULT_REPHRASE_MAX_ROUNDS = 3
DEFAULT_REPHRASE_MAX_QUESTIONS_PER_ROUND = 3
DEFAULT_BLOCK_MAX_ITERATIONS = 5
DEFAULT_BLOCK_MAX_TOKENS = 6000
DEFAULT_OUTLINE_MAX_TOKENS = 2000
DEFAULT_REPORT_OUTLINE_MAX_TOKENS = 2000
DEFAULT_REPORT_INTRO_MAX_TOKENS = 3000
DEFAULT_REPORT_SECTION_MAX_TOKENS = 6000
DEFAULT_REPORT_CONCLUSION_MAX_TOKENS = 3000
DEFAULT_INITIAL_SUBTOPICS = 5
DEFAULT_MAX_PARALLEL_TOPICS = 3
DEFAULT_QUEUE_MAX_LENGTH = 8


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubTopicItem:
    """One entry in the decompose / outline preview output."""

    title: str
    overview: str = ""


@dataclass
class ResearchedBlock:
    """A finished topic block ready for reporting."""

    block: TopicBlock
    knowledge: str  # accumulated FINISH text from the block's agentic loop


@dataclass(frozen=True)
class ReportSectionPlan:
    """Per-section instruction in the report outline."""

    id: str
    title: str
    intent: str  # what this section should cover
    block_ids: tuple[str, ...]  # which TopicBlocks supply evidence


@dataclass(frozen=True)
class ReportOutline:
    title: str
    sections: tuple[ReportSectionPlan, ...]


# ---------------------------------------------------------------------------
# ResearchPipeline
# ---------------------------------------------------------------------------


class ResearchPipeline:
    """One-shot orchestrator: instantiate per turn, call :meth:`run` once.

    The pipeline owns control flow and per-phase prompt assembly; every
    LLM call goes through :mod:`deeptutor.core.agentic` primitives. The
    legacy ``DynamicTopicQueue`` + :class:`CitationManager` are reused
    verbatim as the in-flight scratchpad and citation registry.
    """

    def __init__(
        self,
        *,
        language: str = "en",
        runtime_config: dict[str, Any] | None = None,
        kb_name: str | None = None,
        enabled_tools: list[str] | None = None,
    ) -> None:
        self.language = parse_language(language)
        self.kb_name = (kb_name or "").strip() or None
        self.enabled_tools = list(enabled_tools or [])
        self.runtime_config: dict[str, Any] = dict(runtime_config or {})

        # Read structured policy sub-dicts produced by
        # :func:`build_research_runtime_config`. All keys are best-effort —
        # missing values fall back to module-level defaults so the pipeline
        # also runs against a minimal direct-instantiation in unit tests.
        researching = (
            self.runtime_config.get("researching")
            if isinstance(self.runtime_config.get("researching"), dict)
            else {}
        )
        planning = (
            self.runtime_config.get("planning")
            if isinstance(self.runtime_config.get("planning"), dict)
            else {}
        )
        reporting = (
            self.runtime_config.get("reporting")
            if isinstance(self.runtime_config.get("reporting"), dict)
            else {}
        )
        queue_cfg = (
            self.runtime_config.get("queue")
            if isinstance(self.runtime_config.get("queue"), dict)
            else {}
        )

        self.rephrase_max_iterations = _read_int(
            planning.get("rephrase"),
            key="max_iterations",
            default=DEFAULT_REPHRASE_MAX_ITERATIONS,
        )
        self.rephrase_max_rounds = DEFAULT_REPHRASE_MAX_ROUNDS
        self.rephrase_max_questions_per_round = DEFAULT_REPHRASE_MAX_QUESTIONS_PER_ROUND
        self.rephrase_enabled = bool(
            planning.get("rephrase", {}).get("enabled", True)
            if isinstance(planning.get("rephrase"), dict)
            else True
        )
        self.initial_subtopics = _read_int(
            planning.get("decompose"),
            key="initial_subtopics",
            default=DEFAULT_INITIAL_SUBTOPICS,
        )

        self.block_max_iterations = _read_int(
            researching,
            key="max_iterations",
            default=DEFAULT_BLOCK_MAX_ITERATIONS,
        )
        self.max_parallel_topics = max(
            1,
            _read_int(
                researching,
                key="max_parallel_topics",
                default=DEFAULT_MAX_PARALLEL_TOPICS,
            ),
        )
        self.execution_mode = str(researching.get("execution_mode", "parallel"))
        self.research_mode = str(reporting.get("mode", "report"))

        self.queue_max_length = _read_int(
            queue_cfg, key="max_length", default=DEFAULT_QUEUE_MAX_LENGTH
        )

        # Block-loop tool composition runs through the same shared policy
        # chat uses (``compose_enabled_tools``) — see :meth:`_block_tool_names`.
        # There is no per-source enable_* gating here: the per-block loop
        # sees exactly the user-toggled tools plus auto-mounts (``rag``
        # when a KB is attached). Citations, ``ask_user`` is excluded by
        # the block prompt itself.

        # LLM client setup mirrors solve's pattern so the same engine
        # primitives behave identically across capabilities.
        self.llm_config = get_llm_config()
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.extra_headers = getattr(self.llm_config, "extra_headers", None) or {}
        self.reasoning_effort = getattr(self.llm_config, "reasoning_effort", None)
        self.client_config = LLMClientConfig(
            binding=self.binding,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            extra_headers=self.extra_headers or None,
            reasoning_effort=self.reasoning_effort,
        )

        self.registry = get_tool_registry()
        self.usage = UsageTracker(model=self.model)

        # Default sampling temperature — slightly higher than solve so
        # the research loop can take initiative on APPEND decisions.
        self._temperature = 0.3

        try:
            self._prompts: dict[str, Any] = (
                get_prompt_manager().load_prompts(
                    module_name="research",
                    agent_name="pipeline",
                    language=self.language,
                )
                or {}
            )
        except Exception as exc:
            logger.warning("Failed to load research pipeline prompts: %s", exc)
            self._prompts = {}

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    async def run(
        self,
        *,
        context: UnifiedContext,
        topic: str,
        confirmed_outline: list[SubTopicItem] | None = None,
        attachments: list[Attachment] | None = None,
        stream: StreamBus,
    ) -> dict[str, Any]:
        """Drive the four phases.

        When ``confirmed_outline`` is ``None`` and rephrase + decompose
        complete, the pipeline emits an ``outline_preview`` result and
        returns so the capability can surface the outline for the user
        to edit / confirm. A subsequent call with ``confirmed_outline``
        skips Phase 1+2 (the user already saw the questions and approved
        a structure) and runs Phase 3+4 directly.
        """
        attachments = list(attachments or [])
        image_attachments = [a for a in attachments if getattr(a, "type", "") == "image"]
        client = self._build_client()

        try:
            return await self._run_inner(
                context=context,
                topic=topic,
                image_attachments=image_attachments,
                confirmed_outline=confirmed_outline,
                stream=stream,
                client=client,
            )
        except Exception as exc:
            logger.exception("ResearchPipeline.run failed: %s", exc)
            await self._emit_visible_failure(stream, exc)
            raise

    async def _run_inner(
        self,
        *,
        context: UnifiedContext,
        topic: str,
        image_attachments: list[Attachment],
        confirmed_outline: list[SubTopicItem] | None,
        stream: StreamBus,
        client: Any,
    ) -> dict[str, Any]:
        logger.info(
            "ResearchPipeline.run start: lang=%s kb=%s requested_tools=%s "
            "max_iter/block=%d max_parallel=%d",
            self.language,
            self.kb_name,
            self.enabled_tools,
            self.block_max_iterations,
            self.max_parallel_topics,
        )

        # ----- Phase 1 + Phase 2 (planning) — skipped when an outline is
        # already confirmed so the user isn't asked clarifying questions a
        # second time on the same logical research task.
        if confirmed_outline is None:
            async with stream.stage("rephrasing", source=SOURCE):
                refined_topic = (
                    await self._rephrase(
                        topic=topic,
                        context=context,
                        image_attachments=image_attachments,
                        stream=stream,
                        client=client,
                    )
                    if self.rephrase_enabled
                    else topic.strip()
                )

            async with stream.stage(
                "decomposing",
                source=SOURCE,
                metadata={"research_status_key": "decompose_target"},
            ):
                outline = await self._decompose(
                    topic=refined_topic,
                    context=context,
                    image_attachments=image_attachments,
                    stream=stream,
                    client=client,
                )

            # Flat top-level keys: ``stream.result(data)`` merges ``data``
            # into the event's ``metadata`` field, and the frontend reads
            # ``event.metadata.outline_preview`` (not ``…metadata.metadata.…``).
            #
            # No ``stream.result`` here — the capability emits a single
            # result event after augmenting this payload with
            # ``research_config`` (which the frontend needs to send back
            # on confirm). Emitting here too would land first and the
            # frontend's ``find(type="result")`` would pick this one,
            # leaving ``research_config`` undefined.
            preview_payload: dict[str, Any] = {
                "response": "",
                "output_dir": "",
                "outline_preview": True,
                "topic": refined_topic,
                "sub_topics": [{"title": st.title, "overview": st.overview} for st in outline],
            }
            return preview_payload

        # ----- Phase 3 (research blocks) -----
        refined_topic = topic.strip()
        queue = DynamicTopicQueue(
            f"research_{context.session_id or 'adhoc'}",
            max_length=self.queue_max_length,
        )
        citations = CitationManager(queue.research_id, cache_dir=None)
        for sub in confirmed_outline:
            queue.add_block(sub.title, sub.overview)

        async with stream.stage("researching", source=SOURCE):
            researched = await self._drive_queue(
                queue=queue,
                citations=citations,
                topic=refined_topic,
                context=context,
                image_attachments=image_attachments,
                stream=stream,
                client=client,
            )

        # A planned block that didn't reach COMPLETED (raised, or exhausted its
        # iteration budget without a FINISH) is backfilled with empty knowledge
        # so the surviving blocks can still produce a useful report. But the run
        # must not then look like a clean success — surface the shortfall both
        # visibly (a warning notice) and in the result envelope so callers can
        # tell the report is partial (issue #595).
        incomplete = [rb for rb in researched if rb.block.status != TopicStatus.COMPLETED]
        failed_block_titles = [rb.block.sub_topic for rb in incomplete]
        if incomplete:
            logger.warning(
                "Deep Research partial: %d/%d blocks did not complete: %s",
                len(incomplete),
                len(researched),
                failed_block_titles,
            )
            await stream.progress(
                self._t(
                    "notices.partial_results",
                    default=(
                        "{failed} of {total} research subtopics could not be completed; "
                        "the report is based on the remaining evidence."
                    ),
                    failed=len(incomplete),
                    total=len(researched),
                ),
                source=SOURCE,
                stage="researching",
                metadata={"trace_kind": "warning"},
            )

        # ----- Phase 4 (iterative reporting) -----
        async with stream.stage(
            "reporting",
            source=SOURCE,
            metadata={
                "research_status_key": "report_outline",
                "report_part": "outline",
            },
        ):
            report_text = await self._write_report(
                topic=refined_topic,
                blocks=researched,
                citations=citations,
                stream=stream,
                client=client,
            )

        result_payload: dict[str, Any] = {
            "response": report_text,
            "output_dir": "",
            "metadata": {
                "mode": "agentic_research",
                "topic": refined_topic,
                "block_count": len(researched),
                "citation_count": len(citations.get_all_citations()),
                "partial": bool(incomplete),
                "failed_block_count": len(incomplete),
                "failed_block_titles": failed_block_titles,
            },
        }
        await emit_capability_result(stream, result_payload, source=SOURCE, usage=self.usage)
        return result_payload

    async def _emit_visible_failure(self, stream: StreamBus, exc: BaseException) -> None:
        """Surface a runtime exception as a labelled error trace card so the
        user sees what went wrong instead of an empty assistant message."""
        call_id = new_call_id("research-failure")
        meta = build_trace_metadata(
            call_id=call_id,
            phase="researching",
            label=self._t("labels.research_step", default="Research step"),
            call_kind="llm_final_response",
            trace_id=call_id,
            trace_role="response",
            trace_group="stage",
        )
        message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        await stream.error(
            message,
            source=SOURCE,
            stage="researching",
            metadata=merge_trace_metadata(meta, {"trace_kind": "error"}),
        )
        prefix = self._t("system.warning_prefix", default="⚠ ")
        await stream.content(
            f"{prefix}{message}",
            source=SOURCE,
            stage="researching",
            metadata=merge_trace_metadata(meta, {"trace_kind": "llm_output"}),
        )

    # ------------------------------------------------------------------
    # Phase 1: rephrase
    # ------------------------------------------------------------------
    async def _rephrase(
        self,
        *,
        topic: str,
        context: UnifiedContext,
        image_attachments: list[Attachment] | None = None,
        stream: StreamBus,
        client: Any,
    ) -> str:
        """Mini agentic loop over ``THINK / TOOL / FINISH`` with only
        ``ask_user`` exposed.

        The host (``_RephraseLoopHost``) enforces the round cap, rejects
        any non-``ask_user`` tool call inline, and routes pause/resume
        through the runtime-supplied ``wait_for_user_reply``. When the
        LLM emits ``FINISH`` the post-label text is the refined topic.
        If the loop exits without a valid FINISH (e.g. ``ask_user`` is
        not available, or the LLM bails early) the original topic is
        returned unchanged so the rest of the pipeline can proceed.
        """
        if not self._tool_in_registry("ask_user"):
            return topic.strip()

        system_prompt = self._t(
            "rephrase.system",
            max_rounds=self.rephrase_max_rounds,
            max_questions_per_round=self.rephrase_max_questions_per_round,
            topic=topic,
        )
        user_prompt = self._t("rephrase.user_template", topic=topic)
        messages = self._build_system_user_messages(
            system_prompt, user_prompt, image_attachments=image_attachments
        )

        tool_names = ["ask_user"]
        tool_schemas = (
            self.registry.build_openai_schemas(tool_names)
            if can_use_native_tool_calling(binding=self.binding, model=self.model)
            else None
        )

        host = _RephraseLoopHost(
            pipeline=self,
            stream=stream,
            context=context,
            client=client,
            max_rounds=self.rephrase_max_rounds,
        )
        try:
            outcome = await run_agentic_loop(
                initial_messages=messages,
                protocol=_PROTOCOL_REPHRASE,
                client=client,
                model=self.model,
                completion_kwargs=self._completion_kwargs(DEFAULT_BLOCK_MAX_TOKENS),
                binding=self.binding,
                tool_schemas=tool_schemas,
                stream=stream,
                source=SOURCE,
                stage="rephrasing",
                max_iterations=self.rephrase_max_iterations,
                host=host,
                usage=self.usage,
                # FINISH text is the model's brief user-facing confirmation
                # of what it's about to research — stream it live to the
                # chat bubble body so the user sees the summary forming
                # before the outline editor appears. It also doubles as
                # the refined topic input for the decompose phase.
                stream_body_live=True,
                # Lazy sub-trace open so the FINISH iteration (which
                # streams to the chat body, not into a reasoning card)
                # doesn't leave a near-empty "Reasoning" card behind.
                # THINK iters still get a card the moment their first
                # thinking chunk arrives.
                eager_sub_trace=False,
            )
        except Exception as exc:
            logger.warning("Rephrase loop failed; falling back to raw topic: %s", exc)
            return topic.strip()

        refined = (outcome.final_text or "").strip()
        return refined or topic.strip()

    # ------------------------------------------------------------------
    # Phase 2: decompose
    # ------------------------------------------------------------------
    async def _decompose(
        self,
        *,
        topic: str,
        context: UnifiedContext,
        image_attachments: list[Attachment] | None = None,
        stream: StreamBus,
        client: Any,
    ) -> list[SubTopicItem]:
        """One-shot ``OUTLINE`` labeled step.

        The LLM is asked to emit a JSON array of ``{title, overview}``
        objects (any object with a ``title`` field is accepted). Parsing
        is lenient — if JSON parse fails, the topic itself becomes the
        single fallback sub-topic so the pipeline can still drive the
        outline-preview UX.
        """
        system_prompt = self._t("decompose.system")
        user_prompt = self._t(
            "decompose.user_template",
            topic=topic,
            num_subtopics=self.initial_subtopics,
        )
        messages = self._build_system_user_messages(
            system_prompt, user_prompt, image_attachments=image_attachments
        )
        iter_meta = self._build_simple_trace_meta(
            call_id_root="research-decompose",
            label=self._t("labels.decompose", default="Decompose"),
            stage="decomposing",
            call_kind="llm_planning",
            trace_role="plan",
            trace_group="plan",
            research_status_key="decompose_target",
        )
        step = await self._run_labeled_step(
            client=client,
            messages=messages,
            tool_schemas=None,
            protocol=_PROTOCOL_DECOMPOSE,
            stream=stream,
            stage="decomposing",
            iter_meta=iter_meta,
            max_tokens=DEFAULT_OUTLINE_MAX_TOKENS,
            eager_sub_trace=False,
        )
        return self._parse_outline(topic, step.text)

    def _parse_outline(self, topic: str, raw: str) -> list[SubTopicItem]:
        data = parse_json_response(raw, logger_instance=logger, fallback={})
        if isinstance(data, list):
            iterable: list[Any] = data
        elif isinstance(data, dict):
            iterable = list(data.get("sub_topics") or data.get("subtopics") or [])
        else:
            iterable = []

        items: list[SubTopicItem] = []
        for entry in iterable:
            if isinstance(entry, dict):
                title = str(entry.get("title") or entry.get("topic") or "").strip()
                overview = str(entry.get("overview") or entry.get("description") or "").strip()
            elif isinstance(entry, str):
                title = entry.strip()
                overview = ""
            else:
                continue
            if title:
                items.append(SubTopicItem(title=title, overview=overview))
            if len(items) >= self.initial_subtopics:
                break
        if not items:
            items = [SubTopicItem(title=topic, overview="")]
        return items

    # ------------------------------------------------------------------
    # Phase 3: research one block
    # ------------------------------------------------------------------
    async def _research_block(
        self,
        *,
        block: TopicBlock,
        queue: DynamicTopicQueue,
        citations: CitationManager,
        topic: str,
        context: UnifiedContext,
        stream: StreamBus,
        client: Any,
    ) -> ResearchedBlock:
        """Run one block of the dynamic research queue through an agentic
        loop with the ``THINK`` / ``TOOL`` / ``APPEND`` / ``FINISH``
        protocol. ``FINISH``'s post-label text becomes the block's
        consolidated knowledge for the report layer; ``APPEND`` triggers
        a queue mutation via :meth:`_BlockLoopHost.on_intermediate`.
        """
        queue.mark_researching(block.block_id)

        block_tool_names = self._block_tool_names()
        native_block_tools = self._use_native_block_tools(block_tool_names)
        prompt_tool_names = block_tool_names if native_block_tools else []
        effective_max_iterations = (
            max(self.block_max_iterations, 4) if prompt_tool_names else self.block_max_iterations
        )
        tool_schemas = (
            self._build_block_tool_schemas(prompt_tool_names) if native_block_tools else None
        )
        tool_list = (
            self.registry.build_prompt_text(
                prompt_tool_names,
                format="list_with_usage",
                language=self.language,
            )
            or self._fallback_empty_tool_list()
        )
        kb_note = self._kb_system_note()

        system_prompt = self._t(
            "research_step.system",
            topic=topic,
            block_title=block.sub_topic,
            block_overview=block.overview or "(no overview)",
            mode=self.research_mode,
            max_iterations=effective_max_iterations,
            kb_note=kb_note,
            tool_list=tool_list,
        )
        system_prompt = append_language_directive(system_prompt, self.language)

        sibling_topics = self._render_sibling_topics(queue, block)
        user_prompt = self._t(
            "research_step.user_template",
            accumulated_knowledge=self._t(
                "empty.no_evidence", default="(no evidence collected yet)"
            ),
            sibling_topics=sibling_topics,
        )
        messages = self._build_system_user_messages(system_prompt, user_prompt)

        host = _BlockLoopHost(
            pipeline=self,
            block=block,
            queue=queue,
            citations=citations,
            topic=topic,
            stream=stream,
            context=context,
            client=client,
        )
        try:
            outcome = await run_agentic_loop(
                initial_messages=messages,
                protocol=_PROTOCOL_BLOCK,
                client=client,
                model=self.model,
                completion_kwargs=self._completion_kwargs(DEFAULT_BLOCK_MAX_TOKENS),
                binding=self.binding,
                tool_schemas=tool_schemas,
                stream=stream,
                source=SOURCE,
                stage="researching",
                max_iterations=effective_max_iterations,
                host=host,
                usage=self.usage,
                stream_body_live=False,
                eager_sub_trace=True,
            )
        except Exception as exc:
            logger.exception("Research block %s failed: %s", block.block_id, exc)
            queue.mark_failed(block.block_id)
            return ResearchedBlock(block=block, knowledge="")

        knowledge = (outcome.final_text or "").strip()
        if outcome.completed:
            queue.mark_completed(block.block_id)
        else:
            queue.mark_failed(block.block_id)
        block.iteration_count = outcome.iterations
        return ResearchedBlock(block=block, knowledge=knowledge)

    async def _force_finish_block(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        stream: StreamBus,
        start_iteration: int,
        block: TopicBlock,
    ) -> tuple[str, bool, int]:
        """Per-block ``LoopHost.force_finalize`` recovery: prompt the model
        to emit a final ``FINISH`` consolidating what was learned so far,
        with a small retry budget for protocol-repair attempts."""
        calls = 0
        messages.append({"role": "user", "content": self._t("protocol.force_finish")})
        await stream.progress(
            self._t("notices.max_iterations_reached", default="Max iterations reached."),
            source=SOURCE,
            stage="researching",
            metadata={"trace_kind": "warning"},
        )
        for attempt in range(3):
            iter_meta = self._build_simple_trace_meta(
                call_id_root=f"research-{block.block_id}-force-{start_iteration + attempt}",
                label=self._t("labels.reasoning", default="Reasoning"),
                stage="researching",
                block_id=block.block_id,
                **_research_topic_status_meta(block),
            )
            result = await self._run_labeled_step(
                client=client,
                messages=messages,
                tool_schemas=None,
                protocol=LabelProtocol(
                    allowed=(LABEL_FINISH,),
                    terminal=frozenset({LABEL_FINISH}),
                    intermediate=frozenset(),
                    final=frozenset({LABEL_FINISH}),
                    tool_label=None,
                ),
                stream=stream,
                stage="researching",
                iter_meta=iter_meta,
            )
            calls += 1
            if result.label == LABEL_FINISH and result.text.strip():
                return result.text, True, calls
            messages.append({"role": "assistant", "content": result.text[:500]})
            messages.append({"role": "user", "content": self._t("protocol.force_finish_repair")})
        return self._t("protocol.fallback_final"), False, calls

    # ------------------------------------------------------------------
    # Per-block rendering helpers
    # ------------------------------------------------------------------
    def _render_sibling_topics(self, queue: DynamicTopicQueue, current_block: TopicBlock) -> str:
        """Compact list of other topics in the queue so APPEND can dedup
        against them at prompt-time (in addition to the runtime check)."""
        siblings = [
            f"  - [{b.block_id}] {b.sub_topic}"
            for b in queue.blocks
            if b.block_id != current_block.block_id
        ]
        if not siblings:
            return self._t("empty.no_subtopics", default="(none)")
        return "\n".join(siblings)

    def _kb_system_note(self) -> str:
        if not self.kb_name:
            return ""
        return self._t(
            "system.kb_system_note",
            default=(
                f"Attached knowledge bases: {self.kb_name}. When calling rag, "
                f"kb_name must be {self.kb_name!r}."
            ),
            kb_name=self.kb_name,
            kb_name_repr=repr(self.kb_name),
        )

    def _fallback_empty_tool_list(self) -> str:
        return self._t("empty.no_tools", default="- none")

    # ------------------------------------------------------------------
    # Phase 4: reporting
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Queue scheduler — drains the dynamic topic queue. Series vs.
    # parallel selected from ``researching.execution_mode``.
    # ------------------------------------------------------------------
    async def _drive_queue(
        self,
        *,
        queue: DynamicTopicQueue,
        citations: CitationManager,
        topic: str,
        context: UnifiedContext,
        image_attachments: list[Attachment] | None,
        stream: StreamBus,
        client: Any,
    ) -> list[ResearchedBlock]:
        researched_by_id: dict[str, ResearchedBlock] = {}
        rounds = 0
        safety_cap = max(20, (self.queue_max_length or 0) * 4)

        while True:
            pending = queue.get_all_pending_blocks()
            if not pending:
                break
            batch_size = (
                1 if str(self.execution_mode).lower() == "series" else self.max_parallel_topics
            )
            batch = pending[:batch_size]
            results = await asyncio.gather(
                *[
                    self._research_block(
                        block=block,
                        queue=queue,
                        citations=citations,
                        topic=topic,
                        context=context,
                        stream=stream,
                        client=client,
                    )
                    for block in batch
                ],
                return_exceptions=True,
            )
            for block, result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    logger.exception("Block %s research failed: %s", block.block_id, result)
                    if block.status == TopicStatus.RESEARCHING:
                        queue.mark_failed(block.block_id)
                    researched_by_id[block.block_id] = ResearchedBlock(block=block, knowledge="")
                    continue
                researched_by_id[block.block_id] = result

            rounds += 1
            if rounds > safety_cap:
                logger.warning(
                    "Research scheduler aborted after %d rounds — queue size %d",
                    rounds,
                    len(queue.blocks),
                )
                break

        # Preserve queue order so parents come before APPENDed children.
        ordered: list[ResearchedBlock] = []
        for block in queue.blocks:
            ordered.append(
                researched_by_id.get(block.block_id) or ResearchedBlock(block=block, knowledge="")
            )
        return ordered

    # ------------------------------------------------------------------
    # Note-agent sidecar — summarise + record citation for one tool call.
    # ------------------------------------------------------------------
    async def _summarise_tool_result(
        self,
        *,
        tool_name: str,
        query: str,
        raw_answer: str,
        client: Any,
    ) -> str:
        """One LLM call per citable tool result: condense long retrievals
        into a short, citation-ready summary. Failures fall back to a
        leading slice of the raw answer so the loop never stalls on a
        flaky summariser call.
        """
        cleaned = (raw_answer or "").strip()
        if not cleaned:
            return ""
        system_prompt = self._t("note.system")
        user_prompt = self._t(
            "note.user_template",
            tool_name=tool_name,
            query=query,
            raw_answer=cleaned[:NOTE_RAW_INPUT_TRUNCATE_CHARS],
        )
        messages = self._build_system_user_messages(system_prompt, user_prompt)
        try:
            kwargs = self._completion_kwargs(DEFAULT_NOTE_MAX_TOKENS)
            response = await client.chat.completions.create(
                model=self.model, messages=messages, stream=False, **kwargs
            )
            content = (response.choices[0].message.content if response.choices else "") or ""
            parsed = classify_label(
                content,
                allowed_labels=(LABEL_FINISH,),
                final=True,
            )
            if parsed is not None:
                _label, content = parsed
            return content.strip() or cleaned[:600]
        except Exception as exc:
            logger.warning("Note summarisation failed (%s): %s", tool_name, exc)
            return cleaned[:600]

    # ------------------------------------------------------------------
    # Phase 4: iterative reporting
    #
    # Each sub-phase is one labeled step:
    #   _gen_report_outline → _write_intro → for sec: _write_section →
    #   _write_conclusion. Bodies stream live (``stream_body_live``)
    #   chunk-by-chunk for the section-level steps so the user sees the
    #   report assemble in real time.
    # ------------------------------------------------------------------
    async def _write_report(
        self,
        *,
        topic: str,
        blocks: list[ResearchedBlock],
        citations: CitationManager,
        stream: StreamBus,
        client: Any,
    ) -> str:
        outline = await self._gen_report_outline(
            topic=topic,
            blocks=blocks,
            citations=citations,
            stream=stream,
            client=client,
        )

        # Global numbering: introduction is 1, sub-topic sections are 2..N+1,
        # conclusion is N+2 (where N == len(outline.sections)). Both the
        # rendered ``##`` heading and any ``### N.x`` subsection prefixes the
        # LLM emits reference these numbers, so we resolve them here and pass
        # them into every report-writing step.
        section_count = len(outline.sections)
        conclusion_number = section_count + 2

        section_texts: list[str] = []

        # Emit the report's H1 title before the introduction so the rendered
        # markdown opens with the report name, then the numbered ``## 1.``
        # Introduction heading. The LLM is not asked to write the title — we
        # already have it on the outline.
        title_block = self._render_report_title_block(outline.title)
        if title_block:
            await stream.content(
                title_block,
                source=SOURCE,
                stage="reporting",
                metadata={"trace_kind": "report_title"},
            )
            section_texts.append(title_block)

        intro = await self._write_intro(topic=topic, outline=outline, stream=stream, client=client)
        if intro:
            if section_texts:
                await self._stream_report_separator(stream)
            section_texts.append(intro)

        section_bodies: list[str] = []
        for section_index, section in enumerate(outline.sections, start=1):
            if section_texts:
                await self._stream_report_separator(stream)
            body = await self._write_section(
                section=section,
                section_index=section_index,
                section_count=section_count,
                section_number=section_index + 1,
                topic=topic,
                outline=outline,
                blocks=blocks,
                citations=citations,
                stream=stream,
                client=client,
            )
            if body:
                section_texts.append(body)
                section_bodies.append(body)

        if section_texts:
            await self._stream_report_separator(stream)
        conclusion = await self._write_conclusion(
            topic=topic,
            outline=outline,
            section_bodies=section_bodies,
            section_number=conclusion_number,
            stream=stream,
            client=client,
        )
        if conclusion:
            section_texts.append(conclusion)

        body = self._normalise_report_markdown(
            "\n\n".join(part for part in section_texts if part.strip()),
            citations,
        )
        used_citation_ids = _citation_ids_in_first_appearance(body, citations)
        citation_numbers = {
            citation_id: index for index, citation_id in enumerate(used_citation_ids, start=1)
        }
        body = self._linkify_report_citations(body, citations, citation_numbers=citation_numbers)
        references = self._render_reference_list(
            citations,
            citation_ids=used_citation_ids,
            citation_numbers=citation_numbers,
        )
        if references:
            await self._stream_report_separator(stream)
            await stream.content(
                references,
                source=SOURCE,
                stage="reporting",
                metadata={"trace_kind": "reference_list"},
            )
        return "\n\n".join(part for part in (body, references) if part.strip())

    def _render_reference_list(
        self,
        citations: CitationManager,
        *,
        citation_ids: list[str] | None = None,
        citation_numbers: dict[str, int] | None = None,
    ) -> str:
        """Append a collapsible reference appendix with stable anchors.

        Numbering follows first appearance in the final report body. That
        keeps body links and the appendix compact even when research collected
        additional tool traces that did not survive synthesis.
        """
        entries = []
        ordered_ids = citation_ids if citation_ids is not None else _sorted_citation_ids(citations)
        numbers = citation_numbers or {
            citation_id: index for index, citation_id in enumerate(ordered_ids, start=1)
        }
        for citation_id in ordered_ids:
            formatted = self._format_reference_entry(citations, citation_id)
            if formatted:
                anchor = _citation_anchor_id(citation_id)
                ref_number = numbers.get(citation_id, len(entries) + 1)
                entries.append(
                    f'<li id="{anchor}" data-citation-id="{html.escape(citation_id)}">'
                    f'<span data-ref-number="{ref_number}">{formatted}</span>'
                    "</li>"
                )
        if not entries:
            return ""
        heading = self._t("labels.references_heading", default="References")
        return (
            '<details id="references" open>\n'
            f"<summary>{heading}</summary>\n"
            "<ol>\n" + "\n".join(entries) + "\n</ol>\n"
            "</details>"
        )

    def _linkify_report_citations(
        self,
        text: str,
        citations: CitationManager,
        *,
        citation_numbers: dict[str, int] | None = None,
    ) -> str:
        """Turn generated ``[CIT-...]`` markers into same-page anchor links.

        The section writer is intentionally instructed to copy plain markers,
        because that is easier for models to follow. This renderer pass makes
        the final persisted Markdown navigable without asking the model to
        manufacture link syntax.
        """
        numbers = citation_numbers or _citation_number_map(citations)
        if not text or not numbers:
            return text

        def _replace(match: re.Match[str]) -> str:
            citation_id = match.group("id")
            ref_number = numbers.get(citation_id)
            if ref_number is None:
                return ""
            return _citation_markdown_link(citation_id, ref_number)

        return _REPORT_CITATION_MARKER_RE.sub(_replace, text)

    def _normalise_report_markdown(
        self,
        text: str,
        citations: CitationManager,
    ) -> str:
        """Clean model-authored report markdown before persistence.

        The report writer is instructed to copy raw ``[CIT-...]`` markers,
        but models sometimes pre-link them or repeat heading markers. This
        pass converts pre-linked markers back to canonical form, strips
        unknown citation ids, and normalises duplicate headings like
        ``## ## Title``.
        """
        if not text:
            return ""
        known = set(citations.get_all_citations())

        def _replace_link(match: re.Match[str]) -> str:
            citation_id = match.group("id")
            return f"[{citation_id}]" if citation_id in known else ""

        cleaned = _REPORT_CITATION_LINK_RE.sub(_replace_link, text)

        def _replace_bare(match: re.Match[str]) -> str:
            citation_id = match.group("id")
            return match.group(0) if citation_id in known else ""

        cleaned = _REPORT_CITATION_MARKER_RE.sub(_replace_bare, cleaned)
        return _normalise_markdown_headings(cleaned).strip()

    def _format_reference_entry(
        self,
        citations: CitationManager,
        citation_id: str,
    ) -> str | None:
        """Return a reference-list entry as HTML-safe HTML.

        ``CitationManager.format_citation_for_report`` already produces escaped
        HTML for known tool types; the fallback path below also escapes
        user-controlled fields so the caller can drop the result into the page
        without re-escaping.
        """
        formatted = citations.format_citation_for_report(citation_id)
        if formatted:
            return formatted
        citation = citations.get_citation(citation_id)
        if not citation:
            return None
        tool = str(citation.get("tool_type") or "tool")
        query = str(citation.get("query") or "").strip()
        summary = str(citation.get("summary") or "").strip()
        parts = [html.escape(tool.replace("_", " ").title())]
        if query:
            parts.append(f"query: {html.escape(query)}")
        if summary:
            parts.append(f"note: {html.escape(summary[:180])}")
        return " — ".join(parts)

    async def _stream_report_separator(self, stream: StreamBus) -> None:
        await stream.content("\n\n", source=SOURCE, stage="reporting")

    def _render_report_title_block(self, title: str) -> str:
        """Build the ``# <title>`` H1 block emitted before the introduction.

        Strips any leading ``#`` the model may have left on the outline title
        so the rendered output is always a single H1 line.
        """
        clean = _clean_report_heading_text(title or "").strip()
        if not clean:
            return ""
        return f"# {clean}"

    async def _gen_report_outline(
        self,
        *,
        topic: str,
        blocks: list[ResearchedBlock],
        citations: CitationManager,
        stream: StreamBus,
        client: Any,
    ) -> ReportOutline:
        """One ``OUTLINE`` labeled step that proposes the report sections.

        The model sees the topic + each researched block's title and a
        short knowledge snippet, then emits a JSON ``{title, sections:
        [{id, title, intent, block_ids}]}`` payload mapping each
        section to one or more blocks that supply its evidence.
        """
        block_summaries = []
        for rb in blocks:
            preview = (rb.knowledge or "").strip().split("\n\n")[0][:400]
            block_summaries.append(f"- [{rb.block.block_id}] {rb.block.sub_topic}\n  {preview}")
        system_prompt = self._t("report.outline.system")
        user_prompt = self._t(
            "report.outline.user_template",
            topic=topic,
            block_summaries="\n".join(block_summaries) or "(no researched blocks)",
        )
        messages = self._build_system_user_messages(system_prompt, user_prompt)
        iter_meta = self._build_simple_trace_meta(
            call_id_root="research-report-outline",
            label=self._t("labels.report_outline", default="Report outline"),
            stage="reporting",
            call_kind="llm_planning",
            trace_role="plan",
            trace_group="plan",
            research_status_key="report_outline",
            report_part="outline",
        )
        step = await self._run_labeled_step(
            client=client,
            messages=messages,
            tool_schemas=None,
            protocol=_PROTOCOL_REPORT_OUTLINE,
            stream=stream,
            stage="reporting",
            iter_meta=iter_meta,
            max_tokens=DEFAULT_REPORT_OUTLINE_MAX_TOKENS,
            eager_sub_trace=False,
        )
        return self._parse_report_outline(topic, step.text, blocks)

    def _parse_report_outline(
        self, topic: str, raw: str, blocks: list[ResearchedBlock]
    ) -> ReportOutline:
        data = parse_json_response(raw, logger_instance=logger, fallback={})
        valid_ids = {rb.block.block_id for rb in blocks}
        title_to_id = {rb.block.sub_topic.lower(): rb.block.block_id for rb in blocks}

        if isinstance(data, dict):
            title = _clean_report_heading_text(str(data.get("title") or topic)) or topic
            raw_sections = data.get("sections") or []
        elif isinstance(data, list):
            title = _clean_report_heading_text(topic) or topic
            raw_sections = data
        else:
            title = _clean_report_heading_text(topic) or topic
            raw_sections = []

        sections: list[ReportSectionPlan] = []
        for i, item in enumerate(raw_sections if isinstance(raw_sections, list) else []):
            if not isinstance(item, dict):
                continue
            sec_title = _clean_report_heading_text(str(item.get("title") or ""))
            if not sec_title:
                continue
            sec_id = str(item.get("id") or f"R{i + 1}").strip() or f"R{i + 1}"
            intent = str(item.get("intent") or item.get("summary") or "").strip()
            raw_block_ids = item.get("block_ids") or item.get("blocks") or []
            resolved_ids: list[str] = []
            if isinstance(raw_block_ids, list):
                for entry in raw_block_ids:
                    if not isinstance(entry, str):
                        continue
                    if entry in valid_ids:
                        resolved_ids.append(entry)
                    else:
                        bid = title_to_id.get(entry.strip().lower())
                        if bid:
                            resolved_ids.append(bid)
            sections.append(
                ReportSectionPlan(
                    id=sec_id,
                    title=sec_title,
                    intent=intent,
                    block_ids=tuple(resolved_ids),
                )
            )
        if not sections:
            # Fallback: one section per researched block in queue order.
            for rb in blocks:
                sections.append(
                    ReportSectionPlan(
                        id=rb.block.block_id,
                        title=rb.block.sub_topic,
                        intent=rb.block.overview or "",
                        block_ids=(rb.block.block_id,),
                    )
                )
        sections = self._repair_report_section_coverage(sections, blocks)
        return ReportOutline(title=title, sections=tuple(sections))

    def _repair_report_section_coverage(
        self,
        sections: list[ReportSectionPlan],
        blocks: list[ResearchedBlock],
    ) -> list[ReportSectionPlan]:
        """Make report planning robust to partial / invalid block maps.

        The prompt asks the model to map every researched block into at
        least one report section, but outline JSON is still model output.
        This deterministic pass keeps the report from silently dropping a
        block when the LLM omits its id, misspells it, or leaves a section
        with an empty ``block_ids`` list.
        """
        if not sections or not blocks:
            return sections

        valid_ids = {rb.block.block_id for rb in blocks}
        covered: set[str] = set()
        repaired: list[ReportSectionPlan] = []

        for section in sections:
            ids = tuple(dict.fromkeys(bid for bid in section.block_ids if bid in valid_ids))
            if not ids:
                best = _best_block_for_section(section, blocks, exclude=covered)
                if best is not None:
                    ids = (best.block.block_id,)
            covered.update(ids)
            repaired.append(_section_with_block_ids(section, ids))

        missing = [rb for rb in blocks if rb.block.block_id not in covered]
        if not missing:
            return repaired

        addendum: list[str] = []
        for rb in missing:
            section_index = _best_section_for_block(rb, repaired)
            if section_index is None:
                addendum.append(rb.block.block_id)
                continue
            section = repaired[section_index]
            repaired[section_index] = _section_with_block_ids(
                section,
                tuple(dict.fromkeys((*section.block_ids, rb.block.block_id))),
            )

        if addendum:
            addendum_title = self._t("labels.addendum_title", default="Additional findings")
            addendum_intent = self._t(
                "labels.addendum_intent",
                default=(
                    "Covers researched blocks that did not fit cleanly into the earlier sections."
                ),
            )
            repaired.append(
                ReportSectionPlan(
                    id=f"S{len(repaired) + 1}",
                    title=addendum_title,
                    intent=addendum_intent,
                    block_ids=tuple(addendum),
                )
            )
        return repaired

    async def _write_intro(
        self,
        *,
        topic: str,
        outline: ReportOutline,
        stream: StreamBus,
        client: Any,
    ) -> str:
        system_prompt = self._t("report.intro.system", section_number=1)
        user_prompt = self._t(
            "report.intro.user_template",
            topic=topic,
            title=outline.title,
            section_number=1,
            sections_overview="\n".join(
                f"- {s.title}: {s.intent}".rstrip(": ") for s in outline.sections
            ),
        )
        return await self._stream_report_step(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            protocol=_PROTOCOL_REPORT_INTRO,
            stream=stream,
            client=client,
            label=self._t("labels.report_intro", default="Introduction"),
            call_id_root="research-report-intro",
            max_tokens=DEFAULT_REPORT_INTRO_MAX_TOKENS,
            extra_meta={
                "research_status_key": "report_intro",
                "report_part": "intro",
            },
        )

    async def _write_section(
        self,
        *,
        section: ReportSectionPlan,
        section_index: int,
        section_count: int,
        section_number: int,
        topic: str,
        outline: ReportOutline,
        blocks: list[ResearchedBlock],
        citations: CitationManager,
        stream: StreamBus,
        client: Any,
    ) -> str:
        evidence = self._render_section_evidence(
            section=section, blocks=blocks, citations=citations
        )
        system_prompt = self._t("report.section.system", section_number=section_number)
        user_prompt = self._t(
            "report.section.user_template",
            topic=topic,
            report_title=outline.title,
            section_id=section.id,
            section_title=section.title,
            section_intent=section.intent or "(no extra guidance)",
            section_number=section_number,
            evidence=evidence,
        )
        return await self._stream_report_step(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            protocol=_PROTOCOL_REPORT_SECTION,
            stream=stream,
            client=client,
            label=(f"{self._t('labels.report_section', default='Section')}: {section.title}"),
            call_id_root=f"research-report-section-{section.id}",
            max_tokens=DEFAULT_REPORT_SECTION_MAX_TOKENS,
            extra_meta={
                "research_status_key": "report_section",
                "report_part": "section",
                "section_index": section_index,
                "section_count": section_count,
                "section_title": section.title,
            },
        )

    async def _write_conclusion(
        self,
        *,
        topic: str,
        outline: ReportOutline,
        section_bodies: list[str],
        section_number: int,
        stream: StreamBus,
        client: Any,
    ) -> str:
        # Recap: first paragraph of each rendered sub-topic section so the
        # conclusion writer can land the answer without re-reading the full
        # raw evidence. ``section_bodies`` contains only the middle sections
        # (title block and intro are intentionally excluded).
        recap_chunks: list[str] = []
        for sec, body in zip(outline.sections, section_bodies, strict=False):
            snippet = (body or "").strip().split("\n\n", 1)[0]
            recap_chunks.append(f"### {sec.title}\n{snippet[:300]}")
        system_prompt = self._t("report.conclusion.system", section_number=section_number)
        user_prompt = self._t(
            "report.conclusion.user_template",
            topic=topic,
            title=outline.title,
            section_number=section_number,
            sections_recap="\n\n".join(recap_chunks) or "(no section bodies)",
        )
        return await self._stream_report_step(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            protocol=_PROTOCOL_REPORT_CONCLUSION,
            stream=stream,
            client=client,
            label=self._t("labels.report_conclusion", default="Conclusion"),
            call_id_root="research-report-conclusion",
            max_tokens=DEFAULT_REPORT_CONCLUSION_MAX_TOKENS,
            extra_meta={
                "research_status_key": "report_conclusion",
                "report_part": "conclusion",
            },
        )

    async def _stream_report_step(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        protocol: LabelProtocol,
        stream: StreamBus,
        client: Any,
        label: str,
        call_id_root: str,
        max_tokens: int,
        extra_meta: dict[str, Any] | None = None,
    ) -> str:
        """Common runner for the four report sub-phases: one labeled step
        with body streaming live to the chat bubble + a sub-trace card."""
        messages = self._build_system_user_messages(system_prompt, user_prompt)
        trace_extra = dict(extra_meta or {})
        iter_meta = self._build_simple_trace_meta(
            call_id_root=call_id_root,
            label=label,
            stage="reporting",
            call_kind="llm_final_response",
            trace_role="response",
            trace_group="stage",
            **trace_extra,
        )
        final_call_id = new_call_id(f"{call_id_root}-final")
        final_meta = build_trace_metadata(
            call_id=final_call_id,
            phase="reporting",
            label=label,
            call_kind="llm_final_response",
            trace_id=final_call_id,
            trace_role="response",
            trace_group="stage",
            **trace_extra,
        )
        step = await self._run_labeled_step(
            client=client,
            messages=messages,
            tool_schemas=None,
            protocol=protocol,
            stream=stream,
            stage="reporting",
            iter_meta=iter_meta,
            max_tokens=max_tokens,
            final_meta=final_meta,
        )
        return (step.text or "").strip()

    def _render_section_evidence(
        self,
        *,
        section: ReportSectionPlan,
        blocks: list[ResearchedBlock],
        citations: CitationManager,
    ) -> str:
        block_ids = section.block_ids or tuple(rb.block.block_id for rb in blocks)
        by_id = {rb.block.block_id: rb for rb in blocks}
        chunks: list[str] = []
        total = 0
        cap_per_block = 4000
        cap_total = 12000

        for bid in block_ids:
            rb = by_id.get(bid)
            if rb is None:
                continue
            title = _clean_report_heading_text(rb.block.sub_topic) or rb.block.sub_topic
            lines = [f"### Block [{rb.block.block_id}] {title}"]
            block_chars = 0
            for trace in rb.block.tool_traces:
                cid = trace.citation_id or trace.tool_id
                summary = (trace.summary or "").strip()
                if not summary:
                    continue
                citation = citations.get_citation(cid) or {}
                source_preview = _citation_source_preview(citation)
                line_parts = [
                    f"#### Evidence [{cid}]",
                    f"- tool: {trace.tool_type}",
                    f"- query: {trace.query}",
                ]
                if source_preview:
                    line_parts.append(f"- source hints: {source_preview}")
                line_parts.append(f"- note: {summary}")
                line = "\n".join(line_parts)
                line = line[: cap_per_block - block_chars]
                if not line:
                    break
                lines.append(line)
                block_chars += len(line)
                if block_chars >= cap_per_block:
                    break
            if rb.knowledge:
                lines.append(f"#### Block FINISH\n{rb.knowledge[:1500]}")
            chunk = "\n\n".join(lines)
            if total + len(chunk) > cap_total:
                chunk = chunk[: max(0, cap_total - total)]
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
            if total >= cap_total:
                break
        return "\n\n".join(chunks) or "(no evidence available)"

    # ------------------------------------------------------------------
    # Tool composition for the block loop
    # ------------------------------------------------------------------
    def _block_tool_names(self) -> list[str]:
        """Tools available inside the per-block research loop.

        Uses the same shared composition policy chat uses
        (:func:`compose_enabled_tools`): user-toggled tools first, then
        the conditional and always-on auto-mounts. Two block-phase-only
        adjustments:

        * Only evidence-producing research tools are surfaced. Chat's
          always-on convenience tools (``write_memory``, ``web_fetch``,
          ``github``, ``ask_user``) are deliberately not part of the
          block loop because they do not provide broad citable retrieval
          for an arbitrary sub-topic.
        * Each name is filtered through the registry so an inactive tool
          (mis-configured backend, missing dep) doesn't end up in the
          prompt.
        """
        composed = compose_enabled_tools(
            registry=self.registry,
            requested_tools=self.enabled_tools,
            optional_whitelist=RESEARCH_OPTIONAL_TOOLS,
            mount_flags=ToolMountFlags(
                has_kb=bool(self.kb_name),
                has_sources=False,
                has_memory=user_has_memory(),
                has_notebooks=user_has_notebooks(),
                has_code=exec_capability_available(),
            ),
        )
        return [
            name
            for name in composed
            if name in RESEARCH_BLOCK_TOOL_ALLOWLIST and self._tool_in_registry(name)
        ]

    def _build_block_tool_schemas(
        self,
        tool_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        names = self._block_tool_names() if tool_names is None else tool_names
        schemas = self.registry.build_openai_schemas(names)
        kb_choices = [self.kb_name] if self.kb_name else []
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if not isinstance(function, dict):
                continue
            parameters = function.get("parameters")
            if not isinstance(parameters, dict):
                continue
            properties = parameters.get("properties") or {}
            if function.get("name") == "rag" and isinstance(properties, dict):
                if isinstance(properties.get("query"), dict):
                    properties["query"].setdefault("minLength", 1)
                kb_schema = properties.get("kb_name")
                if isinstance(kb_schema, dict) and kb_choices:
                    kb_schema["enum"] = kb_choices
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
            task_dir = get_path_service().get_task_workspace("deep_research", turn_id)
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
        elif tool_name == "web_search":
            kwargs.setdefault("query", context.user_message)
            if task_dir is not None:
                kwargs.setdefault("output_dir", str(task_dir / "web_search"))
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

    def _use_native_block_tools(self, tool_names: list[str] | None = None) -> bool:
        names = self._block_tool_names() if tool_names is None else tool_names
        return bool(names) and can_use_native_tool_calling(binding=self.binding, model=self.model)

    def _tool_in_registry(self, name: str) -> bool:
        try:
            return self.registry.get(name) is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # LLM call helpers
    # ------------------------------------------------------------------
    def _build_client(self) -> Any:
        return build_openai_client(self.client_config)

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
        max_tokens: int = DEFAULT_BLOCK_MAX_TOKENS,
        final_meta: dict[str, Any] | None = None,
        eager_sub_trace: bool = True,
    ) -> LabeledStepResult:
        """Research-flavoured thin wrapper over :func:`run_labeled_step`."""
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
# Helpers
# ---------------------------------------------------------------------------

_REPORT_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_REPORT_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
    "with",
}


_REPORT_CITATION_MARKER_RE = re.compile(r"`?\[(?P<id>CIT-\d+-\d+|PLAN-\d+)\]`?(?!\s*\()")
_REPORT_CITATION_LINK_RE = re.compile(r"`?\[(?P<id>CIT-\d+-\d+|PLAN-\d+)\]`?\([^)]*\)")
_MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
_LEADING_HEADING_MARKERS_RE = re.compile(r"^(?:#{1,6}\s+)+")
_LEADING_SECTION_ID_RE = re.compile(r"^(?:[\[\(]?S\d+[\]\)]?\s*[:：\-]\s*)+", re.I)


def _clean_report_heading_text(text: str) -> str:
    cleaned = _LEADING_HEADING_MARKERS_RE.sub("", (text or "").strip())
    cleaned = _LEADING_SECTION_ID_RE.sub("", cleaned).strip()
    return cleaned


def _normalise_markdown_headings(text: str) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        match = _MARKDOWN_HEADING_RE.match(line)
        if not match:
            lines.append(line.rstrip())
            continue
        title = _clean_report_heading_text(match.group("title"))
        hashes = match.group("hashes")
        lines.append(f"{hashes} {title}" if title else hashes)
    return "\n".join(lines)


def _citation_ids_in_first_appearance(
    text: str,
    citations: CitationManager,
) -> list[str]:
    known = set(citations.get_all_citations())
    ordered: list[str] = []
    seen: set[str] = set()
    for match in _REPORT_CITATION_MARKER_RE.finditer(text or ""):
        citation_id = match.group("id")
        if citation_id not in known or citation_id in seen:
            continue
        seen.add(citation_id)
        ordered.append(citation_id)
    return ordered


def _citation_source_preview(citation: dict[str, Any]) -> str:
    if not citation:
        return ""
    tool_type = str(citation.get("tool_type") or "").lower()
    if tool_type == "web_search":
        sources = citation.get("web_sources")
        if isinstance(sources, list):
            hints = []
            for source in sources[:3]:
                if not isinstance(source, dict):
                    continue
                title = str(source.get("title") or source.get("domain") or "").strip()
                url = str(source.get("url") or "").strip()
                if title and url:
                    hints.append(f"{title} <{url}>")
                elif url:
                    hints.append(url)
            return "; ".join(hints)
    if tool_type == "paper_search":
        papers = citation.get("papers")
        if isinstance(papers, list):
            hints = []
            for paper in papers[:3]:
                if not isinstance(paper, dict):
                    continue
                title = str(paper.get("title") or "").strip()
                year = str(paper.get("year") or "").strip()
                if title:
                    hints.append(f"{title} ({year})" if year else title)
            return "; ".join(hints)
    if tool_type in {"rag", "rag_naive", "rag_hybrid"}:
        sources = citation.get("sources")
        if isinstance(sources, list):
            hints = []
            for source in sources[:3]:
                if not isinstance(source, dict):
                    continue
                title = str(source.get("title") or source.get("source_file") or "").strip()
                page = str(source.get("page") or "").strip()
                if title:
                    hints.append(f"{title} p.{page}" if page else title)
            return "; ".join(hints)
    return ""


def _section_with_block_ids(
    section: ReportSectionPlan,
    block_ids: tuple[str, ...],
) -> ReportSectionPlan:
    return ReportSectionPlan(
        id=section.id,
        title=section.title,
        intent=section.intent,
        block_ids=block_ids,
    )


def _report_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _REPORT_TOKEN_RE.findall((text or "").lower()):
        token = raw.strip()
        if not token or token in _REPORT_STOPWORDS:
            continue
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 3 and token.endswith("s"):
            token = token[:-1]
        tokens.add(token)
    return tokens


def _report_overlap_score(left: str, right: str) -> float:
    left_tokens = _report_tokens(left)
    right_tokens = _report_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    return len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))


def _best_block_for_section(
    section: ReportSectionPlan,
    blocks: list[ResearchedBlock],
    *,
    exclude: set[str],
) -> ResearchedBlock | None:
    candidates = [rb for rb in blocks if rb.block.block_id not in exclude] or blocks
    section_text = f"{section.title} {section.intent}"
    best: tuple[float, ResearchedBlock] | None = None
    for rb in candidates:
        block_text = f"{rb.block.sub_topic} {rb.block.overview} {rb.knowledge[:500]}"
        score = _report_overlap_score(section_text, block_text)
        if best is None or score > best[0]:
            best = (score, rb)
    return best[1] if best is not None else None


def _best_section_for_block(
    block: ResearchedBlock,
    sections: list[ReportSectionPlan],
) -> int | None:
    block_text = f"{block.block.sub_topic} {block.block.overview} {block.knowledge[:500]}"
    best: tuple[float, int] | None = None
    for idx, section in enumerate(sections):
        section_text = f"{section.title} {section.intent}"
        score = _report_overlap_score(block_text, section_text)
        if best is None or score > best[0]:
            best = (score, idx)
    if best is None or best[0] <= 0:
        return None
    return best[1]


def _citation_anchor_id(citation_id: str) -> str:
    return "ref-" + re.sub(r"[^a-z0-9_-]+", "-", citation_id.lower()).strip("-")


def _citation_markdown_link(citation_id: str, ref_number: int) -> str:
    return f'[{ref_number}](#{_citation_anchor_id(citation_id)} "citation")'


def _sorted_citation_ids(citations: CitationManager) -> list[str]:
    return sorted(citations.get_all_citations(), key=_citation_sort_key)


def _citation_number_map(citations: CitationManager) -> dict[str, int]:
    return {
        citation_id: index
        for index, citation_id in enumerate(_sorted_citation_ids(citations), start=1)
    }


def _citation_sort_key(citation_id: str) -> tuple[int, int, int]:
    """Sort PLAN and per-block CIT ids in the same order users see them."""
    try:
        if citation_id.startswith("PLAN-"):
            return (0, 0, int(citation_id.replace("PLAN-", "", 1)))
        if citation_id.startswith("CIT-"):
            block_num, seq_num = citation_id.replace("CIT-", "", 1).split("-", 1)
            return (1, int(block_num), int(seq_num))
    except (IndexError, ValueError):
        pass
    return (999, 999, 999)


def _topic_index_from_block_id(block_id: str) -> int | None:
    match = re.search(r"block_(\d+)", block_id or "")
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _research_topic_status_meta(block: TopicBlock) -> dict[str, Any]:
    return {
        "research_status_key": "research_topic",
        "topic_index": _topic_index_from_block_id(block.block_id),
        "topic_title": block.sub_topic,
    }


def _read_int(cfg: Any, *, key: str, default: int) -> int:
    if isinstance(cfg, dict):
        value = cfg.get(key, default)
    else:
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# _BlockLoopHost — per-block research loop callbacks
# ---------------------------------------------------------------------------


class _BlockLoopHost:
    """Binds a ``ResearchPipeline`` + one ``TopicBlock`` + queue + citation
    store so the generic agentic loop can call back for per-block side
    effects.

    Three loop hooks are implemented beyond the default protocol:
    * :meth:`dispatch_tools` — wraps the standard parallel dispatch with
      a note-agent sidecar that summarises citable tool results and
      records them in :class:`CitationManager`. The summary then
      replaces the raw tool message content sent back to the model so
      long retrievals don't blow the context budget.
    * :meth:`on_intermediate` — handles the ``APPEND`` label. Parses
      ``<title>\n<overview?>`` out of the post-label text, runs dedup
      + capacity checks, appends a child block to the queue, and
      returns a confirmation / rejection message that the loop injects
      as the next iteration's user feedback.
    * :meth:`force_finalize` — drives the per-block force-finish
      recovery when the iteration budget is exhausted before a
      terminal label fires.
    """

    def __init__(
        self,
        *,
        pipeline: "ResearchPipeline",
        block: TopicBlock,
        queue: DynamicTopicQueue,
        citations: CitationManager,
        topic: str,
        stream: StreamBus,
        context: UnifiedContext,
        client: Any,
    ) -> None:
        self._pipeline = pipeline
        self._block = block
        self._queue = queue
        self._citations = citations
        self._topic = topic
        self._stream = stream
        self._context = context
        self._client = client
        self._tool_rounds_used = 0

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        # Per-block budgets keep messages bounded; no trimming for v1.
        return None

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        status_meta = _research_topic_status_meta(self._block)
        iter_call_id = new_call_id(f"research-{self._block.block_id}-iter-{iteration}")
        iter_meta = build_trace_metadata(
            call_id=iter_call_id,
            phase="researching",
            label=self._pipeline._t("labels.reasoning", default="Reasoning"),
            call_kind="llm_reasoning",
            trace_id=iter_call_id,
            trace_role="thought",
            trace_group="stage",
            block_id=self._block.block_id,
            **status_meta,
        )
        final_call_id = new_call_id(f"research-{self._block.block_id}-final")
        final_meta = build_trace_metadata(
            call_id=final_call_id,
            phase="researching",
            label=(
                f"{self._pipeline._t('labels.research_step', default='Research step')}: "
                f"{self._block.sub_topic}"
            ),
            call_kind="llm_final_response",
            trace_id=final_call_id,
            trace_role="response",
            trace_group="stage",
            block_id=self._block.block_id,
            **status_meta,
        )
        return iter_meta, final_meta

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
        outcome = await dispatch_tool_calls(
            tool_calls=tool_calls,
            context=self._context,
            stream=self._stream,
            source=SOURCE,
            stage="researching",
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
            trace_id_prefix=f"research-{self._block.block_id}-iter",
        )
        if tool_calls:
            self._tool_rounds_used += 1
        await self._summarise_and_record(tool_calls, outcome)
        return outcome

    async def validate_terminal(self, label: str, text: str) -> str | None:
        """Reject a first-turn FINISH when native evidence tools are callable.

        The prompt tells the model to call a tool before FINISH, but some
        models still jump straight to synthesis. This hook makes that rule
        executable instead of prompt-only.
        """
        if (
            label == LABEL_FINISH
            and self._tool_rounds_used <= 0
            and self._pipeline._use_native_block_tools()
        ):
            return "finish_without_tool"
        return None

    async def _summarise_and_record(
        self,
        tool_calls: list[dict[str, Any]],
        outcome: DispatchOutcome,
    ) -> None:
        """Walk every emitted tool message; for citable tools, summarise
        the raw answer through ``_summarise_tool_result``, register the
        result in :class:`CitationManager`, and substitute the summary
        back into the tool message body the LLM sees."""
        if not outcome.tool_messages:
            return
        call_meta_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
        for tc in tool_calls:
            cid = tc.get("id") or ""
            name = str(tc.get("name") or "")
            raw_args = tc.get("arguments") or {}
            if isinstance(raw_args, str):
                parsed = parse_json_response(raw_args, fallback={})
                args = parsed if isinstance(parsed, dict) else {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            call_meta_by_id[cid] = (name, args)

        for tm in outcome.tool_messages:
            tool_call_id = str(tm.get("tool_call_id") or "")
            tool_name, tool_args = call_meta_by_id.get(tool_call_id, ("", {}))
            if tool_name not in CITABLE_TOOLS:
                continue
            raw_answer = str(tm.get("content") or "")
            if not raw_answer.strip():
                continue
            try:
                query = str(tool_args.get("query") or "")
                summary = await self._pipeline._summarise_tool_result(
                    tool_name=tool_name,
                    query=query,
                    raw_answer=raw_answer,
                    client=self._client,
                )
                citation_id = await self._citations.generate_research_citation_id_async(
                    self._block.block_id
                )
                trace = ToolTrace.create_with_size_limit(
                    tool_id=f"{self._block.block_id}-tool-{citation_id}",
                    citation_id=citation_id,
                    tool_type=tool_name,
                    query=query,
                    raw_answer=raw_answer,
                    summary=summary,
                )
                self._block.add_tool_trace(trace)
                tool_metadata = outcome.tool_metadata_by_id.get(tool_call_id)
                await self._citations.add_citation_async(
                    citation_id, tool_name, trace, raw_answer, tool_metadata
                )
                tm["content"] = f"[{citation_id}] {summary}"
            except Exception:
                logger.exception(
                    "Failed to record research citation for %s in %s",
                    tool_name,
                    self._block.block_id,
                )

    async def resolve_pause(self, dispatch: DispatchOutcome) -> bool:
        # Per-block research never surfaces ask_user; clarification only
        # happens in the rephrase phase.
        return False

    async def emit_terminator(self, payload: dict[str, Any] | None) -> None:
        return None

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        # Block FINISH text is consumed by the reporting phase, not
        # streamed live as user-facing content — streaming it here would
        # dump raw per-block findings into the chat bubble before the
        # actual report begins.
        return None

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

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        return await self._pipeline._force_finish_block(
            client=self._client,
            messages=messages,
            stream=self._stream,
            block=self._block,
            start_iteration=start_iteration,
        )

    async def on_intermediate(self, label: str, text: str) -> str | None:
        """Parse ``APPEND`` payload and extend the queue.

        Format: first line = title, remainder (optional) = overview.
        Empty / duplicate / over-capacity proposals get a rejection note
        the loop injects as the next iteration's user message so the LLM
        can adapt rather than spam the same proposal.
        """
        if label != LABEL_APPEND:
            return None
        first_line, _, rest = (text or "").strip().partition("\n")
        # Strip leading markdown heading markers (``#``, ``##``, …) so the
        # queue stores a clean title even if the LLM rendered the new
        # sub-topic as a markdown header.
        title = first_line.strip().lstrip("#").strip()
        overview = rest.strip()
        if not title:
            return self._pipeline._t(
                "notices.append_rejected_empty",
                default="APPEND rejected: missing title.",
            )

        if self._queue.is_full():
            await self._stream.progress(
                self._pipeline._t(
                    "notices.append_rejected_full_progress",
                    title=title,
                    default=f"Queue is full; rejected append: {title}",
                ),
                source=SOURCE,
                stage="researching",
                metadata={
                    "trace_kind": "queue_append_rejected",
                    "block_id": self._block.block_id,
                    "reason": "full",
                    "title": title,
                },
            )
            return self._pipeline._t(
                "notices.append_rejected_full",
                default=(
                    "APPEND rejected: the topic queue is at capacity. Continue "
                    "researching the current block and emit FINISH when done."
                ),
            )

        dup = self._queue.find_similar(title)
        if dup is not None:
            await self._stream.progress(
                self._pipeline._t(
                    "notices.append_rejected_dup_progress",
                    title=title,
                    existing=dup.block_id,
                    default=(
                        f"APPEND rejected: '{title}' is too similar to "
                        f"existing block {dup.block_id}"
                    ),
                ),
                source=SOURCE,
                stage="researching",
                metadata={
                    "trace_kind": "queue_append_rejected",
                    "block_id": self._block.block_id,
                    "reason": "duplicate",
                    "title": title,
                    "existing_id": dup.block_id,
                },
            )
            return self._pipeline._t(
                "notices.append_rejected_duplicate",
                existing_id=dup.block_id,
                existing_title=dup.sub_topic,
                default=(
                    f"APPEND rejected: too similar to existing block "
                    f"{dup.block_id} ({dup.sub_topic!r})."
                ),
            )

        new_block = self._queue.append_child(parent=self._block, sub_topic=title, overview=overview)
        if new_block is None:
            return self._pipeline._t(
                "notices.append_rejected_full",
                default="APPEND rejected: queue is full.",
            )

        await self._stream.progress(
            self._pipeline._t(
                "notices.append_accepted_progress",
                title=title,
                new_block_id=new_block.block_id,
                default=f"Sub-topic queued: {title}",
            ),
            source=SOURCE,
            stage="researching",
            metadata={
                "trace_kind": "queue_append",
                "block_id": self._block.block_id,
                "parent_block_id": self._block.block_id,
                "new_block_id": new_block.block_id,
                "title": title,
            },
        )
        return self._pipeline._t(
            "notices.append_accepted",
            new_block_id=new_block.block_id,
            title=title,
            default=f"Appended block {new_block.block_id}: {title}",
        )


# ---------------------------------------------------------------------------
# _RephraseLoopHost — ask_user-only mini loop
# ---------------------------------------------------------------------------


class _RephraseLoopHost:
    """Drives the rephrase mini-loop. Only ``ask_user`` is allowed as a
    tool; the round cap (``rephrase_max_rounds``) is enforced here. When
    exhausted, any further ``ask_user`` call is replied to with a tool
    message instructing the model to FINISH with the best refined topic
    it has."""

    def __init__(
        self,
        *,
        pipeline: "ResearchPipeline",
        stream: StreamBus,
        context: UnifiedContext,
        client: Any,
        max_rounds: int,
    ) -> None:
        self._pipeline = pipeline
        self._stream = stream
        self._context = context
        self._client = client
        self._max_rounds = max(0, int(max_rounds))
        self._rounds_used = 0
        # Reuse one call_id across all rephrase iterations so the FE
        # groups every THINK trace from before *and* after ``ask_user``
        # into a single "Rephrasing" reasoning card. Without this each
        # iter would get its own card and the post-answer reasoning
        # would appear as a brand-new box below the user's reply.
        self._shared_iter_call_id = new_call_id("research-rephrase-iter")

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        return None

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        iter_meta = build_trace_metadata(
            call_id=self._shared_iter_call_id,
            phase="rephrasing",
            label=self._pipeline._t("labels.rephrase", default="Rephrase"),
            call_kind="llm_reasoning",
            trace_id=self._shared_iter_call_id,
            trace_role="thought",
            trace_group="stage",
        )
        final_call_id = new_call_id(f"research-rephrase-final-{iteration}")
        final_meta = build_trace_metadata(
            call_id=final_call_id,
            phase="rephrasing",
            label=self._pipeline._t("labels.rephrase", default="Rephrase"),
            call_kind="llm_final_response",
            trace_id=final_call_id,
            trace_role="response",
            trace_group="stage",
        )
        return iter_meta, final_meta

    async def dispatch_tools(
        self,
        *,
        iteration: int,
        tool_calls: list[dict[str, Any]],
    ) -> DispatchOutcome:
        allowed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for tc in tool_calls:
            if tc.get("name") == "ask_user":
                allowed.append(tc)
            else:
                rejected.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": tc.get("name", ""),
                        "content": self._pipeline._t(
                            "notices.rephrase_only_ask_user",
                            tool=tc.get("name", ""),
                            default=(
                                "Only `ask_user` is available in this phase. "
                                "Use it or emit FINISH with the refined topic."
                            ),
                        ),
                    }
                )

        if self._rounds_used >= self._max_rounds and allowed:
            cap_messages = [
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": "ask_user",
                    "content": self._pipeline._t(
                        "notices.rephrase_cap_reached",
                        max_rounds=self._max_rounds,
                        default=(
                            f"ask_user limit reached ({self._max_rounds} "
                            "rounds). Emit FINISH now with the best refined "
                            "topic you can produce from prior answers."
                        ),
                    ),
                }
                for tc in allowed
            ]
            return DispatchOutcome(sources=[], tool_messages=cap_messages + rejected)

        if not allowed:
            return DispatchOutcome(sources=[], tool_messages=rejected)

        too_many = None
        if len(allowed) > MAX_PARALLEL_TOOL_CALLS:
            too_many = self._pipeline._t(
                "notices.too_many_tool_calls",
                requested=len(allowed),
                limit=MAX_PARALLEL_TOOL_CALLS,
            )
        outcome = await dispatch_tool_calls(
            tool_calls=allowed,
            context=self._context,
            stream=self._stream,
            source=SOURCE,
            stage="rephrasing",
            iteration_index=iteration,
            registry=self._pipeline.registry,
            kwarg_augmenter=self._pipeline._augment_tool_kwargs,
            retrieve_meta_factory=lambda meta, tn, ta: None,
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
            trace_id_prefix="research-rephrase-iter",
        )
        if rejected:
            outcome.tool_messages.extend(rejected)
        self._rounds_used += 1
        return outcome

    async def resolve_pause(self, dispatch: DispatchOutcome) -> bool:
        from deeptutor.agents.chat.agentic_pipeline import (
            _format_user_reply_body,
            _normalise_user_reply,
        )

        ask_user = (dispatch.pause_payload or {}).get("ask_user") or {}
        waiter = self._context.metadata.get("wait_for_user_reply")
        if not callable(waiter):
            return False
        raw_reply = await waiter()
        if raw_reply is None:
            return False
        reply_text, answers = _normalise_user_reply(raw_reply)
        body_text = _format_user_reply_body(reply_text, answers, ask_user)
        for tm in dispatch.tool_messages:
            if tm.get("tool_call_id") == dispatch.pause_tool_call_id:
                tm["content"] = (
                    f"{body_text}\n\n[ask_user resolved. Continue to FINISH "
                    "with the refined research topic when you have enough "
                    "information.]"
                )
                break
        progress_meta: dict[str, Any] = {
            "trace_kind": "user_reply",
            "ask_user_resolved": True,
            "ask_user_tool_call_id": dispatch.pause_tool_call_id,
            "reply_preview": (reply_text or "")[:200],
        }
        if answers:
            progress_meta["answers"] = list(answers)
        await self._stream.progress("", source=SOURCE, stage="rephrasing", metadata=progress_meta)
        return True

    async def emit_terminator(self, payload: dict[str, Any] | None) -> None:
        return None

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        # The refined topic is internal; not streamed as user content.
        return None

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

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        # Rephrase exhaustion falls back to the raw topic (handled by
        # the caller); we report no extra calls and "not completed" so
        # the loop returns with an empty final_text.
        return ("", False, 0)


# Re-export ``Awaitable`` so host implementations can type their
# coroutine return values without an extra import (mirrors solve).
_ = Awaitable  # type: ignore[assignment]


__all__ = [
    "CITABLE_TOOLS",
    "LABEL_APPEND",
    "LABEL_CONCLUSION",
    "LABEL_FINISH",
    "LABEL_INTRO",
    "LABEL_OUTLINE",
    "LABEL_SECTION",
    "LABEL_THINK",
    "LABEL_TOOL",
    "ResearchPipeline",
    "ResearchedBlock",
    "ReportOutline",
    "ReportSectionPlan",
    "SOURCE",
    "SubTopicItem",
]
