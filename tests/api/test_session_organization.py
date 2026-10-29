from __future__ import annotations

from typing import Any

import pytest

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.session.organization import validate_parent_assignment


class _ReorderingStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {row["session_id"]: row for row in rows}
        self.clock = max((float(row.get("updated_at") or 0) for row in rows), default=0)

    async def get_session(self, session_id: str):
        return self.rows.get(session_id)

    async def list_sessions(self, *, limit: int, offset: int):
        ordered = sorted(self.rows.values(), key=lambda row: -float(row["updated_at"]))
        return ordered[offset : offset + limit]

    async def update_session_preferences(self, session_id: str, updates: dict[str, Any]):
        row = self.rows[session_id]
        row.setdefault("preferences", {}).update(updates)
        self.clock += 1
        row["updated_at"] = self.clock
        return True


@pytest.mark.asyncio
async def test_cascade_uses_snapshot_when_updates_reorder_session_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"session_id": "root", "updated_at": 500, "preferences": {}},
        *[
            {
                "session_id": f"child-{index}",
                "updated_at": 499 - index,
                "preferences": {"parent_session_id": "root"},
            }
            for index in range(250)
        ],
    ]
    store = _ReorderingStore(rows)
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    await sessions_router.update_session_organization(
        "root",
        sessions_router.SessionOrganizationRequest(archived=True),
    )

    children = [row for key, row in store.rows.items() if key.startswith("child-")]
    assert len(children) == 250
    assert all(row["preferences"].get("archived") is True for row in children)


@pytest.mark.asyncio
async def test_parent_assignment_rejects_indirect_cycle() -> None:
    store = _ReorderingStore(
        [
            {
                "session_id": "a",
                "updated_at": 3,
                "preferences": {"parent_session_id": "b"},
            },
            {
                "session_id": "b",
                "updated_at": 2,
                "preferences": {"parent_session_id": "c"},
            },
            {"session_id": "c", "updated_at": 1, "preferences": {}},
        ]
    )

    with pytest.raises(ValueError, match="parent cycle"):
        await validate_parent_assignment(
            store,
            session_id="c",
            parent_session_id="a",
        )


@pytest.mark.asyncio
async def test_threads_lists_only_this_conversations_tutor_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReorderingStore(
        [
            {"session_id": "root", "updated_at": 10, "preferences": {}},
            {
                "session_id": "older-thread",
                "updated_at": 4,
                "preferences": {"parent_session_id": "root", "session_kind": "selection_tutor"},
            },
            {
                "session_id": "newer-thread",
                "updated_at": 8,
                "preferences": {"parent_session_id": "root", "session_kind": "selection_tutor"},
            },
            {
                "session_id": "other-parent",
                "updated_at": 9,
                "preferences": {
                    "parent_session_id": "elsewhere",
                    "session_kind": "selection_tutor",
                },
            },
            {
                "session_id": "filed-child",
                "updated_at": 7,
                "preferences": {"parent_session_id": "root", "session_kind": "chat"},
            },
        ]
    )
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    result = await sessions_router.list_session_threads("root")

    assert [row["session_id"] for row in result["threads"]] == ["newer-thread", "older-thread"]


@pytest.mark.asyncio
async def test_organization_read_skips_the_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _ReorderingStore(
        [{"session_id": "root", "updated_at": 1, "preferences": {"pinned": True}}]
    )
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    result = await sessions_router.get_session_organization("root")

    assert result["session"]["preferences"] == {"pinned": True}
    with pytest.raises(sessions_router.HTTPException):
        await sessions_router.get_session_organization("missing")
