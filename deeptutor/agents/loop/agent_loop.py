"""Single-loop chat agent.

One chat turn = ONE agent loop over a single growing conversation:

* each round is one LLM call; its text streams to the user as a ``content``
  block, and its tool calls are dispatched with their ``role=tool`` results
  appended back into the conversation;
* a round that DOES call tools is "narration" by default — its text is a
  preamble to the tool work — and the loop continues; modes that intentionally
  combine learner-facing prose with a tool call mark that prose answer-visible;
* a round that calls NO tools is the ``finish``: its text IS the final
  user-facing answer and the loop ends (the model deciding it is done; a
  first round without tool calls is the "no exploration needed" fast path);
* if the exploration budget runs out while work is still in protocol, a
  small bounded settlement phase keeps tools available for already-started
  follow-up (including user input); one final tool-less round is forced only
  after that settlement allowance is exhausted.

``ask_user`` pauses the turn for a reply and resumes in-protocol; an
unresolved pause (or a terminator tool) halts the turn.

There is no separate respond pass and no text destination has to be guessed
mid-stream: every round's text streams to the user as it is generated, and a
``call_role`` (``narration`` vs ``finish``) emitted when the round completes
tells the frontend how to render that round's text.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.agents.loop.ask_user_drafts import AskUserDraftEmitter
from deeptutor.agents.loop.context_budget import LLMRequestSnapshot
from deeptutor.agents.loop.dsml_tool_calls import DSMLStreamFilter, extract_dsml_tool_calls
from deeptutor.core.context import UnifiedContext
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id
from deeptutor.runtime.agentic.messages import assistant_message_with_tool_calls
from deeptutor.runtime.agentic.think_stream import InlineThinkFilter
from deeptutor.runtime.agentic.tool_call_stream import ToolCallAccumulator
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.runtime.agentic.usage import message_content_chars, record_streamed_usage
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm import (
    LLMProviderTransportError,
    clean_thinking_tags,
    supports_streaming,
)
from deeptutor.services.llm.capabilities import threads_session_id
from deeptutor.services.llm.multimodal import should_degrade_to_text, strip_image_parts_inplace
from deeptutor.services.llm.request_compat import (
    is_image_input_unsupported,
    is_stream_options_unsupported,
    is_tool_schema_unsupported,
    is_transient_transport_error,
    logged_error_text,
)
from deeptutor.services.session.provider_response_state import (
    normalize_provider_response_state,
)

if TYPE_CHECKING:  # pragma: no cover
    from deeptutor.agents.loop.pipeline import AgenticLoopPipeline

logger = logging.getLogger(__name__)

# The loop runs over a single conversation. Its configured round budget covers
# exploration; bounded settlement and the emergency hard finish are separate.
LOOP_STAGE = "responding"
# Settlement is deliberately small but large enough for the longest built-in
# interaction boundary: register state -> ask/resume -> record result -> reply.
# A single additional tool-less hard finish follows if all of these rounds
# still request tools, making the total upper bound ``exploration + 4``.
MAX_SETTLEMENT_ROUNDS = 3
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})
# The SDK already retries failures that happen before response headers. These
# short outer retries also cover SSE connections that fail before yielding any
# user-visible output. Once output is visible, replay is unsafe because it can
# duplicate prose or tool calls.
_PROVIDER_RETRY_DELAYS = (0.5, 1.5)


def _finish_was_truncated(reason: str | None) -> bool:
    """Return whether a provider ended generation because output hit a cap."""
    return str(reason or "").strip().lower() in _TRUNCATED_FINISH_REASONS


def _join_answer_parts(parts: list[str], final_text: str) -> str:
    """Build the canonical answer returned by RESULT across continuations."""
    return "".join([*parts, final_text])


@dataclass(slots=True)
class AgentLoopState:
    """Turn-level counters shared across the loop's rounds."""

    rounds: int = 0
    exploration_rounds: int = 0
    settlement_rounds: int = 0
    tool_steps: int = 0
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class LLMCallResult:
    text: str
    visible_text: str = ""
    response_output_items: list[dict[str, Any]] = field(default_factory=list)
    reasoning_content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # Anthropic's signed thinking blocks, replayed verbatim on the next round.
    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    # This round's ``call_status`` metadata, set whether or not the round was
    # buffered. A streamed round needs it to publish a correction when its
    # finish is later rejected; the ``deferred_*`` pair below is set only while
    # the text is still withheld.
    completion_metadata: dict[str, Any] | None = None
    deferred_chunk_metadata: dict[str, Any] | None = None
    deferred_completion_metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class LoopOutcome:
    """Result of running the turn's loop.

    ``final_text`` is the user-facing answer (the finish round's text, or a
    terminator tool's content). ``completed`` is False only when the turn
    halted on an unresolved ``ask_user`` pause — the pending question is then
    the turn's final artefact.
    """

    final_text: str = ""
    completed: bool = False
    provider_response_state: dict[str, Any] | None = None


def _provider_response_state(
    response_output_items: list[dict[str, Any]],
    reasoning_content: str,
    thinking_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    state: dict[str, Any] = {}
    if response_output_items:
        state["responses_output_items"] = response_output_items
    if reasoning_content:
        state["reasoning_content"] = reasoning_content
    if thinking_blocks:
        state["thinking_blocks"] = thinking_blocks
    return normalize_provider_response_state(state)


def _assistant_round_message(result: LLMCallResult) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": result.text}
    state = _provider_response_state(
        result.response_output_items,
        result.reasoning_content,
        result.thinking_blocks,
    )
    if state is not None:
        message["_provider_response_state"] = state
    if result.thinking_blocks:
        # Replayed on the message itself as well as in the private state: the
        # provider reads this field directly when the round is still in this
        # turn's working set, and rebuilds it from the state for history.
        message["thinking_blocks"] = result.thinking_blocks
    if result.reasoning_content:
        # Some chat-completions reasoning models require this field on the
        # immediately following round. Historical turns rebuild it from the
        # private provider state instead.
        message["reasoning_content"] = result.reasoning_content
    return message


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
            outcome = await self._run_loop(
                messages=messages,
                state=state,
                checkpoint_boundary=len(messages),
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
            "rounds": state.rounds,
            "settlement_rounds": state.settlement_rounds,
            "tool_steps": state.tool_steps,
        }
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
    ) -> LoopOutcome:
        """Run rounds of one LLM call + tool dispatch over *messages*.

        A round with tool calls keeps its assistant message (text + tool
        calls) and the ``role=tool`` results in-conversation, then continues.
        A round with no tool calls is the finish: its text — already streamed
        to the user — is the answer, and the loop ends.
        """
        explore_label = self.pipeline._t("labels.exploring", default="Exploring")
        settlement_label = self.pipeline._t("labels.final_response", default="Final response")
        exploration_budget = max(1, self.pipeline.effective_max_rounds(self.context))
        settlement_started = False
        nudged_empty_finish = False
        finish_redirect_used = False
        continued_answer_parts: list[str] = []
        while True:
            settling = state.exploration_rounds >= exploration_budget
            if settling:
                if state.settlement_rounds >= MAX_SETTLEMENT_ROUNDS:
                    # A model may ignore the settlement directive and keep
                    # requesting tools. One tool-less call is the absolute
                    # stop, so malformed/empty tool cycles cannot run forever.
                    return await self._forced_finish(
                        messages,
                        state,
                        continued_answer_parts=continued_answer_parts,
                    )
                if not settlement_started:
                    await self._begin_settlement(messages)
                    settlement_started = True
            try:
                result = await self._call_llm(
                    messages=messages,
                    label=settlement_label if settling else explore_label,
                    call_kind="agent_loop_round",
                    trace_role="response" if settling else "explore",
                    max_tokens=self.pipeline.loop_max_tokens,
                    tool_schemas=self.tool_schemas,
                    defer_visible_output=self.pipeline._capability_buffers_visible_output(
                        self.context
                    ),
                    tool_choice=(self.pipeline.initial_tool_choice if state.rounds == 0 else None),
                )
            except Exception as exc:
                # A mid-loop LLM failure (timeout / transient network) must not
                # discard a turn that already gathered useful work. Salvage it
                # with a forced finish; only a failure on the very first round
                # (nothing gathered yet) propagates as before. Once a failed
                # stream emitted output, however, replay is unsafe: a second
                # completion would mix new prose with the visible partial one.
                if state.rounds == 0 or (
                    isinstance(exc, LLMProviderTransportError) and exc.partial_response
                ):
                    raise
                logger.warning(
                    "agent loop round failed after %d round(s); forcing finish: %s",
                    state.rounds,
                    exc,
                )
                return await self._forced_finish(
                    messages,
                    state,
                    reason="error",
                    continued_answer_parts=continued_answer_parts,
                )
            state.rounds += 1
            if settling:
                state.settlement_rounds += 1
            else:
                state.exploration_rounds += 1
            if not result.tool_calls:
                final_text = self._clean(result.text)
                if _finish_was_truncated(result.finish_reason):
                    # ``length`` is an incomplete generation, not the model's
                    # decision to finish. Keep its visible prefix in protocol
                    # and ask for a continuation. The ordinary exploration /
                    # settlement counters still apply, so repeated truncation
                    # has the same hard upper bound as repeated tool calls.
                    await self._release_deferred_output(result)
                    await self.stream.progress(
                        self.pipeline._t(
                            "notices.output_truncated",
                            default=(
                                "The model output reached its token limit; asked it to continue."
                            ),
                        ),
                        source=self.source,
                        stage=self.stage,
                        metadata={"trace_kind": "warning"},
                    )
                    if result.visible_text:
                        continued_answer_parts.append(result.visible_text)
                    if result.text:
                        messages.append(_assistant_round_message(result))
                    if result.visible_text:
                        instruction = self.pipeline._t(
                            "loop.continue_truncated",
                            default=(
                                "Your previous response stopped at the token limit. "
                                "Continue from where it ended without repeating it, "
                                "and complete the user-facing answer."
                            ),
                        )
                    else:
                        # Nothing visible was produced: the whole budget went to
                        # reasoning. "Continue from where it ended" is then the
                        # wrong instruction — there is no visible end to continue
                        # from, and a model that reasoned itself out of budget
                        # once will do it again on the same prompt. This is the
                        # shape a reasoning model falls into when it keeps
                        # revising a plan it had already settled: rounds burn,
                        # nothing reaches the reader, and the turn looks stuck.
                        instruction = self.pipeline._t(
                            "loop.continue_truncated_reasoning",
                            default=(
                                "Your previous round spent its entire output budget "
                                "on internal reasoning and hit the token limit "
                                "before writing anything — so there is nothing to "
                                "continue from, and reasoning it through again will "
                                "end the same way. Act now instead: make the tool "
                                "call, or write the answer with the judgement you "
                                "already have. Good enough is required; optimal is "
                                "not. Do not redesign or second-guess what you had "
                                "already settled on."
                            ),
                        )
                    self._append_loop_instruction(messages, instruction)
                    continue
                if not final_text and not nudged_empty_finish:
                    # The round produced only internal reasoning (e.g. the
                    # whole reply inside <think>) — the model planned but
                    # never acted. Keep its raw text in-conversation (the
                    # plan/script lives there) and nudge it once to act
                    # instead of falling back to an empty answer.
                    nudged_empty_finish = True
                    await self.stream.progress(
                        self.pipeline._t(
                            "notices.empty_finish_nudged",
                            default=(
                                "The round produced only internal reasoning; "
                                "asked the model to continue."
                            ),
                        ),
                        source=self.source,
                        stage=self.stage,
                        metadata={"trace_kind": "warning"},
                    )
                    if result.text:
                        messages.append(_assistant_round_message(result))
                    self._append_loop_instruction(
                        messages,
                        self.pipeline._t(
                            "loop.finish_empty_nudge",
                            default=(
                                "Your previous round produced only internal "
                                "reasoning — no tool call and no user-facing "
                                "answer. Continue now: either call the tools "
                                "to execute your plan, or write the final "
                                "user-facing answer directly."
                            ),
                        ),
                    )
                    continue
                finish_redirect = self.pipeline._capability_finish_instruction(
                    self.context, final_text
                )
                if finish_redirect:
                    await self._discard_deferred_output(result)
                    if not finish_redirect_used:
                        finish_redirect_used = True
                        if result.text:
                            messages.append(_assistant_round_message(result))
                        self._append_loop_instruction(messages, finish_redirect)
                        continue
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
                final_override = self.pipeline._capability_final_text_override(
                    self.context, final_text
                )
                if final_override is not None:
                    await self._discard_deferred_output(result)
                    if not self.context.capability_output.answer_published:
                        await self.pipeline._emit_protocol_fallback_final_response(
                            self.stream, final_override
                        )
                        self.context.capability_output.answer_published = True
                    return await self._finalize_finish(
                        final_override,
                        continued_answer_parts=continued_answer_parts,
                        allow_empty=True,
                    )
                await self._release_deferred_output(result)
                # Finish: the text streamed live this round IS the answer.
                return await self._finalize_finish(
                    final_text,
                    visible_text=result.visible_text,
                    continued_answer_parts=continued_answer_parts,
                    provider_response_state=_provider_response_state(
                        result.response_output_items,
                        result.reasoning_content,
                        result.thinking_blocks,
                    ),
                )

            tool_names = tuple(str(call.get("name") or "") for call in result.tool_calls)
            output_policy = self.pipeline._capability_tool_round_output_policy(
                self.context,
                self._clean(result.text),
                tool_names,
            )
            if output_policy == "discard":
                await self._discard_deferred_output(result)
            else:
                if output_policy == "publish" and result.deferred_completion_metadata is not None:
                    result.deferred_completion_metadata["answer_visible"] = True
                await self._release_deferred_output(result)
            assistant = assistant_message_with_tool_calls(
                result.text,
                result.tool_calls,
                reasoning_content=result.reasoning_content or None,
                thinking_blocks=result.thinking_blocks or None,
            )
            provider_state = _provider_response_state(
                result.response_output_items,
                result.reasoning_content,
                result.thinking_blocks,
            )
            if provider_state is not None:
                assistant["_provider_response_state"] = provider_state
            messages.append(assistant)
            dispatch = await self.pipeline._dispatch_tool_calls(
                tool_calls=result.tool_calls,
                context=self.context,
                stream=self.stream,
                iteration_index=state.tool_steps,
                stage=self.stage,
            )
            state.tool_steps += 1
            state.sources.extend(dispatch.sources)
            messages.extend(dispatch.tool_messages)

            if dispatch.pause:
                resumed = await self.pipeline._await_user_reply_and_resolve(
                    context=self.context,
                    stream=self.stream,
                    dispatch=dispatch,
                )
                if not resumed:
                    # The pending question is already the turn's final
                    # artefact (or the user abandoned the turn) — stop.
                    return LoopOutcome(final_text="", completed=False)
                # The user's answers were substituted into the matching
                # ``role=tool`` message; the next round sees them in-protocol.
                continue

            checkpoint_boundary = self._fold_context_checkpoint(
                messages=messages,
                dispatch=dispatch,
                checkpoint_boundary=checkpoint_boundary,
            )

            final_override = self.pipeline._capability_final_text_override(self.context, "")
            if final_override is not None:
                if not self.context.capability_output.answer_published:
                    await self.pipeline._emit_protocol_fallback_final_response(
                        self.stream, final_override
                    )
                    self.context.capability_output.answer_published = True
                return await self._finalize_finish(
                    final_override,
                    continued_answer_parts=continued_answer_parts,
                    allow_empty=True,
                )

            if dispatch.terminate:
                payload = dispatch.terminate_payload or {}
                await self.pipeline._emit_terminator_final_response(self.stream, payload)
                terminal_text = str(payload.get("content") or "")
                return LoopOutcome(
                    final_text=_join_answer_parts(continued_answer_parts, terminal_text),
                    completed=True,
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
            prior = str(messages[-1].get("content") or "").rstrip()
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
        summary = _last_context_checkpoint_summary(dispatch)
        if not summary:
            return checkpoint_boundary
        prefix = messages[:checkpoint_boundary]
        prefix.append(
            {
                "role": "system",
                "content": f"[Context checkpoint]\n{summary}",
            }
        )
        messages[:] = prefix
        return len(messages)

    async def _forced_finish(
        self,
        messages: list[dict[str, Any]],
        state: AgentLoopState,
        *,
        reason: str = "budget",
        continued_answer_parts: list[str] | None = None,
    ) -> LoopOutcome:
        if reason == "error":
            notice = self.pipeline._t(
                "notices.loop_error_finish",
                default="A step failed; answering with what has been gathered.",
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
            # The salvage call itself failed (e.g. the provider is still
            # returning unusable data). Don't bubble up and lose the turn —
            # emit the graceful fallback answer instead.
            logger.warning("forced-finish LLM call failed: %s", exc)
            return await self._finalize_finish(
                "",
                continued_answer_parts=continued_answer_parts,
            )
        state.rounds += 1
        return await self._finalize_finish(
            result.text,
            visible_text=result.visible_text,
            continued_answer_parts=continued_answer_parts,
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
        """Take a rejected round's prose back out of the answer.

        Two shapes reach here. A *buffered* round is simply never published:
        closing its trace as ``narration`` is the whole retraction. A round
        that already **streamed** — the ordinary case now that only protocol
        capabilities buffer — was published optimistically and closed as
        ``finish``, so its retraction has to be a correction: the same
        ``call_id``, re-marked ``narration``, which is what moves that text out
        of the answer and into the collapsed trace on the reader's side.

        Emitting nothing in that second case was what left rejected prose
        sitting in the answer as though it had been accepted.
        """
        metadata = result.deferred_completion_metadata or result.completion_metadata
        if metadata is not None:
            metadata = dict(metadata)
            metadata["call_role"] = "narration"
            metadata.pop("answer_visible", None)
            metadata["finish_rejected"] = True
            await self.stream.progress(
                "",
                source=self.source,
                stage=self.stage,
                metadata=metadata,
            )
        result.completion_metadata = None
        result.deferred_chunk_metadata = None
        result.deferred_completion_metadata = None

    # ---- LLM call ----------------------------------------------------------

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
        await self.pipeline._guard_context_window(messages, self.stream)
        stage = self.stage
        call_id = new_call_id(f"{self.source}-{stage}")
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
            "messages": messages,
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
        self._last_request = LLMRequestSnapshot(messages=list(messages), tool_schemas=carried)

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
            finish_reason = ""
            think_filter = InlineThinkFilter()
            # DeepSeek's Anthropic-compatible endpoint can interleave
            # user-facing prose and DSML calls in one content stream.
            dsml_filter = DSMLStreamFilter()
            answer_content_emitted = False
            visible_text_parts: list[str] = []
            output_emitted = False

            async def _emit_segments(segments: list[tuple[str, str]]) -> None:
                nonlocal answer_content_emitted, output_emitted
                for kind, segment in segments:
                    if kind == "thinking":
                        # Reasoning goes to the trace on every round shape.
                        # A forced tool round used to skip this whole function,
                        # which discarded the model's own inline ``<think>``
                        # block along with the prose it was written around.
                        output_emitted = True
                        await self.stream.thinking(
                            segment, source=self.source, stage=stage, metadata=chunk_meta
                        )
                        continue
                    if forced_tool_choice:
                        # This round exists to produce a call, so its prose is
                        # not an answer and must not reach the reader — but
                        # that is a rule about *content*, not about reasoning.
                        continue
                    output_emitted = True
                    visible_text_parts.append(segment)
                    if segment.strip():
                        answer_content_emitted = True
                    if not defer_visible_output:
                        await self.stream.content(
                            segment, source=self.source, stage=stage, metadata=chunk_meta
                        )

            response_stream = None
            try:
                response_stream = await self._create_response_stream(kwargs, trace_meta, stage)
                async for chunk in response_stream:
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
                        output_chars += len(reasoning_text)
                        output_emitted = True
                        await self.stream.thinking(
                            reasoning_text, source=self.source, stage=stage, metadata=chunk_meta
                        )

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
                        output_chars += tool_acc.feed(tc_delta)
                        if ask_user_drafts is not None:
                            index = int(getattr(tc_delta, "index", 0) or 0)
                            part = tool_acc.part_at(index)
                            if part is not None:
                                await ask_user_drafts.observe(
                                    call_id=str(part.get("id") or f"call_{index}"),
                                    tool_name=str(part.get("name") or ""),
                                    arguments=str(part.get("arguments") or ""),
                                )
            except Exception as exc:
                if not is_transient_transport_error(exc):
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
                raise LLMProviderTransportError(
                    message,
                    partial_response=partial_response,
                ) from exc
            finally:
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
        completion_metadata: dict[str, Any] = {
            "trace_kind": "call_status",
            "call_state": "complete",
            # A round with tool calls is narration; a tool-less round is the
            # finish whose text is the user-facing answer. Token-truncated
            # output remains visible but is not terminal: the loop continues.
            "call_role": "narration" if tool_calls or truncated_round else "finish",
        }
        mastery_tool_round = bool(tool_calls) and bool(self.context.metadata.get("mastery_mode"))
        if (dsml_calls or truncated_round or mastery_tool_round) and answer_content_emitted:
            # DSML providers may intentionally combine tutor feedback and an
            # ask_user/tool call in the same round. Preserve only that cleaned
            # surrounding prose in the answer surfaces. Truncated rounds also
            # keep their partial answer visible while retaining a truthful
            # non-terminal ``narration`` role. Mastery rounds likewise combine
            # learner-facing teaching with state/quiz tools; that teaching is
            # answer content, not an internal tool preamble.
            completion_metadata["answer_visible"] = True

        completion_event_metadata = merge_trace_metadata(trace_meta, completion_metadata)
        if forced_tool_choice and not tool_calls and text:
            # Some compatibility providers accept ``tool_choice`` but ignore
            # it. Do not lose their answer merely because it was buffered.
            fallback_dsml = DSMLStreamFilter()
            fallback_filter = InlineThinkFilter()
            visible = fallback_dsml.feed(text) + fallback_dsml.flush()
            await _emit_segments(fallback_filter.feed(visible) + fallback_filter.flush())

        if not defer_visible_output:
            await self.stream.progress(
                "",
                source=self.source,
                stage=stage,
                metadata=completion_event_metadata,
            )
        return LLMCallResult(
            text=text,
            visible_text="".join(visible_text_parts),
            response_output_items=response_output_items,
            reasoning_content="".join(reasoning_parts),
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
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


def _last_context_checkpoint_summary(dispatch: DispatchOutcome) -> str:
    summary = ""
    for tool_message in dispatch.tool_messages:
        tool_call_id = str(tool_message.get("tool_call_id") or "")
        metadata = dispatch.tool_metadata_by_id.get(tool_call_id) or {}
        checkpoint = metadata.get("_context_checkpoint")
        if not isinstance(checkpoint, dict):
            continue
        candidate = str(checkpoint.get("summary") or "").strip()
        if candidate:
            summary = candidate
    return summary


__all__ = [
    "AgentLoop",
    "AgentLoopState",
    "InlineThinkFilter",
    "LLMCallResult",
    "LOOP_STAGE",
    "LoopOutcome",
]
