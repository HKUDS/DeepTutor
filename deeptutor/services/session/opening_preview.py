"""What a conversation needs the moment it is opened.

Bubble text lives on the message row. Tool folds, thinking, and cards the
reader has already dealt with stay in ``turn_events`` until they open the
trace. The events that still have to travel with the open are question cards
they can answer.
"""

from __future__ import annotations

from typing import Any, Callable


def select_opening_events(messages: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
    """Unfinished card events keyed by message id.

    ``messages`` are in chronological order. Each item carries ``id``,
    ``role``, ``metadata``, ``candidates`` (events in seq order), and
    ``project``. Rows with ``project`` false are still walked — a later grade
    or answer has to be able to close an earlier card — but their events are
    not returned. The caller keeps whatever preview those rows already have.
    """
    closed: set[str] = set()
    open_asks: dict[str, dict[str, Any]] = {}
    anonymous_asks: list[dict[str, Any]] = []
    poses: list[tuple[Any, dict[str, Any], str]] = []
    ask_poses: list[tuple[Any, dict[str, Any]]] = []
    grades: dict[str, tuple[Any, dict[str, Any]]] = {}
    rejections: dict[str, tuple[Any, dict[str, Any]]] = {}

    def close(question_id: str) -> None:
        question_id = question_id.strip()
        if question_id:
            closed.add(question_id)

    def reopen(question_id: str) -> None:
        closed.discard(question_id.strip())

    for message in messages:
        metadata = message.get("metadata")
        if message.get("role") == "user" and isinstance(metadata, dict):
            _apply_user_closure(metadata, close)
        project = bool(message.get("project"))
        message_id = message.get("id")
        for event in message.get("candidates") or []:
            if isinstance(event, dict):
                _apply_event(
                    event,
                    message_id,
                    project,
                    close,
                    reopen,
                    open_asks,
                    anonymous_asks,
                    poses,
                    ask_poses,
                    grades,
                    rejections,
                )

    kept: dict[Any, list[dict[str, Any]]] = {}
    open_ask_ids = {id(event) for event in open_asks.values()}
    open_ask_ids.update(id(event) for event in anonymous_asks)

    def add(message_id: Any, event: dict[str, Any]) -> None:
        kept.setdefault(message_id, []).append(event)

    for message_id, event, question_id in poses:
        if question_id not in closed:
            add(message_id, event)
    for message_id, event in ask_poses:
        if id(event) in open_ask_ids:
            add(message_id, event)
    for question_id, (message_id, event) in grades.items():
        if question_id not in closed:
            add(message_id, event)
    for question_id, (message_id, event) in rejections.items():
        if question_id not in closed:
            add(message_id, event)
    for events in kept.values():
        events.sort(key=lambda event: int(event.get("seq") or 0))
    return kept


def project_loaded_messages(messages: list[dict[str, Any]]) -> None:
    """Drop tool-fold events from an already-loaded session detail, in place.

    Used where the store has already read a trace preview (PocketBase). A
    message with no ``turn_id`` keeps that preview: there is no trace endpoint
    to fetch the rest from.
    """
    prepared: list[dict[str, Any]] = []
    for message in messages:
        trace = message.get("trace") if isinstance(message.get("trace"), dict) else {}
        prepared.append(
            {
                "id": message.get("id"),
                "role": message.get("role"),
                "metadata": message.get("metadata") or {},
                "candidates": message.get("events") or [],
                "project": message.get("role") == "assistant" and bool(trace.get("turn_id")),
            }
        )
    kept = select_opening_events(prepared)
    for message in messages:
        trace = message.get("trace") if isinstance(message.get("trace"), dict) else {}
        if message.get("role") != "assistant" or not trace.get("turn_id"):
            continue
        events = kept.get(message.get("id"), [])
        message["events"] = events
        total = int(trace.get("total") or 0)
        trace["truncated"] = bool(trace.get("truncated")) or total != len(events)
        message["trace"] = trace


def _apply_user_closure(metadata: dict[str, Any], close: Callable[[str], None]) -> None:
    snapshot = metadata.get("request_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = metadata
    answer = snapshot.get("masteryAnswer") or snapshot.get("mastery_answer") or {}
    if isinstance(answer, dict):
        close(str(answer.get("question_id") or ""))
        answers = answer.get("answers")
        if isinstance(answers, dict):
            for child_id in answers:
                close(str(child_id))
    skip = snapshot.get("masterySkip") or snapshot.get("mastery_skip") or {}
    if isinstance(skip, dict):
        close(str(skip.get("question_id") or ""))


def _apply_event(
    event: dict[str, Any],
    message_id: Any,
    project: bool,
    close: Callable[[str], None],
    reopen: Callable[[str], None],
    open_asks: dict[str, dict[str, Any]],
    anonymous_asks: list[dict[str, Any]],
    poses: list[tuple[Any, dict[str, Any], str]],
    ask_poses: list[tuple[Any, dict[str, Any]]],
    grades: dict[str, tuple[Any, dict[str, Any]]],
    rejections: dict[str, tuple[Any, dict[str, Any]]],
) -> None:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if metadata.get("ask_user_resolved"):
        _resolve_ask(metadata, open_asks, anonymous_asks)
        return
    question = _mastery_question(event)
    if question is not None:
        question_id = str(question.get("question_id") or "").strip()
        if project and question_id:
            poses.append((message_id, event, question_id))
        return
    grade = _grade_result(event)
    if grade is not None:
        question_id = str(grade.get("question_id") or "").strip()
        if _settled(grade):
            close(question_id)
            for child in grade.get("results") or []:
                if isinstance(child, dict):
                    close(str(child.get("question_id") or ""))
        elif project and question_id:
            grades[question_id] = (message_id, event)
        return
    tool_metadata = _tool_metadata(event)
    skip = tool_metadata.get("mastery_skip_question")
    if isinstance(skip, dict) and skip.get("skipped") is True:
        close(str(skip.get("question_id") or ""))
        return
    rejected = tool_metadata.get("mastery_answer_rejected")
    if isinstance(rejected, dict):
        question_id = str(rejected.get("question_id") or "").strip()
        reopen(question_id)
        if project and question_id:
            rejections[question_id] = (message_id, event)
        return
    if _is_ask_user_pose(event):
        call_id = _call_id(event)
        if call_id:
            open_asks[call_id] = event
        else:
            anonymous_asks.append(event)
        if project:
            ask_poses.append((message_id, event))


def _resolve_ask(
    metadata: dict[str, Any],
    open_asks: dict[str, dict[str, Any]],
    anonymous_asks: list[dict[str, Any]],
) -> None:
    call_id = str(metadata.get("ask_user_tool_call_id") or "").strip()
    if call_id and call_id in open_asks:
        del open_asks[call_id]
        return
    # A resolution that does not name a live call closes the latest card, which
    # is how the transcript matches a reply that omitted the tool-call id.
    if anonymous_asks:
        anonymous_asks.pop()
        return
    if open_asks:
        open_asks.pop(next(reversed(open_asks)))


def _tool_metadata(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    tool_metadata = metadata.get("tool_metadata")
    return tool_metadata if isinstance(tool_metadata, dict) else {}


def _payload(event: dict[str, Any], key: str) -> dict[str, Any] | None:
    tool_metadata = _tool_metadata(event)
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    value = tool_metadata.get(key) or metadata.get(key)
    return value if isinstance(value, dict) else None


def _mastery_question(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "tool_result":
        return None
    own = _payload(event, "mastery_question")
    if own is not None and str(own.get("question_id") or "").strip():
        return own
    ask_user = _payload(event, "ask_user")
    if not isinstance(ask_user, dict) or ask_user.get("kind") != "mastery_question":
        return None
    nested = ask_user.get("mastery_question")
    if isinstance(nested, dict) and str(nested.get("question_id") or "").strip():
        return nested
    return None


def _grade_result(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "tool_result":
        return None
    payload = _payload(event, "mastery_grade")
    if payload is None:
        return None
    result = payload.get("result")
    if isinstance(result, dict):
        if not str(result.get("question_id") or "").strip():
            question_id = str(payload.get("question_id") or "").strip()
            if question_id:
                return {**result, "question_id": question_id}
        return result
    return None


def _settled(grade: dict[str, Any]) -> bool:
    return grade.get("complete") is not False and grade.get("final") is not False


def _is_ask_user_pose(event: dict[str, Any]) -> bool:
    if event.get("type") != "tool_result":
        return False
    payload = _payload(event, "ask_user")
    return isinstance(payload, dict) and payload.get("kind") != "mastery_question"


def _call_id(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    for value in (metadata.get("tool_call_id"), event.get("tool_call_id")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
