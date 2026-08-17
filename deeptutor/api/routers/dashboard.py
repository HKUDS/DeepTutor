"""Dashboard API — what the home screen shows before a conversation starts.

Recent activity comes from the unified SQLite session store; the starter lines
come from :mod:`deeptutor.services.suggestions`, which reads memory.

Route order matters here: ``/{entry_id}`` at the bottom of this module matches
any single segment, so every literal path must be declared above it or it will
never be reached.
"""

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


@router.get("/suggestions")
async def get_starter_suggestions():
    """The three starting points for the home composer.

    Returns immediately, even when the set is stale — regeneration happens
    behind the response. An empty ``suggestions`` list means there is nothing
    in memory to ground a suggestion in, and the client renders nothing.

    No language parameter: the output language is the learner's own
    model-output setting, resolved server-side. See
    :mod:`deeptutor.services.suggestions`.
    """
    from deeptutor.services.suggestions import get_suggestions

    return await get_suggestions()


@router.post("/suggestions/refresh")
async def refresh_starter_suggestions():
    """Generate a new set now. Backs the reroll control.

    Synchronous, unlike the read: a human clicked and is waiting for a
    different set.
    """
    from deeptutor.services.suggestions import refresh_suggestions

    result = await refresh_suggestions()
    return {**result.to_dict(), "stale": False}


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
