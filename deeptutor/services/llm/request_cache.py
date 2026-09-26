"""Content-free diagnostics for consecutive agent-loop request prefixes.

These observations describe the canonical request before provider translation.
Only the provider's usage counters establish real KV-cache hits.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def fingerprint_request(
    messages: list[dict[str, Any]],
    tools: Any,
    route: dict[str, Any],
) -> dict[str, Any]:
    from deeptutor.services.session.context_builder import count_tokens

    # Hash an entire message, never individual tokens (which disclose vocabulary).
    return {
        "route": _digest(route),
        "tools": _digest(tools or []),
        "messages": [
            {
                "hash": _digest(message),
                "tokens": count_tokens(_encoded(message)),
                "role": message.get("role"),
            }
            for message in messages
        ],
    }


def compare_requests(previous: Any, current: dict[str, Any]) -> dict[str, Any]:
    """Report a conservative common prefix made of whole unchanged messages."""
    if not isinstance(previous, dict):
        return {"first_change": "first_observed_request", "shared_prefix_messages": 0}
    for key in ("route", "tools"):
        if previous.get(key) != current[key]:
            return {"first_change": key, "shared_prefix_messages": 0}
    old = previous.get("messages") or []
    if not isinstance(old, list) or any(not isinstance(item, dict) for item in old):
        return {"first_change": "first_observed_request", "shared_prefix_messages": 0}
    new = current["messages"]
    shared = 0
    tokens = 0
    for before, after in zip(old, new):
        if before.get("hash") != after["hash"]:
            break
        shared += 1
        tokens += after["tokens"]
    return {
        "first_change": (
            "append"
            if shared == len(old) and len(new) >= len(old)
            else "system"
            if shared == 0 and new and new[0]["role"] == "system"
            else "history"
        ),
        "shared_prefix_messages": shared,
        "shared_prefix_tokens_estimate": tokens,
        "previous_request_messages": len(old),
    }
