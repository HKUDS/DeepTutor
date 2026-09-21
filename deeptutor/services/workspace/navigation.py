"""Account navigation across content stores, without changing their isolation.

Only index readers opt in. Content reads and mutations still resolve exactly
one workspace from the request. Every row names its authoritative source,
including legacy records whose preferences contain no workspace id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from deeptutor.services.workspace import get_content_workspace_service
from deeptutor.services.workspace.context import workspace_context

logger = logging.getLogger(__name__)


async def read_workspace_indexes(
    reader: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    catalog = get_content_workspace_service().list_workspaces()
    names = {row["workspace_id"]: row["display_name"] for row in catalog}
    ids = [""] + [row["workspace_id"] for row in catalog if row["kind"] == "workspace"]
    rows: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for workspace_id in dict.fromkeys(ids):
        try:
            with workspace_context(workspace_id):
                rows.extend(
                    {
                        **row,
                        "content_workspace_id": workspace_id,
                        "content_workspace_name": names.get(workspace_id, ""),
                    }
                    for row in await reader()
                )
        except Exception:
            # One offline folder must not hide the rest of the account history.
            logger.warning(
                "Workspace navigation index unavailable: %s", workspace_id, exc_info=True
            )
            unavailable.append(workspace_id)
    return rows, unavailable


async def session_index(limit: int, offset: int, query: str | None = None) -> dict[str, Any]:
    from deeptutor.services.session import get_session_store

    total = 0

    async def read():
        nonlocal total
        store = get_session_store()
        rows = []
        # Read only the prefix needed for the globally sorted page. Store APIs
        # have their own page caps; never pass an unbounded offset+limit to them.
        for start in range(0, offset + limit, 100):
            size = min(100, offset + limit - start)
            if query is None:
                page = await store.list_sessions(limit=size, offset=start)
            else:
                result = await store.search_sessions(query, limit=size, offset=start)
                if start == 0:
                    total += result["total"]
                page = result["sessions"]
            rows.extend(page)
            if len(page) < size:
                break
        return rows

    rows, unavailable = await read_workspace_indexes(read)
    rows.sort(key=lambda row: (-row["updated_at"], row["content_workspace_id"], row["session_id"]))
    return {
        "sessions": rows[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
        "unavailable_workspaces": unavailable,
    }
