"""Label-driven iteration scheduler.

The agentic loop drives a conversation with the LLM until one of the
caller-declared *terminal labels* fires. Each iteration is one
:func:`~deeptutor.core.agentic.labeled_step.run_labeled_step` call, after
which the loop:

* validates the protocol (one label, no inline duplicates, tools only with
  the tool label),
* on a terminal label, optionally streams the buffered post-label text as
  body content (for labels in :attr:`LabelProtocol.final`) and exits,
* on the tool label, appends the assistant + tool messages and dispatches
  the requested tool calls via the host,
* on intermediate labels (e.g. ``THINK``), preserves the prose as
  assistant context so the next iteration builds on it,
* on protocol violations, emits a retry notice and feeds the host's
  repair message back into the conversation.

Capability-specific bits — context-window guard, iteration trace metadata,
tool dispatch, pause/terminate handling, max-iter forced finalization,
protocol-violation copy — are delegated to :class:`LoopHost`. The loop
itself stays capability-agnostic.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Protocol

from deeptutor.core.agentic.labeled_step import LabeledStepResult, run_labeled_step
from deeptutor.core.agentic.labels import LABEL_UNKNOWN, find_inline_labels
from deeptutor.core.agentic.tool_dispatch import DispatchOutcome
from deeptutor.core.agentic.usage import UsageTracker
from deeptutor.core.stream_bus import StreamBus


@dataclass(frozen=True)
class LabelProtocol:
    """Declarative description of a capability's label vocabulary.

    * ``allowed``      — every label the LLM may emit on the first line.
    * ``terminal``     — labels that exit the loop. The outcome's
      ``final_label`` reflects which one fired.
    * ``intermediate`` — labels that keep the loop running (the post-label
      prose is appended as assistant context).
    * ``final``        — labels whose post-label text should be emitted as
      body content via the host's ``emit_final``. ``final`` is independent
      of ``terminal`` / ``intermediate``: a terminal label may opt out of
      body emission (e.g. ``REPLAN`` bubbles up text without streaming),
      and an intermediate label may opt **in** to body emission so its
      text appears in the user-facing chat bubble while the loop continues
      (e.g. chat's ``PAUSE`` — narrate to the user mid-reasoning without
      ending the turn).
    * ``tool_label``   — the single label that means "call tools this
      round" (or ``None`` to disable native tool calling for this loop).
    """

    allowed: tuple[str, ...]
    terminal: frozenset[str]
    intermediate: frozenset[str]
    final: frozenset[str]
    tool_label: str | None


@dataclass(frozen=True)
class LoopOutcome:
    """Result of one agentic loop run."""

    final_label: str  # the label that exited the loop (empty when terminated by tool)
    final_text: str  # post-label text (already streamed if in protocol.final)
    iterations: int
    sources: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    completed: bool = False


class LoopHost(Protocol):
    """Capability-supplied hooks the loop calls back into.

    Implementations bundle all chat-/solve-/etc.-specific behavior (trace
    metadata, tool dispatch, prompt copy) so the loop core stays generic.
    """

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        """Optionally trim ``messages`` to keep within the model's window."""

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """Allocate ``(iter_meta, final_meta)`` for one iteration."""

    async def dispatch_tools(
        self,
        *,
        iteration: int,
        tool_calls: list[dict[str, Any]],
    ) -> DispatchOutcome:
        """Execute the iteration's tool calls in parallel."""

    async def resolve_pause(self, dispatch: DispatchOutcome) -> bool:
        """Handle a ``pause_for_user`` request. Return ``True`` to resume."""

    async def emit_terminator(self, payload: dict[str, Any] | None) -> None:
        """Emit the terminating tool's content as a final-response event."""

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        """Emit body content for a label in :attr:`LabelProtocol.final`."""

    async def validate_terminal(self, label: str, text: str) -> str | None:
        """Optional stateful validation before accepting a terminal label.

        Return a protocol-violation key to repair/retry instead of ending
        the loop, or ``None`` to accept the terminal label.
        """
        return None

    def assistant_message_with_tool_calls(
        self,
        *,
        content: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Format the assistant turn that carries this iteration's tool calls."""

    def protocol_retry_notice(self) -> str:
        """Notice text shown when a protocol violation triggers a retry."""

    def protocol_repair_message(self, violation: str) -> str:
        """Per-violation correction prompt fed back to the next LLM call."""

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        """Drive whatever recovery the capability wants when ``max_iterations``
        is exhausted without a terminal label. Returns
        ``(final_text, completed, extra_iterations_consumed)``."""

    async def before_iteration(
        self,
        *,
        messages: list[dict[str, Any]],
        iteration: int,
        max_iterations: int,
    ) -> None:
        """Optional hook fired at the start of each iteration, **after**
        :py:meth:`guard_context_window` and **before** the LLM call.

        Capabilities can use this to inject per-iteration context the model
        should see — e.g. a small "you are at iteration N/M" marker so the
        LLM can pace itself. The hook mutates ``messages`` in place; the
        loop checks for the method's presence with ``getattr`` so existing
        hosts keep working unchanged. Returning anything is ignored.
        """
        return None

    async def on_intermediate(self, label: str, text: str) -> str | None:
        """Optional side-effect hook for intermediate labels.

        Called *after* the loop has appended an intermediate label's
        post-label prose as an assistant message, before the next
        iteration begins. Capabilities can override to mutate their own
        state (e.g. extending a dynamic topic queue when an ``APPEND``
        label fires) and optionally return a non-empty string which the
        loop appends as a ``role=user`` feedback message — useful to
        confirm a successful mutation or report a rejection so the LLM
        can adapt in the next iteration.

        Returning ``None`` (the default) is a no-op. Implementing this
        hook is optional — hosts that omit it preserve the legacy
        behaviour of just appending the prose and continuing. The loop
        checks for the method's presence with ``getattr`` so existing
        hosts (chat, solve) keep working unchanged without having to
        spell out a stub.
        """
        return None


async def run_agentic_loop(
    *,
    initial_messages: list[dict[str, Any]],
    protocol: LabelProtocol,
    client: Any,
    model: str | None,
    completion_kwargs: dict[str, Any],
    binding: str | None,
    tool_schemas: list[dict[str, Any]] | None,
    stream: StreamBus,
    source: str,
    stage: str,
    max_iterations: int,
    host: LoopHost,
    usage: UsageTracker | None = None,
    stream_body_live: bool = False,
    eager_sub_trace: bool = False,
    implicit_think_label: str | None = None,
) -> LoopOutcome:
    """Run a label-driven LLM loop until a terminal label fires or the
    iteration budget is exhausted.

    ``initial_messages`` is mutated in place (and returned via
    :attr:`LoopOutcome.messages`) so the caller can inspect / reuse the
    full message history if needed.

    ``stream_body_live=True`` makes the labeled step stream final-label
    chunks directly to ``stream.content`` (chunk-by-chunk body output) and
    causes the loop to skip :py:meth:`LoopHost.emit_final` — the text is
    already on the wire. Default ``False`` preserves chat's existing
    one-shot emit behavior.

    ``eager_sub_trace=True`` opens the per-iteration sub-trace card before
    the LLM stream begins, eliminating the visible "nothing happening"
    gap during each call's time-to-first-token (network + model warm-up).
    Default ``False`` keeps chat's lazy-open behavior so FINISH-only
    iterations don't spawn empty "Reasoning…" cards.
    """
    messages = initial_messages
    aggregated_sources: list[dict[str, Any]] = []
    final_text = ""
    final_label_seen = ""
    completed = False
    iterations_run = 0
    max_iter = max(1, max_iterations)

    for iteration in range(max_iter):
        await host.guard_context_window(messages)
        before_iteration = getattr(host, "before_iteration", None)
        if before_iteration is not None:
            await before_iteration(
                messages=messages,
                iteration=iteration,
                max_iterations=max_iter,
            )
        iter_meta, final_meta = host.build_iteration_trace_meta(iteration)

        step = await run_labeled_step(
            client=client,
            model=model,
            messages=messages,
            completion_kwargs=completion_kwargs,
            tool_schemas=tool_schemas,
            allowed_labels=protocol.allowed,
            final_labels=protocol.final,
            tool_label=protocol.tool_label,
            stream=stream,
            source=source,
            stage=stage,
            iter_meta=iter_meta,
            binding=binding,
            usage=usage,
            final_meta=final_meta if stream_body_live else None,
            eager_sub_trace=eager_sub_trace,
            implicit_think_label=implicit_think_label,
        )
        iterations_run += 1

        violation = _protocol_violation(step, protocol)
        if violation:
            await _emit_retry_notice(
                stream=stream,
                source=source,
                stage=stage,
                host=host,
                violation=violation,
            )
            _append_repair_messages(
                messages=messages,
                iteration_text=step.text,
                violation=violation,
                host=host,
            )
            continue

        if step.label in protocol.terminal:
            validate_terminal = getattr(host, "validate_terminal", None)
            if validate_terminal is not None:
                violation = await validate_terminal(step.label, step.text)
                if violation:
                    await _emit_retry_notice(
                        stream=stream,
                        source=source,
                        stage=stage,
                        host=host,
                        violation=violation,
                    )
                    _append_repair_messages(
                        messages=messages,
                        iteration_text=step.text,
                        violation=violation,
                        host=host,
                    )
                    continue
            if step.label in protocol.final and not stream_body_live:
                # When body chunks have already been streamed live by
                # ``run_labeled_step``, calling ``host.emit_final`` here
                # would double-emit the text into the chat bubble.
                await host.emit_final(step.text, final_meta)
            final_text = step.text
            final_label_seen = step.label
            completed = True
            break

        if protocol.tool_label is not None and step.label == protocol.tool_label:
            messages.append(
                host.assistant_message_with_tool_calls(
                    content=step.text,
                    tool_calls=step.tool_calls,
                )
            )
            outcome = await host.dispatch_tools(
                iteration=iteration,
                tool_calls=step.tool_calls,
            )
            aggregated_sources.extend(outcome.sources)
            messages.extend(outcome.tool_messages)
            if outcome.pause:
                resumed = await host.resolve_pause(outcome)
                if not resumed:
                    completed = False
                    break
                continue
            if outcome.terminate:
                await host.emit_terminator(outcome.terminate_payload)
                final_text = (outcome.terminate_payload or {}).get("content", "")
                completed = True
                break
            continue

        if step.label in protocol.intermediate:
            # An intermediate label may also be marked ``final``: that
            # means "stream this prose into the user-facing chat bubble,
            # but don't end the turn" (chat's ``PAUSE``). The text is
            # also kept as assistant context below so the next iteration
            # sees what was already told to the user.
            if step.label in protocol.final and step.text and not stream_body_live:
                await host.emit_final(step.text, final_meta)
            if step.text:
                messages.append({"role": "assistant", "content": step.text})
            # Optional hook for capabilities that attach side-effects to
            # intermediate labels (e.g. research's ``APPEND`` mutates the
            # topic queue). When the hook returns a non-empty string we
            # inject it as the next iteration's user message so the
            # model sees structured feedback (e.g. "Appended block #4").
            on_intermediate = getattr(host, "on_intermediate", None)
            if on_intermediate is not None:
                feedback = await on_intermediate(step.label, step.text)
                if feedback:
                    messages.append({"role": "user", "content": feedback})
            continue

        # Defensive fallback for any future label value not covered above.
        # Do not terminate; repair and retry.
        await _emit_retry_notice(
            stream=stream,
            source=source,
            stage=stage,
            host=host,
            violation="unknown_action",
        )
        _append_repair_messages(
            messages=messages,
            iteration_text=step.text,
            violation="unknown_action",
            host=host,
        )
        continue
    else:
        finish_text, did_finish, extra_calls = await host.force_finalize(
            messages=messages,
            start_iteration=max_iter,
        )
        iterations_run += extra_calls
        final_text = finish_text
        completed = did_finish

    return LoopOutcome(
        final_label=final_label_seen,
        final_text=final_text,
        iterations=iterations_run,
        sources=aggregated_sources,
        messages=messages,
        completed=completed,
    )


def _protocol_violation(
    step: LabeledStepResult,
    protocol: LabelProtocol,
) -> str | None:
    """Classify a labeled-step result against the protocol; return a
    violation key (matching the host's repair-message vocabulary) or
    ``None`` if compliant."""
    if step.label == LABEL_UNKNOWN:
        return "missing_label"
    if find_inline_labels(step.text, allowed_labels=protocol.allowed):
        return "multiple_labels"
    if protocol.tool_label is not None:
        if step.label == protocol.tool_label and not step.tool_calls:
            return "tool_without_calls"
        if step.label != protocol.tool_label and step.tool_calls:
            # The violation key carries the actual offending label so the
            # host can render an accurate repair message. The legacy keys
            # ``think_with_tools`` / ``finish_with_tools`` are still
            # produced for the canonical THINK/FINISH labels, but new
            # label vocabularies (e.g. chat's ``PAUSE`` — intermediate +
            # final) get their own ``{label}_with_tools`` key.
            return f"{step.label.lower()}_with_tools"
    return None


async def _emit_retry_notice(
    *,
    stream: StreamBus,
    source: str,
    stage: str,
    host: LoopHost,
    violation: str,
) -> None:
    await stream.progress(
        host.protocol_retry_notice(),
        source=source,
        stage=stage,
        metadata={"trace_kind": "warning", "protocol_violation": violation},
    )


_REPAIR_PREVIEW_CHARS = 500


def _append_repair_messages(
    *,
    messages: list[dict[str, Any]],
    iteration_text: str,
    violation: str,
    host: LoopHost,
) -> None:
    """Preserve the model's unlabeled draft as assistant context, then add
    a correction prompt that tells the next iteration what to do."""
    clipped = str(iteration_text or "").strip()
    if clipped:
        if len(clipped) > _REPAIR_PREVIEW_CHARS:
            clipped = clipped[:_REPAIR_PREVIEW_CHARS].rstrip() + "\n...[truncated]"
        messages.append({"role": "assistant", "content": clipped})
    messages.append({"role": "user", "content": host.protocol_repair_message(violation)})


# Re-export ``Awaitable`` here so consumers needn't import it just to type
# their host implementations (mirrors what ``asyncio`` does with ``Future``).
__all__ = [
    "Awaitable",
    "LabelProtocol",
    "LoopHost",
    "LoopOutcome",
    "run_agentic_loop",
]
