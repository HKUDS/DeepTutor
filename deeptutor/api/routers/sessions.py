"""
Unified session history API.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from deeptutor.services.session import get_session_store, get_sqlite_session_store
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


@router.get("/{session_id}")
async def get_session(session_id: str):
    store = get_session_store()
    session = await store.get_session_with_messages(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Truncate oversized event payloads (e.g. full KB documents returned by RAG
    # tools) so that the frontend TraceSurface can load large sessions without
    # running out of memory.  This only affects the UI rendering path — the LLM
    # context builder reads from a separate content-only store and is unaffected.
    MAX_EVENT_PAYLOAD = 1024 * 1024
    for msg in session.get("messages", []):
        events_raw = msg.get("events_json") or msg.get("events")
        if not events_raw or not isinstance(events_raw, (str, list)):
            continue
        try:
            events = json.loads(events_raw) if isinstance(events_raw, str) else events_raw
            truncated = False
            for event in events:
                if event.get("type") in ("tool_result", "observation"):
                    # Truncate top-level content
                    if isinstance(event.get("content"), str) and len(event["content"]) > MAX_EVENT_PAYLOAD:
                        event["content"] = event["content"][:MAX_EVENT_PAYLOAD] + "\n\n[... content truncated]"
                        event["_truncated"] = True
                        truncated = True
                    # Truncate nested tool_metadata fields
                    tm = event.get("metadata", {}).get("tool_metadata", {})
                    if isinstance(tm, dict):
                        for field in ("content", "answer"):
                            val = tm.get(field)
                            if isinstance(val, str) and len(val) > MAX_EVENT_PAYLOAD:
                                tm[field] = val[:MAX_EVENT_PAYLOAD] + "\n\n[... content truncated]"
                                event["_truncated"] = True
                                truncated = True
            if truncated:
                msg["events"] = events
                msg.pop("events_json", None)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    # Deduplicate redundant events_json strings (the events dict already
    # carries the same data after the transformations above).
    for msg in session.get("messages", []):
        msg.pop("events_json", None)

    return session


@router.patch("/{session_id}")
async def rename_session(session_id: str, payload: SessionRenameRequest):
    store = get_session_store()
    updated = await store.update_session_title(session_id, payload.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await store.get_session(session_id)
    return {"session": session}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    store = get_session_store()
    deleted = await store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
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
