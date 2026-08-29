"""Canonical message builders for agentic conversations."""

from __future__ import annotations

from typing import Any


def assistant_message_with_tool_calls(
    content: str,
    tool_calls: list[dict[str, Any]],
    *,
    reasoning_content: str | None = None,
) -> dict[str, Any]:
    """Build the assistant message that precedes tool result messages.

    ``reasoning_content`` is optional: DeepSeek thinking-mode Chat Completions
    requires the prior round's reasoning to be echoed on the assistant turn
    that issued the tool calls (#1058). Responses-API replay is handled
    separately via ``_responses_output_items``.
    """
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": tool_call["id"],
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": tool_call.get("arguments") or "{}",
                },
            }
            for tool_call in tool_calls
        ],
    }
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return message


__all__ = ["assistant_message_with_tool_calls"]
