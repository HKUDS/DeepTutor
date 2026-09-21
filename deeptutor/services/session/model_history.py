"""Private, versioned model messages retained independently of display text.

Each assistant row owns one complete turn, including its prepared user input,
context updates and tool exchanges. Retention operates on these whole turns;
an older database without this metadata continues to use display history.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

MODEL_TURN_KEY = "model_turn"
MODEL_TURN_VERSION = 1
_MESSAGE_KEYS = frozenset(
    {
        "role",
        "content",
        "tool_calls",
        "tool_call_id",
        "name",
        "reasoning_content",
        "thinking_blocks",
        "_provider_response_state",
        "_context_snapshot",
    }
)


def normalize_model_turn(value: Any) -> dict[str, Any] | None:
    """Read an internal turn record only when its tool protocol is complete.

    Unknown versions and incomplete writes fall back to the displayed exchange.
    Do not truncate reasoning, image blocks or tool arguments during replay.
    """
    if not isinstance(value, dict) or value.get("version") != MODEL_TURN_VERSION:
        return None
    if "system" in value and not isinstance(value["system"], str):
        return None
    tools = value.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            return None
        for tool in tools:
            if (
                not isinstance(tool, dict)
                or not isinstance(tool.get("function"), dict)
                or not isinstance(tool["function"].get("name"), str)
            ):
                return None
    route = value.get("route")
    if route is not None and (
        not isinstance(route, dict)
        or any(not isinstance(route.get(key), str) for key in ("provider", "model"))
    ):
        return None
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    pending: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            return None
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                return None
            pending.remove(call_id)
        elif pending:
            return None
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or (calls and role != "assistant"):
            return None
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                return None
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id or call_id in pending:
                return None
            pending.add(call_id)
        if message.get("content") is not None and not isinstance(message["content"], (str, list)):
            return None
        cleaned.append({k: v for k, v in message.items() if k in _MESSAGE_KEYS})
    if pending:
        return None
    record = {"version": MODEL_TURN_VERSION, "messages": cleaned}
    for key in ("system", "tools", "route", "request_fingerprint"):
        if key in value:
            record[key] = value[key]
    try:
        return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return None


def model_turn(row: dict[str, Any]) -> dict[str, Any] | None:
    metadata = row.get("metadata")
    return (
        normalize_model_turn(metadata.get(MODEL_TURN_KEY)) if isinstance(metadata, dict) else None
    )


def history_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Keep an admitted user and its assistant together across budget cuts."""
    groups: list[list[dict[str, Any]]] = []
    for row in rows:
        if (
            row.get("role") == "assistant"
            and model_turn(row) is not None
            and groups
            and groups[-1][-1].get("role") == "user"
        ):
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def replay_group(
    rows: list[dict[str, Any]], route: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Prefer the model's complete exchange over the corresponding UI rows."""
    from .context_builder import expand_message_context

    if rows and rows[-1].get("role") == "assistant":
        record = model_turn(rows[-1])
        if record is not None:
            messages = record["messages"]
            if route and record.get("route") and record["route"] != route:
                # Signed thinking/encrypted response items belong to the route
                # that produced them. Tool evidence and public text are portable.
                for message in messages:
                    for key in ("_provider_response_state", "thinking_blocks", "reasoning_content"):
                        message.pop(key, None)
                    for call in message.get("tool_calls") or []:
                        call.pop("extra_content", None)
            return messages
    messages = []
    for row in rows:
        expanded = expand_message_context(row)
        metadata = row.get("metadata") or {}
        if row.get("role") == "assistant" and expanded:
            from .provider_response_state import normalize_provider_response_state

            state = normalize_provider_response_state(metadata.get("provider_response_state"))
            if state:
                expanded[-1]["_provider_response_state"] = state
        messages.extend(expanded)
    return messages


def replay_history(
    rows: list[dict[str, Any]],
    summary: str = "",
    route: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    messages = (
        [{"role": "system", "content": f"[Conversation summary]\n{summary}"}] if summary else []
    )
    for group in history_groups(rows):
        messages.extend(replay_group(group, route))
    return messages


def complete_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Close calls interrupted before their results could be admitted."""
    result = deepcopy(messages)
    pending: dict[str, None] = {}
    for message in result:
        for call in message.get("tool_calls") or []:
            pending[call["id"]] = None
        if message.get("role") == "tool":
            pending.pop(message.get("tool_call_id"), None)
    for call_id in pending:
        result.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "The turn was interrupted before this tool result was available. Do not assume it succeeded.",
            }
        )
    return result
