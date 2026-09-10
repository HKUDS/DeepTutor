"""Bounded event previews used by session-detail responses.

``turn_events`` remains the authoritative full trace. Session lists only need
enough semantic state to render a completed message, resume pending input, and
offer the trace disclosure; the complete trace is fetched on demand.
"""

from __future__ import annotations

import copy
import json
from typing import Any

MAX_TRACE_PREVIEW_EVENTS = 200
MAX_TRACE_PREVIEW_BYTES = 128 * 1024
MAX_LEGACY_EVENT_PAYLOAD_CHARS = 16 * 1024
_TRUNCATION_NOTICE = "...[truncated]"
_TERMINAL_EVENT_TYPES = frozenset({"done", "error", "cancelled"})
_SEMANTIC_EVENT_TYPES = _TERMINAL_EVENT_TYPES | {
    "result",
    "tool_call",
    "tool_result",
}


def _metadata(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


#: Tool-metadata keys an interactive card travels under: the generic
#: ``ask_user`` one and the mastery course's own question card. A card is the
#: one trace row a settled message cannot be rendered without, so both have to
#: be named here — a preview that drops one leaves the learner looking at a
#: question they can no longer answer.
_CARD_METADATA_KEYS = ("ask_user", "mastery_question")


def _carries_card(event: dict[str, Any]) -> bool:
    metadata = _metadata(event)
    if metadata.get("ask_user_resolved"):
        return True
    tool_metadata = metadata.get("tool_metadata")
    return any(
        metadata.get(key)
        or (isinstance(tool_metadata, dict) and isinstance(tool_metadata.get(key), dict))
        for key in _CARD_METADATA_KEYS
    )


def _is_semantic(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or "")
    if event_type in _SEMANTIC_EVENT_TYPES:
        return True
    return _carries_card(event)


def _is_critical(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "") in _TERMINAL_EVENT_TYPES | {"result"}:
        return True
    return _carries_card(event)


def _truncate_legacy_payloads(event: dict[str, Any]) -> dict[str, Any]:
    """Bound old embedded payloads without mutating the source event."""
    truncated = False
    bounded = copy.deepcopy(event)

    def cap(container: dict[str, Any], field: str) -> None:
        nonlocal truncated
        value = container.get(field)
        if isinstance(value, str) and len(value) > MAX_LEGACY_EVENT_PAYLOAD_CHARS:
            container[field] = value[:MAX_LEGACY_EVENT_PAYLOAD_CHARS] + _TRUNCATION_NOTICE
            truncated = True

    cap(bounded, "content")
    metadata = bounded.get("metadata")
    if isinstance(metadata, dict):
        tool_metadata = metadata.get("tool_metadata")
        if isinstance(tool_metadata, dict):
            cap(tool_metadata, "content")
            cap(tool_metadata, "answer")
    return bounded if truncated else event


def compact_trace_preview(
    events: list[dict[str, Any]],
    *,
    max_events: int = MAX_TRACE_PREVIEW_EVENTS,
    max_bytes: int = MAX_TRACE_PREVIEW_BYTES,
) -> tuple[list[dict[str, Any]], bool]:
    """Return a bounded semantic preview and whether any event was omitted."""
    semantic = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, dict) and _is_semantic(event)
    ]
    # Cards, results, errors, and terminal state outrank ordinary trace rows.
    # Keep the most recent critical rows, then fill toward the turn's tail.
    critical = {index for index, event in semantic if _is_critical(event)}
    if len(critical) > max_events:
        ordered_critical = sorted(critical)
        critical = set(ordered_critical[-max_events:])
    selected_indices = set(critical)
    for index, _event in reversed(semantic):
        if len(selected_indices) >= max_events:
            break
        selected_indices.add(index)
    selected = [event for index, event in semantic if index in selected_indices]
    result: list[dict[str, Any]] = []
    used_bytes = 0
    for event in selected:
        bounded = _truncate_legacy_payloads(event)
        size = len(json.dumps(bounded, ensure_ascii=False, default=str).encode("utf-8"))
        if result and used_bytes + size > max_bytes:
            continue
        if not result and size > max_bytes:
            bounded = {
                "type": bounded.get("type", ""),
                "turn_id": bounded.get("turn_id"),
                "session_id": bounded.get("session_id"),
                "seq": bounded.get("seq"),
                "content": _TRUNCATION_NOTICE,
                "_truncated": True,
            }
            size = len(json.dumps(bounded, ensure_ascii=False, default=str).encode("utf-8"))
        result.append(bounded)
        used_bytes += size

    omitted = len(events) != len(result) or len(selected) != len(result)
    terminal = next(
        (
            event
            for event in reversed(result)
            if str(event.get("type") or "") in _TERMINAL_EVENT_TYPES
        ),
        None,
    )
    if terminal is None:
        for event in reversed(events):
            if isinstance(event, dict) and str(event.get("type") or "") in _TERMINAL_EVENT_TYPES:
                result.append(copy.deepcopy(event))
                break
    return result, omitted
