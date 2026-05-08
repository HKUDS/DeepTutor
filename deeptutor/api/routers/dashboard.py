"""Dashboard API backed by the unified SQLite session store."""

from typing import Any

from fastapi import APIRouter, HTTPException

from deeptutor.services.session import get_session_store

router = APIRouter()


@router.get("/recent")
async def get_recent_activities(limit: int = 50, type: str | None = None):
    store = get_session_store()
    sessions = await store.list_sessions(limit=limit, offset=0)
    activities: list[dict[str, Any]] = []

    for session in sessions:
        capability = str(session.get("capability") or "chat")
        activity_type = capability.replace("deep_", "")
        if type is not None and activity_type != type:
            continue
        activities.append(
            {
                "id": session.get("session_id"),
                "type": activity_type,
                "capability": capability,
                "title": session.get("title", "Untitled"),
                "timestamp": session.get("updated_at", session.get("created_at", 0)),
                "summary": (session.get("last_message") or "")[:160],
                "session_ref": f"sessions/{session.get('session_id')}",
                "message_count": session.get("message_count", 0),
                "status": session.get("status", "idle"),
                "active_turn_id": session.get("active_turn_id"),
            }
        )

    return activities[:limit]


@router.get("/{entry_id}")
async def get_activity_entry(entry_id: str):
    store = get_session_store()
    session = await store.get_session_with_messages(entry_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    capability = str(session.get("capability") or "chat")
    return {
        "id": session.get("session_id"),
        "type": capability.replace("deep_", ""),
        "capability": capability,
        "title": session.get("title"),
        "timestamp": session.get("updated_at", session.get("created_at")),
        "content": {
            "messages": session.get("messages", []),
            "active_turns": session.get("active_turns", []),
            "status": session.get("status", "idle"),
            "summary": session.get("compressed_summary", ""),
        },
    }
