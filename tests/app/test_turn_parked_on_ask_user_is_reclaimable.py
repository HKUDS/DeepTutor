"""A turn stopped while parked on ``ask_user`` must not block its session.

Two halves of the same report (#1297, #1359):

* The terminal write on cancellation CAS'd on ``expected_status="running"``
  only. A turn parked on ``ask_user`` sits at ``waiting_input``, and the
  waiter's restore to ``running`` is fired through ``asyncio.shield`` — so it
  races that write. When it lost, nothing terminal was written and the row
  stayed ``waiting_input`` forever.
* ``_begin_turn_sync`` counts ``waiting_input`` as active, so that row made
  every later message in the session raise "Session already has an active
  turn" — the chat window looked dead until the row was edited by hand.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


async def _park_a_turn(store: SQLiteSessionStore) -> tuple[str, str]:
    session = await store.create_session("Parked")
    session_id = session["id"]
    turn = await store.begin_turn(session_id, capability="chat")
    turn_id = turn["id"]
    assert await store.transition_turn(turn_id, "waiting_input", expected_status="running")
    return session_id, turn_id


@pytest.mark.asyncio
async def test_terminal_write_settles_a_turn_parked_on_ask_user(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session_id, turn_id = await _park_a_turn(store)
    manager = TurnRuntimeManager(store)

    settled = await manager._transition_execution(
        SimpleNamespace(turn_id=turn_id, lease=None), "cancelled", "Turn cancelled"
    )

    assert settled is True, "a waiting_input row must be a valid predecessor of a terminal state"
    row = await store.get_turn(turn_id)
    assert row is not None and row["status"] == "cancelled"

    # The session is usable again: this is the assertion the report was about.
    following = await store.begin_turn(session_id, capability="chat")
    assert following["id"] != turn_id


@pytest.mark.asyncio
async def test_a_running_turn_still_settles(tmp_path) -> None:
    """The pre-existing predecessor keeps working, and is still tried first."""
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session = await store.create_session("Running")
    turn = await store.begin_turn(session["id"], capability="chat")
    manager = TurnRuntimeManager(store)

    settled = await manager._transition_execution(
        SimpleNamespace(turn_id=turn["id"], lease=None), "failed", "boom"
    )

    assert settled is True
    row = await store.get_turn(turn["id"])
    assert row is not None and row["status"] == "failed"


@pytest.mark.asyncio
async def test_an_already_terminal_turn_is_left_alone(tmp_path) -> None:
    """Neither predecessor matches a finished row, so a late write is a no-op
    rather than a resurrection."""
    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session = await store.create_session("Done")
    turn = await store.begin_turn(session["id"], capability="chat")
    assert await store.transition_turn(turn["id"], "completed", expected_status="running")
    manager = TurnRuntimeManager(store)

    settled = await manager._transition_execution(
        SimpleNamespace(turn_id=turn["id"], lease=None), "cancelled", "Turn cancelled"
    )

    assert settled is False
    row = await store.get_turn(turn["id"])
    assert row is not None and row["status"] == "completed"


@pytest.mark.asyncio
async def test_cancelling_an_unowned_parked_turn_frees_the_session(tmp_path) -> None:
    """Stop on a card whose worker is gone: no lease means a queued cancel
    would never be read, so the row has to be settled here."""
    from deeptutor.app.service import TurnApplicationService
    from deeptutor.runtime.coordination import MemoryCoordinator

    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session_id, turn_id = await _park_a_turn(store)
    runtime = TurnRuntimeManager(store)
    application = TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: runtime),
        MemoryCoordinator(lease_ttl_seconds=5),
    )

    assert await application.cancel_turn(turn_id) is True

    row = await store.get_turn(turn_id)
    assert row is not None
    assert row["status"] == "failed"
    assert row["failure_code"] == "worker_lost"
    following = await store.begin_turn(session_id, capability="chat")
    assert following["id"] != turn_id


@pytest.mark.asyncio
async def test_an_unowned_queued_turn_is_reclaimed_too(tmp_path) -> None:
    """``queued`` and ``running`` orphans block a session exactly as a parked
    one does, which is why the reaper is not named after one status."""
    from deeptutor.app.service import TurnApplicationService
    from deeptutor.runtime.coordination import MemoryCoordinator

    store = SQLiteSessionStore(tmp_path / "s.sqlite3")
    session = await store.create_session("Orphan")
    session_id = session["id"]
    turn = await store.begin_turn(session_id, capability="chat")
    application = TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: TurnRuntimeManager(store)),
        MemoryCoordinator(lease_ttl_seconds=5),
    )

    assert await application.cancel_turn(turn["id"]) is True

    row = await store.get_turn(turn["id"])
    assert row is not None and row["status"] == "failed"
    following = await store.begin_turn(session_id, capability="chat")
    assert following["id"] != turn["id"]
