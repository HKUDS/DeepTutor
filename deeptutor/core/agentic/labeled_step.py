r"""One streaming LLM call with protocol-label routing.

The core single-round-trip primitive. Given an OpenAI-compatible streaming
client, optional tool schemas, and a label protocol, this:

* Parses the first chunks for a ``\`\`LABEL\`\``` prefix.
* For *non-final* labels (e.g. ``THINK``, ``TOOL``, ``REPLAN``), streams
  post-label text live to ``stream.thinking`` under the supplied
  ``iter_meta`` — i.e. into a reasoning sub-trace.
* For *final* labels (e.g. ``FINISH``, ``PLAN``, ``SUMMARY``), buffers the
  post-label text and returns it to the caller; the caller decides whether
  to emit it as body content (so a mixed ``FINISH+TOOL`` reply never leaks
  prose into the answer area before the protocol is validated).
* Accumulates ``tool_calls`` deltas. Tool-call presence alone does not choose
  the action label: the formal content stream must still begin with the
  caller's tool label (e.g. ``TOOL``), otherwise the caller's protocol repair
  path handles the missing label.
* When a reasoning model prepends a literal ``<think>...</think>`` block
  *before* the protocol label, that prelude is detected and streamed live
  into the reasoning sub-trace (same routing as the ``THINK`` label).
  Label probing resumes on the content after ``</think>``: if the label
  resolves to an intermediate label (e.g. ``THINK``) the post-label text
  continues into the *same* sub-trace; if it resolves to a final label
  (e.g. ``FINISH``) the post-label text routes to the final-response area
  as usual. The ``<think>``/``</think>`` markers themselves are not emitted
  live, only kept in the accumulated buffer so ``clean_thinking_tags`` can
  strip the block from the returned text.

Returns the resolved label, the accumulated post-label text (with provider
``<think>`` tags stripped), and the parsed tool calls.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import re
from typing import Any

from deeptutor.core.agentic.labels import (
    LABEL_PROBE_MAX_CHARS,
    LABEL_UNKNOWN,
    classify_label,
    strip_label_probe_prefix,
)
from deeptutor.core.agentic.usage import UsageTracker
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import merge_trace_metadata
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.llm.multimodal import should_degrade_to_text, strip_image_parts_inplace

# Reasoning models (Qwen, Deepseek-R1 via certain proxies, etc.) sometimes
# inline a literal ``<think>...</think>`` block in the content stream before
# emitting the protocol label. Match the opening tag *only* at the start of
# the (whitespace-stripped) probe buffer — anything later belongs to the
# post-label body and is handled by ``clean_thinking_tags`` at the end.
#
# Backticks must appear in matched pairs (e.g. `` `<think>` `` or
# ``<think>``) — a lone optional ``backtick on either side would greedily
# eat a leading ```` of the protocol label that follows (e.g. ``</think>``
# immediately preceding ``\`\`FINISH\`\```), corrupting the post-prelude
# label probe.
_THINK_OPEN_RE = re.compile(
    r"\A(?:`<\s*think(?:ing)?\b[^>]*>`|<\s*think(?:ing)?\b[^>]*>)",
    re.IGNORECASE,
)
_THINK_CLOSE_RE = re.compile(
    r"(?:`<\s*/\s*think(?:ing)?\s*>`|<\s*/\s*think(?:ing)?\s*>)",
    re.IGNORECASE,
)
# Headroom for ``</think>`` plus optional surrounding backticks/whitespace.
# We keep at most this many trailing chars of the prelude unsent so a close
# tag that arrives split across chunks is still detectable.
_THINK_CLOSE_TAIL_GUARD = 24
# Once a provider has explicitly sent ``finish_reason`` the text generation is
# done. Some OpenAI-compatible gateways keep the SSE connection open while
# waiting for an optional usage trailer; wait briefly for that frame, then
# close locally so the UI can receive RESULT/DONE promptly.
_USAGE_TRAILER_GRACE_TIMEOUT_S = 1.0
# Defensive fallback for gateways that never emit ``finish_reason`` but have
# already sent a final-label answer and then leave the stream idle.
_FINAL_LABEL_IDLE_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class LabeledStepResult:
    """Outcome of a single labeled LLM call."""

    label: str  # one of allowed_labels, or LABEL_UNKNOWN on protocol failure
    text: str  # post-label content with provider <think> tags cleaned
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class _UsageShim:
    """Adapt streaming ``CompletionUsage`` to the shape ``UsageTracker`` wants."""

    def __init__(self, raw: Any) -> None:
        self.usage = raw


def _message_content_chars(message: dict[str, Any]) -> int:
    """Best-effort character count for usage fallback estimates."""
    content = message.get("content")
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    total += len(str(part.get("text") or ""))
                elif "text" in part:
                    total += len(str(part.get("text") or ""))
            elif isinstance(part, str):
                total += len(part)
        return total
    if content is None:
        return 0
    return len(str(content))


def _error_text(exc: Exception) -> str:
    """Best-effort lowercase error body for provider-capability detection."""
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
    """Detect providers that reject OpenAI's ``stream_options`` parameter."""
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
    """Detect providers that reject native tool/function-calling schemas."""
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
    """Detect providers/models that reject image (multimodal) content.

    Covers both explicit "no vision" rejections and the structural errors a
    text-only OpenAI-compatible model raises when it receives the content
    *array* the image injection produced (it expected a plain string).
    Transient errors (rate limit / 5xx) never mention these markers, so they
    don't trigger the image fallback.
    """
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


async def run_labeled_step(
    *,
    client: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    completion_kwargs: dict[str, Any],
    tool_schemas: list[dict[str, Any]] | None,
    allowed_labels: tuple[str, ...],
    final_labels: frozenset[str],
    tool_label: str | None,
    stream: StreamBus,
    source: str,
    stage: str,
    iter_meta: dict[str, Any],
    binding: str | None = None,
    usage: UsageTracker | None = None,
    final_meta: dict[str, Any] | None = None,
    eager_sub_trace: bool = False,
    implicit_think_label: str | None = None,
) -> LabeledStepResult:
    """Drive one streaming LLM call under the label protocol.

    ``final_meta`` opts the post-label stream into **live body streaming**:
    when set, every chunk that resolves under a label in ``final_labels``
    is emitted as a :py:meth:`StreamBus.content` event using ``final_meta``
    (with ``trace_kind="llm_chunk"``), so the chat bubble fills up
    chunk-by-chunk instead of appearing in one shot at the end. When
    ``final_meta`` is ``None`` (chat's existing behavior), final-label
    text is buffered and the caller emits it after protocol validation.

    ``eager_sub_trace=True`` opens the iteration's sub-trace card before
    the LLM stream begins, so the trace panel renders a "running" indicator
    immediately instead of after the first chunk arrives. This closes the
    visual gap during the time-to-first-token of each call (often 0.5–3s
    of network + model warm-up). Lazy default keeps chat's existing
    behavior — its cards only open when there is actual reasoning text to
    show, avoiding empty "Reasoning…" cards for direct FINISH replies.

    ``implicit_think_label`` is kept for API compatibility with older
    callers, but is intentionally ignored. Reasoning traces from
    ``reasoning_content`` or inline ``<think>`` are trace data, not loop
    actions; the formal content stream must still provide the protocol label.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        **completion_kwargs,
    }
    auto_stream_options_added = False
    if usage is not None and "stream_options" not in kwargs:
        kwargs["stream_options"] = {"include_usage": True}
        auto_stream_options_added = True
    if tool_schemas:
        kwargs["tools"] = tool_schemas
        kwargs["tool_choice"] = "auto"

    label: str | None = None
    label_buf = ""
    in_prelude_think = False
    # Trailing slice of the in-progress prelude held back so a ``</think>``
    # split across chunks is still detectable.
    prelude_tail = ""
    # True once we have observed a pre-label ``<think>`` opener. The final
    # ``clean_thinking_tags`` pass is gated on ``binding`` to preserve
    # existing behavior; we always force the cleanup when a prelude was
    # detected so the synthetic markers we recorded don't leak out.
    saw_pre_label_think = False
    sub_trace_opened = False
    content_acc: list[str] = []
    tc_acc: dict[int, dict[str, Any]] = {}
    usage_seen: Any = None
    output_chars_seen = 0
    finish_reason_seen: str | None = None
    usage_trailer_waited = False

    async def _open_sub_trace() -> None:
        nonlocal sub_trace_opened
        if sub_trace_opened:
            return
        await stream.progress(
            iter_meta.get("label", ""),
            source=source,
            stage=stage,
            metadata=merge_trace_metadata(
                iter_meta,
                {"trace_kind": "call_status", "call_state": "running"},
            ),
        )
        sub_trace_opened = True

    async def _emit_text(text: str) -> None:
        """Route post-label fragments.

        * Final-label text: buffered. If ``final_meta`` was supplied, the
          fragment is *also* emitted live as a ``content`` event so the chat
          bubble streams chunk-by-chunk (call_kind ``llm_final_response``).
        * Non-final labels: streamed into the reasoning sub-trace.
        """
        nonlocal output_chars_seen
        if not text:
            return
        output_chars_seen += len(text)
        content_acc.append(text)
        if label in final_labels:
            if final_meta is not None:
                await stream.content(
                    text,
                    source=source,
                    stage=stage,
                    metadata=merge_trace_metadata(final_meta, {"trace_kind": "llm_chunk"}),
                )
            return
        await _open_sub_trace()
        await stream.thinking(
            text,
            source=source,
            stage=stage,
            metadata=merge_trace_metadata(iter_meta, {"trace_kind": "llm_chunk"}),
        )

    async def _emit_prelude_content(text: str) -> None:
        """Stream pre-label ``<think>`` body content into the reasoning
        sub-trace, identical to the routing used for the non-final ``THINK``
        label so a real ``THINK`` label that follows naturally merges into
        the same trace. The raw text is also retained in ``content_acc`` so
        :func:`clean_thinking_tags` can strip the entire prelude block from
        the returned text at the end.
        """
        nonlocal output_chars_seen
        if not text:
            return
        output_chars_seen += len(text)
        content_acc.append(text)
        await _open_sub_trace()
        await stream.thinking(
            text,
            source=source,
            stage=stage,
            metadata=merge_trace_metadata(iter_meta, {"trace_kind": "llm_chunk"}),
        )

    async def _emit_prelude_marker(tag_text: str) -> None:
        """Stream a ``<think>``/``</think>`` marker live into the reasoning
        sub-trace AND record it in ``content_acc``.

        The marker is visible in the trace UI (so users see the actual
        ``<think>...</think>`` structure the model emitted) and the
        accumulated buffer keeps the literal tag so downstream consumers
        — including the implicit-``THINK`` resolution path — can preserve
        or strip the prelude block as needed.
        """
        nonlocal output_chars_seen
        if not tag_text:
            return
        output_chars_seen += len(tag_text)
        content_acc.append(tag_text)
        await _open_sub_trace()
        await stream.thinking(
            tag_text,
            source=source,
            stage=stage,
            metadata=merge_trace_metadata(iter_meta, {"trace_kind": "llm_chunk"}),
        )

    async def _close_prelude_artificially() -> None:
        """Force-end an in-progress ``<think>`` prelude (used when tool
        calls arrive mid-prelude or the stream ends with no close tag).
        Flushes any held-back tail to the live sub-trace and emits a
        synthesized ``</think>`` marker so both the trace and the
        accumulated buffer reflect a clean close."""
        nonlocal in_prelude_think, prelude_tail
        if prelude_tail:
            await _emit_prelude_content(prelude_tail)
            prelude_tail = ""
        await _emit_prelude_marker("</think>")
        in_prelude_think = False

    async def _drain_prelude_or_close() -> None:
        """While ``in_prelude_think`` is set, scan ``prelude_tail`` for a
        ``</think>`` close tag. If found, emit the content before the tag
        live, emit the close marker live, and move whatever follows the
        tag into ``label_buf`` so label probing resumes. If not found,
        emit as much of the tail as we can while keeping a small guard
        window so a close tag split across chunks is still detectable
        next time."""
        nonlocal in_prelude_think, prelude_tail, label_buf
        close_m = _THINK_CLOSE_RE.search(prelude_tail)
        if close_m is None:
            if len(prelude_tail) > _THINK_CLOSE_TAIL_GUARD:
                split = len(prelude_tail) - _THINK_CLOSE_TAIL_GUARD
                safe = prelude_tail[:split]
                prelude_tail = prelude_tail[split:]
                await _emit_prelude_content(safe)
            return
        before = prelude_tail[: close_m.start()]
        if before:
            await _emit_prelude_content(before)
        await _emit_prelude_marker(close_m.group(0))
        in_prelude_think = False
        label_buf = prelude_tail[close_m.end() :]
        prelude_tail = ""

    async def _ingest_pre_label(text: str) -> None:
        """Drive the pre-label state machine for one streamed chunk.

        Handles, in a single chunk if the data permits: continuing an open
        ``<think>`` prelude, entering a new prelude when the buffer opens
        with ``<think>``, closing a prelude on ``</think>``, resolving the
        protocol label, and the probe-overflow fallback.
        """
        nonlocal label, label_buf, in_prelude_think, prelude_tail
        nonlocal saw_pre_label_think

        if in_prelude_think:
            prelude_tail += text
        elif text:
            label_buf += text

        # Drive the state machine forward as long as the current buffers
        # allow progress. A single chunk can carry the entire prelude AND
        # the label AND the post-label text, so we keep looping until either
        # the label resolves or we run out of decidable input.
        while True:
            if in_prelude_think:
                await _drain_prelude_or_close()
                if in_prelude_think:
                    return  # waiting for ``</think>``
                # ``</think>`` consumed; ``label_buf`` now holds the
                # post-prelude remainder. Continue to label probing.

            stripped = strip_label_probe_prefix(label_buf)
            open_m = _THINK_OPEN_RE.match(stripped)
            if open_m:
                leading_len = len(label_buf) - len(stripped)
                if leading_len:
                    # Preserve incidental leading whitespace verbatim — the
                    # final ``cleaned.strip()`` inside
                    # ``clean_thinking_tags`` will smooth over it.
                    content_acc.append(label_buf[:leading_len])
                in_prelude_think = True
                saw_pre_label_think = True
                prelude_tail = stripped[open_m.end() :]
                label_buf = ""
                # Emit the ``<think>`` marker live so the reasoning sub-
                # trace shows the model's native structure. This also
                # opens the sub-trace card immediately, so short preludes
                # (≤24 chars) still surface UI activity even before the
                # close-tag guard window flushes any content.
                await _emit_prelude_marker(open_m.group(0))
                continue  # re-enter loop to drain the new prelude

            parsed = classify_label(label_buf, allowed_labels=allowed_labels)
            if parsed is not None:
                label, after_label = parsed
                label_buf = ""
                await _emit_text(after_label)
                return

            if len(label_buf) > LABEL_PROBE_MAX_CHARS:
                # Probe window exhausted with no protocol label match.
                # Reasoning traces are not action labels, so fall to
                # ``LABEL_UNKNOWN`` and let the caller repair.
                label = LABEL_UNKNOWN
                flushed = label_buf
                label_buf = ""
                await _emit_text(flushed)
                return

            return  # no further decision possible without more input

    if eager_sub_trace:
        # Open the sub-trace card *before* the LLM stream begins so the
        # trace panel renders activity during the time-to-first-token of
        # the upcoming call (which would otherwise be silent UI).
        await _open_sub_trace()

    async def _create_response_stream() -> Any:
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:
            if auto_stream_options_added and _is_stream_options_unsupported(exc):
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("stream_options", None)
                return await client.chat.completions.create(**retry_kwargs)
            if tool_schemas and _is_tool_schema_unsupported(exc):
                await stream.progress(
                    "Provider rejected native tool schemas; retrying without tools.",
                    source=source,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        iter_meta,
                        {"trace_kind": "warning", "tool_schema_fallback": True},
                    ),
                )
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("tools", None)
                retry_kwargs.pop("tool_choice", None)
                return await client.chat.completions.create(**retry_kwargs)
            # Stage-2 vision fallback: the model rejected our image content and
            # it is not in the known-vision allowlist. Strip images in place
            # (so they aren't re-sent on later loop iterations) and retry the
            # turn text-only rather than hard-failing.
            if _is_image_input_unsupported(exc) and should_degrade_to_text(
                binding, model, kwargs.get("messages") or []
            ):
                strip_image_parts_inplace(kwargs["messages"])
                await stream.progress(
                    "Model does not support image input; retrying without images.",
                    source=source,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        iter_meta,
                        {"trace_kind": "warning", "image_fallback": True},
                    ),
                )
                return await client.chat.completions.create(**kwargs)
            raise

    response_stream = await _create_response_stream()
    try:
        stream_iter = response_stream.__aiter__()
        while True:
            timeout: float | None = None
            if finish_reason_seen:
                if usage is not None and usage_seen is None and not usage_trailer_waited:
                    timeout = _USAGE_TRAILER_GRACE_TIMEOUT_S
                    usage_trailer_waited = True
                else:
                    break
            elif label in final_labels and content_acc:
                timeout = _FINAL_LABEL_IDLE_TIMEOUT_S
            try:
                if timeout is None:
                    chunk = await stream_iter.__anext__()
                else:
                    chunk = await asyncio.wait_for(stream_iter.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                # Terminal enough for the chat UI: the model already sent a
                # final-label answer (or an explicit finish_reason), but the
                # gateway is holding the connection open.
                if finish_reason_seen or label in final_labels:
                    break
                raise
            if getattr(chunk, "usage", None):
                usage_seen = chunk.usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            if getattr(choice, "finish_reason", None):
                finish_reason_seen = str(choice.finish_reason)
            delta = choice.delta
            if delta is None:
                continue

            # Reasoning models that surface chain-of-thought via the dedicated
            # ``reasoning_content`` (or ``reasoning``) field — e.g. DeepSeek-R1
            # via certain providers, OpenAI o1/o3 in some compatibility modes
            # — emit *no* ``delta.content`` during the reasoning phase. Without
            # this branch the UI would sit frozen for the entire reasoning
            # duration, then the answer chunk would arrive and the user would
            # see only the answer with no reasoning trace. Route the reasoning
            # stream live into the same sub-trace the inline-``<think>``
            # prelude uses, so both flavors of reasoning model surface
            # identically. ``saw_pre_label_think`` forces the final cleanup
            # path to run even when ``binding`` is unset.
            reasoning_text = getattr(delta, "reasoning_content", None) or getattr(
                delta, "reasoning", None
            )
            if reasoning_text and label is None:
                output_chars_seen += len(reasoning_text)
                saw_pre_label_think = True
                await _open_sub_trace()
                await stream.thinking(
                    reasoning_text,
                    source=source,
                    stage=stage,
                    metadata=merge_trace_metadata(iter_meta, {"trace_kind": "llm_chunk"}),
                )

            if delta.content:
                text = delta.content
                if label is None:
                    await _ingest_pre_label(text)
                else:
                    await _emit_text(text)

            for tc_delta in getattr(delta, "tool_calls", None) or []:
                fn_for_chars = getattr(tc_delta, "function", None)
                output_chars_seen += len(str(getattr(fn_for_chars, "name", "") or ""))
                output_chars_seen += len(str(getattr(fn_for_chars, "arguments", "") or ""))
                idx = getattr(tc_delta, "index", 0)
                entry = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if getattr(tc_delta, "id", None):
                    entry["id"] = tc_delta.id
                fn = getattr(tc_delta, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        entry["name"] = entry["name"] + fn.name
                    if getattr(fn, "arguments", None):
                        entry["arguments"] = entry["arguments"] + fn.arguments
    finally:
        close = getattr(response_stream, "close", None)
        if callable(close):
            with suppress(Exception):
                await close()

    # Stream ended while still buffering a label. Decide how to resolve:
    #
    # - Reasoning traces (``reasoning_content`` or inline ``<think>``) are
    #   not action labels. If no formal content label appeared, fall to
    #   ``LABEL_UNKNOWN`` and let the caller repair.
    if label is None:
        if in_prelude_think:
            # Stream ended mid-prelude — flush remaining reasoning live so
            # the user sees what the model managed to produce, then close
            # the block synthetically.
            await _close_prelude_artificially()
        final_parsed = classify_label(
            label_buf,
            allowed_labels=allowed_labels,
            final=True,
        )
        if final_parsed is not None:
            label, after_label = final_parsed
            label_buf = ""
            await _emit_text(after_label)
        if label is None:
            label = LABEL_UNKNOWN
        if label_buf:
            await _emit_text(label_buf)
            label_buf = ""

    if usage_seen is not None and usage is not None:
        usage.add_from_response(_UsageShim(usage_seen))
    elif usage is not None:
        input_chars = sum(_message_content_chars(message) for message in messages)
        if input_chars or output_chars_seen:
            usage.add_estimated(
                input_chars=input_chars,
                output_chars=output_chars_seen,
            )

    if sub_trace_opened:
        await stream.progress(
            "",
            source=source,
            stage=stage,
            metadata=merge_trace_metadata(
                iter_meta,
                {"trace_kind": "call_status", "call_state": "complete"},
            ),
        )

    text = "".join(content_acc)
    # Reasoning traces have already been streamed into the trace channel; the
    # returned formal text should not leak inline provider markers or private
    # pre-label thinking.
    if binding or saw_pre_label_think:
        text = clean_thinking_tags(text, binding, model)
    ordered_tool_calls = [tc_acc[k] for k in sorted(tc_acc.keys())]
    ordered_tool_calls = [tc for tc in ordered_tool_calls if tc.get("name")]
    return LabeledStepResult(label=label, text=text, tool_calls=ordered_tool_calls)
