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
import re
from typing import TYPE_CHECKING, Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.agents.chat.context_budget import LLMRequestSnapshot
from deeptutor.agents.chat.dsml_tool_calls import DSMLStreamFilter, extract_dsml_tool_calls
from deeptutor.core.agentic.messages import assistant_message_with_tool_calls
from deeptutor.core.agentic.tool_call_stream import ToolCallAccumulator
from deeptutor.core.agentic.tool_dispatch import DispatchOutcome
from deeptutor.core.agentic.usage import message_content_chars, record_streamed_usage
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id
from deeptutor.services.llm import LLMProviderTransportError, clean_thinking_tags
from deeptutor.services.llm.capabilities import threads_session_id
from deeptutor.services.llm.multimodal import should_degrade_to_text, strip_image_parts_inplace
from deeptutor.services.llm.request_compat import (
    is_image_input_unsupported,
    is_stream_options_unsupported,
    is_tool_schema_unsupported,
    is_transient_transport_error,
    logged_error_text,
)

if TYPE_CHECKING:  # pragma: no cover
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline

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

_THINK_OPEN_RE = re.compile(r"<\s*think(?:ing)?\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"<\s*/\s*think(?:ing)?\s*>", re.IGNORECASE)
# Longest partial tag worth waiting a chunk for (e.g. "</thinking" + slack).
_TAG_HOLDBACK_CHARS = 24


def _finish_was_truncated(reason: str | None) -> bool:
    """Return whether a provider ended generation because output hit a cap."""
    return str(reason or "").strip().lower() in _TRUNCATED_FINISH_REASONS


def _join_answer_parts(parts: list[str], final_text: str) -> str:
    """Build the canonical answer returned by RESULT across continuations."""
    return "".join([*parts, final_text])


class InlineThinkFilter:
    """Incremental ``<think>``/``<thinking>`` splitter for streamed content.

    Some providers surface reasoning inline in the *content* channel (instead
    of ``reasoning_content``), wrapped in think tags. Splitting at streaming
    time keeps the user-facing content channel clean everywhere downstream —
    the live bubble, the persisted message, and the loop's finish detection —
    in one place. The raw text (tags included) still goes back into the LLM
    conversation untouched.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """Consume *chunk*; return ``(kind, text)`` segments, kind in
        ``{"content", "thinking"}``. May hold back a partial trailing tag
        until the next chunk (``flush`` releases it at stream end)."""
        self._buffer += chunk
        segments: list[tuple[str, str]] = []
        while True:
            pattern = _THINK_CLOSE_RE if self._in_think else _THINK_OPEN_RE
            match = pattern.search(self._buffer)
            if match is None:
                break
            if match.start() > 0:
                segments.append((self._kind(), self._buffer[: match.start()]))
            self._buffer = self._buffer[match.end() :]
            self._in_think = not self._in_think
        emit_upto = len(self._buffer)
        tag_start = self._buffer.rfind("<")
        if (
            tag_start != -1
            and len(self._buffer) - tag_start <= _TAG_HOLDBACK_CHARS
            and ">" not in self._buffer[tag_start:]
        ):
            emit_upto = tag_start
        if emit_upto > 0:
            segments.append((self._kind(), self._buffer[:emit_upto]))
            self._buffer = self._buffer[emit_upto:]
        return segments

    def flush(self) -> list[tuple[str, str]]:
        """Release whatever is still buffered (stream ended)."""
        if not self._buffer:
            return []
        segments = [(self._kind(), self._buffer)]
        self._buffer = ""
        return segments

    def _kind(self) -> str:
        return "thinking" if self._in_think else "content"


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
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
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


class AgentLoop:
    """Run one chat turn as a single agent loop over one conversation."""

    def __init__(
        self,
        *,
        pipeline: "AgenticChatPipeline",
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

    async def run(self) -> None:
        state = AgentLoopState()
        # Optional async pre-pass briefings (e.g. explore_context) run BEFORE
        # the answer stage so they form their own preceding activity group and
        # their grounding can ride in the loop's user-message seed.
        capability_briefing = await self.pipeline._capability_pre_loop_briefings(
            self.context, self.stream
        )
        async with self.stream.stage(LOOP_STAGE, source="chat"):
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

        if state.sources:
            await self.stream.sources(
                state.sources,
                source="chat",
                stage=LOOP_STAGE,
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
        await emit_capability_result(
            self.stream,
            payload,
            source="chat",
            usage=self.pipeline.usage,
        )

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
                    defer_visible_output=self.pipeline._has_capability_finish_guard(self.context),
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
                        source="chat",
                        stage=LOOP_STAGE,
                        metadata={"trace_kind": "warning"},
                    )
                    if result.visible_text:
                        continued_answer_parts.append(result.visible_text)
                    if result.text:
                        messages.append({"role": "assistant", "content": result.text})
                    self._append_loop_instruction(
                        messages,
                        self.pipeline._t(
                            "loop.continue_truncated",
                            default=(
                                "Your previous response stopped at the token limit. "
                                "Continue from where it ended without repeating it, "
                                "and complete the user-facing answer."
                            ),
                        ),
                    )
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
                        source="chat",
                        stage=LOOP_STAGE,
                        metadata={"trace_kind": "warning"},
                    )
                    if result.text:
                        messages.append({"role": "assistant", "content": result.text})
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
                            messages.append({"role": "assistant", "content": result.text})
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
                        source="chat",
                        stage=LOOP_STAGE,
                        metadata={"trace_kind": "warning"},
                    )
                    return LoopOutcome(final_text="", completed=False)
                await self._release_deferred_output(result)
                # Finish: the text streamed live this round IS the answer.
                return await self._finalize_finish(
                    final_text,
                    visible_text=result.visible_text,
                    continued_answer_parts=continued_answer_parts,
                )

            await self._release_deferred_output(result)
            messages.append(assistant_message_with_tool_calls(result.text, result.tool_calls))
            dispatch = await self.pipeline._dispatch_tool_calls(
                tool_calls=result.tool_calls,
                context=self.context,
                stream=self.stream,
                iteration_index=state.tool_steps,
                stage=LOOP_STAGE,
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
            source="chat",
            stage=LOOP_STAGE,
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
            source="chat",
            stage=LOOP_STAGE,
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
        )

    async def _finalize_finish(
        self,
        raw_text: str,
        *,
        visible_text: str | None = None,
        continued_answer_parts: list[str] | None = None,
    ) -> LoopOutcome:
        cleaned_text = self._clean(raw_text)
        if continued_answer_parts:
            final_text = _join_answer_parts(
                continued_answer_parts,
                visible_text if visible_text is not None else cleaned_text,
            )
        else:
            final_text = cleaned_text
        if not final_text:
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
        return LoopOutcome(final_text=final_text, completed=True)

    async def _release_deferred_output(self, result: LLMCallResult) -> None:
        """Publish a buffered capability round only after its protocol accepts it."""
        if result.deferred_chunk_metadata is not None and result.visible_text:
            await self.stream.content(
                result.visible_text,
                source="chat",
                stage=LOOP_STAGE,
                metadata=result.deferred_chunk_metadata,
            )
        if result.deferred_completion_metadata is not None:
            await self.stream.progress(
                "",
                source="chat",
                stage=LOOP_STAGE,
                metadata=result.deferred_completion_metadata,
            )
        result.deferred_chunk_metadata = None
        result.deferred_completion_metadata = None

    async def _discard_deferred_output(self, result: LLMCallResult) -> None:
        """Close a rejected round's trace without publishing its buffered prose."""
        metadata = result.deferred_completion_metadata
        if metadata is not None:
            metadata = dict(metadata)
            metadata["call_role"] = "narration"
            metadata.pop("answer_visible", None)
            metadata["finish_rejected"] = True
            await self.stream.progress(
                "",
                source="chat",
                stage=LOOP_STAGE,
                metadata=metadata,
            )
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
        stage = LOOP_STAGE
        call_id = new_call_id(f"chat-{stage}")
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
            source="chat",
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
            tool_acc = ToolCallAccumulator()
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
                    output_emitted = True
                    if kind == "content":
                        visible_text_parts.append(segment)
                        if segment.strip():
                            answer_content_emitted = True
                        if not defer_visible_output:
                            await self.stream.content(
                                segment, source="chat", stage=stage, metadata=chunk_meta
                            )
                    else:
                        await self.stream.thinking(
                            segment, source="chat", stage=stage, metadata=chunk_meta
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
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue

                    reasoning_text = getattr(delta, "reasoning_content", None) or getattr(
                        delta,
                        "reasoning",
                        None,
                    )
                    if reasoning_text:
                        output_chars += len(reasoning_text)
                        output_emitted = True
                        await self.stream.thinking(
                            reasoning_text, source="chat", stage=stage, metadata=chunk_meta
                        )

                    content = getattr(delta, "content", None)
                    if content:
                        output_chars += len(content)
                        text_parts.append(content)
                        # Every round's text streams to the user; inline
                        # <think> segments remain trace-only while DSML markup
                        # and its argument payload never enter either channel.
                        visible_content = dsml_filter.feed(content)
                        if visible_content and not forced_tool_choice:
                            await _emit_segments(think_filter.feed(visible_content))

                    for tc_delta in getattr(delta, "tool_calls", None) or []:
                        output_chars += tool_acc.feed(tc_delta)
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
                        source="chat",
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
                    source="chat",
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
        if not forced_tool_choice:
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
                source="chat",
                stage=stage,
                metadata=completion_event_metadata,
            )
        return LLMCallResult(
            text=text,
            visible_text="".join(visible_text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            deferred_chunk_metadata=chunk_meta if defer_visible_output else None,
            deferred_completion_metadata=(
                completion_event_metadata if defer_visible_output else None
            ),
        )

    async def _create_response_stream(
        self,
        kwargs: dict[str, Any],
        trace_meta: dict[str, Any],
        stage: str,
    ) -> Any:
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
                    source="chat",
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
                    source="chat",
                    stage=stage,
                    metadata=merge_trace_metadata(
                        trace_meta,
                        {"trace_kind": "warning", "image_fallback": True},
                    ),
                )
                return await self.client.chat.completions.create(**kwargs)
            raise


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
