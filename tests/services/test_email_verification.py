from __future__ import annotations

import sqlite3

import pytest

from deeptutor.services import email_verification


@pytest.fixture
def verification_store(tmp_path, monkeypatch):
    from deeptutor.multi_user import identity
    from deeptutor.services import auth as auth_service

    auth_dir = tmp_path / "data" / "system" / "auth"
    monkeypatch.setattr(identity, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-verification-secret")
    monkeypatch.setattr(
        email_verification,
        "load_auth_settings",
        lambda: {
            "verification_code_ttl_minutes": 10,
            "verification_resend_cooldown_seconds": 60,
            "verification_max_attempts": 5,
            "verification_max_per_email_hour": 5,
            "verification_max_per_ip_hour": 30,
        },
    )
    return auth_dir


def test_code_is_hashed_and_is_one_time(verification_store) -> None:
    challenge = email_verification.issue_challenge(
        "User@example.com", "$2b$12$hash", "127.0.0.1"
    )

    db = verification_store / "email_verification.sqlite3"
    with sqlite3.connect(db) as connection:
        row = connection.execute(
            "SELECT email, password_hash, code_digest FROM pending_registrations"
        ).fetchone()
    assert row[0] == "user@example.com"
    assert row[1] == "$2b$12$hash"
    assert row[2] != challenge.code
    assert len(row[2]) == 64

    assert email_verification.consume_challenge(challenge.email, "000000") is None
    assert email_verification.consume_challenge(challenge.email, challenge.code) == "$2b$12$hash"
    assert email_verification.consume_challenge(challenge.email, challenge.code) is None


def test_wrong_codes_eventually_invalidate_challenge(verification_store) -> None:
    challenge = email_verification.issue_challenge("user@example.com", "hash", "127.0.0.1")

    for _ in range(5):
        assert email_verification.consume_challenge(challenge.email, "111111") is None

    assert email_verification.consume_challenge(challenge.email, challenge.code) is None


def test_expired_code_is_rejected(verification_store, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(email_verification.time, "time", lambda: clock[0])
    challenge = email_verification.issue_challenge("user@example.com", "hash", "127.0.0.1")

    clock[0] += 10 * 60 + 1
    assert email_verification.consume_challenge(challenge.email, challenge.code) is None


def test_resend_cooldown_is_persistent(verification_store) -> None:
    email_verification.issue_challenge("user@example.com", "hash", "127.0.0.1")

    with pytest.raises(email_verification.VerificationCooldown):
        email_verification.check_registration_rate_limit("user@example.com", "127.0.0.1")
