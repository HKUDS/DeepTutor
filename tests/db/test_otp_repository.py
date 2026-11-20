"""OTP persistence: single use, attempt limits, no plaintext at rest."""

from __future__ import annotations

import time

import pytest

from deeptutor.db.connection import Database
from deeptutor.db.repositories.otp import OtpRecord, OtpRepository

PHONE = "989121234567"
SALT = "0123456789abcdef0123456789abcdef"
CODE = "482913"


def make_record(**overrides) -> OtpRecord:
    now = time.time()
    values = {
        "phone": PHONE,
        "salt": SALT,
        "digest": "deadbeef" * 8,
        "expires_at": now + 120,
        "attempts": 0,
        "max_attempts": 5,
        "last_sent_at": now,
        "window_started_at": now,
        "sends_in_window": 1,
    }
    values.update(overrides)
    return OtpRecord(**values)


class TestStoreShape:
    def test_round_trip_returns_the_json_store_shape(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        store = repo.load_all()
        assert PHONE in store
        assert set(store[PHONE]) == {
            "salt",
            "digest",
            "expires_at",
            "attempts",
            "last_sent_at",
            "window_started_at",
            "sends_in_window",
        }

    def test_get_returns_a_typed_record(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record(attempts=2))
        record = repo.get(PHONE)
        assert record is not None
        assert record.attempts == 2

    def test_get_unknown_returns_none(self, db: Database):
        assert OtpRepository(db).get("980000000000") is None

    def test_upsert_replaces_the_existing_row(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record(attempts=1))
        repo.upsert(make_record(attempts=4, digest="cafebabe" * 8))
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded.attempts == 4

    def test_one_row_per_phone(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        repo.upsert(make_record(attempts=1))
        with db.read() as conn:
            assert conn.scalar("SELECT COUNT(*) FROM otp_codes") == 1


class TestNoPlaintext:
    def test_the_code_never_appears_in_the_table(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        with db.read() as conn:
            rows = conn.query("SELECT * FROM otp_codes").rows
        blob = str(rows)
        assert CODE not in blob

    def test_no_column_could_hold_a_plaintext_code(self, db: Database):
        """A schema fact, asserted so a future migration cannot add one quietly."""
        with db.read() as conn:
            columns = (
                {r["name"] for r in conn.query("PRAGMA table_info(otp_codes)").rows}
                if db.backend == "sqlite"
                else {
                    r["column_name"]
                    for r in conn.query(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'otp_codes'"
                    ).rows
                }
            )
        assert "code" not in columns
        assert "otp" not in columns
        assert {"salt", "digest"} <= columns


class TestConsume:
    def test_consume_deletes_the_row(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        assert repo.consume(PHONE, make_record().digest) is True
        assert repo.get(PHONE) is None

    def test_consume_with_a_wrong_digest_does_nothing(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        assert repo.consume(PHONE, "wrong") is False
        assert repo.get(PHONE) is not None

    def test_a_code_cannot_be_consumed_twice(self, db: Database):
        """Replay resistance: the second consume must fail, not succeed silently."""
        repo = OtpRepository(db)
        record = make_record()
        repo.upsert(record)
        assert repo.consume(PHONE, record.digest) is True
        assert repo.consume(PHONE, record.digest) is False

    def test_consume_unknown_phone_returns_false(self, db: Database):
        assert OtpRepository(db).consume("980000000000", "x") is False


class TestAttemptsAndPurge:
    def test_attempt_counter_persists(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        repo.record_attempt(PHONE, 3)
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded.attempts == 3

    def test_purge_expired_removes_only_expired(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record(phone="980000000001", expires_at=time.time() - 5))
        repo.upsert(make_record(phone="980000000002", expires_at=time.time() + 500))
        assert repo.purge_expired() == 1
        assert repo.get("980000000001") is None
        assert repo.get("980000000002") is not None

    def test_delete_removes_one_phone(self, db: Database):
        repo = OtpRepository(db)
        repo.upsert(make_record())
        assert repo.delete(PHONE) is True
        assert repo.delete(PHONE) is False


class TestBackfill:
    def test_backfill_copies_live_codes(self, db: Database):
        repo = OtpRepository(db)
        now = time.time()
        store = {
            PHONE: {
                "salt": SALT,
                "digest": "abc123",
                "expires_at": now + 60,
                "attempts": 1,
                "last_sent_at": now,
                "window_started_at": now,
                "sends_in_window": 2,
            }
        }
        assert repo.backfill(store) == 1
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded.digest == "abc123"
        assert loaded.attempts == 1

    def test_backfill_drops_expired_codes(self, db: Database):
        """An expired code has no value and carrying it forward only risks confusion."""
        repo = OtpRepository(db)
        store = {
            PHONE: {
                "salt": SALT,
                "digest": "abc",
                "expires_at": time.time() - 60,
                "attempts": 0,
                "last_sent_at": 0,
                "window_started_at": 0,
                "sends_in_window": 1,
            }
        }
        assert repo.backfill(store) == 0
        assert repo.get(PHONE) is None

    def test_backfill_skips_malformed_entries_without_aborting(self, db: Database):
        repo = OtpRepository(db)
        now = time.time()
        store = {
            "980000000001": {"salt": "s", "digest": "d", "expires_at": now + 60},
            "980000000002": {"nonsense": True},
        }
        assert repo.backfill(store) == 1
        assert repo.get("980000000001") is not None

    def test_backfill_is_idempotent(self, db: Database):
        repo = OtpRepository(db)
        store = {
            PHONE: {
                "salt": SALT,
                "digest": "abc",
                "expires_at": time.time() + 60,
                "attempts": 0,
                "last_sent_at": time.time(),
                "window_started_at": time.time(),
                "sends_in_window": 1,
            }
        }
        repo.backfill(store)
        repo.backfill(store)
        with db.read() as conn:
            assert conn.scalar("SELECT COUNT(*) FROM otp_codes") == 1
