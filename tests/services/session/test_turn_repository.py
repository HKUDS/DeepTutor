from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys

import pytest

from deeptutor.services.session.protocol import TurnRepository
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

_PROCESS_BEGIN_SCRIPT = """
import asyncio
from pathlib import Path
import sys
import time

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

database_path, session_id, start_path = sys.argv[1:]
deadline = time.monotonic() + 15
while not Path(start_path).exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("start barrier was not released")
    time.sleep(0.005)
try:
    turn = asyncio.run(
        SQLiteSessionStore(Path(database_path)).begin_turn(session_id, capability="chat")
    )
    print(f"ok:{turn['id']}")
except Exception as exc:
    print(f"error:{type(exc).__name__}")
"""


@pytest.mark.asyncio
async def test_sqlite_store_satisfies_narrow_turn_repository(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "turns.db")
    assert isinstance(store, TurnRepository)


def test_sqlite_turn_store_enables_wal_and_busy_timeout(tmp_path) -> None:
    path = tmp_path / "turns.db"
    store = SQLiteSessionStore(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    with store._connect() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not authoritative")
def test_sqlite_turn_store_uses_private_directory_and_database_modes(tmp_path) -> None:
    private_dir = tmp_path / "private"
    path = private_dir / "turns.db"

    SQLiteSessionStore(path)

    assert stat.S_IMODE(private_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_only_one_store_can_begin_an_active_turn_per_session(tmp_path) -> None:
    path = tmp_path / "turns.db"
    seed = SQLiteSessionStore(path)
    session = await seed.ensure_session(None)
    stores = [SQLiteSessionStore(path) for _ in range(8)]

    results = await asyncio.gather(
        *(store.begin_turn(session["id"], capability="chat") for store in stores),
        return_exceptions=True,
    )

    successes = [item for item in results if isinstance(item, dict)]
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(successes) == 1
    assert len(failures) == 7
    assert all(isinstance(item, RuntimeError) for item in failures)


@pytest.mark.asyncio
async def test_only_one_process_can_begin_an_active_turn_per_session(tmp_path) -> None:
    path = tmp_path / "turns-process.db"
    seed = SQLiteSessionStore(path)
    session = await seed.ensure_session(None)
    start_path = tmp_path / "start-turn-race"
    project_root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(project_root), environment.get("PYTHONPATH", "")) if part
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _PROCESS_BEGIN_SCRIPT,
                str(path),
                session["id"],
                str(start_path),
            ],
            cwd=project_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    try:
        start_path.touch()
        completed = [process.communicate(timeout=30) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    errors = [stderr for _stdout, stderr in completed if stderr]
    assert errors == []
    results = [stdout.strip().splitlines()[-1] for stdout, _stderr in completed]
    assert sum(result.startswith("ok:") for result in results) == 1, results
    assert results.count("error:RuntimeError") == 7, results


@pytest.mark.asyncio
async def test_turn_transition_is_compare_and_swap_and_records_failure(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "turns.db")
    session = await store.ensure_session(None)
    turn = await store.begin_turn(
        session["id"],
        capability="chat",
        owner_id="worker-a",
        fencing_token=7,
    )

    assert (
        await store.transition_turn(
            turn["id"],
            "failed",
            expected_status="waiting_input",
            fencing_token=7,
            error="lost",
            failure_code="worker_lost",
        )
        is False
    )
    assert (
        await store.transition_turn(
            turn["id"],
            "failed",
            expected_status="running",
            fencing_token=7,
            error="lost",
            failure_code="worker_lost",
        )
        is True
    )

    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["failure_code"] == "worker_lost"
    assert persisted["state_version"] == 2


@pytest.mark.asyncio
async def test_turn_event_seq_is_idempotent_but_never_overwritten(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "turns.db")
    session = await store.ensure_session(None)
    turn = await store.begin_turn(session["id"], capability="chat")
    event = {"seq": 1, "type": "content", "content": "first"}

    assert (await store.append_events(turn["id"], [event]))[0]["content"] == "first"
    assert (await store.append_events(turn["id"], [event]))[0]["content"] == "first"
    with pytest.raises(ValueError, match="conflict"):
        await store.append_events(
            turn["id"],
            [{"seq": 1, "type": "content", "content": "replacement"}],
        )

    [persisted] = await store.get_events(turn["id"])
    assert persisted["content"] == "first"
