"""Security state regression tests for public session handoff."""

from __future__ import annotations

import sqlite3

import pytest

from deeptutor.multi_user import session_handoff


def test_public_origin_is_https_and_host_bound() -> None:
    assert session_handoff.public_origin("https://APP.example/") == "https://app.example"
    assert session_handoff.public_origin("https://app.example:8443") == "https://app.example:8443"

    for raw in (
        "http://app.example",
        "https://app.example/chat",
        "https://user@app.example",
        "https://127.0.0.1",
        "https://192.168.1.10",
        "https://localhost",
    ):
        with pytest.raises(session_handoff.HandoffError):
            session_handoff.public_origin(raw)


def test_handoff_code_and_ticket_are_single_use(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: "test-secret")
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    ticket = session_handoff.encrypt_ticket_payload(
        {"mode": "builtin", "host": "app.example", "exp": 220},
        secret="test-secret",
    )
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=100,
    )

    with pytest.raises(session_handoff.HandoffRejected):
        store.exchange(code=record.code, public_host="other.example", now=101)
    exchanged = store.exchange(code=record.code, public_host="app.example", now=102)
    assert exchanged != ticket
    assert session_handoff.decrypt_ticket_payload(exchanged)["exp"] == 222
    with pytest.raises(session_handoff.HandoffRejected):
        store.exchange(code=record.code, public_host="app.example", now=103)

    with pytest.raises(session_handoff.HandoffRejected):
        store.consume_ticket(ticket=exchanged, public_host="other.example", now=104)
    assert store.consume_ticket(ticket=exchanged, public_host="app.example", now=105) == exchanged
    with pytest.raises(session_handoff.HandoffRejected):
        store.consume_ticket(ticket=exchanged, public_host="app.example", now=106)


def test_invalid_public_requests_cannot_exhaust_other_users_handoffs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: "test-secret")
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    ticket = session_handoff.encrypt_ticket_payload(
        {"mode": "builtin", "host": "app.example", "exp": 220},
        secret="test-secret",
    )
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=100,
    )

    for index in range(40):
        with pytest.raises(session_handoff.HandoffRejected):
            store.exchange(code=f"invalid-code-{index:032d}", public_host="app.example", now=101)
    exchanged = store.exchange(code=record.code, public_host="app.example", now=102)

    for index in range(40):
        with pytest.raises(session_handoff.HandoffRejected):
            store.consume_ticket(
                ticket=f"invalid-ticket-{index:032d}", public_host="app.example", now=103
            )
    assert store.consume_ticket(ticket=exchanged, public_host="app.example", now=104) == exchanged


def test_expired_code_is_rejected_and_rate_limited(tmp_path, monkeypatch) -> None:
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    ticket = session_handoff.encrypt_ticket_payload(
        {"mode": "builtin", "host": "app.example", "exp": 150},
        secret="test-secret",
    )
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=100,
        code_lifetime=100,
    )
    with pytest.raises(session_handoff.HandoffRejected):
        store.exchange(code=record.code, public_host="app.example", now=201)

    monkeypatch.setattr(session_handoff, "CREATE_RATE_LIMIT", (1, 60))
    limited = session_handoff.SessionHandoffStore(tmp_path / "limited.sqlite3")
    ticket = session_handoff.encrypt_ticket_payload({}, secret="test-secret")
    limited.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=300,
        rate_key="alice",
    )
    with pytest.raises(session_handoff.HandoffRateLimited):
        limited.create(
            encrypted_ticket=ticket + "different",
            ticket_hash=session_handoff.hash_secret(ticket + "different"),
            public_host="app.example",
            now=301,
            rate_key="alice",
        )


def test_database_never_stores_plaintext_code_ticket_or_bearer(tmp_path) -> None:
    store = session_handoff.SessionHandoffStore(tmp_path / "handoff.sqlite3")
    bearer = "pb-bearer-token-that-must-not-persist"
    ticket = session_handoff.encrypt_ticket_payload(
        {"mode": "pocketbase", "token": bearer, "host": "app.example", "exp": 220},
        secret="test-secret",
    )
    record = store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host="app.example",
        now=100,
    )

    connection = sqlite3.connect(store.db_path)
    persisted = " ".join(
        str(value) for row in connection.execute("SELECT * FROM handoff_records") for value in row
    )
    connection.close()

    assert record.code not in persisted
    assert bearer not in persisted


def test_invalid_encrypted_ticket_is_a_controlled_rejection() -> None:
    with pytest.raises(session_handoff.HandoffRejected):
        session_handoff.decrypt_ticket_payload("not-a-valid-jwe", secret="test-secret")
