"""Partner runtime status operations release their SQLite connections."""

import sqlite3

import pytest

from deeptutor.services.partners.runtime_status import PartnerRuntimeStatusRepository


@pytest.mark.parametrize("operation", ["initialize", "set", "get", "list", "delete"])
def test_status_operations_close_native_connections(tmp_path, monkeypatch, operation):
    path = tmp_path / "status.sqlite3"
    repository = PartnerRuntimeStatusRepository(path)
    repository.set("partner", owner_id="owner", running=True, state="running")
    connect = sqlite3.connect
    connections = []

    def track(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track)
    if operation == "initialize":
        PartnerRuntimeStatusRepository(path)
    elif operation == "set":
        repository.set("partner", owner_id="owner", running=False, state="stopped")
    elif operation == "get":
        assert repository.get("partner")["running"] is True
    elif operation == "list":
        assert "partner" in repository.list()
    else:
        repository.delete("partner")
    assert connections
    try:
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
    finally:
        for connection in connections:
            connection.close()

    with connect(path) as observer:
        row = observer.execute("SELECT running FROM partner_runtime_status").fetchone()
    observer.close()
    expected = {"set": (0,), "delete": None}.get(operation, (1,))
    assert row == expected
