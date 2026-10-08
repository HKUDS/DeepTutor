"""Web synchronization repositories release real SQLite connection handles."""

from pathlib import Path
import sqlite3
import time
from typing import Any

import pytest

from deeptutor.services.web_source.repository import SQLiteWebSourceSyncRepository


@pytest.mark.parametrize(
    "operation",
    [
        "initialize",
        "reconcile",
        "ensure",
        "recover",
        "list",
        "due",
        "claim",
        "renew",
        "success",
        "failure",
        "interrupted",
        "cancelled",
        "request_cancel",
        "delete",
        "retry",
        "get",
        "pairings",
        "list_pairings",
        "delete_pairings",
        "pairing_failure",
    ],
)
def test_web_repository_closes_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Successful and failing calls must close handles independently of collection."""
    connections: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def track_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connect)
    try:
        repo = SQLiteWebSourceSyncRepository(tmp_path / "web.sqlite3")
        key = ("owner", "knowledge", "source")
        job = repo.ensure_source(key)
        if operation == "reconcile":
            repo.reconcile_sources({key})
        elif operation == "ensure":
            repo.ensure_source(key)
        elif operation == "recover":
            repo.recover_interrupted("runner")
        elif operation == "list":
            assert len(repo.list_jobs(*key[:2])) == 1
        elif operation == "due":
            assert len(repo.due_jobs()) == 1
        elif operation in {"claim", "renew", "success", "failure", "interrupted", "cancelled"}:
            claimed = repo.claim(
                job, runner_id="runner", lease_until_ms=int(time.time() * 1000) + 60000
            )
            assert claimed is not None
            if operation == "renew":
                assert repo.renew_lease(claimed, int(time.time() * 1000) + 60000)
            elif operation == "success":
                repo.mark_success(claimed, 0)
            elif operation == "failure":
                repo.mark_failure(claimed, error="failed", next_run_at_ms=0)
            elif operation == "interrupted":
                repo.mark_interrupted(claimed)
            elif operation == "cancelled":
                repo.mark_cancelled(claimed)
        elif operation == "request_cancel":
            assert repo.request_cancel(key)
        elif operation == "delete":
            assert repo.delete(key)
        elif operation == "retry":
            assert repo.request_cancel(key)
            assert repo.retry(key) is not None
        elif operation == "get":
            assert repo.get(key) is not None
        elif operation == "pairings":
            assert repo.record_pairings(*key, []) == []
        elif operation == "list_pairings":
            assert repo.list_pairings(*key) == []
        elif operation == "delete_pairings":
            assert repo.delete_pairings(*key) == 0
        elif operation == "pairing_failure":
            with pytest.raises(KeyError, match="pairing_id"):
                repo.record_pairings(*key, [{}])
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        repo.path.replace(tmp_path / "moved.sqlite3")
    finally:
        for connection in connections:
            connection.close()
