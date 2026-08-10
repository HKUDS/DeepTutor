"""Per-user session isolation on the PocketBase backend (issue #596).

PocketBase is a single shared server with no filesystem-level isolation, so
``PocketBaseSessionStore`` must scope every session row by ``user_id`` (derived
from the request-scoped current-user ContextVar). These tests stand up a tiny
in-memory fake of the PocketBase SDK — the real ``pocketbase`` package is not a
test dependency — and assert that one user can never see or mutate another
user's sessions.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from deeptutor.agents.research.recovery import seal_checkpoint
from deeptutor.api.routers.unified_ws import unified_websocket
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

pytestmark = pytest.mark.asyncio

_CLAUSE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


@contextmanager
def as_user(uid: str, *, role: str = "user"):
    scope = UserScope(kind=role, user_id=uid, root=Path("/tmp") / uid)  # noqa: S108
    token = set_current_user(CurrentUser(id=uid, username=uid, role=role, scope=scope))
    try:
        yield
    finally:
        reset_current_user(token)


class _Record:
    def __init__(self, pb_id: str, data: dict) -> None:
        self.id = pb_id
        for key, value in data.items():
            setattr(self, key, value)


class _Result:
    def __init__(self, items: list[_Record]) -> None:
        self.items = items


class _Collection:
    """In-memory stand-in for a PocketBase collection (equality filters only)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._rows: list[_Record] = []
        self._seq = 0
        self._lock = threading.Lock()
        self.create_barrier: threading.Barrier | None = None
        self.create_started: threading.Event | None = None
        self.create_release: threading.Event | None = None

    def _matches(self, record: _Record, query_params: dict | None) -> bool:
        flt = (query_params or {}).get("filter") or ""
        for field, expected in _CLAUSE.findall(flt):
            if str(getattr(record, field, "")) != expected:
                return False
        return True

    def create(self, data: dict) -> _Record:
        if self.create_barrier is not None:
            self.create_barrier.wait(timeout=2)
        if self.create_started is not None:
            self.create_started.set()
        if self.create_release is not None:
            self.create_release.wait(timeout=2)
        with self._lock:
            if self.name == "research_retry_bindings" and any(
                str(getattr(row, "reservation_id", "")) == str(data.get("reservation_id", ""))
                for row in self._rows
            ):
                raise RuntimeError("unique reservation_id")
            if self.name == "research_retry_reservations" and any(
                all(
                    str(getattr(row, key, "")) == str(data.get(key, ""))
                    for key in ("session_id", "parent_attempt_id", "retry_request_id")
                )
                for row in self._rows
            ):
                raise RuntimeError("unique retry identity")
            self._seq += 1
            record = _Record(f"pb{self._seq:04d}", data)
            self._rows.append(record)
            return record

    def get_full_list(self, query_params: dict | None = None) -> list[_Record]:
        return [r for r in self._rows if self._matches(r, query_params)]

    def get_list(self, page: int, per_page: int, query_params: dict | None = None) -> _Result:
        matched = self.get_full_list(query_params)
        start = (page - 1) * per_page
        return _Result(matched[start : start + per_page])

    def update(self, pb_id: str, data: dict) -> _Record:
        record = next(r for r in self._rows if r.id == pb_id)
        for key, value in data.items():
            setattr(record, key, value)
        return record

    def delete(self, pb_id: str) -> None:
        self._rows = [r for r in self._rows if r.id != pb_id]


class _FakeClient:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def collection(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection(name))


class _RetryWebSocket:
    def __init__(self, request: dict) -> None:
        self._request = json.dumps(request)
        self._request_sent = False
        self.disconnect = asyncio.Event()
        self.done = asyncio.Event()
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._request_sent:
            self._request_sent = True
            return self._request
        await self.disconnect.wait()
        raise WebSocketDisconnect()

    async def send_text(self, payload: str) -> None:
        event = json.loads(payload)
        self.sent.append(event)
        if event.get("type") == "done":
            self.done.set()


@pytest.fixture
def fake_pb(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client", lambda: client, raising=True
    )
    return client


async def test_create_session_stamps_current_user(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="A's chat", session_id="s_alice")
    [row] = fake_pb.collection("sessions").get_full_list()
    assert row.user_id == "alice"
    assert row.session_id == "s_alice"


async def test_list_sessions_only_returns_own(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="a1", session_id="s_a1")
        await store.create_session(title="a2", session_id="s_a2")
    with as_user("bob"):
        await store.create_session(title="b1", session_id="s_b1")

        bob_sessions = await store.list_sessions()
    assert {s["session_id"] for s in bob_sessions} == {"s_b1"}

    with as_user("alice"):
        alice_sessions = await store.list_sessions()
    assert {s["session_id"] for s in alice_sessions} == {"s_a1", "s_a2"}


async def test_get_session_404s_for_other_user(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="secret", session_id="s_secret")

    # Bob must not be able to read Alice's session by id.
    with as_user("bob"):
        assert await store.get_session("s_secret") is None
        assert await store.get_session_with_messages("s_secret") is None

    # The owner still reads it fine.
    with as_user("alice"):
        own = await store.get_session("s_secret")
    assert own is not None and own["session_id"] == "s_secret"


async def test_mutations_are_scoped_to_owner(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="orig", session_id="s_m")

    with as_user("bob"):
        assert await store.update_session_title("s_m", "hijacked") is False
        assert await store.delete_session("s_m") is False
        assert await store.update_summary("s_m", "x", 1) is False

    # Alice's row is untouched and still present.
    with as_user("alice"):
        assert await store.update_session_title("s_m", "renamed") is True
        session = await store.get_session("s_m")
    assert session is not None and session["title"] == "renamed"


async def test_create_turn_rejects_foreign_session(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="orig", session_id="s_t")

    with as_user("bob"):
        with pytest.raises(ValueError, match="Session not found"):
            await store.create_turn("s_t")

    with as_user("alice"):
        turn = await store.create_turn("s_t")
    assert turn["session_id"] == "s_t"


async def test_research_retry_reservation_replays_conflicts_and_bound_release_fails(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_retry")
        first = await store.reserve_research_retry("s_retry", "attempt_a", "request_a", "hash_a")
        replay = await store.reserve_research_retry("s_retry", "attempt_a", "request_a", "hash_a")
        assert replay["id"] == first["id"]
        with pytest.raises(RuntimeError, match="idempotency_conflict"):
            await store.reserve_research_retry("s_retry", "attempt_a", "request_a", "hash_b")
        assert await store.bind_research_retry_turn(first["id"], "turn_a")
        assert not await store.bind_research_retry_turn(first["id"], "turn_b")
        assert await store.get_research_retry_bound_turn(first["id"]) == "turn_a"
        assert await store.is_research_retry_bound_turn("turn_a")
        assert not await store.is_research_retry_bound_turn("turn_b")
        assert not await store.release_research_retry(first["id"])


@pytest.mark.parametrize("outcome,strategy", [("completed", "full_research"), ("partial", "failed_blocks"), ("failed", "report_only")])
async def test_research_attempt_metadata_round_trips_in_fake_pocketbase(fake_pb, outcome, strategy) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id=f"s_{outcome}")
        checkpoint = {"schema_version": 1, "attempt_id": f"attempt_{outcome}", "strategy": strategy, "report": {"outcome": outcome}, "citation_ids": ["CIT-1-01"]}
        await store.add_message(session["id"], "assistant", "report", metadata={"research_attempt": checkpoint})
        [message] = await store.get_messages(session["id"])
    assert message["metadata"]["research_attempt"] == checkpoint


async def test_retry_reservation_missing_collection_fails_closed(monkeypatch) -> None:
    class _Missing:
        def collection(self, _name):
            raise RuntimeError("collection missing")
    monkeypatch.setattr("deeptutor.services.session.pocketbase_store._pb", lambda: _Missing())
    store = PocketBaseSessionStore()
    with as_user("alice"):
        with pytest.raises(RuntimeError, match="reservation_unavailable"):
            await store.reserve_research_retry("s", "a", "r", "h")


@pytest.mark.parametrize("winner_hash,raises", [("hash_a", None), ("hash_b", "idempotency_conflict")])
async def test_retry_reservation_unique_create_race_rereads_winner(fake_pb, winner_hash, raises) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_race")
        collection = fake_pb.collection("research_retry_reservations")
        original_create = collection.create
        raced = False
        def create(data):
            nonlocal raced
            if not raced:
                raced = True
                original_create({**data, "parameters_hash": winner_hash})
                raise RuntimeError("unique constraint")
            return original_create(data)
        collection.create = create
        if raises:
            with pytest.raises(RuntimeError, match=raises):
                await store.reserve_research_retry("s_race", "a", "r", "hash_a")
        else:
            replay = await store.reserve_research_retry("s_race", "a", "r", "hash_a")
            assert replay["parameters_hash"] == "hash_a"


async def test_retry_bind_unique_create_selects_one_concurrent_winner(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_bind")
        reservation = await store.reserve_research_retry("s_bind", "a", "r", "h")
        binding_collection = fake_pb.collection("research_retry_bindings")
        binding_collection.create_barrier = threading.Barrier(2)
        outcomes = await asyncio.gather(
            store.bind_research_retry_turn(reservation["id"], "turn_a"),
            store.bind_research_retry_turn(reservation["id"], "turn_b"),
        )
        binding_collection.create_barrier = None
        assert sorted(outcomes) == [False, True]
        [winner] = binding_collection.get_full_list(
            query_params={"filter": f'reservation_id="{reservation["id"]}"'}
        )
        winning_turn = str(winner.turn_id)
        losing_turn = "turn_b" if winning_turn == "turn_a" else "turn_a"
        assert await store.get_research_retry_bound_turn(reservation["id"]) == winning_turn
        assert await store.bind_research_retry_turn(reservation["id"], winning_turn)
        assert not await store.bind_research_retry_turn(reservation["id"], losing_turn)
        replay = await store.reserve_research_retry("s_bind", "a", "r", "h")
        assert replay["turn_id"] == winning_turn
        assert not await store.release_research_retry(reservation["id"])


async def test_retry_lease_heartbeat_requires_the_binding_owner(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_lease_owner")
        reservation = await store.reserve_research_retry(
            "s_lease_owner", "attempt", "request", "hash"
        )
        assert await store.bind_research_retry_turn(
            reservation["id"], "turn_lease", "worker_a", 100.0
        )
        assert await store.get_research_retry_lease("turn_lease") == {
            "turn_id": "turn_lease",
            "owner_id": "worker_a",
            "heartbeat_at": 100.0,
        }
        assert not await store.heartbeat_research_retry_turn(
            "turn_lease", "worker_b", 110.0
        )
        assert await store.heartbeat_research_retry_turn(
            "turn_lease", "worker_a", 120.0
        )
        assert (await store.get_research_retry_lease("turn_lease") or {})[
            "heartbeat_at"
        ] == 120.0


async def test_retry_binding_missing_collection_fails_closed(monkeypatch) -> None:
    client = _FakeClient()
    client.collection("research_retry_reservations")
    original_collection = client.collection

    def collection(name: str):
        if name == "research_retry_bindings":
            raise RuntimeError("binding collection missing")
        return original_collection(name)

    client.collection = collection
    monkeypatch.setattr("deeptutor.services.session.pocketbase_store._pb", lambda: client)
    store = PocketBaseSessionStore()
    with as_user("alice"):
        assert not await store.is_research_retry_bound_turn("turn_missing")
        assert await store.get_research_retry_lease("turn_missing") is None
        assert not await store.heartbeat_research_retry_turn(
            "turn_missing", "worker", 1.0
        )
        with pytest.raises(RuntimeError, match="reservation_unavailable"):
            await store.reserve_research_retry("s", "a", "r", "h")


async def test_legacy_bound_reservation_remains_immutable(fake_pb) -> None:
    store = PocketBaseSessionStore()
    reservation = fake_pb.collection("research_retry_reservations").create({
        "session_id": "s_legacy", "parent_attempt_id": "a", "retry_request_id": "r",
        "parameters_hash": "h", "turn_id": "turn_legacy", "created_at": 1,
    })
    assert await store.bind_research_retry_turn(reservation.id, "turn_legacy")
    assert not await store.bind_research_retry_turn(reservation.id, "turn_new")
    assert await store.is_research_retry_bound_turn("turn_legacy")
    assert await store.get_research_retry_lease("turn_legacy") == {
        "turn_id": "turn_legacy",
        "owner_id": "",
        "heartbeat_at": 0.0,
    }
    replay = await store.reserve_research_retry("s_legacy", "a", "r", "h")
    assert replay["turn_id"] == "turn_legacy"
    assert not await store.release_research_retry(reservation.id)


async def test_cross_worker_retry_requests_replay_atomic_binding_winner(fake_pb) -> None:
    store_a = PocketBaseSessionStore()
    store_b = PocketBaseSessionStore()
    with as_user("alice", role="admin"):
        session = await store_a.create_session(session_id="s_cross_worker")
        checkpoint = seal_checkpoint({
            "schema_version": 1, "attempt_id": "attempt_parent", "strategy": "full_research",
            "input": {
                "topic": "topic", "confirmed_outline": [], "research_config": {},
                "request_snapshot": {
                    "content": "topic", "config": {"mode": "report", "depth": "quick"},
                    "enabledTools": [], "knowledgeBases": [], "attachments": [],
                    "language": "en",
                },
            },
            "model_snapshot": {}, "blocks": [], "citations": [],
            "report": {"outcome": "failed", "content": ""},
            "failure": {"code": "model_output_empty", "retry_strategy": "full_research"},
        })
        await store_a.add_message(
            session["id"], "assistant", "",
            metadata={"research_attempt": checkpoint},
        )

        runtime_a = TurnRuntimeManager(store_a)
        runtime_b = TurnRuntimeManager(store_b)
        release_execution = asyncio.Event()

        async def hold_execution(_execution):
            await release_execution.wait()

        runtime_a._run_turn = hold_execution
        runtime_b._run_turn = hold_execution

        fake_pb.collection("research_retry_reservations").create_barrier = threading.Barrier(2)
        fake_pb.collection("turns").create_barrier = threading.Barrier(2)
        fake_pb.collection("research_retry_bindings").create_barrier = threading.Barrier(2)

        first, second = await asyncio.gather(
            runtime_a.retry_research_attempt(
                session_id=session["id"], attempt_id="attempt_parent",
                strategy="full_research", retry_request_id="request_same",
            ),
            runtime_b.retry_research_attempt(
                session_id=session["id"], attempt_id="attempt_parent",
                strategy="full_research", retry_request_id="request_same",
            ),
        )

        for name in ("research_retry_reservations", "turns", "research_retry_bindings"):
            fake_pb.collection(name).create_barrier = None

        winner_turn_id = first[1]["id"]
        assert second[1]["id"] == winner_turn_id
        owners = [
            runtime for runtime in (runtime_a, runtime_b)
            if winner_turn_id in runtime._executions
        ]
        assert len(owners) == 1
        active = await store_a.list_active_turns(session["id"])
        assert [turn["id"] for turn in active] == [winner_turn_id]
        turn_rows = fake_pb.collection("turns").get_full_list()
        assert sorted(str(row.status) for row in turn_rows) == ["cancelled", "running"]
        assert all(str(getattr(row, "error", "")) != "research_retry_reservation_bind_failed" for row in turn_rows)

        replay = await runtime_b.retry_research_attempt(
            session_id=session["id"], attempt_id="attempt_parent",
            strategy="full_research", retry_request_id="request_same",
        )
        assert replay[1]["id"] == winner_turn_id
        with pytest.raises(RuntimeError, match="idempotency_conflict"):
            await runtime_b.retry_research_attempt(
                session_id=session["id"], attempt_id="attempt_parent",
                strategy="report_only", retry_request_id="request_same",
            )

        release_execution.set()
        tasks = [
            execution.task
            for runtime in (runtime_a, runtime_b)
            for execution in runtime._executions.values()
            if execution.task is not None
        ]
        await asyncio.gather(*tasks)
        runtime_a._executions.clear()
        runtime_b._executions.clear()


async def test_retry_heartbeat_keeps_silent_remote_owner_live(fake_pb) -> None:
    store_a = PocketBaseSessionStore()
    store_b = PocketBaseSessionStore()
    clock = [100.0]
    heartbeat_waiting = asyncio.Event()
    allow_heartbeat = asyncio.Event()
    hold_owner = asyncio.Event()

    async def heartbeat_sleep(_delay: float) -> None:
        if not heartbeat_waiting.is_set():
            heartbeat_waiting.set()
            await allow_heartbeat.wait()
            return
        await hold_owner.wait()

    with as_user("alice", role="admin"):
        session = await store_a.create_session(session_id="s_silent_owner")
        reservation = await store_a.reserve_research_retry(
            session["id"], "attempt", "request", "hash"
        )
        runtime_a = TurnRuntimeManager(
            store_a,
            worker_id="worker_a",
            retry_lease_clock=lambda: clock[0],
            retry_lease_timeout=5,
            retry_heartbeat_sleep=heartbeat_sleep,
        )

        async def silent_owner(_execution) -> None:
            await hold_owner.wait()

        runtime_a._run_turn = silent_owner
        _, turn = await runtime_a.start_turn({
            "session_id": session["id"],
            "capability": "chat",
            "content": "retry",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {"_research_retry_reservation_id": reservation["id"]},
        })
        await heartbeat_waiting.wait()
        clock[0] = 120.0
        allow_heartbeat.set()
        for _ in range(20):
            lease = await store_a.get_research_retry_lease(turn["id"])
            if (lease or {}).get("heartbeat_at") == 120.0:
                break
            await asyncio.sleep(0)
        assert (lease or {}).get("heartbeat_at") == 120.0

        terminalized = False

        async def follower_sleep(_delay: float) -> None:
            nonlocal terminalized
            if not terminalized:
                terminalized = True
                await store_a.append_turn_events_durable(
                    turn["id"],
                    [{
                        "type": "done",
                        "source": "test",
                        "metadata": {"status": "completed"},
                        "session_id": session["id"],
                        "turn_id": turn["id"],
                        "seq": 1,
                        "timestamp": clock[0],
                    }],
                )
                await store_a.update_turn_status(turn["id"], "completed")
            await asyncio.sleep(0)

        runtime_b = TurnRuntimeManager(
            store_b,
            retry_lease_clock=lambda: clock[0],
            retry_lease_timeout=5,
            remote_poll_sleep=follower_sleep,
        )
        followed = [event async for event in runtime_b.subscribe_turn(turn["id"])]
        assert [event["type"] for event in followed] == ["done"]
        assert not followed[0]["metadata"].get("synthesized")
        assert (await store_b.get_turn(turn["id"]) or {})["status"] == "completed"

        hold_owner.set()
        owner_task = runtime_a._executions[turn["id"]].task
        assert owner_task is not None
        await owner_task
        runtime_a._executions.clear()


async def test_crashed_retry_owner_expires_once_for_concurrent_followers(fake_pb) -> None:
    store_a = PocketBaseSessionStore()
    store_b = PocketBaseSessionStore()
    clock = [100.0]
    crash_owner = asyncio.Event()
    heartbeat_waiting = asyncio.Event()
    heartbeat_block = asyncio.Event()

    async def heartbeat_sleep(_delay: float) -> None:
        heartbeat_waiting.set()
        await heartbeat_block.wait()

    with as_user("alice", role="admin"):
        session = await store_a.create_session(session_id="s_crashed_owner")
        reservation = await store_a.reserve_research_retry(
            session["id"], "attempt", "request", "hash"
        )
        runtime_a = TurnRuntimeManager(
            store_a,
            worker_id="worker_crashed",
            retry_lease_clock=lambda: clock[0],
            retry_lease_timeout=5,
            retry_heartbeat_sleep=heartbeat_sleep,
        )

        async def crashing_owner(_execution) -> None:
            await crash_owner.wait()
            raise RuntimeError("worker crashed")

        runtime_a._run_turn = crashing_owner
        _, turn = await runtime_a.start_turn({
            "session_id": session["id"],
            "capability": "chat",
            "content": "retry",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {"_research_retry_reservation_id": reservation["id"]},
        })
        await heartbeat_waiting.wait()
        execution = runtime_a._executions[turn["id"]]
        crash_owner.set()
        assert execution.task is not None
        result = await asyncio.gather(execution.task, return_exceptions=True)
        assert isinstance(result[0], RuntimeError)
        await asyncio.sleep(0)
        assert execution.heartbeat_task is not None
        assert execution.heartbeat_task.done()

        clock[0] = 120.0
        followers = [
            TurnRuntimeManager(
                store_b,
                retry_lease_clock=lambda: clock[0],
                retry_lease_timeout=5,
            )
            for _ in range(2)
        ]

        async def collect(runtime: TurnRuntimeManager) -> list[dict]:
            return [event async for event in runtime.subscribe_turn(turn["id"])]

        first, second = await asyncio.gather(*(collect(runtime) for runtime in followers))
        for events in (first, second):
            assert [event["type"] for event in events] == ["error", "done"]
            assert sum(event["type"] == "error" for event in events) == 1
            assert sum(event["type"] == "done" for event in events) == 1
            assert events[-1]["metadata"]["status"] == "failed"
        persisted = await store_b.get_turn(turn["id"])
        assert persisted is not None
        assert persisted["status"] == "failed"
        assert persisted["error"] == "Turn interrupted by server restart. Please retry your message."
        runtime_a._executions.clear()


async def test_cancelling_remote_follower_does_not_touch_fresh_owner(fake_pb) -> None:
    store = PocketBaseSessionStore()
    clock = [100.0]
    sleeping = asyncio.Event()
    never = asyncio.Event()

    async def follower_sleep(_delay: float) -> None:
        sleeping.set()
        await never.wait()

    with as_user("alice", role="admin"):
        session = await store.create_session(session_id="s_cancel_follower")
        turn = await store.create_turn(session["id"], capability="deep_research")
        reservation = await store.reserve_research_retry(
            session["id"], "attempt", "request", "hash"
        )
        assert await store.bind_research_retry_turn(
            reservation["id"], turn["id"], "worker_owner", clock[0]
        )
        runtime = TurnRuntimeManager(
            store,
            retry_lease_clock=lambda: clock[0],
            retry_lease_timeout=5,
            remote_poll_sleep=follower_sleep,
        )
        task = asyncio.create_task(
            anext(runtime.subscribe_turn(turn["id"]))
        )
        await sleeping.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await store.get_turn(turn["id"]) or {})["status"] == "running"
        assert (await store.get_research_retry_lease(turn["id"]) or {})[
            "owner_id"
        ] == "worker_owner"


async def test_unified_ws_follows_remote_retry_winner_without_failing_it(
    fake_pb, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_a = PocketBaseSessionStore()
    store_b = PocketBaseSessionStore()
    with as_user("alice", role="admin"):
        session = await store_a.create_session(session_id="s_remote_follow")
        checkpoint = seal_checkpoint({
            "schema_version": 1,
            "attempt_id": "attempt_remote",
            "strategy": "full_research",
            "input": {
                "topic": "topic",
                "confirmed_outline": [],
                "research_config": {},
                "request_snapshot": {
                    "content": "topic",
                    "config": {"mode": "report", "depth": "quick"},
                    "enabledTools": [],
                    "knowledgeBases": [],
                    "attachments": [],
                    "language": "en",
                },
            },
            "model_snapshot": {},
            "blocks": [],
            "citations": [],
            "report": {"outcome": "failed", "content": ""},
            "failure": {"code": "model_output_empty", "retry_strategy": "full_research"},
        })
        await store_a.add_message(
            session["id"],
            "assistant",
            "",
            metadata={"research_attempt": checkpoint},
        )

        runtime_a = TurnRuntimeManager(store_a)
        owner_started = asyncio.Event()
        release_owner = asyncio.Event()
        events_durable = asyncio.Event()
        owner_terminal_events: list[dict] = []

        async def owner_run(execution) -> None:
            owner_started.set()
            await release_owner.wait()
            await runtime_a._publish_live_event(
                execution,
                StreamEvent(
                    type=StreamEventType.RESULT,
                    source="deep_research",
                    content="winner result",
                    metadata={"response": "winner result", "outcome": "completed"},
                ),
            )
            await runtime_a._publish_live_event(
                execution,
                StreamEvent(
                    type=StreamEventType.DONE,
                    source="deep_research",
                    metadata={"status": "completed"},
                ),
            )
            owner_terminal_events.extend(
                event for event in execution.events if event["type"] in {"result", "done"}
            )
            # Exercise PocketBase's completion-before-background-event-flush
            # ordering. The remote follower must wait and replay once more.
            await store_a.update_turn_status(execution.turn_id, "completed")
            await runtime_a._flush_buffered_events(execution)
            uploads = list(store_a._event_upload_tasks)
            if uploads:
                await asyncio.gather(*uploads)
            events_durable.set()

        runtime_a._run_turn = owner_run
        _, winner = await runtime_a.retry_research_attempt(
            session_id=session["id"],
            attempt_id="attempt_remote",
            strategy="full_research",
            retry_request_id="request_remote",
        )
        await owner_started.wait()
        owner_task = runtime_a._executions[winner["id"]].task
        assert owner_task is not None and not owner_task.done()

        subscription_observed = asyncio.Event()

        async def follower_sleep(_delay: float) -> None:
            if not subscription_observed.is_set():
                persisted = await store_b.get_turn(winner["id"])
                assert persisted is not None and persisted["status"] == "running"
                assert owner_task is not None and not owner_task.done()
                subscription_observed.set()
                release_owner.set()
            await events_durable.wait()

        runtime_b = TurnRuntimeManager(store_b, remote_poll_sleep=follower_sleep)

        async def allow_websocket(_ws):
            return None

        monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", allow_websocket)
        monkeypatch.setattr(
            "deeptutor.services.session.get_turn_runtime_manager", lambda: runtime_b
        )
        websocket = _RetryWebSocket({
            "type": "retry_research_attempt",
            "session_id": session["id"],
            "attempt_id": "attempt_remote",
            "strategy": "full_research",
            "retry_request_id": "request_remote",
        })
        ws_task = asyncio.create_task(unified_websocket(websocket))

        await asyncio.wait_for(subscription_observed.wait(), timeout=1)
        await asyncio.wait_for(websocket.done.wait(), timeout=1)
        await asyncio.wait_for(owner_task, timeout=1)
        await asyncio.sleep(0)
        websocket.disconnect.set()
        await asyncio.wait_for(ws_task, timeout=1)

        assert websocket.accepted
        assert winner["id"] not in runtime_b._executions
        followed = [event for event in websocket.sent if event.get("type") in {"result", "done"}]
        assert followed == owner_terminal_events
        assert not any(event.get("type") == "error" for event in websocket.sent)
        assert not any(
            event.get("metadata", {}).get("synthesized") for event in websocket.sent
        )
        persisted = await store_b.get_turn(winner["id"])
        assert persisted is not None and persisted["status"] == "completed"


async def test_real_run_turn_persists_exact_done_before_remote_ws_sees_it(
    fake_pb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise _run_turn, PocketBase durability, and the unified WS together."""
    store_a = PocketBaseSessionStore()
    store_b = PocketBaseSessionStore()

    class FakeContextBuilder:
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

    class FakeOrchestrator:
        async def handle(self, _context):
            yield StreamEvent(
                type=StreamEventType.RESULT,
                source="deep_research",
                content="durable winner",
                metadata={"response": "durable winner", "outcome": "completed"},
            )
            yield StreamEvent(
                type=StreamEventType.DONE,
                source="deep_research",
                metadata={"status": "completed", "terminal_marker": "real"},
            )

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config",
        lambda: SimpleNamespace(model="test", provider_name="test"),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder",
        FakeContextBuilder,
    )
    monkeypatch.setattr(
        "deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator
    )
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda *_args, **_kwargs: SimpleNamespace(text="", references=[], warnings=[]),
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        lambda: SimpleNamespace(
            summary_entries=lambda: [],
            load_always_for_context=lambda: "",
            load_for_context=lambda _skills: "",
            list_skills=lambda: [],
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        lambda: SimpleNamespace(load_for_context=lambda _name: ""),
    )

    with as_user("alice", role="admin"):
        session = await store_a.create_session(session_id="s_real_done")
        checkpoint = seal_checkpoint({
            "schema_version": 1,
            "attempt_id": "attempt_real_done",
            "strategy": "full_research",
            "input": {
                "topic": "topic",
                "confirmed_outline": [],
                "research_config": {},
                "request_snapshot": {
                    "content": "topic",
                    "config": {"mode": "report", "depth": "quick"},
                    "enabledTools": [],
                    "knowledgeBases": [],
                    "attachments": [],
                    "language": "en",
                },
            },
            "model_snapshot": {},
            "blocks": [],
            "citations": [],
            "report": {"outcome": "failed", "content": ""},
            "failure": {"code": "model_output_empty", "retry_strategy": "full_research"},
        })
        await store_a.add_message(
            session["id"],
            "assistant",
            "",
            metadata={"research_attempt": checkpoint},
        )

        terminal_create_started = threading.Event()
        terminal_create_release = threading.Event()
        turn_events = fake_pb.collection("turn_events")
        turn_events.create_started = terminal_create_started
        turn_events.create_release = terminal_create_release

        runtime_a = TurnRuntimeManager(store_a, remote_poll_interval=0.001)

        async def skip_title(**_kwargs) -> None:
            return None

        monkeypatch.setattr(runtime_a, "_maybe_generate_session_title", skip_title)
        _, winner = await runtime_a.retry_research_attempt(
            session_id=session["id"],
            attempt_id="attempt_real_done",
            strategy="full_research",
            retry_request_id="request_real_done",
        )
        owner_task = runtime_a._executions[winner["id"]].task
        assert owner_task is not None
        assert await asyncio.to_thread(terminal_create_started.wait, 1)

        local_events: list[dict] = []
        local_done = asyncio.Event()

        async def collect_local() -> None:
            async for event in runtime_a.subscribe_turn(winner["id"]):
                local_events.append(event)
                if event.get("type") == "done":
                    local_done.set()

        local_task = asyncio.create_task(collect_local())

        runtime_b = TurnRuntimeManager(
            store_b,
            remote_poll_interval=0.001,
            remote_terminal_grace_polls=2,
        )

        async def allow_websocket(_ws):
            return None

        monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", allow_websocket)
        monkeypatch.setattr(
            "deeptutor.services.session.get_turn_runtime_manager", lambda: runtime_b
        )
        websocket = _RetryWebSocket({
            "type": "retry_research_attempt",
            "session_id": session["id"],
            "attempt_id": "attempt_real_done",
            "strategy": "full_research",
            "retry_request_id": "request_real_done",
        })
        ws_task = asyncio.create_task(unified_websocket(websocket))
        await asyncio.sleep(0.03)
        assert not websocket.done.is_set()
        assert not local_done.is_set()
        assert not any(event.get("type") == "done" for event in websocket.sent)
        assert not any(event.get("type") == "done" for event in local_events)
        assert (await store_b.get_turn(winner["id"]) or {})["status"] == "running"

        terminal_create_release.set()
        await asyncio.wait_for(websocket.done.wait(), timeout=1)
        await asyncio.wait_for(owner_task, timeout=1)
        await asyncio.wait_for(local_task, timeout=1)
        websocket.disconnect.set()
        await asyncio.wait_for(ws_task, timeout=1)
        turn_events.create_started = None
        turn_events.create_release = None

        persisted_events = await store_b.get_turn_events(winner["id"])
        persisted_done = [event for event in persisted_events if event["type"] == "done"]
        sent_done = [event for event in websocket.sent if event.get("type") == "done"]
        assert len(persisted_done) == len(sent_done) == 1
        assert sent_done[0] == persisted_done[0]
        assert sent_done[0]["metadata"]["terminal_marker"] == "real"
        assert sent_done[0]["metadata"]["assistant_message_id"]
        assert not sent_done[0]["metadata"].get("synthesized")
        local_terminal = [event for event in local_events if event["type"] == "done"]
        assert local_terminal == sent_done
        assert (await store_b.get_turn(winner["id"]) or {})["status"] == "completed"
