from __future__ import annotations

import sqlite3

import pytest

from deeptutor.multi_user import byok_usage


def test_byok_usage_is_idempotent_and_redacted(tmp_path, monkeypatch):
    db_path = tmp_path / "byok-usage.sqlite3"
    monkeypatch.setenv("DEEPTUTOR_BYOK_USAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(
        byok_usage,
        "load_policy",
        lambda: {
            "limits": {
                "byok_requests_per_minute": 10,
                "max_single_request_tokens": 1000,
            }
        },
    )

    lease = byok_usage.start_byok_usage(
        service="llm",
        user_id="u_alice",
        profile_id="p_profile",
        provider="openai",
        model="gpt-test",
        estimated_units=100,
    )
    lease.finalize(80)
    lease.finalize(900, status="failed")

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT user_id, profile_id, provider, model, estimated_units, reported_units, status FROM byok_usage"
        ).fetchone()
    assert row == ("u_alice", "p_profile", "openai", "gpt-test", 100, 80, "success")


def test_byok_usage_enforces_request_and_token_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_BYOK_USAGE_DB_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setattr(
        byok_usage,
        "load_policy",
        lambda: {
            "limits": {
                "byok_requests_per_minute": 1,
                "max_single_request_tokens": 100,
            }
        },
    )

    with pytest.raises(byok_usage.ByokUsageLimitExceeded, match="safety limit"):
        byok_usage.start_byok_usage(
            service="llm",
            user_id="u_alice",
            profile_id="p_profile",
            provider="openai",
            model="gpt-test",
            estimated_units=101,
        )

    lease = byok_usage.start_byok_usage(
        service="llm",
        user_id="u_alice",
        profile_id="p_profile",
        provider="openai",
        model="gpt-test",
        estimated_units=100,
    )
    with pytest.raises(byok_usage.ByokUsageLimitExceeded, match="rate limit"):
        byok_usage.start_byok_usage(
            service="llm",
            user_id="u_alice",
            profile_id="p_profile",
            provider="openai",
            model="gpt-test",
            estimated_units=1,
        )
    lease.release()


def test_byok_usage_schema_indexes_expiration_cleanup(tmp_path):
    connection = byok_usage._connect(tmp_path / "usage.sqlite3")
    try:
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('byok_usage')")}
    finally:
        connection.close()

    assert "idx_byok_usage_created_at" in indexes


def test_byok_usage_connect_closes_connection_when_setup_fails(tmp_path, monkeypatch):
    class FailingConnection:
        row_factory = None

        def __init__(self) -> None:
            self.closed = False

        def execute(self, _statement: str) -> None:
            raise sqlite3.OperationalError("broken connection")

        def close(self) -> None:
            self.closed = True

    connection = FailingConnection()
    monkeypatch.setattr(byok_usage.sqlite3, "connect", lambda *_args, **_kwargs: connection)

    with pytest.raises(byok_usage.ByokUsageUnavailable, match="ledger is unavailable"):
        byok_usage._connect(tmp_path / "usage.sqlite3")

    assert connection.closed is True
