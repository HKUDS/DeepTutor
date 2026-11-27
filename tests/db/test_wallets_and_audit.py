"""Wallet, payment and audit: the money invariants.

ROADMAP Phase 3 acceptance: "transaction and unique constraints for
wallet/reservations/account identity". These tests check the *database* refuses
to hold an inconsistent wallet, not merely that the Python refuses to write one.
"""

from __future__ import annotations

import threading

import pytest

from deeptutor.db.connection import Database, DatabaseError
from deeptutor.db.repositories.audit import AuditRepository, redact
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import (
    InsufficientBalance,
    WalletRepository,
    WalletRepositoryError,
)

PHONE = "989121234567"
USER_ID = f"u_{PHONE}"


@pytest.fixture
def seeded(db: Database) -> Database:
    IdentityRepository(db).save(
        PHONE,
        {
            "id": USER_ID,
            "hash": "h",
            "role": "student",
            "created_at": "2026-11-01T00:00:00+00:00",
            "disabled": False,
            "avatar": "",
            "preset": "standard",
            "must_change_password": False,
            "token_version": 0,
            "phone": PHONE,
            "username": PHONE,
        },
    )
    return db


class TestWalletBasics:
    def test_ensure_creates_a_zero_wallet(self, seeded: Database):
        wallet = WalletRepository(seeded).ensure(USER_ID)
        assert wallet["tokens_total"] == 0
        assert wallet["tokens_remaining"] == 0
        assert wallet["storage_used_bytes"] == 0

    def test_ensure_is_idempotent(self, seeded: Database):
        repo = WalletRepository(seeded)
        first = repo.ensure(USER_ID)
        second = repo.ensure(USER_ID)
        assert first["user_id"] == second["user_id"]

    def test_grant_increases_balance(self, seeded: Database):
        repo = WalletRepository(seeded)
        wallet = repo.grant(USER_ID, 15000, duration_days=7, plan_code="trial")
        assert wallet["tokens_total"] == 15000
        assert wallet["tokens_remaining"] == 15000
        assert wallet["plan_code"] == "trial"

    def test_repeated_grants_accumulate(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 100)
        wallet = repo.grant(USER_ID, 250)
        assert wallet["tokens_total"] == 350
        assert wallet["tokens_remaining"] == 350

    def test_negative_grant_is_rejected(self, seeded: Database):
        with pytest.raises(WalletRepositoryError, match="cannot be negative"):
            WalletRepository(seeded).grant(USER_ID, -5)


class TestSpend:
    def test_spend_reduces_both_used_and_remaining(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 1000)
        wallet = repo.spend(USER_ID, 300, action="chat", prompt_tokens=200, completion_tokens=100)
        assert wallet["tokens_used"] == 300
        assert wallet["tokens_remaining"] == 700

    def test_spend_is_logged(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 1000)
        repo.spend(USER_ID, 100, action="summarize", book_id=4)
        usage = repo.usage_summary(USER_ID)
        assert len(usage) == 1
        assert usage[0]["action"] == "summarize"

    def test_overspend_raises_instead_of_going_negative(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 100)
        with pytest.raises(InsufficientBalance):
            repo.spend(USER_ID, 101, action="chat")
        assert repo.get(USER_ID)["tokens_remaining"] == 100  # type: ignore[index]

    def test_zero_spend_is_allowed_and_logged(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 10)
        wallet = repo.spend(USER_ID, 0, action="free-lookup")
        assert wallet["tokens_used"] == 0

    def test_spend_without_a_wallet_is_an_error(self, seeded: Database):
        with pytest.raises(WalletRepositoryError, match="no wallet"):
            WalletRepository(seeded).spend(USER_ID, 1, action="chat")

    def test_concurrent_spends_cannot_overdraw(self, seeded: Database):
        """The conditional UPDATE, not the Python check, is what holds the line."""
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 100)
        outcomes: list[str] = []
        barrier = threading.Barrier(10)

        def attempt() -> None:
            barrier.wait(timeout=10)
            try:
                repo.spend(USER_ID, 30, action="chat")
                outcomes.append("ok")
            except InsufficientBalance:
                outcomes.append("refused")
            except DatabaseError:
                # SQLite serialises writers and can report "database is locked"
                # under heavy contention; that is still a refusal, not a spend.
                outcomes.append("refused")

        threads = [threading.Thread(target=attempt) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        wallet = repo.get(USER_ID)
        assert wallet is not None
        spent = int(wallet["tokens_used"])
        assert spent <= 100, "wallet was overdrawn"
        assert spent == outcomes.count("ok") * 30
        assert int(wallet["tokens_remaining"]) == 100 - spent


class TestSchemaInvariants:
    def test_database_refuses_an_inconsistent_wallet_row(self, seeded: Database):
        """The CHECK constraint is the last line of defence, not the code."""
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 100)
        with pytest.raises(DatabaseError):
            with seeded.transaction() as conn:
                conn.execute(
                    "UPDATE user_wallets SET tokens_remaining = 9999 WHERE user_id = ?",
                    (USER_ID,),
                )

    def test_database_refuses_negative_balance(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 100)
        with pytest.raises(DatabaseError):
            with seeded.transaction() as conn:
                conn.execute(
                    "UPDATE user_wallets SET tokens_remaining = -1, tokens_used = 101 "
                    "WHERE user_id = ?",
                    (USER_ID,),
                )

    def test_billing_settings_is_a_single_row(self, seeded: Database):
        with seeded.transaction() as conn:
            conn.execute("INSERT INTO billing_settings (id, updated_at) VALUES (1, '2026-01-01')")
        with pytest.raises(DatabaseError):
            with seeded.transaction() as conn:
                conn.execute(
                    "INSERT INTO billing_settings (id, updated_at) VALUES (2, '2026-01-01')"
                )


class TestStorageQuota:
    def test_usage_tracks_uploads_and_deletes(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.ensure(USER_ID)
        repo.add_storage(USER_ID, 500)
        assert repo.get(USER_ID)["storage_used_bytes"] == 500  # type: ignore[index]
        repo.add_storage(USER_ID, -200)
        assert repo.get(USER_ID)["storage_used_bytes"] == 300  # type: ignore[index]

    def test_delete_cannot_drive_usage_negative(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.ensure(USER_ID)
        repo.add_storage(USER_ID, -500)
        assert repo.get(USER_ID)["storage_used_bytes"] == 0  # type: ignore[index]

    def test_quota_is_enforced(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.grant(USER_ID, 1, storage_quota_bytes=1000)
        with pytest.raises(WalletRepositoryError, match="quota exceeded"):
            repo.add_storage(USER_ID, 1001)


class TestPayments:
    def _payment(self, repo: WalletRepository, **overrides) -> dict:
        kwargs = {
            "user_id": USER_ID,
            "plan_code": "pro",
            "plan_name": "حرفه‌ای",
            "amount_toman": 99000,
            "tokens_granted": 50000,
            "duration_days": 30,
            "provider": "zarinpal",
            "authority": "A0000000000000000000000000000001",
        }
        kwargs.update(overrides)
        return repo.create_payment(**kwargs)

    def test_creates_a_pending_payment(self, seeded: Database):
        payment = self._payment(WalletRepository(seeded))
        assert payment["status"] == "pending"
        assert payment["amount_toman"] == 99000

    def test_same_authority_returns_the_same_payment(self, seeded: Database):
        repo = WalletRepository(seeded)
        first = self._payment(repo)
        second = self._payment(repo)
        assert first["id"] == second["id"]
        assert len(repo.list_payments(USER_ID)) == 1

    def test_settle_grants_the_quota_once(self, seeded: Database):
        repo = WalletRepository(seeded)
        repo.ensure(USER_ID)
        self._payment(repo)
        granted, payment = repo.settle_payment(
            provider="zarinpal", authority="A0000000000000000000000000000001", ref_id="12345"
        )
        assert granted is True
        assert payment is not None and payment["status"] == "paid"
        assert repo.get(USER_ID)["tokens_remaining"] == 50000  # type: ignore[index]

    def test_replayed_callback_does_not_grant_twice(self, seeded: Database):
        """The whole point of the unique authority: a gateway retry is harmless."""
        repo = WalletRepository(seeded)
        repo.ensure(USER_ID)
        self._payment(repo)
        repo.settle_payment(provider="zarinpal", authority="A0000000000000000000000000000001")
        granted, _ = repo.settle_payment(
            provider="zarinpal", authority="A0000000000000000000000000000001"
        )
        assert granted is False
        assert repo.get(USER_ID)["tokens_remaining"] == 50000  # type: ignore[index]

    def test_settling_an_unknown_authority_is_a_no_op(self, seeded: Database):
        granted, payment = WalletRepository(seeded).settle_payment(
            provider="zarinpal", authority="nope"
        )
        assert granted is False
        assert payment is None

    def test_status_is_constrained(self, seeded: Database):
        payment = self._payment(WalletRepository(seeded))
        with pytest.raises(DatabaseError):
            with seeded.transaction() as conn:
                conn.execute(
                    "UPDATE payment_transactions SET status = 'teleported' WHERE id = ?",
                    (payment["id"],),
                )


class TestAudit:
    def test_records_and_lists_events(self, db: Database):
        repo = AuditRepository(db)
        repo.record("user.disabled", actor_id="u_admin", target_type="user", target_id="u_x")
        events = repo.list_events()
        assert len(events) == 1
        assert events[0]["action"] == "user.disabled"
        assert events[0]["outcome"] == "ok"

    def test_detail_is_json_round_tripped(self, db: Database):
        repo = AuditRepository(db)
        repo.record("plan.changed", detail={"from": "trial", "to": "pro", "count": 3})
        events = repo.list_events()
        assert events[0]["detail"] == {"from": "trial", "to": "pro", "count": 3}

    def test_filters(self, db: Database):
        repo = AuditRepository(db)
        repo.record("a.one", actor_id="u1")
        repo.record("b.two", actor_id="u2")
        assert len(repo.list_events(action="a.one")) == 1
        assert len(repo.list_events(actor_id="u2")) == 1

    def test_count(self, db: Database):
        repo = AuditRepository(db)
        repo.record("x")
        repo.record("y")
        assert repo.count() == 2


class TestRedaction:
    @pytest.mark.parametrize(
        "key",
        ["password", "password_hash", "hash", "code", "otp", "token", "secret", "api_key"],
    )
    def test_secret_keys_are_masked(self, key):
        assert redact({key: "super-secret"})[key] == "***"

    def test_nested_secrets_are_masked(self):
        payload = {"user": {"password": "hunter2", "name": "ali"}}
        assert redact(payload)["user"]["password"] == "***"
        assert redact(payload)["user"]["name"] == "ali"

    def test_phone_numbers_in_strings_are_masked(self):
        assert "0912***67" in redact("login from 09121234567")

    def test_lists_are_handled(self):
        assert redact([{"token": "t"}]) == [{"token": "***"}]

    def test_none_and_scalars_pass_through(self):
        assert redact(None) is None
        assert redact(42) == 42

    def test_audit_row_never_stores_a_raw_secret(self, db: Database):
        """The end-to-end guarantee, not just the helper's unit behaviour."""
        repo = AuditRepository(db)
        repo.record("login.attempt", detail={"password": "hunter2", "otp_code": "123456"})
        events = repo.list_events()
        blob = str(events[0]["detail"])
        assert "hunter2" not in blob
        assert "123456" not in blob
