"""Round values and provider-message replay shared by scheduler adapters.

These helpers do not execute rounds, invoke tools, or emit stream events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deeptutor.services.llm import finish_was_truncated as _finish_was_truncated
from deeptutor.services.session.provider_response_state import normalize_provider_response_state


def _reasoning_budget_exhausted(result: "LLMCallResult", max_tokens: int) -> bool:
    """Detect a round that spent its output budget without taking action."""
    if result.tool_calls or result.visible_text.strip():
        return False
    has_reasoning = bool(result.reasoning_chars or result.reasoning_content) or any(
        isinstance(item, dict) and item.get("type") == "reasoning"
        for item in result.response_output_items
    )
    if not has_reasoning:
        return False
    # Content filtering is a terminal provider decision, not a reasoning
    # budget failure. In particular, do not let the token-count fallback below
    # turn a filtered response that happens to reach the cap into a retry loop.
    if str(result.finish_reason or "").strip().lower() == "content_filter":
        return False
    if _finish_was_truncated(result.finish_reason):
        return True
    completion_tokens = result.usage.get("completion_tokens")
    if completion_tokens is None or completion_tokens < max(1, int(max_tokens)):
        return False
    # Some gateways omit the terminal reason and report an incomplete
    # reasoning response with a zero/absent reasoning-token detail.  Once the
    # canonical completion counter reaches this round's request cap, the
    # zero-visible-output shape is enough to identify the exhausted round.
    return True


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
    reasoning_budget_recoveries: int = 0
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
    usage: dict[str, int] = field(default_factory=dict)
    output_chars: int = 0
    reasoning_chars: int = 0
    content_chars: int = 0
    tool_call_chars: int = 0
    finish_reason: str = ""
    # Completion metadata describes the round; it never revokes public text.
    # Deferred metadata is reserved for unpublished structured protocol output.
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


def _has_replayable_assistant_state(result: LLMCallResult) -> bool:
    """Whether a tool-less round still has provider state to replay."""
    return bool(
        result.text
        or result.reasoning_content
        or result.response_output_items
        or result.thinking_blocks
    )
