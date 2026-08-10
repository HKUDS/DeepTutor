"""Durable retry reservation contract shared by session stores."""

from __future__ import annotations

import sqlite3

import pytest

from deeptutor.agents.research.recovery import seal_checkpoint
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


@pytest.mark.asyncio
async def test_sqlite_reservation_replays_and_rejects_conflicts(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "retry.db")
    session = await store.create_session()
    first = await store.reserve_research_retry(session["id"], "attempt_a", "request_a", "hash_a")
    replay = await store.reserve_research_retry(session["id"], "attempt_a", "request_a", "hash_a")
    assert replay["id"] == first["id"]
    with pytest.raises(RuntimeError, match="idempotency_conflict"):
        await store.reserve_research_retry(session["id"], "attempt_a", "request_a", "hash_b")


@pytest.mark.asyncio
async def test_sqlite_reservation_binds_turn_and_failed_start_releases(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "retry.db")
    session = await store.create_session()
    pending = await store.reserve_research_retry(session["id"], "attempt_a", "request_a", "hash_a")
    assert await store.release_research_retry(pending["id"])
    fresh = await store.reserve_research_retry(session["id"], "attempt_a", "request_a", "hash_a")
    turn = await store.create_turn(session["id"], capability="deep_research")
    assert not await store.is_research_retry_bound_turn(turn["id"])
    assert await store.bind_research_retry_turn(fresh["id"], turn["id"])
    assert await store.get_research_retry_bound_turn(fresh["id"]) == turn["id"]
    assert await store.is_research_retry_bound_turn(turn["id"])
    replay = await store.reserve_research_retry(session["id"], "attempt_a", "request_a", "hash_a")
    assert replay["turn_id"] == turn["id"]
    assert not await store.release_research_retry(fresh["id"])


@pytest.mark.asyncio
async def test_sqlite_retry_lease_owner_and_conditional_orphan_failure(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "retry-lease.db")
    session = await store.create_session()
    reservation = await store.reserve_research_retry(
        session["id"], "attempt", "request", "hash"
    )
    turn = await store.create_turn(session["id"], capability="deep_research")
    assert await store.bind_research_retry_turn(
        reservation["id"], turn["id"], "worker_a", 100.0
    )
    assert await store.get_research_retry_lease(turn["id"]) == {
        "turn_id": turn["id"],
        "owner_id": "worker_a",
        "heartbeat_at": 100.0,
    }
    assert not await store.heartbeat_research_retry_turn(
        turn["id"], "worker_b", 110.0
    )
    assert await store.heartbeat_research_retry_turn(
        turn["id"], "worker_a", 120.0
    )
    await store.update_turn_status(turn["id"], "completed")
    assert not await store.fail_running_turn(turn["id"], "restart orphan")
    assert (await store.get_turn(turn["id"]) or {})["status"] == "completed"


@pytest.mark.asyncio
async def test_sqlite_migrates_legacy_retry_rows_to_stale_leases(tmp_path) -> None:
    db_path = tmp_path / "legacy-retry.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE research_retry_reservations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                parent_attempt_id TEXT NOT NULL,
                retry_request_id TEXT NOT NULL,
                parameters_hash TEXT NOT NULL,
                turn_id TEXT,
                created_at REAL NOT NULL,
                UNIQUE(session_id, parent_attempt_id, retry_request_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_retry_reservations
                (id, session_id, parent_attempt_id, retry_request_id,
                 parameters_hash, turn_id, created_at)
            VALUES ('retry_legacy', 'session_legacy', 'attempt', 'request',
                    'hash', 'turn_legacy', 1)
            """
        )
    store = SQLiteSessionStore(db_path)
    assert await store.get_research_retry_lease("turn_legacy") == {
        "turn_id": "turn_legacy",
        "owner_id": "",
        "heartbeat_at": 0.0,
    }
    assert not await store.heartbeat_research_retry_turn(
        "turn_legacy", "worker", 2.0
    )


@pytest.mark.asyncio
async def test_terminal_failed_retry_winner_replays_durable_events(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "failed-replay.db")
    session = await store.create_session()
    reservation = await store.reserve_research_retry(
        session["id"], "attempt_a", "request_a", "hash_a"
    )
    turn = await store.create_turn(session["id"], capability="deep_research")
    assert await store.bind_research_retry_turn(reservation["id"], turn["id"])
    expected = await store.append_turn_events(
        turn["id"],
        [
            {
                "type": "error",
                "source": "deep_research",
                "content": "Research failed safely.",
                "metadata": {"turn_terminal": True, "status": "failed"},
            },
            {
                "type": "done",
                "source": "deep_research",
                "metadata": {"status": "failed"},
            },
        ],
    )
    await store.update_turn_status(turn["id"], "failed", "Research failed safely.")

    follower = TurnRuntimeManager(store)
    replay = [event async for event in follower.subscribe_turn(turn["id"])]

    assert [(event["type"], event["content"], event["metadata"], event["seq"]) for event in replay] == [
        (
            "error",
            "Research failed safely.",
            {"turn_terminal": True, "status": "failed"},
            expected[0]["seq"],
        ),
        ("done", "", {"status": "failed"}, expected[1]["seq"]),
    ]
    assert all(not event.get("metadata", {}).get("synthesized") for event in replay)
    persisted = await store.get_turn(turn["id"])
    assert persisted is not None and persisted["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,strategy", [("completed", "full_research"), ("partial", "failed_blocks"), ("failed", "report_only")])
async def test_sqlite_attempt_checkpoint_metadata_round_trips(tmp_path, outcome, strategy) -> None:
    store = SQLiteSessionStore(tmp_path / f"{outcome}.db")
    session = await store.create_session()
    checkpoint = {"schema_version": 1, "attempt_id": f"attempt_{outcome}", "strategy": strategy, "report": {"outcome": outcome}, "citation_ids": ["CIT-1-01"]}
    await store.add_message(session["id"], "assistant", "report", metadata={"research_attempt": checkpoint})
    [message] = await store.get_messages(session["id"])
    assert message["metadata"]["research_attempt"] == checkpoint


@pytest.mark.asyncio
async def test_planning_checkpoint_full_retry_reenters_planning_without_empty_outline(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = SQLiteSessionStore(tmp_path / "planning-retry.db")
    session = await store.ensure_session(None)
    checkpoint = seal_checkpoint({
        "schema_version": 1, "attempt_id": "attempt_planning", "strategy": "full_research",
        "input": {
            "topic": "topic", "confirmed_outline": [], "research_config": {},
            "request_snapshot": {
                "content": "topic", "config": {}, "enabledTools": [],
                "knowledgeBases": [], "attachments": [], "language": "en",
            },
        },
        "model_snapshot": {}, "blocks": [], "citations": [],
        "report": {"outcome": "failed", "content": ""},
        "failure": {"code": "model_output_empty", "retry_strategy": "full_research"},
    })
    await store.add_message(
        session["id"], "assistant", "", metadata={"research_attempt": checkpoint}
    )
    runtime = TurnRuntimeManager(store)
    captured: dict = {}

    async def fake_start_turn(payload):
        captured.update(payload)
        return session, {"id": "turn_retry", "session_id": session["id"]}

    monkeypatch.setattr(runtime, "start_turn", fake_start_turn)
    await runtime._retry_research_attempt_locked(
        session_id=session["id"], attempt_id="attempt_planning",
        strategy="full_research", retry_request_id="request_1",
    )

    assert "confirmed_outline" not in captured["config"]
