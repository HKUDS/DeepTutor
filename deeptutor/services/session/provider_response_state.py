"""Validation and redaction for provider-private response replay state."""

from __future__ import annotations

import json
from typing import Any

MAX_REASONING_CONTENT_CHARS = 64_000
MAX_RESPONSE_OUTPUT_ITEMS = 64
MAX_RESPONSE_OUTPUT_BYTES = 256 * 1024
MAX_THINKING_BLOCKS = 64
MAX_THINKING_BLOCK_BYTES = 256 * 1024

# These are the output item kinds emitted by the Responses API that the
# agentic loop can legitimately need on the next request.  In particular,
# function_call_output is an input item built from our own tool message and
# must never be accepted from persisted provider state.
_ALLOWED_RESPONSE_OUTPUT_TYPES = frozenset(
    {"reasoning", "message", "function_call", "web_search_call", "web_search"}
)
_PRIVATE_MESSAGE_METADATA_KEYS = frozenset({"provider_response_state"})


def _normalized_output_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_RESPONSE_OUTPUT_ITEMS:
        return []

    normalized: list[dict[str, Any]] = []
    total_bytes = 0
    for item in value:
        if not isinstance(item, dict) or item.get("type") not in _ALLOWED_RESPONSE_OUTPUT_TYPES:
            return []
        try:
            encoded = json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            cloned = json.loads(encoded)
        except (TypeError, ValueError):
            return []
        total_bytes += len(encoded)
        if total_bytes > MAX_RESPONSE_OUTPUT_BYTES or not isinstance(cloned, dict):
            return []
        normalized.append(cloned)
    return normalized


def _normalized_thinking_blocks(value: Any) -> list[dict[str, Any]]:
    """Bound Anthropic's signed thinking blocks for persistence and replay.

    Only ``thinking`` blocks are accepted, and only with the two fields the
    provider replays. A block is useless without its signature, so one that
    lost it is dropped rather than sent back: Anthropic rejects an unsigned
    replay, which would turn a missing signature into a failed turn.
    """
    if not isinstance(value, list) or len(value) > MAX_THINKING_BLOCKS:
        return []
    normalized: list[dict[str, Any]] = []
    total_bytes = 0
    for item in value:
        if not isinstance(item, dict) or item.get("type") != "thinking":
            return []
        thinking = item.get("thinking")
        signature = item.get("signature")
        if not isinstance(thinking, str) or not isinstance(signature, str) or not signature:
            return []
        block = {"type": "thinking", "thinking": thinking, "signature": signature}
        try:
            encoded = json.dumps(
                block,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            return []
        total_bytes += len(encoded)
        if total_bytes > MAX_THINKING_BLOCK_BYTES:
            return []
        normalized.append(block)
    return normalized


def normalize_provider_response_state(value: Any) -> dict[str, Any] | None:
    """Return bounded, JSON-safe provider state suitable for persistence/replay."""
    if not isinstance(value, dict):
        return None

    normalized: dict[str, Any] = {}
    reasoning_content = value.get("reasoning_content")
    if (
        isinstance(reasoning_content, str)
        and reasoning_content
        and len(reasoning_content) <= MAX_REASONING_CONTENT_CHARS
    ):
        normalized["reasoning_content"] = reasoning_content

    output_items = _normalized_output_items(value.get("responses_output_items"))
    if output_items:
        normalized["responses_output_items"] = output_items

    thinking_blocks = _normalized_thinking_blocks(value.get("thinking_blocks"))
    if thinking_blocks:
        normalized["thinking_blocks"] = thinking_blocks

    return normalized or None


def redact_private_message_metadata(messages: list[dict[str, Any]]) -> None:
    """Remove provider-only replay state before messages cross a public boundary."""
    for message in messages:
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in _PRIVATE_MESSAGE_METADATA_KEYS:
            metadata.pop(key, None)
