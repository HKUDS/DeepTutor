"""Lossless sharing of repeated mastery state inside one model request.

This is a request projection, not session compaction. Raw history stays intact.
Only known state fields are eligible; dialogue and source/tool evidence are not.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Any

from deeptutor.services.session.model_history import _MASTERY_SNAPSHOT_NOTICE

STATE_REFERENCE_NOTICE = (
    "\n\n[Historical mastery state sharing]\n"
    'A {"$mastery_same_value": {"tool_call_id": "...", "pointer": "/..."}} '
    'or {"$mastery_same_value": {"snapshot": "mastery_status_snapshot", "pointer": "/..."}} '
    "inside a tool result means EXACTLY the same JSON value at that "
    "pointer in the named tool result or runtime snapshot's full payload. "
    "For a mastery status snapshot, the payload is the JSON after its notice. "
    "The referenced value is included in this request, not external memory. "
    "Only identical repeated state is shared; unique past state and learner "
    "exchanges are retained. Historical status is not current progress."
)

_FIELDS = {
    "mastery_status": (
        "map",
        "learner_profile",
        "learning_stages",
        "visual_requirements",
        "sources",
    ),
    "mastery_build": ("map",),
    "mastery_revise": ("map",),
    "mastery_revise_batch": ("map", "proposed_map"),
    "mastery_profile": ("learner_profile",),
}


def project_mastery_replay(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project past turns; the loop supplies fresh runtime state and evidence.

    Never interpret an unmarked user quotation as runtime context. Tool pairs,
    dialogue and unique historical state stay intact until successful condensing.
    """
    projected = deepcopy(
        [
            m
            for m in messages
            if not (m.get("role") == "user" and (isinstance(m.get("_context_snapshot"), str)))
        ]
    )
    share_mastery_history(projected, len(projected))
    return projected


def share_mastery_history(messages: list[dict[str, Any]], history_end: int) -> None:
    """Share exact repeated state in the owned historical request copy in-place.

    References point forward to full values, never to another reference. Current
    messages are anchors only. No messages are added/removed, so turn boundaries
    and tool protocol remain unchanged. Ambiguous call IDs are not eligible.
    """
    calls = [call for m in messages for call in m.get("tool_calls", [])]
    counts = Counter(call.get("id") for call in calls)
    results = Counter(m.get("tool_call_id") for m in messages if m.get("role") == "tool")
    names = {
        call["id"]: call.get("function", {}).get("name")
        for call in calls
        if isinstance(call.get("id"), str) and counts[call["id"]] == 1 and results[call["id"]] == 1
    }
    snapshot_count = sum(m.get("_context_snapshot") == "mastery_status_snapshot" for m in messages)
    anchors: dict[str, dict[str, Any]] = {}

    def visit(
        value: Any, locator: dict[str, str], pointer: str, *, replace: bool
    ) -> tuple[Any, bool]:
        if not isinstance(value, (dict, list)):
            return value, False
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        # Small values cost less verbatim than a locator plus its explanation.
        candidate = anchors.get(encoded) if len(encoded) >= 512 else None
        if replace and candidate is not None:
            reference = {"$mastery_same_value": candidate}
            if len(json.dumps(reference)) < len(encoded):
                return reference, True
        changed = False
        result: Any = {} if isinstance(value, dict) else []
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            token = str(key).replace("~", "~0").replace("/", "~1")
            projected, shared = visit(child, locator, f"{pointer}/{token}", replace=replace)
            if isinstance(result, dict):
                result[key] = projected
            else:
                result.append(projected)
            changed |= shared
        # A projected parent is not a full anchor. This excludes reference chains.
        if not changed and len(encoded) >= 512:
            anchors.setdefault(encoded, {**locator, "pointer": pointer})
        return result, changed

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        content = message.get("content")
        if not isinstance(content, str):
            continue
        is_snapshot = (
            message.get("role") == "user"
            and snapshot_count == 1
            and message.get("_context_snapshot") == "mastery_status_snapshot"
            and content.startswith(_MASTERY_SNAPSHOT_NOTICE)
        )
        name = names.get(message.get("tool_call_id")) if message.get("role") == "tool" else None
        if not is_snapshot and name not in _FIELDS:
            continue
        try:
            payload = json.loads(
                content[len(_MASTERY_SNAPSHOT_NOTICE) :] if is_snapshot else content
            )
            if not isinstance(payload, dict):
                continue
            # Do not reinterpret non-standard numbers or pre-existing reference syntax.
            encoded = json.dumps(payload, allow_nan=False)
            if '"$mastery_same_value"' in encoded:
                continue
        except (ValueError, TypeError):
            continue
        if is_snapshot and not isinstance(payload.get("path_id"), str):
            continue
        fields = _FIELDS["mastery_status"] if is_snapshot else _FIELDS[name]
        locator = (
            {"snapshot": "mastery_status_snapshot"}
            if is_snapshot
            else {"tool_call_id": message["tool_call_id"]}
        )
        changed = False
        for field in fields:
            if field not in payload:
                continue
            projected, shared = visit(
                payload[field],
                locator,
                f"/{field}",
                replace=index < history_end and not is_snapshot,
            )
            payload[field] = projected
            changed |= shared
        if changed:
            message["content"] = json.dumps(payload, ensure_ascii=False)
