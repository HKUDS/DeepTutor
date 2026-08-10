"""Canonical message builders for agentic conversations."""

from __future__ import annotations

from typing import Any


def assistant_message_with_tool_calls(
    content: str,
    tool_calls: list[dict[str, Any]],
    *,
    continuation_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the assistant message that precedes tool result messages."""
    message = {
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
    if continuation_items:
        message["responses_continuation_items"] = list(continuation_items)
    return message


__all__ = ["assistant_message_with_tool_calls"]
