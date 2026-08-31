"""
Unified session history API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from deeptutor.learning.storage import LearningStore
from deeptutor.services.session import get_session_store, get_sqlite_session_store
from deeptutor.services.session.organization import (
    list_all_sessions_snapshot,
    validate_parent_assignment,
)
from deeptutor.services.session.provider_response_state import (
    redact_private_message_metadata as _redact_provider_state_metadata,
)
from deeptutor.services.storage.attachment_store import get_attachment_store

logger = logging.getLogger(__name__)

router = APIRouter()


class SessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class BranchSelectionRequest(BaseModel):
    """Edit-branch picker state: `{parent_message_id: chosen_child_id}`.

    Stored inside the session preferences blob so it survives reloads
    without a dedicated column.
    """

    selected_branches: dict[str, int] = Field(default_factory=dict)


class SessionOrganizationRequest(BaseModel):
    """User-controlled organization metadata stored with the conversation."""

    course_id: str | None = None
    parent_session_id: str | None = None
    session_kind: Literal["chat", "selection_tutor", "immersive_reading"] | None = None
    pinned: bool | None = None
    archived: bool | None = None


class QuizResultItem(BaseModel):
    question_id: str = ""
    question: str = Field(..., min_length=1)
    question_type: str = ""
    options: dict[str, str] | None = None
    user_answer: str = ""
    correct_answer: str = ""
    explanation: str | None = ""
    difficulty: str | None = ""
    is_correct: bool

    @field_validator("options", mode="before")
    @classmethod
    def _coerce_options(cls, v):
        return v if isinstance(v, dict) else {}

    @field_validator("explanation", "difficulty", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return v if isinstance(v, str) else ""


class QuizResultsRequest(BaseModel):
    answers: list[QuizResultItem] = Field(default_factory=list)
    turn_id: str = ""


def _format_quiz_results_message(answers: list[QuizResultItem]) -> str:
    total = len(answers)
    correct = sum(1 for item in answers if item.is_correct)
    score_pct = round((correct / total) * 100) if total else 0
    lines = ["[Quiz Performance]"]
    for idx, item in enumerate(answers, 1):
        question = item.question.strip().replace("\n", " ")
        user_answer = (item.user_answer or "").strip() or "(blank)"
        status = "Correct" if item.is_correct else "Incorrect"
        suffix = f" ({status})"
        if not item.is_correct and (item.correct_answer or "").strip():
            suffix = f" ({status}, correct: {(item.correct_answer or '').strip()})"
        qid = f"[{item.question_id}] " if item.question_id else ""
        lines.append(f"{idx}. {qid}Q: {question} -> Answered: {user_answer}{suffix}")
    lines.append(f"Score: {correct}/{total} ({score_pct}%)")
    return "\n".join(lines)


@router.get("")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    store = get_session_store()
    sessions = await store.list_sessions(limit=limit, offset=offset)
    return {"sessions": sessions}


# Cap (in characters) for a single event payload returned to the UI. RAG
# tools can attach whole KB documents to ``tool_result``/``observation``
# events; the frontend TraceSurface only needs a preview, and the LLM context
# is built from a separate content-only store, so capping here never affects
# model input.
MAX_EVENT_PAYLOAD = 1024 * 1024
_TRUNCATION_NOTICE = "\n\n[... content truncated]"
_TRUNCATABLE_EVENT_TYPES = ("tool_result", "observation")


def _redact_private_message_metadata(messages: list[dict[str, Any]]) -> None:
    """Remove provider-only state before session details cross the API."""
    _redact_provider_state_metadata(messages)


def _truncate_oversized_events(
    messages: list[dict[str, Any]], limit: int = MAX_EVENT_PAYLOAD
) -> None:
    """Cap oversized ``tool_result``/``observation`` payloads in place.

    The session store already returns each message's events as a parsed
    ``events`` list (see ``SqliteSessionStore._serialize_message``), so we
    mutate that list directly. Only the UI rendering path is affected.
    """

    def _cap(container: dict[str, Any], field: str) -> bool:
        value = container.get(field)
        if isinstance(value, str) and len(value) > limit:
            container[field] = value[:limit] + _TRUNCATION_NOTICE
            return True
        return False

    for msg in messages:
        events = msg.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict) or event.get("type") not in _TRUNCATABLE_EVENT_TYPES:
                continue
            truncated = _cap(event, "content")
            tool_metadata = (event.get("metadata") or {}).get("tool_metadata")
            if isinstance(tool_metadata, dict):
                for field in ("content", "answer"):
                    truncated = _cap(tool_metadata, field) or truncated
            if truncated:
                event["_truncated"] = True


@router.get("/{session_id}")
async def get_session(session_id: str):
    store = get_session_store()
    session = await store.get_session_with_messages(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _redact_private_message_metadata(session.get("messages", []))
    _truncate_oversized_events(session.get("messages", []))
    return session


@router.get("/{session_id}/ask-hint")
async def get_session_ask_hint(session_id: str) -> dict[str, Any]:
    """One line the user is likely to type next, for the home composer placeholder."""
    from deeptutor.services.chat_hints import get_ask_hint

    return await get_ask_hint(session_id)


@router.patch("/{session_id}")
async def rename_session(session_id: str, payload: SessionRenameRequest):
    store = get_session_store()
    updated = await store.update_session_title(session_id, payload.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    return {"session": session}


@router.patch("/{session_id}/organization")
async def update_session_organization(session_id: str, payload: SessionOrganizationRequest):
    store = get_session_store()
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    updates: dict[str, Any] = {}
    fields = payload.model_fields_set
    if "course_id" in fields:
        course_id = str(payload.course_id or "").strip()
        if course_id:
            from deeptutor.services.courses import CourseNotFoundError, get_course_service

            try:
                get_course_service().get(course_id)
            except CourseNotFoundError as exc:
                raise HTTPException(status_code=404, detail="Course not found") from exc
        updates["course_id"] = course_id
    if "parent_session_id" in fields:
        parent_id = str(payload.parent_session_id or "").strip()
        if parent_id == session_id:
            raise HTTPException(status_code=400, detail="A session cannot be its own parent")
        if parent_id:
            try:
                await validate_parent_assignment(
                    store,
                    session_id=session_id,
                    parent_session_id=parent_id,
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="Parent session not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        updates["parent_session_id"] = parent_id
    if "session_kind" in fields:
        updates["session_kind"] = payload.session_kind or "chat"
    if "pinned" in fields:
        updates["pinned"] = bool(payload.pinned)
    if "archived" in fields:
        updates["archived"] = bool(payload.archived)

    if updates:
        await store.update_session_preferences(session_id, updates)
        cascade_updates = {key: updates[key] for key in ("course_id", "archived") if key in updates}
        if cascade_updates:
            # Selected-text tutor threads stay with their source conversation.
            candidates = await list_all_sessions_snapshot(store)
            for candidate in candidates:
                prefs = candidate.get("preferences") or {}
                if str(prefs.get("parent_session_id") or "") == session_id:
                    await store.update_session_preferences(candidate["session_id"], cascade_updates)
    refreshed = await store.get_session(session_id)
    return {"session": refreshed}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    store = get_session_store()
    list_active_turns = getattr(store, "list_active_turns", None)
    if callable(list_active_turns):
        from deeptutor.services.session import get_turn_runtime_manager

        runtime = get_turn_runtime_manager()
        for turn in await list_active_turns(session_id):
            await runtime.cancel_turn(turn["id"])
    deleted = await store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        await asyncio.to_thread(LearningStore().detach_session, session_id)
    except Exception:
        logger.exception("failed to detach mastery paths for session %s", session_id)
    try:
        await get_attachment_store().delete_session(session_id)
    except Exception:
        logger.exception("failed to clean up attachments for session %s", session_id)
    return {"deleted": True, "session_id": session_id}


@router.put("/{session_id}/branch-selection")
async def update_branch_selection(session_id: str, payload: BranchSelectionRequest):
    store = get_sqlite_session_store()
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    updated = await store.update_session_preferences(
        session_id, {"selected_branches": dict(payload.selected_branches)}
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"selected_branches": payload.selected_branches}


@router.delete("/{session_id}/messages/{message_id}")
async def delete_turn_by_message(session_id: str, message_id: int):
    store = get_sqlite_session_store()
    result = await store.delete_turn_by_message(session_id, message_id)
    if result["was_running"]:
        raise HTTPException(
            status_code=409, detail="Cannot delete a message while its turn is running"
        )
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="Message not found")
    attachment_store = get_attachment_store()
    for aid in result["attachment_ids"]:
        try:
            await attachment_store.delete_attachment(session_id, aid)
        except Exception:
            logger.exception("failed to delete attachment %s for session %s", aid, session_id)
    return result


@router.post("/{session_id}/quiz-results")
async def record_quiz_results(session_id: str, payload: QuizResultsRequest):
    if not payload.answers:
        raise HTTPException(status_code=400, detail="Quiz results are required")
    store = get_sqlite_session_store()
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    content = _format_quiz_results_message(payload.answers)
    await store.add_message(
        session_id=session_id,
        role="user",
        content=content,
        capability="deep_question",
    )
    notebook_count = 0
    try:
        notebook_count = await store.upsert_notebook_entries(
            session_id,
            [{**item.model_dump(), "turn_id": payload.turn_id} for item in payload.answers],
        )
    except Exception:
        logger.warning(
            "Failed to upsert notebook entries for session %s", session_id, exc_info=True
        )
    return {
        "recorded": True,
        "session_id": session_id,
        "answer_count": len(payload.answers),
        "notebook_count": notebook_count,
        "content": content,
    }
