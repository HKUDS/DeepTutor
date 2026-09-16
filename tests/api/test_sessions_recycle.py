from __future__ import annotations

from typing import Any

import pytest


class _RecycleBinStore:
    """Minimal in-memory stand-in covering the recycle-bin lifecycle."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}

    def seed(self, session_id: str) -> None:
        self.sessions[session_id] = {
            "session_id": session_id,
            "title": f"Session {session_id}",
            "deleted_at": None,
        }

    async def delete_session(self, session_id: str) -> bool:
        row = self.sessions.get(session_id)
        if row is None or row.get("deleted_at") is not None:
            return False
        row["deleted_at"] = 1.0
        return True

    async def restore_session(self, session_id: str) -> bool:
        row = self.sessions.get(session_id)
        if row is None or row.get("deleted_at") is None:
            return False
        row["deleted_at"] = None
        return True

    async def purge_session(self, session_id: str) -> bool:
        row = self.sessions.get(session_id)
        if row is None or row.get("deleted_at") is None:
            return False
        del self.sessions[session_id]
        return True

    async def list_deleted_sessions(self, *, limit: int, offset: int):
        deleted = [s for s in self.sessions.values() if s.get("deleted_at") is not None]
        return deleted[offset : offset + limit]

    async def get_session(self, session_id: str):
        return self.sessions.get(session_id)


def _make_store() -> _RecycleBinStore:
    store = _RecycleBinStore()
    store.seed("s-active")
    store.seed("s-doomed")
    return store


@pytest.mark.asyncio
async def test_delete_marks_recycled():
    store = _make_store()
    assert await store.delete_session("s-doomed")
    assert store.sessions["s-doomed"]["deleted_at"] is not None
    assert store.sessions["s-active"]["deleted_at"] is None


@pytest.mark.asyncio
async def test_restore_clears_deleted_at():
    store = _make_store()
    await store.delete_session("s-doomed")
    assert await store.restore_session("s-doomed")
    assert store.sessions["s-doomed"]["deleted_at"] is None


@pytest.mark.asyncio
async def test_restore_fails_when_not_deleted():
    store = _make_store()
    assert not await store.restore_session("s-active")


@pytest.mark.asyncio
async def test_purge_removes_only_deleted():
    store = _make_store()
    await store.delete_session("s-doomed")
    assert await store.purge_session("s-doomed")
    assert "s-doomed" not in store.sessions
    assert not await store.purge_session("s-active")


@pytest.mark.asyncio
async def test_list_deleted_excludes_active():
    store = _make_store()
    await store.delete_session("s-doomed")
    deleted = await store.list_deleted_sessions(limit=50, offset=0)
    assert len(deleted) == 1
    assert deleted[0]["session_id"] == "s-doomed"


@pytest.mark.asyncio
async def test_delete_fails_when_already_deleted():
    store = _make_store()
    await store.delete_session("s-doomed")
    assert not await store.delete_session("s-doomed")
