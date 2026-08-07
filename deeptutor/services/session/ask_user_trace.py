"""Recover resolved ``ask_user`` exchanges from persisted assistant rows.

Card replies resume the same backend turn, so they are stored in the assistant
message's event trace rather than as standalone user messages. Rehydrate them
into future model context or later turns would forget the answers and could ask
the same questions again.
"""

from __future__ import annotations

import json
from typing import Any

#: Raw-text probe run before parsing a stored trace. An assistant row can hold
#: a thousand streamed content deltas, and only the rare row that paused on
#: ``ask_user`` is worth the JSON parse.
_RESOLVED_MARKER = '"ask_user_resolved"'


def _ask_user_payload(metadata: dict[str, Any]) -> dict[str, Any] | None:
    tool_metadata = metadata.get("tool_metadata")
    payload = (
        tool_metadata.get("ask_user") if isinstance(tool_metadata, dict) else None
    ) or metadata.get("ask_user")
    return payload if isinstance(payload, dict) else None


def _is_ask_user_event(event: dict[str, Any]) -> bool:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return False
    if metadata.get("ask_user_resolved"):
        return True
    return event.get("type") == "tool_result" and _ask_user_payload(metadata) is not None


def filter_ask_user_events(events: Any) -> list[dict[str, Any]]:
    """Keep only the ask_user exchanges of an already-parsed event trace.

    Context building never needs the streamed deltas, so the caller keeps only
    these events instead of holding a full trace per message in memory.
    """
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict) and _is_ask_user_event(event)]


def select_ask_user_events(raw_events: str | None) -> list[dict[str, Any]]:
    """Filter a stored ``events_json`` blob down to its ask_user exchanges."""
    if not raw_events or _RESOLVED_MARKER not in raw_events:
        return []
    try:
        return filter_ask_user_events(json.loads(raw_events))
    except (TypeError, ValueError):
        return []


def extract_ask_user_clarifications(message: dict[str, Any]) -> str:
    """Render a message's resolved ask_user exchanges as plain context text."""

    pending_questions: dict[str, str] = {}
    exchanges: list[tuple[str, str]] = []
    for event in message.get("events") or []:
        if not isinstance(event, dict):
            continue
        metadata = event.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        if event.get("type") == "tool_result":
            ask_user = _ask_user_payload(metadata)
            if ask_user is None:
                continue
            pending_questions = {
                str(question.get("id") or ""): str(question.get("prompt") or "").strip()
                for question in ask_user.get("questions") or []
                if isinstance(question, dict) and str(question.get("prompt") or "").strip()
            }
            continue
        if not metadata.get("ask_user_resolved"):
            continue
        answers = metadata.get("answers") or []
        resolved = False
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            question_id = str(answer.get("questionId") or answer.get("question_id") or "")
            answer_text = str(answer.get("text") or "").strip()
            question_text = pending_questions.get(question_id, question_id).strip()
            if question_text and answer_text:
                exchanges.append((question_text, answer_text))
                resolved = True
        if not resolved:
            preview = str(metadata.get("reply_preview") or "").strip()
            if preview:
                question_text = next(iter(pending_questions.values()), "User clarification")
                exchanges.append((question_text, preview))
        pending_questions = {}

    if not exchanges:
        return ""
    lines = ["[Earlier ask_user clarification — treat these answers as user-provided context]"]
    for question, answer in exchanges:
        lines.extend((f"- Question: {question}", f"  User answer: {answer}"))
    return "\n".join(lines)


__all__ = [
    "extract_ask_user_clarifications",
    "filter_ask_user_events",
    "select_ask_user_events",
]
