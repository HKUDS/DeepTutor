"""A ``waiting_input`` turn whose waiter is gone must not block the session.

#1297: the row says ``waiting_input`` after the worker that owned the turn
died; every card submission hits a missing in-memory queue, the session can
never start another turn, and the background recovery pass only sweeps it
asynchronously. The synchronous reap at submission time must fire for the
zombie shape — persisted ``waiting_input`` with no live lease — and only for
it: a turn owned elsewhere (live lease) and a finished turn's history are
untouched. The terminal write mirrors :class:`TurnRecoveryService` (CAS with
fencing token, ``worker_lost`` failure code, error+done events) so the
client's subscription terminates deterministically.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.app.service import TurnApplicationService
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


class _ContextBuilder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **_kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


def _application(store, runtime, coordinator) -> TurnApplicationService:
    return TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: runtime),
        coordinator,
    )


def _payload() -> dict:
    return {
        "content": "hello",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }


async def _seed_waiting_turn(store: SQLiteSessionStore) -> dict:
    """Persist the exact state #1297 observed: a turn stuck on waiting_input
    with no live worker behind it (a dead process leaves precisely this)."""
    session = await store.create_session(title="Stuck")
    turn = await store.begin_turn(session["id"], "chat", turn_id="zombie-turn")
    await store.update_turn_status(turn["id"], "waiting_input")
    return turn


@pytest.fixture(autouse=True)
def _workspace_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the workspace binding at a real folder for this test process.

    Turn execution builds a workspace runtime context; without this the
    binding resolves to the developer's own (absent) workspace folder and
    every turn fails before reaching the ask_user pause.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_ROOT", str(root))
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)


@pytest.fixture
def llm_and_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", _ContextBuilder
    )


@pytest.mark.asyncio
async def test_zombie_waiting_turn_is_reaped_on_submission(tmp_path, llm_and_context) -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=5)
    store = SQLiteSessionStore(tmp_path / "shared.sqlite3")
    runtime = TurnRuntimeManager(store, coordinator=coordinator, owner_id="worker-a")
    app = _application(store, runtime, coordinator)
    turn = await _seed_waiting_turn(store)

    accepted = await app.submit_user_reply(turn["id"], text="my answer")
    assert accepted is False

    row = await store.get_turn(turn["id"])
    assert row["status"] == "failed"
    assert "worker" in (row.get("error") or "")
    assert row.get("failure_code") == "worker_lost"
    assert row.get("retryable") in (True, 1)

    # The subscriber-facing stream carries the terminal pair so any client
    # watching the zombie turn stops immediately.
    events = await store.get_turn_events(turn["id"])
    types = [event["type"] for event in events]
    assert "error" in types
    assert types[-1] == "done"

    # The session accepts new turns again — the zombie no longer blocks it.
    _session, fresh = await app.start_turn(_payload())
    assert fresh["status"] in ("queued", "running")


@pytest.mark.asyncio
async def test_live_lease_blocks_the_reap(tmp_path, llm_and_context) -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    store = SQLiteSessionStore(tmp_path / "shared.sqlite3")
    runtime = TurnRuntimeManager(store, coordinator=coordinator, owner_id="worker-a")
    app = _application(store, runtime, coordinator)
    turn = await _seed_waiting_turn(store)

    # Another worker owns the turn right now (renewing, mid-handoff): the
    # application service accepts the reply and routes it to the owner via
    # the coordinator — only an unowned zombie hits the reap.
    await coordinator.acquire_turn(turn["id"], turn["session_id"], owner_id="worker-b")
    accepted = await app.submit_user_reply(turn["id"], text="my answer")
    assert accepted is True

    row = await store.get_turn(turn["id"])
    assert row["status"] == "waiting_input"


@pytest.mark.asyncio
async def test_terminal_turns_are_never_touched(tmp_path, llm_and_context) -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=5)
    store = SQLiteSessionStore(tmp_path / "shared.sqlite3")
    runtime = TurnRuntimeManager(store, coordinator=coordinator, owner_id="worker-a")
    app = _application(store, runtime, coordinator)

    session = await store.create_session(title="done")
    turn = await store.begin_turn(session["id"], "chat", turn_id="finished-turn")
    await store.update_turn_status(turn["id"], "completed")

    assert await app.submit_user_reply(turn["id"], text="late") is False
    row = await store.get_turn(turn["id"])
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_live_owner_still_receives_replies(tmp_path, llm_and_context) -> None:
    """The reap never interferes with the healthy multiworker path: a reply
    routed to the worker that owns the waiter is delivered and the turn
    completes."""
    waiting = asyncio.Event()

    class Engine:
        async def execute(self, context):
            yield StreamEvent(
                type=StreamEventType.WAIT_FOR_INPUT,
                source="chat",
                content="Continue?",
            )
            waiting.set()
            reply = await context.runtime.wait_for_user_reply()
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                content=f"reply:{reply['text']}",
            )

    coordinator = MemoryCoordinator(lease_ttl_seconds=5)
    path = tmp_path / "shared.sqlite3"
    store_a = SQLiteSessionStore(path)
    store_b = SQLiteSessionStore(path)
    runtime_a = TurnRuntimeManager(
        store_a, coordinator=coordinator, owner_id="worker-a", turn_engine=Engine()
    )
    runtime_b = TurnRuntimeManager(
        store_b, coordinator=coordinator, owner_id="worker-b", turn_engine=Engine()
    )
    app_a = _application(store_a, runtime_a, coordinator)
    app_b = _application(store_b, runtime_b, coordinator)

    _session, turn = await app_a.start_turn(_payload())
    await asyncio.wait_for(waiting.wait(), timeout=2)

    delivered = await app_b.submit_user_reply(turn["id"], text="ping")
    assert delivered is True

    # The owner consumes the routed command, the pipeline resumes, and the
    # turn leaves waiting_input on its own — reap never interfered.
    row = await store_b.get_turn(turn["id"])
    for _ in range(100):
        row = await store_b.get_turn(turn["id"])
        if row["status"] != "waiting_input":
            break
        await asyncio.sleep(0.05)
    assert row["status"] in ("running", "completed")
