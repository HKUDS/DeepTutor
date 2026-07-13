"""Single-loop chat agent.

One chat turn = ONE agent loop over a single growing conversation:

* each round is one LLM call; its text streams to the user as a ``content``
  block, and its tool calls are dispatched with their ``role=tool`` results
  appended back into the conversation;
* a round that DOES call tools is "narration" — its text is a preamble to
  the tool work — and the loop continues;
* a round that calls NO tools is the ``finish``: its text IS the final
  user-facing answer and the loop ends (the model deciding it is done; a
  first round without tool calls is the "no exploration needed" fast path);
* if the round budget runs out while tools are still being requested, one
  final tool-less ``finish`` round is forced.

``ask_user`` pauses the turn for a reply and resumes in-protocol; an
unresolved pause (or a terminator tool) halts the turn.

There is no separate respond pass and no text destination has to be guessed
mid-stream: every round's text streams to the user as it is generated, and a
``call_role`` (``narration`` vs ``finish``) emitted when the round completes
tells the frontend how to render that round's text.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
import logging
import re
from typing import TYPE_CHECKING, Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.agentic.tool_dispatch import DispatchOutcome
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.llm.multimodal import should_degrade_to_text, strip_image_parts_inplace

if TYPE_CHECKING:  # pragma: no cover
    from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline

logger = logging.getLogger(__name__)

# The loop runs over a single conversation; this is the maximum number of
# tool-calling rounds before a tool-less finish is forced. The model normally
# exits earlier by replying without tool calls.
LOOP_STAGE = "responding"

_THINK_OPEN_RE = re.compile(r"<\s*think(?:ing)?\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"<\s*/\s*think(?:ing)?\s*>", re.IGNORECASE)
# Longest partial tag worth waiting a chunk for (e.g. "</thinking" + slack).
_TAG_HOLDBACK_CHARS = 24


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
    tool_steps: int = 0
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class LLMCallResult:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""


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
        await emit_capability_result(
            self.stream,
            {
                "response": outcome.final_text,
                "completed": outcome.completed,
                "engine": "agent_loop",
                "rounds": state.rounds,
                "tool_steps": state.tool_steps,
            },
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
        nudged_empty_finish = False
        for _round in range(max(1, self.pipeline.effective_max_rounds(self.context))):
            try:
                result = await self._call_llm(
                    messages=messages,
                    label=explore_label,
                    call_kind="agent_loop_round",
                    trace_role="explore",
                    max_tokens=self.pipeline.loop_max_tokens,
                    tool_schemas=self.tool_schemas,
                )
            except Exception as exc:
                # A mid-loop LLM failure (timeout / transient network) must not
                # discard a turn that already gathered useful work. Salvage it
                # with a forced finish; only a failure on the very first round
                # (nothing gathered yet) propagates as before.
                if state.rounds == 0:
                    raise
                logger.warning(
                    "agent loop round failed after %d round(s); forcing finish: %s",
                    state.rounds,
                    exc,
                )
                return await self._forced_finish(messages, state, reason="error")
            state.rounds += 1
            if not result.tool_calls:
                final_text = self._clean(result.text)
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
                    messages.append(
                        {
                            "role": "user",
                            "content": self.pipeline._t(
                                "loop.finish_empty_nudge",
                                default=(
                                    "Your previous round produced only internal "
                                    "reasoning — no tool call and no user-facing "
                                    "answer. Continue now: either call the tools "
                                    "to execute your plan, or write the final "
                                    "user-facing answer directly."
                                ),
                            ),
                        }
                    )
                    continue
                # Finish: the text streamed live this round IS the answer.
                return await self._finalize_finish(final_text)

            messages.append(_assistant_message_with_tool_calls(result.text, result.tool_calls))
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
                return LoopOutcome(
                    final_text=str(payload.get("content") or ""),
                    completed=True,
                )

        # Round budget ran out while still requesting tools — force a finish.
        return await self._forced_finish(messages, state)

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
        messages.append({"role": "user", "content": self.pipeline._finish_exhausted_instruction()})
        try:
            result = await self._call_llm(
                messages=messages,
                label=self.pipeline._t("labels.final_response", default="Final response"),
                call_kind="llm_final_response",
                trace_role="response",
                max_tokens=self.pipeline.loop_max_tokens,
                tool_schemas=None,  # tools disabled so the model must finish
            )
        except Exception as exc:
            # The salvage call itself failed (e.g. the provider is still
            # stalling). Don't bubble up and lose the turn — emit the graceful
            # fallback answer instead.
            logger.warning("forced-finish LLM call failed: %s", exc)
            return await self._finalize_finish("")
        state.rounds += 1
        return await self._finalize_finish(result.text)

    async def _finalize_finish(self, raw_text: str) -> LoopOutcome:
        final_text = self._clean(raw_text)
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
        if self.pipeline.usage is not None:
            kwargs["stream_options"] = {"include_usage": True}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"

        before_usage_calls = self.pipeline.usage.calls
        text_parts: list[str] = []
        tool_acc: dict[int, dict[str, str]] = {}
        output_chars = 0
        finish_reason = ""
        think_filter = InlineThinkFilter()
        chunk_meta = merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"})

        async def _emit_segments(segments: list[tuple[str, str]]) -> None:
            for kind, segment in segments:
                if kind == "content":
                    await self.stream.content(
                        segment, source="chat", stage=stage, metadata=chunk_meta
                    )
                else:
                    await self.stream.thinking(
                        segment, source="chat", stage=stage, metadata=chunk_meta
                    )

        response_stream = await self._create_response_stream(kwargs, trace_meta, stage)
        try:
            async for chunk in response_stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    self.pipeline.usage.add_from_response(usage)
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
                    await self.stream.thinking(
                        reasoning_text, source="chat", stage=stage, metadata=chunk_meta
                    )

                content = getattr(delta, "content", None)
                if content:
                    output_chars += len(content)
                    text_parts.append(content)
                    # Every round's text streams to the user; the round's
                    # call_role (emitted at completion) tells the frontend
                    # whether to render it as narration or as the answer.
                    # Inline <think> segments are split off to the thinking
                    # channel so the content stream stays user-facing.
                    await _emit_segments(think_filter.feed(content))

                for tc_delta in getattr(delta, "tool_calls", None) or []:
                    index = int(getattr(tc_delta, "index", 0) or 0)
                    acc = tool_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    tcid = getattr(tc_delta, "id", None)
                    if tcid:
                        acc["id"] += str(tcid)
                    fn = getattr(tc_delta, "function", None)
                    if fn is None:
                        continue
                    name = getattr(fn, "name", None)
                    arguments = getattr(fn, "arguments", None)
                    if name:
                        acc["name"] += str(name)
                        output_chars += len(str(name))
                    if arguments:
                        acc["arguments"] += str(arguments)
                        output_chars += len(str(arguments))
        finally:
            close = getattr(response_stream, "close", None)
            if callable(close):
                with suppress(Exception):
                    await close()

        await _emit_segments(think_filter.flush())
        text = "".join(text_parts)
        if self.pipeline.usage.calls == before_usage_calls:
            self.pipeline.usage.add_estimated(
                input_chars=sum(_message_content_chars(message) for message in messages),
                output_chars=output_chars,
            )

        tool_calls = [
            {
                "id": data.get("id") or f"call_{idx}",
                "name": data.get("name", ""),
                "arguments": data.get("arguments") or "{}",
            }
            for idx, data in sorted(tool_acc.items())
            if data.get("name")
        ]

        await self.stream.progress(
            "",
            source="chat",
            stage=stage,
            metadata=merge_trace_metadata(
                trace_meta,
                {
                    "trace_kind": "call_status",
                    "call_state": "complete",
                    # A round with tool calls is narration; a tool-less round
                    # is the finish whose text is the user-facing answer.
                    "call_role": "narration" if tool_calls else "finish",
                },
            ),
        )
        return LLMCallResult(text=text, tool_calls=tool_calls, finish_reason=finish_reason)

    async def _create_response_stream(
        self,
        kwargs: dict[str, Any],
        trace_meta: dict[str, Any],
        stage: str,
    ) -> Any:
        try:
            return await self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            if "stream_options" in kwargs and _is_stream_options_unsupported(exc):
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("stream_options", None)
                return await self.client.chat.completions.create(**retry_kwargs)
            if kwargs.get("tools") and _is_tool_schema_unsupported(exc):
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
            if _is_image_input_unsupported(exc) and should_degrade_to_text(
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


def _assistant_message_with_tool_calls(
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


def _message_content_chars(message: dict[str, Any]) -> int:
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                total += len(str(part.get("text") or ""))
            elif isinstance(part, str):
                total += len(part)
        return total
    return 0


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


def _error_text(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    body = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
        or getattr(exc, "message", None)
        or str(exc)
    )
    return str(body).lower()


def _is_stream_options_unsupported(exc: Exception) -> bool:
    text = _error_text(exc)
    return any(
        marker in text
        for marker in (
            "stream_options",
            "stream options",
            "unknown parameter",
            "unrecognized request argument",
            "unsupported parameter",
            "extra inputs are not permitted",
            "unexpected keyword",
        )
    )


def _is_tool_schema_unsupported(exc: Exception) -> bool:
    text = _error_text(exc)
    return any(
        marker in text
        for marker in (
            "tool",
            "function_declaration",
            "function declaration",
            "function_declarations",
            "tool_choice",
            "parameters.properties",
            "404_not_found",
            "404 not_found",
        )
    )


def _is_image_input_unsupported(exc: Exception) -> bool:
    text = _error_text(exc)
    return any(
        marker in text
        for marker in (
            "image",
            "vision",
            "multimodal",
            "image_url",
            "content type",
            "must be a string",
            "expected a string",
            "expected string",
            "invalid type for 'messages",
        )
    )


__all__ = [
    "AgentLoop",
    "AgentLoopState",
    "InlineThinkFilter",
    "LLMCallResult",
    "LOOP_STAGE",
    "LoopOutcome",
]
