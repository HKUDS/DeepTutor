"""Single-loop chat agent.

One chat turn = ONE agent loop over a single growing conversation:

* each round is one LLM call; its text streams to the user as a ``content``
  block, and its tool calls are dispatched with their ``role=tool`` results
  appended back into the conversation;
* every round's text is part of the answer, in the order it was written. A
  round that DOES call tools has written *commentary* — what it is about to do
  and why — and the loop continues; the reader keeps that text, with the tool
  work rendered inline beneath it, the way a terminal agent reads;
* a round that calls NO tools is the ``finish``: its text closes the answer and
  the loop ends (the model deciding it is done; a first round without tool
  calls is the "no exploration needed" fast path);
* if the exploration budget runs out while work is still in protocol, a
  small bounded settlement phase keeps tools available for already-started
  follow-up (including user input); one final tool-less round is forced only
  after that settlement allowance is exhausted.

``ask_user`` pauses the turn for a reply and resumes in-protocol; an
unresolved pause (or a terminator tool) halts the turn.

There is no separate respond pass and no text destination has to be guessed:
every round's text streams to the user as it is generated and stays there. The
``call_status`` marker a completed round emits describes its phase —
``call_role`` (``narration`` = more work follows, ``finish`` = terminal) says
where the turn is. ``answer_visible`` remains true for compatibility; published
answer text is never retracted by a finish check.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import os
from time import monotonic
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.agents.loop.ask_user_drafts import AskUserDraftEmitter
from deeptutor.agents.loop.context_budget import LLMRequestSnapshot
from deeptutor.agents.loop.dsml_tool_calls import DSMLStreamFilter, extract_dsml_tool_calls
from deeptutor.agents.loop.loop_state import (
    AgentLoopState,
    LLMCallResult,
    LoopOutcome,
    _assistant_round_message,
    _join_answer_parts,
    _provider_response_state,
    _reasoning_budget_exhausted,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id
from deeptutor.runtime.agentic.messages import (
    image_content_hashes,
    with_transient_model_messages,
)
from deeptutor.runtime.agentic.think_stream import InlineThinkFilter
from deeptutor.runtime.agentic.tool_call_stream import ToolCallAccumulator
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.agentic.usage import message_content_chars, record_streamed_usage
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm import (
    LLMProviderTransportError,
    LLMReasoningBudgetExhausted,
    clean_thinking_tags,
    supports_streaming,
)
from deeptutor.services.llm import finish_was_truncated as _finish_was_truncated
from deeptutor.services.llm.capabilities import threads_session_id
from deeptutor.services.llm.image_replay import deduplicate_user_images
from deeptutor.services.llm.multimodal import (
    has_image_parts,
    should_degrade_to_text,
    strip_image_parts_inplace,
)
from deeptutor.services.llm.request_compat import (
    is_forced_tool_choice_unsupported,
    is_image_input_unsupported,
    is_stream_options_unsupported,
    is_tool_schema_unsupported,
    is_transient_transport_error,
    logged_error_text,
)
from deeptutor.services.llm.usage_frame import usage_breakdown
from deeptutor.services.llm.utils import unreachable_endpoint_hint

if TYPE_CHECKING:  # pragma: no cover
    from deeptutor.agents.loop.pipeline import AgenticLoopPipeline

logger = logging.getLogger(__name__)

# The loop runs over a single conversation. Its configured round budget covers
# exploration; bounded settlement and the emergency hard finish are separate.
LOOP_STAGE = "responding"
# Settlement is deliberately small but large enough for the longest built-in
# interaction boundary: register state -> ask/resume -> record result -> reply.
# A single additional tool-less hard finish follows if all of these rounds
# still request tools. A receipt-backed capability delivery can use that final
# round instead, with a restricted tool surface: the bound stays exploration + 4.
MAX_SETTLEMENT_ROUNDS = 3
# Reasoning-only completions can recur when a model rewrites its plan instead
# of acting. Give it a stronger directive on the second miss, then use the
# forced tool-less finish instead of spending the full exploration budget on
# the same failure.
MAX_REASONING_ONLY_RECOVERIES = 2
# The SDK already retries failures that happen before response headers. These
# short outer retries also cover SSE connections that fail before yielding any
# user-visible output. Once output is visible, replay is unsafe because it can
# duplicate prose or tool calls.
_PROVIDER_RETRY_DELAYS = (0.5, 1.5)
_STREAM_IDLE_TIMEOUT_SECONDS = 90.0


async def _bounded_stream_chunks(stream: Any):
    """#1421: a connected provider that never produces a chunk must settle."""
    iterator = stream.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(iterator.__anext__(), _STREAM_IDLE_TIMEOUT_SECONDS)
        except StopAsyncIteration:
            return
        except TimeoutError:
            raise LLMProviderTransportError("The model provider stream timed out.") from None


def _append_directive_to_parts(parts: list[Any], instruction: str) -> list[Any]:
    """Extend a multimodal user message with a text directive, keeping its parts.

    The trailing user message can carry content parts: a chat PDF's embedded
    images arrive as ``image_url`` blocks beside the text that references them.
    Text is appended to the message's own text part (the parts-list analogue of
    the plain-string branch in :meth:`AgentLoop._append_loop_instruction`), and
    a message holding nothing but images gets a text part of its own.

    Only the directive is added. Rebuilding the message as a string instead
    would fold every ``data:...;base64,`` payload into prompt text and send the
    image bytes to the provider as language tokens on the next round.
    """
    updated = list(parts)
    for index in range(len(updated) - 1, -1, -1):
        part = updated[index]
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            prior = part["text"].rstrip()
            merged = f"{prior}\n\n{instruction}" if prior else instruction
            updated[index] = {**part, "text": merged}
            return updated
    updated.append({"type": "text", "text": instruction})
    return updated


def _reasoning_item_text(item: dict[str, Any]) -> str:
    """Extract display-safe text from a Responses reasoning output item."""
    parts: list[str] = []
    for block in item.get("content") or []:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if text:
            parts.append(str(text))
    for summary in item.get("summary") or []:
        if not isinstance(summary, dict):
            continue
        text = summary.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts)


class AgentLoop:
    """Run one chat turn as a single agent loop over one conversation."""

    def __init__(
        self,
        *,
        pipeline: "AgenticLoopPipeline",
        context: UnifiedContext,
        stream: StreamBus,
        client: Any,
        enabled_tools: list[str],
        tool_schemas: list[dict[str, Any]] | None,
    ) -> None:
        self.pipeline = pipeline
        self.context = context
        self.stream = stream
        self.client = client
        self.enabled_tools = enabled_tools
        self.tool_schemas = tool_schemas
        # Keep the schema catalog even if a provider rejects native ``tools``
        # and subsequent calls switch to DSML fallback. The parser still needs
        # the declared parameter types to decode string-marked containers.
        self._tool_schema_catalog = tool_schemas
        self._last_request: LLMRequestSnapshot | None = None
        self._request_tools: list[dict[str, Any]] | None = tool_schemas
        # #1611: retrieved pixels belong to this turn's requests, never to
        # durable history. Both loop engines share the same ordering/budget.
        self._transient_model_messages: list[dict[str, Any]] = []
        context.extension("source_visual_evidence")["image_hashes"] = []
        self._request_fingerprint = (context.runtime.previous_model_turn or {}).get(
            "request_fingerprint"
        )
        self.source = pipeline.event_source
        self.stage = pipeline.event_stage

    async def run(self) -> dict[str, Any]:
        state = AgentLoopState()
        # Optional async pre-pass briefings (e.g. explore_context) run BEFORE
        # the answer stage so they form their own preceding activity group and
        # their grounding can ride in the loop's user-message seed.
        capability_briefing = await self.pipeline._capability_pre_loop_briefings(
            self.context, self.stream
        )
        async with self.stream.stage(self.stage, source=self.source):
            seed_block = await self.pipeline._retrieve_kb_seed_block(self.context, self.stream)
            capability_seed = self.pipeline._capability_pre_loop_seed(self.context)
            seed_block = "\n\n".join(
                block
                for block in (
                    seed_block.strip(),
                    capability_seed.strip(),
                    capability_briefing.strip(),
                )
                if block
            )
            messages = self.pipeline._build_loop_messages(
                context=self.context,
                enabled_tools=self.enabled_tools,
                kb_seed=seed_block,
                include_tool_manifest=bool(self.tool_schemas),
            )
            try:
                engine = os.getenv("DEEPTUTOR_CHAT_ENGINE", "python").strip().lower()
                if engine == "typescript-native":
                    engine = "typescript"  # Provider admitted to the compatibility path.
                if engine not in {"python", "typescript"}:
                    raise ValueError("DEEPTUTOR_CHAT_ENGINE must be python or typescript")
                outcome = await self._run_loop(
                    messages=messages,
                    state=state,
                    checkpoint_boundary=len(messages),
                    scheduler=engine,
                )
                if outcome.final_text and (
                    messages[-1].get("role") != "assistant" or not messages[-1].get("content")
                ):
                    # Terminator tools and capability overrides can produce the
                    # visible answer without a final model message.
                    messages.append({"role": "assistant", "content": outcome.final_text})
            finally:
                from deeptutor.services.session.model_history import (
                    complete_tool_results,
                    normalize_model_turn,
                )

                # Keep the prepared input (including attachments and briefings)
                # and every model/tool message, independently of display repair.
                self.context.runtime.model_turn = normalize_model_turn(
                    {
                        "version": 1,
                        "messages": complete_tool_results(
                            messages[self.pipeline._model_turn_start :]
                        ),
                        "system": messages[0]["content"],
                        "tools": self._request_tools,
                        "route": {"provider": self.pipeline.binding, "model": self.pipeline.model},
                        "request_fingerprint": self._request_fingerprint,
                    }
                )
        if outcome.provider_response_state is not None:
            self.context.runtime.provider_response_state = outcome.provider_response_state

        if state.sources:
            await self.stream.sources(
                state.sources,
                source=self.source,
                stage=self.stage,
                metadata={"trace_kind": "sources"},
            )
        payload: dict[str, Any] = {
            "response": outcome.final_text,
            "completed": outcome.completed,
            "engine": "agent_loop",
            "scheduler": engine,
            "rounds": state.rounds,
            "settlement_rounds": state.settlement_rounds,
            "tool_steps": state.tool_steps,
        }
        if os.getenv("DEEPTUTOR_CHAT_ENGINE") == "typescript-native":
            from deeptutor.runtime.ts_engine.config import compatibility_reason

            payload["execution_runtime"] = "python-effects"
            payload["compatibility_reason"] = compatibility_reason(self.pipeline.llm_config)
        if self._last_request is not None:
            budget = self.pipeline.measure_context_budget(self._last_request)
            if budget is not None:
                payload["metadata"] = {"context_budget": budget}
        if self.pipeline.emit_result:
            await emit_capability_result(
                self.stream,
                payload,
                source=self.source,
                usage=self.pipeline.usage,
            )
        return payload

    def _clean(self, text: str) -> str:
        return clean_thinking_tags(text, self.pipeline.binding, self.pipeline.model).strip()

    # ---- agent loop --------------------------------------------------------

    async def _run_loop(
        self,
        *,
        messages: list[dict[str, Any]],
        state: AgentLoopState,
        checkpoint_boundary: int,
        scheduler: str = "python",
    ) -> LoopOutcome:
        from deeptutor.agents.loop.loop_host import run_loop_with_host

        return await run_loop_with_host(
            self,
            messages=messages,
            state=state,
            checkpoint_boundary=checkpoint_boundary,
            scheduler=scheduler,
            config={
                "explorationBudget": max(1, self.pipeline.effective_max_rounds(self.context)),
                "settlementBudget": MAX_SETTLEMENT_ROUNDS,
                "emptyRecoveryBudget": MAX_REASONING_ONLY_RECOVERIES,
            },
        )

    async def _begin_settlement(self, messages: list[dict[str, Any]]) -> None:
        """Enter the bounded post-budget phase without dropping tool state."""
        await self.stream.progress(
            self.pipeline._t(
                "notices.loop_settlement",
                default=(
                    "Exploration budget reached; completing required follow-up "
                    "before the final answer."
                ),
            ),
            source=self.source,
            stage=self.stage,
            metadata={"trace_kind": "warning"},
        )
        self._append_loop_instruction(
            messages,
            self.pipeline._settle_exhausted_instruction(),
        )

    @staticmethod
    def _append_loop_instruction(messages: list[dict[str, Any]], instruction: str) -> None:
        """Append a loop directive without creating consecutive user roles."""
        if messages and messages[-1].get("role") == "user":
            content = messages[-1].get("content")
            if isinstance(content, list):
                messages[-1]["content"] = _append_directive_to_parts(content, instruction)
                return
            prior = str(content or "").rstrip()
            messages[-1]["content"] = f"{prior}\n\n{instruction}" if prior else instruction
            return
        messages.append({"role": "user", "content": instruction})

    def _fold_context_checkpoint(
        self,
        *,
        messages: list[dict[str, Any]],
        dispatch: DispatchOutcome,
        checkpoint_boundary: int,
    ) -> int:
        summary, state = _last_context_checkpoint(dispatch)
        if not summary:
            return checkpoint_boundary
        prefix = messages[:checkpoint_boundary]
        prefix.append(
            {
                "role": "system",
                "content": f"[Context checkpoint]\n{summary}",
            }
        )
        boundary = len(prefix)
        if state:
            # State sits past the boundary, so the next fold replaces it rather
            # than leaving a stale copy beside every summary.
            prefix.append({"role": "system", "content": state})
        messages[:] = prefix
        return boundary

    async def _reject_capability_finish(self) -> LoopOutcome:
        """Fail a turn whose required interaction could not be completed."""
        await self.stream.progress(
            self.pipeline._t(
                "notices.capability_finish_rejected",
                default=(
                    "The model did not complete the required interactive step. "
                    "Please retry the turn."
                ),
            ),
            source=self.source,
            stage=self.stage,
            metadata={"trace_kind": "warning"},
        )
        return LoopOutcome(final_text="", completed=False)

    async def _forced_finish(
        self,
        messages: list[dict[str, Any]],
        state: AgentLoopState,
        *,
        reason: str = "budget",
        error: str = "",
        continued_answer_parts: list[str] | None = None,
    ) -> LoopOutcome:
        # A tool-free salvage reply cannot satisfy an outstanding interaction.
        # Empty text asks capabilities about state, without inventing prose to
        # validate or giving the model another chance to claim completion.
        if self.pipeline._capability_finish_instruction(self.context, ""):
            outcome = await self._reject_capability_finish()
            outcome.final_text = _join_answer_parts(continued_answer_parts or [], "")
            return outcome
        if reason == "error":
            # The caller has the exception and logs it; without it here the
            # reader is told a step failed and never which one or why — the
            # same silence ``tool_error_message_factory`` was built to end.
            notice = self.pipeline._t(
                "notices.loop_error_finish",
                error=error,
                default=f"A step failed ({error}); answering with what has been gathered."
                if error
                else "A step failed; answering with what has been gathered.",
            )
        else:
            notice = self.pipeline._t(
                "notices.loop_budget_exhausted",
                default="Exploration budget reached; answering with what has been gathered.",
            )
        await self.stream.progress(
            notice,
            source=self.source,
            stage=self.stage,
            metadata={"trace_kind": "warning"},
        )
        self._append_loop_instruction(messages, self.pipeline._finish_exhausted_instruction())
        try:
            result = await self._call_llm(
                messages=messages,
                label=self.pipeline._t("labels.final_response", default="Final response"),
                call_kind="llm_final_response",
                trace_role="response",
                max_tokens=self.pipeline.loop_max_tokens,
                tool_schemas=None,  # tools disabled so the model must finish
            )
        except LLMProviderTransportError:
            # Preserve the structured retryable error. Treating an unavailable
            # provider as a successful empty answer hides the real failure and
            # prevents callers from offering an accurate retry action.
            raise
        except Exception as exc:
            from deeptutor.core.capability_protocol import CapabilityPrerequisiteError

            if isinstance(exc, CapabilityPrerequisiteError):
                raise
            # The salvage call itself failed (e.g. the provider is still
            # returning unusable data). Don't bubble up and lose the turn —
            # emit the graceful fallback answer instead.
            logger.warning("forced-finish LLM call failed: %s", exc)
            return await self._finalize_finish(
                "",
                continued_answer_parts=continued_answer_parts,
            )
        state.rounds += 1
        # Two readings of one scene, at different precisions. The budget
        # check fires only when this round demonstrably hit its cap — that is
        # a configuration the user can act on (lower the effort, split the
        # task), so it is worth failing the turn with the counters that prove
        # it. Everything else that reasoned without answering is a softer
        # miss: the turn still ends, but it says which kind of empty it was
        # rather than reporting an opaque model failure.
        if _reasoning_budget_exhausted(result, self.pipeline.loop_max_tokens):
            message = self.pipeline._t(
                "notices.reasoning_budget_exhausted",
                default=(
                    "The model exhausted its output budget on internal reasoning "
                    "without producing an answer or tool action. Please retry, "
                    "lower reasoning effort, or split the task into smaller steps."
                ),
            )
            raise LLMReasoningBudgetExhausted(
                message,
                diagnostics={
                    "rounds": state.rounds,
                    "reasoning_chars": result.reasoning_chars,
                    "completion_tokens": result.usage.get("completion_tokens"),
                    "reasoning_tokens": result.usage.get("reasoning_tokens"),
                },
            )
        reasoning_without_answer = bool(result.reasoning_content) or bool(
            result.text.strip() and not self._clean(result.text)
        )
        messages.append(_assistant_round_message(result))
        return await self._finalize_finish(
            result.text,
            visible_text=result.visible_text,
            continued_answer_parts=continued_answer_parts,
            empty_response_kind=("reasoning_only" if reasoning_without_answer else None),
            provider_response_state=_provider_response_state(
                result.response_output_items,
                result.reasoning_content,
                result.thinking_blocks,
            ),
        )

    async def _finalize_finish(
        self,
        raw_text: str,
        *,
        visible_text: str | None = None,
        continued_answer_parts: list[str] | None = None,
        allow_empty: bool = False,
        empty_response_kind: str | None = None,
        provider_response_state: dict[str, Any] | None = None,
    ) -> LoopOutcome:
        cleaned_text = self._clean(raw_text)
        if continued_answer_parts:
            final_text = _join_answer_parts(
                continued_answer_parts,
                visible_text if visible_text is not None else cleaned_text,
            )
        else:
            final_text = cleaned_text
        if not final_text and not allow_empty:
            # The finish round produced no usable text; nothing streamed to
            # the user, so emit a fallback answer here.
            if empty_response_kind == "reasoning_only":
                final_text = self.pipeline._t(
                    "notices.reasoning_only_final_response",
                    default=(
                        "The model produced internal reasoning but no usable "
                        "answer. Please try again or narrow the request."
                    ),
                )
            else:
                final_text = self.pipeline._t(
                    "notices.empty_final_response",
                    default=(
                        "I could not produce a useful response from the model "
                        "output. Please try again or narrow the request."
                    ),
                )
            await self.pipeline._emit_protocol_fallback_final_response(self.stream, final_text)
        return LoopOutcome(
            final_text=final_text,
            completed=True,
            provider_response_state=provider_response_state,
        )

    async def _release_deferred_output(self, result: LLMCallResult) -> None:
        """Publish a buffered capability round only after its protocol accepts it."""
        if result.deferred_chunk_metadata is not None and result.visible_text:
            await self.stream.content(
                result.visible_text,
                source=self.source,
                stage=self.stage,
                metadata=result.deferred_chunk_metadata,
            )
        if result.deferred_completion_metadata is not None:
            await self.stream.progress(
                "",
                source=self.source,
                stage=self.stage,
                metadata=result.deferred_completion_metadata,
            )
        result.deferred_chunk_metadata = None
        result.deferred_completion_metadata = None

    async def _discard_deferred_output(self, result: LLMCallResult) -> None:
        """Discard only unpublished protocol payloads, never public answer text."""
        if result.deferred_completion_metadata is not None:
            metadata = dict(result.deferred_completion_metadata)
            metadata["call_role"] = "narration"
            await self.stream.progress("", source=self.source, stage=self.stage, metadata=metadata)
        result.deferred_chunk_metadata = None
        result.deferred_completion_metadata = None

    # ---- LLM call ----------------------------------------------------------

    def _apply_prompt_caching(self, kwargs: dict[str, Any]) -> None:
        """Attach Anthropic-style ``cache_control`` breakpoints to the request.

        The loop builds its own ``chat.completions.create`` kwargs and calls the
        SDK client directly, so it never passes through
        ``OpenAICompatProvider._build_kwargs`` — the only other place cache
        breakpoints are added. Without this, an ``anthropic/`` model on a
        prompt-caching gateway (OpenRouter) sends no breakpoint and Anthropic
        caches nothing. Reuse the provider's helper so both paths mark requests
        identically, and add the end-of-stable-history breakpoint the loop
        needs: its transient per-turn context message sits just before the
        learner's message and is never persisted, so the next turn's prefix
        only matches up to the last durable message.
        """
        from deeptutor.services.llm.provider_core.openai_compat_provider import (
            OpenAICompatProvider,
        )

        model = str(kwargs.get("model") or "")
        if not OpenAICompatProvider.supports_prompt_caching_for(model):
            return
        if not self._binding_supports_prompt_caching():
            return
        messages, tools = OpenAICompatProvider._apply_cache_control(
            kwargs["messages"],
            kwargs.get("tools"),
            stable_history_end=True,
        )
        kwargs["messages"] = messages
        if tools is not None:
            kwargs["tools"] = tools

    def _binding_supports_prompt_caching(self) -> bool:
        """Whether this binding reaches the model through OpenAICompatProvider.

        Native Anthropic-backed bindings apply their own ``cache_control``
        inside their provider, so the loop must only add markers for the
        OpenAI-compatible path (gateways such as OpenRouter) that otherwise
        never sees them.
        """
        from deeptutor.services.provider_registry import find_by_name

        spec = find_by_name(self.pipeline.binding)
        if spec is None or not spec.supports_prompt_caching:
            return False
        return spec.backend == "openai_compat"

    async def _call_llm(
        self,
        *,
        messages: list[dict[str, Any]],
        label: str,
        call_kind: str,
        trace_role: str,
        max_tokens: int,
        tool_schemas: list[dict[str, Any]] | None = None,
        defer_visible_output: bool = False,
        tool_choice: str | None = None,
    ) -> LLMCallResult:
        prepare = getattr(self.pipeline, "prepare_model_request", None)
        lesson_messages = await prepare(self.context, self.stream, messages) if prepare else []
        request_messages = with_transient_model_messages(messages, self._transient_model_messages)
        # Current tool pixels take precedence over cached lesson pages. Neither
        # belongs in the durable dialogue; the hook runs again on forced finish.
        if lesson_messages and not has_image_parts(self._transient_model_messages):
            request_messages = [*request_messages, *lesson_messages]
        project = getattr(self.pipeline, "project_model_request", None)
        if project is not None:
            request_messages = project(request_messages)
        projected_messages = deduplicate_user_images(
            [
                {
                    key: value
                    for key, value in message.items()
                    if key not in {"_context_snapshot", "_lesson_packet"}
                }
                for message in request_messages
            ]
        )
        await self.pipeline._guard_context_window(
            projected_messages, self.stream, tool_schemas=tool_schemas
        )
        stage = self.stage
        call_id = new_call_id(f"{self.source}-{stage}")
        # Runtime-only invocation identity: reviewed mutations can require a
        # subsequent model call, rather than trust an LLM-supplied argument.
        self.context.extension("agent_loop")["model_call_id"] = call_id
        trace_meta = build_trace_metadata(
            call_id=call_id,
            phase=stage,
            label=label,
            call_kind=call_kind,
            trace_id=call_id,
            trace_role=trace_role,
            trace_group="stage",
        )
        await self.stream.progress(
            label,
            source=self.source,
            stage=stage,
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "running"},
            ),
        )

        kwargs: dict[str, Any] = {
            "model": self.pipeline.model,
            "messages": projected_messages,
            "stream": True,
            **self.pipeline._completion_kwargs(max_tokens=max_tokens),
        }
        if threads_session_id(self.pipeline.binding):
            kwargs["deeptutor_session_id"] = self.context.session_id
        if self.pipeline.usage is not None:
            kwargs["stream_options"] = {"include_usage": True}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            available_tools = {
                str((schema.get("function") or {}).get("name") or "")
                for schema in tool_schemas
                if isinstance(schema, dict)
            }
            kwargs["tool_choice"] = (
                {
                    "type": "function",
                    "function": {"name": tool_choice},
                }
                if tool_choice and tool_choice in available_tools
                else "auto"
            )
        forced_tool_choice = isinstance(kwargs.get("tool_choice"), dict)
        self._request_tools = tool_schemas
        from deeptutor.services.llm.request_cache import compare_requests, fingerprint_request

        fingerprint = fingerprint_request(
            kwargs["messages"],
            kwargs.get("tools"),
            {
                "provider": self.pipeline.binding,
                "model": self.pipeline.model,
                "base_url": getattr(self.pipeline.llm_config, "base_url", None),
                "wire_api": getattr(self.pipeline.llm_config, "wire_api", None),
            },
        )
        request_cache = compare_requests(self._request_fingerprint, fingerprint)
        self._request_fingerprint = fingerprint
        trace_meta = merge_trace_metadata(trace_meta, {"request_cache": request_cache})
        # What this request actually carried, pinned now: the loop keeps
        # appending to ``messages`` and the deferred loader keeps appending to
        # ``tool_schemas``, so the turn's context budget is read off the last
        # snapshot rather than off the lists' end state.
        #
        # The forced-finish round deliberately ships no ``tools`` so the model
        # must answer. That absence is a loop mechanic, not a turn that ran
        # without tools, so the last non-empty schema list stands — otherwise a
        # turn that spent eight rounds calling tools would report zero tokens
        # for the schemas that sat in its window the whole time.
        carried = list(tool_schemas or [])
        if not carried and self._last_request is not None:
            carried = self._last_request.tool_schemas
        self._last_request = LLMRequestSnapshot(
            messages=list(kwargs["messages"]), tool_schemas=carried
        )

        self._apply_prompt_caching(kwargs)

        chunk_meta = merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"})

        for attempt in range(len(_PROVIDER_RETRY_DELAYS) + 1):
            # Providers (esp. Gemini OpenAI-compat) may attach ``usage`` to
            # more than one stream chunk. Keep the latest frame and record it
            # once, only after a successful attempt.
            usage_seen: Any = None
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            response_output_items: list[dict[str, Any]] = []
            thinking_blocks: list[dict[str, Any]] = []
            tool_acc = ToolCallAccumulator()
            # ``ask_user``'s arguments are the card the reader is waiting on,
            # so they are previewed as they stream. Deferred rounds are the
            # one exception: their whole output is withheld until the
            # capability has ruled on it, and a card is output.
            ask_user_drafts = (
                None
                if defer_visible_output
                else AskUserDraftEmitter(
                    stream=self.stream,
                    source=self.source,
                    stage=stage,
                    metadata=trace_meta,
                )
            )
            output_chars = 0
            reasoning_chars = 0
            content_chars = 0
            tool_call_chars = 0
            call_started_at = monotonic()
            last_reasoning_progress_at = call_started_at
            action_started = False
            finish_reason = ""
            reasoning_progress_task: asyncio.Task[None] | None = None
            think_filter = InlineThinkFilter()
            # DeepSeek's Anthropic-compatible endpoint can interleave
            # user-facing prose and DSML calls in one content stream.
            dsml_filter = DSMLStreamFilter()
            visible_text_parts: list[str] = []
            output_emitted = False

            async def _emit_segments(segments: list[tuple[str, str]]) -> None:
                nonlocal action_started, content_chars, output_emitted
                nonlocal reasoning_chars
                for kind, segment in segments:
                    if kind == "thinking":
                        # Reasoning goes to the trace on every round shape.
                        # A forced tool round used to skip this whole function,
                        # which discarded the model's own inline ``<think>``
                        # block along with the prose it was written around.
                        reasoning_chars += len(segment)
                        output_emitted = True
                        await _ensure_reasoning_progress_task()
                        await self.stream.thinking(
                            segment, source=self.source, stage=stage, metadata=chunk_meta
                        )
                        await _maybe_emit_reasoning_progress()
                        continue
                    if segment.strip():
                        action_started = True
                        content_chars += len(segment)
                    output_emitted = True
                    visible_text_parts.append(segment)
                    if not defer_visible_output:
                        await self.stream.content(
                            segment, source=self.source, stage=stage, metadata=chunk_meta
                        )

            async def _maybe_emit_reasoning_progress() -> None:
                nonlocal last_reasoning_progress_at
                if action_started or reasoning_chars <= 0:
                    return
                now = monotonic()
                if now - last_reasoning_progress_at < 15.0:
                    return
                last_reasoning_progress_at = now
                await self.stream.progress(
                    self.pipeline._t(
                        "notices.reasoning_progress",
                        default=(
                            "The model is still reasoning; it has not produced an "
                            "answer or tool action yet."
                        ),
                    ),
                    source=self.source,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        trace_meta,
                        {
                            "trace_kind": "reasoning_progress",
                            "reasoning_chars": reasoning_chars,
                            "elapsed_s": round(now - call_started_at, 1),
                        },
                    ),
                )

            async def _reasoning_progress_loop() -> None:
                """Keep progress visible while a provider is between chunks."""
                while True:
                    await asyncio.sleep(15.0)
                    if action_started or reasoning_chars <= 0:
                        return
                    await _maybe_emit_reasoning_progress()

            async def _ensure_reasoning_progress_task() -> None:
                nonlocal reasoning_progress_task
                if reasoning_progress_task is None or reasoning_progress_task.done():
                    reasoning_progress_task = asyncio.create_task(_reasoning_progress_loop())

            async def _stop_reasoning_progress_task() -> None:
                nonlocal reasoning_progress_task
                task = reasoning_progress_task
                reasoning_progress_task = None
                if task is None or task.done():
                    return
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

            response_stream = None
            try:
                sent_content = [message.get("content") for message in kwargs["messages"]]
                sent_had_images = has_image_parts(kwargs["messages"])
                # The loop owns retries. Bound both connection setup and idle
                # reads so cold-start failures cannot park a durable turn.
                response_stream = await asyncio.wait_for(
                    self._create_response_stream(kwargs, trace_meta, stage),
                    _STREAM_IDLE_TIMEOUT_SECONDS,
                )
                # A declared vision capability is not evidence of delivered
                # pixels when the provider actually falls back to text.
                self.context.extension("source_visual_evidence")["image_hashes"] = (
                    image_content_hashes(kwargs["messages"])
                )
                # Retain an actual provider fallback for later rounds. The
                # request-only image deduplication must never overwrite history.
                if sent_had_images and not has_image_parts(kwargs["messages"]):
                    # Degrade all canonical copies too, including duplicates
                    # replaced only on the wire. Otherwise the next round would
                    # retry images the provider has already rejected.
                    strip_image_parts_inplace(messages)
                    strip_image_parts_inplace(self._transient_model_messages)
                else:
                    for original, accepted, sent in zip(
                        request_messages, kwargs["messages"], sent_content
                    ):
                        if "content" in accepted and accepted["content"] is not sent:
                            original["content"] = accepted["content"]
                async for chunk in _bounded_stream_chunks(response_stream):
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        usage_seen = usage
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    choice = choices[0]
                    if getattr(choice, "finish_reason", None):
                        finish_reason = str(choice.finish_reason)
                    provider_fields = getattr(choice, "provider_specific_fields", None)
                    if isinstance(provider_fields, dict):
                        # A native-provider adapter reports in-flight tool
                        # arguments here; a plain OpenAI-compatible stream
                        # reports them as ``delta.tool_calls`` fragments,
                        # handled below. Both end at the same emitter.
                        preview = provider_fields.get("tool_args_preview")
                        if isinstance(preview, dict) and ask_user_drafts is not None:
                            if str(preview.get("arguments") or ""):
                                action_started = True
                            await ask_user_drafts.observe(
                                call_id=str(preview.get("id") or ""),
                                tool_name=str(preview.get("name") or ""),
                                arguments=str(preview.get("arguments") or ""),
                            )
                        signed_blocks = provider_fields.get("thinking_blocks")
                        if isinstance(signed_blocks, list) and signed_blocks:
                            thinking_blocks = [
                                dict(block) for block in signed_blocks if isinstance(block, dict)
                            ]
                        native_items = provider_fields.get("native_output_items")
                        if isinstance(native_items, list) and any(
                            isinstance(item, dict) and item.get("type") == "reasoning"
                            for item in native_items
                        ):
                            response_output_items = [
                                dict(item) for item in native_items if isinstance(item, dict)
                            ]
                        provider_reasoning = provider_fields.get("reasoning_content")
                        if (
                            not reasoning_parts
                            and isinstance(provider_reasoning, str)
                            and provider_reasoning
                        ):
                            reasoning_parts.append(provider_reasoning)
                            reasoning_chars += len(provider_reasoning)
                            output_chars += len(provider_reasoning)
                            output_emitted = True
                            await _ensure_reasoning_progress_task()
                            await self.stream.thinking(
                                provider_reasoning,
                                source=self.source,
                                stage=stage,
                                metadata=chunk_meta,
                            )
                            await _maybe_emit_reasoning_progress()
                        if not reasoning_parts:
                            for item in native_items or []:
                                if not isinstance(item, dict) or item.get("type") != "reasoning":
                                    continue
                                item_reasoning = _reasoning_item_text(item)
                                if not item_reasoning:
                                    continue
                                reasoning_parts.append(item_reasoning)
                                reasoning_chars += len(item_reasoning)
                                output_chars += len(item_reasoning)
                                output_emitted = True
                                await _ensure_reasoning_progress_task()
                                await self.stream.thinking(
                                    item_reasoning,
                                    source=self.source,
                                    stage=stage,
                                    metadata=chunk_meta,
                                )
                                await _maybe_emit_reasoning_progress()
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue

                    reasoning_text = getattr(delta, "reasoning_content", None) or getattr(
                        delta,
                        "reasoning",
                        None,
                    )
                    if reasoning_text:
                        reasoning_parts.append(reasoning_text)
                        reasoning_chars += len(reasoning_text)
                        output_chars += len(reasoning_text)
                        output_emitted = True
                        await _ensure_reasoning_progress_task()
                        await self.stream.thinking(
                            reasoning_text, source=self.source, stage=stage, metadata=chunk_meta
                        )
                        await _maybe_emit_reasoning_progress()

                    content = getattr(delta, "content", None)
                    if content:
                        output_chars += len(content)
                        text_parts.append(content)
                        # Every round's text streams to the user; inline
                        # <think> segments remain trace-only while DSML markup
                        # and its argument payload never enter either channel.
                        visible_content = dsml_filter.feed(content)
                        if visible_content:
                            await _emit_segments(think_filter.feed(visible_content))

                    for tc_delta in getattr(delta, "tool_calls", None) or []:
                        fed_chars = tool_acc.feed(tc_delta)
                        tool_call_chars += fed_chars
                        output_chars += fed_chars
                        if fed_chars:
                            action_started = True
                        if ask_user_drafts is not None:
                            index = int(getattr(tc_delta, "index", 0) or 0)
                            part = tool_acc.part_at(index)
                            if part is not None:
                                await ask_user_drafts.observe(
                                    call_id=str(part.get("id") or f"call_{index}"),
                                    tool_name=str(part.get("name") or ""),
                                    arguments=str(part.get("arguments") or ""),
                                )
            except asyncio.CancelledError:
                if text_parts or reasoning_parts:
                    messages.append(
                        _assistant_round_message(
                            LLMCallResult(
                                text="".join(text_parts),
                                reasoning_content="".join(reasoning_parts),
                                thinking_blocks=thinking_blocks,
                            )
                        )
                    )
                raise
            except Exception as exc:
                if not is_transient_transport_error(exc):
                    if text_parts or reasoning_parts:
                        messages.append(
                            _assistant_round_message(
                                LLMCallResult(
                                    text="".join(text_parts),
                                    reasoning_content="".join(reasoning_parts),
                                    thinking_blocks=thinking_blocks,
                                )
                            )
                        )
                    raise
                can_retry = not output_emitted and attempt < len(_PROVIDER_RETRY_DELAYS)
                if can_retry:
                    logger.warning(
                        "provider stream failed before output (attempt %d/%d); retrying: %s",
                        attempt + 1,
                        len(_PROVIDER_RETRY_DELAYS) + 1,
                        exc,
                    )
                    await self.stream.progress(
                        self.pipeline._t(
                            "notices.provider_retry",
                            default="The model provider connection was interrupted; retrying.",
                        ),
                        source=self.source,
                        stage=stage,
                        metadata=merge_trace_metadata(
                            trace_meta,
                            {
                                "trace_kind": "warning",
                                "error_code": "provider_transport",
                                "retry_attempt": attempt + 1,
                            },
                        ),
                    )
                    await asyncio.sleep(_PROVIDER_RETRY_DELAYS[attempt])
                    continue

                partial_response = output_emitted
                if text_parts or reasoning_parts:
                    messages.append(
                        _assistant_round_message(
                            LLMCallResult(
                                text="".join(text_parts),
                                reasoning_content="".join(reasoning_parts),
                                thinking_blocks=thinking_blocks,
                            )
                        )
                    )
                await self.stream.progress(
                    "",
                    source=self.source,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        trace_meta,
                        {
                            "trace_kind": "call_status",
                            "call_state": "failed",
                            "error_code": "provider_transport",
                            "retryable": True,
                            "partial_response": partial_response,
                        },
                    ),
                )
                message = self.pipeline._t(
                    (
                        "notices.provider_stream_interrupted"
                        if partial_response
                        else "notices.provider_unavailable"
                    ),
                    default=(
                        "The model provider interrupted this response. Please retry."
                        if partial_response
                        else "Unable to reach the model provider. Please retry."
                    ),
                )
                if not partial_response:
                    # "Please retry" is the whole story for a cloud endpoint and
                    # none of it for a self-hosted one, where the connection was
                    # refused because nothing is listening — or because the
                    # container's own ``localhost`` is not the host running
                    # Ollama. Say which, instead of leaving the reader a bare
                    # ``ConnectError`` in the server log.
                    hint = unreachable_endpoint_hint(self.pipeline.base_url)
                    if hint:
                        message = f"{message} {hint}"
                raise LLMProviderTransportError(
                    message,
                    partial_response=partial_response,
                ) from exc
            finally:
                await _stop_reasoning_progress_task()
                close = getattr(response_stream, "close", None)
                if callable(close):
                    with suppress(Exception):
                        await close()
            break

        dsml_tail = dsml_filter.flush()
        if dsml_tail:
            await _emit_segments(think_filter.feed(dsml_tail))
        await _emit_segments(think_filter.flush())
        text = "".join(text_parts)
        usage_details = usage_breakdown(usage_seen)
        record_streamed_usage(
            self.pipeline.usage,
            usage_seen,
            input_chars=sum(message_content_chars(message) for message in messages),
            output_chars=output_chars,
        )

        tool_calls = tool_acc.collected()
        if ask_user_drafts is not None:
            # Give the previewed card its finished text before the dispatch
            # that replaces it (or, for a call that is never dispatched,
            # instead of it).
            await ask_user_drafts.settle(tool_calls)

        # Fallback: a DeepSeek deployment without native function calling emits
        # its tool calls as DSML markup in the content channel instead of as
        # structured ``tool_calls`` (issue #666). Always parse/clean the markup
        # (even if the provider also emitted native deltas); prefer native calls
        # when both representations are present to avoid double dispatch.
        dsml_calls, cleaned_text = extract_dsml_tool_calls(text, self._tool_schema_catalog)
        if dsml_calls:
            if not tool_calls:
                tool_calls = dsml_calls
            text = cleaned_text

        if forced_tool_choice and tool_choice == "ask_user" and not tool_calls:
            # A few OpenAI-compatible providers either reject tool schemas or
            # accept ``tool_choice`` and then ignore it. Ask Questions is an
            # explicit UI mode, so preserve its contract by turning the
            # model's buffered question into a local ask_user card instead of
            # silently degrading to an ordinary prose answer.
            question = clean_thinking_tags(text, self.pipeline.binding, self.pipeline.model).strip()
            if not question:
                question = self.pipeline._t(
                    "notices.ask_questions_fallback_prompt",
                    default="What is the most important goal or constraint I should account for?",
                )
            tool_calls = [
                {
                    "id": new_call_id("ask-user-fallback"),
                    "name": "ask_user",
                    "arguments": json.dumps(
                        {
                            "questions": [
                                {
                                    "id": "clarification",
                                    "prompt": question,
                                    "allow_free_text": True,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                }
            ]

        if finish_reason == "error" and not text and not tool_calls and not output_emitted:
            # An OpenAI-compatible endpoint may report failure *in band* — a
            # ``finish_reason`` of "error" on an otherwise well-formed stream —
            # rather than as an HTTP status. With no text, no tool call and
            # nothing streamed there is no round to keep, and finishing the turn
            # on it would end it as a silent empty answer. Raising instead hands
            # it to the retry path that every other transport failure takes.
            raise LLMProviderTransportError(
                self.pipeline._t(
                    "notices.provider_unavailable",
                    default="Unable to reach the model provider. Please retry.",
                ),
            )

        truncated_round = call_kind == "agent_loop_round" and _finish_was_truncated(finish_reason)
        visible_text = "".join(visible_text_parts)
        reasoning_budget_exhausted = bool(
            call_kind == "agent_loop_round"
            and not tool_calls
            and not visible_text.strip()
            and (
                reasoning_chars > 0
                or bool(reasoning_parts)
                or any(
                    isinstance(item, dict) and item.get("type") == "reasoning"
                    for item in response_output_items
                )
            )
            and str(finish_reason or "").strip().lower() != "content_filter"
            and (
                truncated_round
                or (usage_details.get("completion_tokens", 0) >= max(1, int(max_tokens)))
            )
        )
        completion_metadata: dict[str, Any] = {
            "trace_kind": "call_status",
            "call_state": "complete",
            # ``call_role`` states this round's PHASE, not whether its text is
            # shown: ``narration`` is mid-turn commentary (more work follows),
            # ``finish`` is the terminal round. Token-truncated output is
            # visible but not terminal, so it stays ``narration``.
            "call_role": "narration" if tool_calls or truncated_round else "finish",
            # Every round's prose belongs to the answer, in the order it was
            # written. Commentary written before a tool call is what the reader
            # is told while the work happens, not an internal preamble to hide,
            # and a capability finish check must never retract it.
            "answer_visible": True,
            "finish_reason": finish_reason or "stop",
            "requested_max_tokens": int(max_tokens),
            "usage_reported": bool(usage_details),
            "output_chars": output_chars,
            "reasoning_chars": reasoning_chars,
            "content_chars": content_chars,
            "tool_call_chars": tool_call_chars,
            "tool_call_count": len(tool_calls),
        }
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
            completion_metadata[key] = usage_details.get(key, "unavailable")
        if reasoning_budget_exhausted:
            completion_metadata["reasoning_budget_exhausted"] = True
        log_line = (
            "agent_loop_round_complete model=%s call_id=%s finish_reason=%s "
            "requested_max_tokens=%d usage_reported=%s prompt_tokens=%s "
            "completion_tokens=%s reasoning_tokens=%s output_chars=%d "
            "reasoning_chars=%d content_chars=%d tool_call_chars=%d tool_call_count=%d"
        )
        log_args = (
            self.pipeline.model,
            call_id,
            finish_reason or "stop",
            int(max_tokens),
            bool(usage_details),
            usage_details.get("prompt_tokens", "unavailable"),
            usage_details.get("completion_tokens", "unavailable"),
            usage_details.get("reasoning_tokens", "unavailable"),
            output_chars,
            reasoning_chars,
            content_chars,
            tool_call_chars,
            len(tool_calls),
        )
        if (
            truncated_round
            or reasoning_budget_exhausted
            or (not tool_calls and not visible_text.strip())
        ):
            logger.warning(log_line, *log_args)
        else:
            logger.info(log_line, *log_args)

        completion_event_metadata = merge_trace_metadata(trace_meta, completion_metadata)
        if not defer_visible_output:
            await self.stream.progress(
                "",
                source=self.source,
                stage=stage,
                metadata=completion_event_metadata,
            )
        return LLMCallResult(
            text=text,
            visible_text=visible_text,
            response_output_items=response_output_items,
            reasoning_content="".join(reasoning_parts),
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
            usage=usage_details,
            output_chars=output_chars,
            reasoning_chars=reasoning_chars,
            content_chars=content_chars,
            tool_call_chars=tool_call_chars,
            finish_reason=finish_reason,
            completion_metadata=completion_event_metadata,
            deferred_chunk_metadata=chunk_meta if defer_visible_output else None,
            deferred_completion_metadata=(
                completion_event_metadata if defer_visible_output else None
            ),
        )

    async def _single_shot_stream(self, kwargs: dict[str, Any]) -> Any:
        """Serve a non-streaming endpoint through the streaming consumer.

        The round loses its typing effect and nothing else: tool-call deltas,
        usage and finish reason are all reported through the same shapes the
        consumer already reads, so one chunk carrying the whole completion is
        indistinguishable from a stream that happened to arrive at once.
        """
        request = dict(kwargs)
        request["stream"] = False
        request.pop("stream_options", None)
        response = await self.client.chat.completions.create(**request)
        return _single_chunk_stream(response)

    async def _create_response_stream(
        self,
        kwargs: dict[str, Any],
        trace_meta: dict[str, Any],
        stage: str,
    ) -> Any:
        if kwargs.get("stream") and not supports_streaming(
            self.pipeline.binding, self.pipeline.model
        ):
            # An endpoint declared as non-streaming used to be sent
            # ``stream: True`` anyway — the capability flag existed but nothing
            # ever read it — so such a provider failed the turn outright
            # instead of answering in one piece.
            return await self._single_shot_stream(kwargs)
        try:
            return await self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            if (
                kwargs.get("tools")
                and kwargs.get("tool_choice") != "auto"
                and is_forced_tool_choice_unsupported(exc)
            ):
                # Some thinking models reject a forced choice while supporting
                # the schemas themselves. Keep the tool surface and its cache.
                retry_kwargs = {**kwargs, "tool_choice": "auto"}
                return await self._create_response_stream(retry_kwargs, trace_meta, stage)
            if kwargs.get("tools") and is_tool_schema_unsupported(exc):
                # Capture the provider's raw rejection body. Without it there is
                # no way to tell *which* parameter/shape a new model family
                # objects to — the fallback below silently strips tools and the
                # model degrades to prose with no visible error (see #708:
                # gpt-5.6-luna/-terra/-sol 400 on tools, root cause still
                # unconfirmed for lack of this exact log line).
                logger.warning(
                    "provider rejected tool schemas for model=%s; retrying without tools. error=%s",
                    kwargs.get("model"),
                    logged_error_text(exc),
                )
                await self.stream.progress(
                    self.pipeline._t(
                        "notices.tool_schema_fallback",
                        default="Provider rejected native tool schemas; retrying without tools.",
                    ),
                    source=self.source,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        trace_meta,
                        {"trace_kind": "warning", "tool_schema_fallback": True},
                    ),
                )
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("tools", None)
                retry_kwargs.pop("tool_choice", None)
                self.tool_schemas = None
                self._request_tools = None
                return await self.client.chat.completions.create(**retry_kwargs)
            if "stream_options" in kwargs and is_stream_options_unsupported(exc):
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("stream_options", None)
                return await self.client.chat.completions.create(**retry_kwargs)
            if is_image_input_unsupported(exc) and should_degrade_to_text(
                self.pipeline.binding,
                self.pipeline.model,
                kwargs.get("messages") or [],
            ):
                strip_image_parts_inplace(kwargs["messages"])
                await self.stream.progress(
                    self.pipeline._t(
                        "notices.image_fallback",
                        default="Model does not support image input; retrying without images.",
                    ),
                    source=self.source,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        trace_meta,
                        {"trace_kind": "warning", "image_fallback": True},
                    ),
                )
                return await self.client.chat.completions.create(**kwargs)
            raise


async def _single_chunk_stream(response: Any) -> Any:
    """Replay one completion as the single chunk of a stream."""
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    message = getattr(choice, "message", None)
    tool_calls = [
        SimpleNamespace(
            index=index,
            id=getattr(call, "id", ""),
            extra_content=getattr(call, "extra_content", None),
            function=SimpleNamespace(
                name=getattr(getattr(call, "function", None), "name", ""),
                arguments=getattr(getattr(call, "function", None), "arguments", "") or "",
            ),
        )
        for index, call in enumerate(getattr(message, "tool_calls", None) or [])
    ]
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=getattr(message, "content", None),
                    reasoning_content=getattr(message, "reasoning_content", None),
                    tool_calls=tool_calls or None,
                ),
                finish_reason=getattr(choice, "finish_reason", None),
                provider_specific_fields=getattr(message, "provider_specific_fields", None),
            )
        ],
        usage=getattr(response, "usage", None),
    )


def _last_context_checkpoint(dispatch: DispatchOutcome) -> tuple[str, str]:
    """``(summary, state)`` of the round's last checkpoint.

    ``summary`` is history the fold keeps; ``state`` is the optional current
    state that replaces the previous fold's copy instead of stacking with it.
    """
    summary, state = "", ""
    for tool_message in dispatch.tool_messages:
        tool_call_id = str(tool_message.get("tool_call_id") or "")
        metadata = dispatch.tool_metadata_by_id.get(tool_call_id) or {}
        checkpoint = metadata.get("_context_checkpoint")
        if not isinstance(checkpoint, dict):
            continue
        candidate = str(checkpoint.get("summary") or "").strip()
        if candidate:
            summary = candidate
            state = str(checkpoint.get("state") or "").strip()
    return summary, state


__all__ = [
    "AgentLoop",
    "AgentLoopState",
    "InlineThinkFilter",
    "LLMCallResult",
    "LOOP_STAGE",
    "LoopOutcome",
]
