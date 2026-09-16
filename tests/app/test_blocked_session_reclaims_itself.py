"""A session blocked by a dead turn must unblock itself on the next message.

``_begin_turn_sync`` refuses a new turn while the session owns any row in
``queued``/``running``/``waiting_input``. Correct while a turn is alive, and
catastrophic once one is not: a row left behind by a lost worker or a restart
made every later message raise "Session already has an active turn", with no
way out from the UI. Reporters described exactly that — one window, no
refresh, a conversation that never accepted another word (#1297, #1359).

Reclaiming at the point of conflict, rather than on a timer, is what makes it
safe. The only rows ever considered are ones already blocking a real request,
so a turn that was just inserted cannot be swept before its first lease
renewal — the hazard that kept a periodic sweep out of v1.6.7.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.app.service import TurnApplicationService
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.protocol import ActiveTurnConflict
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


class _Runtime:
    """Enough runtime to make the store's real active-turn conflict happen."""

    def __init__(self, store: SQLiteSessionStore) -> None:
        self._store = store
        self.attempts = 0

    async def start_turn(self, payload: dict[str, Any]) -> tuple[dict, dict]:
        self.attempts += 1
        session_id = str(payload["session_id"])
        turn = await self._store.begin_turn(session_id, capability="chat")
        session = await self._store.get_session(session_id)
        return session or {"id": session_id}, turn


def _payload(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "content": "hello",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }


async def _blocked_session(store: SQLiteSessionStore, status: str) -> tuple[str, str]:
    session = await store.create_session("Blocked")
    session_id = session["id"]
    turn = await store.begin_turn(session_id, capability="chat")
    if status != "running":
        assert await store.transition_turn(turn["id"], status, expected_status="running")
    return session_id, turn["id"]


def _application(
    store: SQLiteSessionStore, runtime: _Runtime, coordinator
) -> TurnApplicationService:
    return TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: runtime),
        coordinator,
    )


@pytest.mark.parametrize("status", ["waiting_input", "running", "queued"])
@pytest.mark.asyncio
async def test_a_message_clears_a_turn_nothing_is_executing(tmp_path, status: str) -> None:
    """Every status ``_begin_turn_sync`` calls active blocks the session equally."""
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session_id, blocking_id = await _blocked_session(store, status)
    runtime = _Runtime(store)
    application = _application(store, runtime, MemoryCoordinator(lease_ttl_seconds=5))

    _session, turn = await application.start_turn(_payload(session_id))

    assert turn["id"] != blocking_id, "the new message must get its own turn"
    blocking = await store.get_turn(blocking_id)
    assert blocking is not None
    assert blocking["status"] == "failed"
    assert blocking["failure_code"] == "worker_lost"
    assert runtime.attempts == 2, "one conflict, one reclamation, one retry — no loop"


@pytest.mark.asyncio
async def test_a_turn_something_is_still_executing_is_left_alone(tmp_path) -> None:
    """The conflict is real while a worker holds the lease, and must surface.

    This is the assertion that keeps the fix from becoming a way to start two
    turns on one session: liveness is the lease, and a live lease wins.
    """
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session_id, blocking_id = await _blocked_session(store, "waiting_input")
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    assert await coordinator.acquire_turn(blocking_id, session_id, "worker-1") is not None
    runtime = _Runtime(store)
    application = _application(store, runtime, coordinator)

    with pytest.raises(ActiveTurnConflict):
        await application.start_turn(_payload(session_id))

    blocking = await store.get_turn(blocking_id)
    assert blocking is not None
    assert blocking["status"] == "waiting_input", "a live turn must not be reaped"
    assert runtime.attempts == 1, "no retry when nothing was reclaimed"


@pytest.mark.asyncio
async def test_a_parked_turn_whose_lease_expired_is_reclaimed(tmp_path) -> None:
    """A worker that stopped renewing is gone, however recently it ran.

    Age of the row cannot decide this: a turn parked on an ``ask_user`` card
    emits no events, so its ``updated_at`` stops advancing while a person is
    simply taking their time to answer.
    """
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session_id, blocking_id = await _blocked_session(store, "waiting_input")
    coordinator = MemoryCoordinator(lease_ttl_seconds=-1)  # already expired
    assert await coordinator.acquire_turn(blocking_id, session_id, "worker-1") is not None
    runtime = _Runtime(store)
    application = _application(store, runtime, coordinator)

    _session, turn = await application.start_turn(_payload(session_id))

    assert turn["id"] != blocking_id
    blocking = await store.get_turn(blocking_id)
    assert blocking is not None and blocking["status"] == "failed"


@pytest.mark.asyncio
async def test_a_session_with_no_blocking_row_is_untouched(tmp_path) -> None:
    """The happy path must not pay for any of this."""
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session = await store.create_session("Fresh")
    runtime = _Runtime(store)
    application = _application(store, runtime, MemoryCoordinator(lease_ttl_seconds=5))

    _session, turn = await application.start_turn(_payload(session["id"]))

    assert turn["status"] == "running"
    assert runtime.attempts == 1
