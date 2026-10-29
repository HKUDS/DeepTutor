"""Dashboard API — what the home screen shows before a conversation starts.

Recent activity comes from the unified SQLite session store; the starter lines
come from :mod:`deeptutor.services.suggestions`, which reads memory.

Route order matters here: ``/{entry_id}`` at the bottom of this module matches
any single segment, so every literal path must be declared above it or it will
never be reached.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from deeptutor.services.session import get_session_store

logger = logging.getLogger(__name__)
router = APIRouter()


async def _workspace_rows(reader) -> list[dict[str, Any]]:
    """Read one index in the request's workspace, naming it on every row.

    Switching workspace is switching stores: these indexes never merge another
    workspace's content. The name stays on the row so follow-up requests and
    links remain pinned to the store the row came from.
    """
    from deeptutor.services.workspace import get_content_workspace_service
    from deeptutor.services.workspace.context import current_workspace_id

    workspace_id = current_workspace_id()
    names = {
        row["workspace_id"]: row["display_name"]
        for row in get_content_workspace_service().list_workspaces()
    }
    return [
        {
            **row,
            "content_workspace_id": workspace_id,
            "content_workspace_name": names.get(workspace_id, ""),
        }
        for row in await reader()
    ]


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


@router.get("/learning-index")
async def get_learning_index():
    """Read-only entry points into the request's workspace."""
    from deeptutor.modules.catalog import module_enabled
    from deeptutor.multi_user.learning_access import learning_surface_allowed

    async def books():
        from deeptutor.api.routers.book import list_books

        return (await list_books())["books"]

    async def mastery():
        from deeptutor.api.routers.mastery_path import list_topics

        return (await list_topics())["topics"]

    async def reading():
        from deeptutor.api.routers.reading import list_workspaces

        return (await list_workspaces(search=""))["workspaces"]

    async def watching():
        from deeptutor.services.session.organization import list_all_sessions_snapshot

        rows = await list_all_sessions_snapshot(get_session_store())
        return [
            row
            for row in rows
            if not (row.get("preferences") or {}).get("archived")
            and (
                (row.get("preferences") or {}).get("workspace_mode") == "immersive_watching"
                or (row.get("preferences") or {}).get("capability") == "immersive_watching"
            )
        ]

    async def practice():
        from deeptutor.services.session import get_sqlite_session_store

        return await get_sqlite_session_store().list_notebook_navigation()

    result = {}
    failed = []
    for kind, surface, reader in (
        ("books", "books", books),
        ("mastery", "chat", mastery),
        ("reading", "reading", reading),
        ("watching", "reading", watching),
        ("practice", "chat", practice),
    ):
        # Calling a route function directly bypasses its HTTP dependencies.
        # Never load a source that the learner could not open individually.
        result[kind] = []
        owner = {"watching": "reading", "practice": "notebook"}.get(kind, kind)
        if not module_enabled(owner) or not learning_surface_allowed(surface):
            continue
        try:
            result[kind] = await _workspace_rows(reader)
        except Exception:
            logger.warning("Workspace learning index unavailable: %s", kind, exc_info=True)
            failed.append(kind)
    return {"sources": result, "failed": failed}


@router.get("/source-library/{kind}")
async def get_source_library(kind: str):
    """Source indexes of the request's workspace, for the topic and book pickers."""

    async def read():
        if kind == "notebooks":
            from deeptutor.services.notebook import notebook_manager

            return notebook_manager.list_notebooks()
        if kind == "chats":
            from deeptutor.services.session.organization import list_all_sessions_snapshot

            return await list_all_sessions_snapshot(get_session_store())
        if kind == "drafts":
            from deeptutor.api.routers.co_writer import list_documents

            return [row.model_dump() for row in (await list_documents())["documents"]]
        raise HTTPException(404, "Unknown source library")

    if kind == "knowledge":
        # The workspace's own knowledge bases plus the ones assigned to it.
        from deeptutor.multi_user.knowledge_access import list_visible_knowledge_bases
        from deeptutor.services.workspace.context import current_workspace_id
        from deeptutor.services.workspace.knowledge import parse_kb_id

        items = []
        for row in list_visible_knowledge_bases():
            # Own bases carry a local id; assigned ones name their home store.
            parsed = parse_kb_id(str(row.get("id") or ""))
            origin = parsed[0] if parsed is not None else current_workspace_id()
            items.append(
                {
                    **row,
                    "content_workspace_id": origin,
                    "content_workspace_name": row.get("provenance_label", ""),
                }
            )
        return {"items": items, "unavailable_workspaces": []}
    if kind in {"books", "practice"}:
        return await get_learning_library(kind)
    if kind not in {"notebooks", "chats", "drafts"}:
        raise HTTPException(404, "Unknown source library")
    return {"items": await _workspace_rows(read), "unavailable_workspaces": []}


@router.get("/learning-library/{kind}")
async def get_learning_library(kind: str):
    """The request's workspace library of one kind."""
    can_create = True

    async def read():
        nonlocal can_create
        if kind == "books":
            from deeptutor.api.routers.book import list_books

            result = await list_books()
            can_create = result["can_create"]
            return result["books"]
        if kind == "mastery":
            from deeptutor.api.routers.mastery_path import list_topics

            return (await list_topics())["topics"]
        if kind == "reading":
            from deeptutor.api.routers.reading import list_workspaces

            return (await list_workspaces(search=""))["workspaces"]
        if kind == "materials":
            from deeptutor.api.routers.reading import list_library_materials

            return (await list_library_materials(search="", status=None, library_filter="all"))[
                "materials"
            ]
        if kind == "practice":
            from deeptutor.services.session import get_sqlite_session_store

            store = get_sqlite_session_store()
            items = []
            offset = 0
            while True:
                result = await store.list_notebook_entries(limit=200, offset=offset)
                items.extend(result["items"])
                offset += len(result["items"])
                if not result["items"] or offset >= result["total"]:
                    return items
        from deeptutor.services.session.organization import list_all_sessions_snapshot

        rows = await list_all_sessions_snapshot(get_session_store())
        return [
            row
            for row in rows
            if not (row.get("preferences") or {}).get("archived")
            and (
                (row.get("preferences") or {}).get("workspace_mode") == "immersive_watching"
                or (row.get("preferences") or {}).get("capability") == "immersive_watching"
            )
        ]

    if kind not in {"books", "mastery", "reading", "materials", "practice", "watching"}:
        raise HTTPException(status_code=404, detail="Unknown learning library")
    rows = await _workspace_rows(read)
    return {"items": rows, "unavailable_workspaces": [], "can_create": can_create}


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
