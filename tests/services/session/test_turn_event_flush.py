"""Post-stream turn-event flush: batching, workspace mirror, PocketBase upload.

The turn runtime buffers every live event in memory and persists the whole
batch after the stream drains, right before publishing DONE. Everything on
that path must stay O(1) round-trips w.r.t. the event count — per-event
commits/opens/POSTs sat between the last streamed token and the client's
spinner clearing (the "stuck on generating" report).
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
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


async def _drain_uploads(store: PocketBaseSessionStore) -> None:
    """Wait for the store's background turn-event uploads to finish."""
    tasks = list(store._event_upload_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        # Let the done-callbacks (set discard) run before returning.
        await asyncio.sleep(0)


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
# SQLite path: batch DB append + single-write workspace mirror
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_workspace(monkeypatch, tmp_path):
    """Point the runtime's workspace mirror at an isolated tmp tree."""

    class _StubPathService:
        def get_task_workspace(self, feature: str, task_id: str) -> Path:
            return tmp_path / "workspace" / feature / task_id

    monkeypatch.setattr(
        "deeptutor.services.session.turn_runtime.get_path_service",
        lambda: _StubPathService(),
    )
    return tmp_path / "workspace"


async def test_flush_mirrors_whole_batch_in_one_file_write(
    tmp_path, stub_workspace, monkeypatch
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
    execution.events = _buffered(session["id"], turn["id"], 5)

    open_calls = 0
    real_open = open

    def counting_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1
        return real_open(*args, **kwargs)

    # Scope the ``open`` patch to the flush itself so the assertions below
    # (and fixture teardown) run against the real builtin.
    with pytest.MonkeyPatch.context() as flush_patch:
        flush_patch.setattr("builtins.open", counting_open)
        await runtime._flush_buffered_events(execution)

    # All five events reach the DB and the jsonl mirror, via ONE file open.
    persisted = await store.get_turn_events(turn["id"])
    assert [event["content"] for event in persisted] == [f"chunk-{i}" for i in range(5)]
    mirror = stub_workspace / "chat" / turn["id"] / "events.jsonl"
    lines = [json.loads(line) for line in mirror.read_text().splitlines()]
    assert [line["content"] for line in lines] == [f"chunk-{i}" for i in range(5)]
    assert open_calls == 1


async def test_flush_is_idempotent_per_execution(tmp_path, stub_workspace) -> None:
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
    mirror = stub_workspace / "chat" / turn["id"] / "events.jsonl"
    assert len(mirror.read_text().splitlines()) == 3


async def test_flush_survives_turn_deleted_mid_drain(tmp_path, stub_workspace) -> None:
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
# PocketBase path: background upload, no rglob, no update_turn_status hook
# ---------------------------------------------------------------------------


async def test_pb_append_turn_events_uploads_in_background(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        events = _buffered("s1", "turn_1", 4)
        persisted = await store.append_turn_events("turn_1", events)

        # Annotated payloads come back synchronously with their seqs intact —
        # the runtime mirrors these to events.jsonl without waiting on HTTP.
        assert [payload["seq"] for payload in persisted] == [1, 2, 3, 4]

        await _drain_uploads(store)
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
        await _drain_uploads(store)
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
        await _drain_uploads(store)
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
