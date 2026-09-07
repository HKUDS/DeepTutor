"""Post-stream turn-event flush: batching and PocketBase upload.

The turn runtime buffers every live event in memory and persists the whole
batch, including DONE and any post-turn ``session_meta`` title update, once
the turn has fully finished. Everything on that path must stay O(1) round
trips with respect to the event count.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import re

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager, _TurnExecution

pytestmark = pytest.mark.asyncio

_CLAUSE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


# ---------------------------------------------------------------------------
# Fake PocketBase SDK (same shape as test_pocketbase_isolation.py)
# ---------------------------------------------------------------------------


class _Record:
    def __init__(self, pb_id: str, data: dict) -> None:
        self.id = pb_id
        for key, value in data.items():
            setattr(self, key, value)


class _Collection:
    def __init__(self) -> None:
        self._rows: list[_Record] = []
        self._seq = 0

    def _matches(self, record: _Record, query_params: dict | None) -> bool:
        flt = (query_params or {}).get("filter") or ""
        for field, expected in _CLAUSE.findall(flt):
            if str(getattr(record, field, "")) != expected:
                return False
        return True

    def create(self, data: dict) -> _Record:
        self._seq += 1
        record = _Record(f"pb{self._seq:04d}", data)
        self._rows.append(record)
        return record

    def get_full_list(self, query_params: dict | None = None) -> list[_Record]:
        return [r for r in self._rows if self._matches(r, query_params)]

    def update(self, pb_id: str, data: dict) -> _Record:
        record = next(r for r in self._rows if r.id == pb_id)
        for key, value in data.items():
            setattr(record, key, value)
        return record


class _FakeClient:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def collection(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


@pytest.fixture
def fake_pb(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client", lambda: client, raising=True
    )
    return client


@contextmanager
def as_user(uid: str):
    scope = UserScope(kind="user", user_id=uid, root=Path("/tmp") / uid)  # noqa: S108
    token = set_current_user(CurrentUser(id=uid, username=uid, role="user", scope=scope))
    try:
        yield
    finally:
        reset_current_user(token)


def _buffered(session_id: str, turn_id: str, count: int) -> list[dict]:
    return [
        {
            "type": "content",
            "source": "chat",
            "stage": "",
            "content": f"chunk-{i}",
            "metadata": {},
            "session_id": session_id,
            "turn_id": turn_id,
            "seq": i + 1,
            "timestamp": 1000.0 + i,
        }
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# SQLite path: one canonical database copy
# ---------------------------------------------------------------------------


async def test_flush_persists_the_whole_batch_once(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 5)

    await runtime._flush_buffered_events(execution)

    persisted = await store.get_turn_events(turn["id"])
    assert [event["content"] for event in persisted] == [f"chunk-{i}" for i in range(5)]


async def test_flush_is_idempotent_per_execution(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 3)

    await runtime._flush_buffered_events(execution)
    await runtime._flush_buffered_events(execution)

    persisted = await store.get_turn_events(turn["id"])
    assert len(persisted) == 3


async def test_concurrent_flush_callers_share_one_persistence_attempt(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 4)

    await asyncio.gather(
        runtime._flush_buffered_events(execution),
        runtime._flush_buffered_events(execution),
    )

    assert len(await store.get_turn_events(turn["id"])) == 4


async def test_non_batch_flush_retry_continues_after_committed_prefix(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 3)

    async def real_append(turn_id, payload):
        return (await store._run(store._append_turn_events_sync, turn_id, [payload], None))[0]

    calls = 0

    async def flaky_append(turn_id, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("transient persistence failure")
        return await real_append(turn_id, payload)

    monkeypatch.setattr(store, "append_turn_events", None)
    monkeypatch.setattr(store, "append_events", None)
    monkeypatch.setattr(store, "append_turn_event", flaky_append)

    with pytest.raises(RuntimeError, match="transient persistence failure"):
        await runtime._flush_buffered_events(execution)
    await runtime._flush_buffered_events(execution)

    persisted = await store.get_turn_events(turn["id"])
    assert [event["content"] for event in persisted] == ["chunk-0", "chunk-1", "chunk-2"]


async def test_flush_survives_turn_deleted_mid_drain(tmp_path) -> None:
    """Deleting the session mid-flush must not raise out of the turn task."""
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    execution.events = _buffered(session["id"], turn["id"], 2)
    await store.delete_session(session["id"])

    await runtime._flush_buffered_events(execution)  # must not raise


# ---------------------------------------------------------------------------
# PocketBase path: synchronous durability, no rglob
# ---------------------------------------------------------------------------


async def test_pb_append_turn_events_is_durable_before_return(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        events = _buffered("s1", "turn_1", 4)
        persisted = await store.append_turn_events("turn_1", events)

        # Annotated payloads come back synchronously with their seqs intact —
        # the runtime receives the durable sequence numbers without another fetch.
        assert [payload["seq"] for payload in persisted] == [1, 2, 3, 4]

        rows = fake_pb.collection("turn_events").get_full_list()
        assert sorted(int(row.seq) for row in rows) == [1, 2, 3, 4]
        assert all(row.turn_id == "turn_1" for row in rows)
        assert all(row.session_id == "s1" for row in rows)


async def test_pb_append_turn_event_single_delegates_to_batch(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        payload = await store.append_turn_event("turn_9", {"type": "content", "content": "x"})
        assert payload["turn_id"] == "turn_9"
        assert payload["seq"]  # fallback seq assigned
        rows = fake_pb.collection("turn_events").get_full_list()
        assert len(rows) == 1


async def test_pb_update_turn_status_no_longer_flushes_events(fake_pb) -> None:
    """Finalising a turn only updates the row — the old events.jsonl rglob +
    per-event POST flush is gone (events flow through append_turn_events)."""
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="t", session_id="s_flush")
        turn = await store.create_turn("s_flush", capability="chat")
        assert await store.update_turn_status(turn["turn_id"], "completed") is True
        assert fake_pb.collection("turn_events").get_full_list() == []


async def test_pb_add_message_returns_real_record_id(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="t", session_id="s_ids")
        message_id = await store.add_message("s_ids", "assistant", "hello")
        messages = await store.get_messages("s_ids")
        # The id handed back (and forwarded to the frontend via the DONE
        # reconcile metadata) must be the same id get_messages serves.
        assert message_id == messages[0]["id"]
