"""Handoff operations release their native SQLite connections."""

from __future__ import annotations

import sqlite3

import pytest

from deeptutor.multi_user import session_handoff


@pytest.mark.parametrize("operation", ["create", "exchange", "consume", "reject"])
def test_handoff_closes_connections(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: "test-secret")
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    connections = []
    connect = store._connect

    def observed_connect():
        connection = connect()
        connections.append(connection)
        return connection

    monkeypatch.setattr(store, "_connect", observed_connect)
    ticket = session_handoff.encrypt_ticket_payload({"host": "app.example", "exp": 220})
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=100,
    )
    if operation == "reject":
        with pytest.raises(session_handoff.HandoffRejected):
            store.exchange(code=record.code, public_host="other.example", now=101)
    elif operation in {"exchange", "consume"}:
        exchanged = store.exchange(code=record.code, public_host="app.example", now=101)
        if operation == "consume":
            assert (
                store.consume_ticket(ticket=exchanged, public_host="app.example", now=102)
                == exchanged
            )
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    store.db_path.rename(tmp_path / "released.sqlite3")
