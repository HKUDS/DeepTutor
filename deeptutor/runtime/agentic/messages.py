"""Canonical message builders for agentic conversations."""

from __future__ import annotations

from typing import Any


def assistant_message_with_tool_calls(
    content: str,
    tool_calls: list[dict[str, Any]],
    *,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the assistant message that precedes tool result messages.

    ``reasoning_content`` is optional: DeepSeek thinking-mode Chat Completions
    requires the prior round's reasoning to be echoed on the assistant turn
    that issued the tool calls (#1058). Responses-API replay is handled
    separately via ``_responses_output_items``.

    ``thinking_blocks`` is the Anthropic equivalent, and stricter: extended
    thinking returns *signed* blocks, and a turn that issued tool calls must
    replay them verbatim. The provider has always known how to read this field
    off a message — nothing ever wrote it, so the signatures were dropped on
    every round.
    """
    serialized_calls: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        serialized: dict[str, Any] = {
            "id": tool_call["id"],
            "type": "function",
            "function": {
                "name": tool_call["name"],
                "arguments": tool_call.get("arguments") or "{}",
            },
        }
        # Gemini's OpenAI-compatible endpoint requires the exact opaque
        # thought signature from each function call to be sent back on the
        # next round (#1181). Other providers simply omit this extension.
        extra_content = tool_call.get("extra_content")
        if isinstance(extra_content, dict) and extra_content:
            serialized["extra_content"] = extra_content
        serialized_calls.append(serialized)

    message: dict[str, Any] = {
        "role": "assistant",
        "content": content or None,
        "tool_calls": serialized_calls,
    }
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    if thinking_blocks:
        message["thinking_blocks"] = thinking_blocks
    return message


def assistant_message(
    content: str,
    *,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a plain assistant turn, carrying its reasoning when there was any.

    The tool-call builder above and this one exist for the same reason: a
    thinking model's history has to keep the reasoning that produced each
    assistant turn, or the provider refuses the continuation. Which of the two
    a round needs depends only on whether it called tools.
    """
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    if thinking_blocks:
        message["thinking_blocks"] = thinking_blocks
    return message


__all__ = ["assistant_message", "assistant_message_with_tool_calls"]
