"""Canonical message builders for agentic conversations."""

from __future__ import annotations

from typing import Any


def image_content_hashes(messages: list[dict]) -> list[str]:
    """Hashes of bounded image bytes on the accepted provider wire (#1611)."""
    from base64 import b64decode
    from hashlib import sha256

    hashes = set()
    for message in messages:
        content = message.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            value = part.get("image_url")
            url = value.get("url") if isinstance(value, dict) else value
            source = part.get("source")
            if (
                part.get("type") == "image"
                and isinstance(source, dict)
                and source.get("type") == "base64"
            ):
                url = f"data:{source.get('media_type', '')};base64,{source.get('data', '')}"
            if (
                not isinstance(url, str)
                or not url.startswith("data:image/")
                or ";base64," not in url
            ):
                continue
            encoded = url.split(";base64,", 1)[1]
            if len(encoded) > 7 * 1024 * 1024:
                continue
            try:
                hashes.add(sha256(b64decode(encoded, validate=True)).hexdigest())
            except ValueError:
                continue
    return sorted(hashes)


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


def with_transient_model_messages(
    messages: list[dict[str, Any]], transient: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Place model-only images after their tool result without mutating history."""
    if not transient:
        return messages
    anchored: dict[str, list[dict[str, Any]]] = {}
    for item in transient:
        tool_call_id = item.get("_after_tool_call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            continue
        anchored.setdefault(tool_call_id, []).append({"role": "user", "content": item["content"]})
    request_messages: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        request_messages.append(message)
        if message.get("role") == "tool":
            pending.extend(anchored.pop(str(message.get("tool_call_id") or ""), []))
            # Providers require all replies to one assistant tool-call batch
            # before another user message. Inject images after the batch.
            if index + 1 == len(messages) or messages[index + 1].get("role") != "tool":
                request_messages.extend(pending)
                pending.clear()
    return request_messages


def _transient_image_count(message: dict[str, Any]) -> int:
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    return sum(1 for part in content if isinstance(part, dict) and part.get("type") == "image_url")


def extend_transient_model_messages(
    transient: list[dict[str, Any]], incoming: list[dict[str, Any]], *, max_images: int = 2
) -> None:
    """Keep the latest bounded source evidence across tool rounds."""
    transient.extend(incoming)
    while sum(_transient_image_count(item) for item in transient) > max_images:
        transient.pop(0)


__all__ = [
    "assistant_message",
    "assistant_message_with_tool_calls",
    "extend_transient_model_messages",
    "with_transient_model_messages",
]
