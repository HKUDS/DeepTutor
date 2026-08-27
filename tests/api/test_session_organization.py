from __future__ import annotations

from typing import Any

import pytest

from deeptutor.api.routers import courses as courses_router
from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.courses import CourseNotFoundError, CourseService
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
async def test_course_delete_unclassifies_every_session_before_removing_course(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    service = CourseService(tmp_path / "courses")
    course = service.create(name="Operating Systems")
    store = _ReorderingStore(
        [
            {
                "session_id": f"session-{index}",
                "updated_at": 300 - index,
                "preferences": {"course_id": course.id},
            }
            for index in range(250)
        ]
    )
    monkeypatch.setattr(courses_router, "get_course_service", lambda: service)
    monkeypatch.setattr(courses_router, "get_session_store", lambda: store)

    await courses_router.delete_course(course.id)

    assert all(not row["preferences"].get("course_id") for row in store.rows.values())
    with pytest.raises(CourseNotFoundError):
        service.get(course.id)
