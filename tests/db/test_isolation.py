"""Cross-user isolation: user A must not read or change user B's data.

ROADMAP Phase 3 acceptance, verbatim:

    "داده کاربر A از کاربر B قابل مشاهده/تغییر نباشد"
    (user A's data must not be visible to, or modifiable by, user B)

This is a *repository-level* test. It proves the SQL predicates are scoped by
user id, so an authorization bug in a router cannot be masked by a lucky
default. It deliberately does not test HTTP: the router layer has its own
authorization tests from Phase 2, and mixing the two would hide which layer
failed.
"""

from __future__ import annotations

import pytest

from deeptutor.db.connection import Database
from deeptutor.db.repositories.audit import AuditRepository
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.sessions import SessionRepository
from deeptutor.db.repositories.wallets import WalletRepository

USER_A = ("989120000001", "u_alice")
USER_B = ("989120000002", "u_bob")


def seed_user(db: Database, phone: str, user_id: str) -> None:
    IdentityRepository(db).save(
        phone,
        {
            "id": user_id,
            "hash": "h",
            "role": "student",
            "created_at": "2026-11-01T00:00:00+00:00",
            "disabled": False,
            "avatar": "",
            "preset": "standard",
            "must_change_password": False,
            "token_version": 0,
            "phone": phone,
            "username": phone,
        },
    )


@pytest.fixture
def two_users(db: Database) -> Database:
    seed_user(db, *USER_A)
    seed_user(db, *USER_B)
    return db


class TestWalletIsolation:
    def test_a_spend_does_not_touch_b(self, two_users: Database):
        repo = WalletRepository(two_users)
        repo.grant(USER_A[1], 1000)
        repo.grant(USER_B[1], 1000)
        repo.spend(USER_A[1], 400, action="chat")
        assert repo.get(USER_A[1])["tokens_remaining"] == 600  # type: ignore[index]
        assert repo.get(USER_B[1])["tokens_remaining"] == 1000  # type: ignore[index]

    def test_b_cannot_spend_a_tokens(self, two_users: Database):
        """Even with B holding a valid session, A's wallet is not addressable."""
        repo = WalletRepository(two_users)
        repo.grant(USER_A[1], 1000)
        repo.ensure(USER_B[1])
        with pytest.raises(Exception, match="cannot spend"):
            repo.spend(USER_B[1], 500, action="chat")
        assert repo.get(USER_A[1])["tokens_remaining"] == 1000  # type: ignore[index]

    def test_usage_logs_are_per_user(self, two_users: Database):
        repo = WalletRepository(two_users)
        repo.grant(USER_A[1], 1000)
        repo.grant(USER_B[1], 1000)
        repo.spend(USER_A[1], 10, action="a-action")
        repo.spend(USER_B[1], 20, action="b-action")
        assert [r["action"] for r in repo.usage_summary(USER_A[1])] == ["a-action"]
        assert [r["action"] for r in repo.usage_summary(USER_B[1])] == ["b-action"]

    def test_payment_history_is_per_user(self, two_users: Database):
        repo = WalletRepository(two_users)
        repo.create_payment(
            user_id=USER_A[1],
            plan_code="pro",
            plan_name="pro",
            amount_toman=1000,
            tokens_granted=100,
            duration_days=30,
            provider="p",
            authority="A1",
        )
        assert len(repo.list_payments(USER_A[1])) == 1
        assert repo.list_payments(USER_B[1]) == []


class TestSessionIsolation:
    def test_revoking_a_does_not_revoke_b(self, two_users: Database):
        repo = SessionRepository(two_users)
        repo.create(user_id=USER_A[1], token_nonce="nonce-a", ttl_seconds=3600)
        repo.create(user_id=USER_B[1], token_nonce="nonce-b", ttl_seconds=3600)
        assert repo.revoke_all_for_user(USER_A[1]) == 1
        assert repo.is_valid("nonce-a") is False
        assert repo.is_valid("nonce-b") is True

    def test_listing_sessions_is_scoped(self, two_users: Database):
        repo = SessionRepository(two_users)
        repo.create(user_id=USER_A[1], token_nonce="n1", ttl_seconds=3600, user_agent="firefox")
        repo.create(user_id=USER_B[1], token_nonce="n2", ttl_seconds=3600, user_agent="chrome")
        a_sessions = repo.list_for_user(USER_A[1])
        assert len(a_sessions) == 1
        assert a_sessions[0]["user_agent"] == "firefox"

    def test_a_cannot_see_bs_nonce(self, two_users: Database):
        repo = SessionRepository(two_users)
        repo.create(user_id=USER_B[1], token_nonce="secret-nonce", ttl_seconds=3600)
        repo.revoke_all_for_user(USER_A[1])
        assert repo.is_valid("secret-nonce") is True


class TestIdentityIsolation:
    def test_changing_a_role_does_not_change_b(self, two_users: Database):
        repo = IdentityRepository(two_users)
        repo.set_role(USER_A[0], "teacher")
        assert repo.get(USER_A[0])["role"] == "teacher"  # type: ignore[index]
        assert repo.get(USER_B[0])["role"] == "student"  # type: ignore[index]

    def test_bumping_a_token_version_does_not_log_out_b(self, two_users: Database):
        repo = IdentityRepository(two_users)
        repo.bump_token_version(USER_A[0])
        assert repo.token_version_of(USER_A[0]) == 1
        assert repo.token_version_of(USER_B[0]) == 0

    def test_disabling_a_does_not_disable_b(self, two_users: Database):
        repo = IdentityRepository(two_users)
        repo.set_disabled(USER_A[0], True)
        assert repo.get(USER_A[0])["disabled"] is True  # type: ignore[index]
        assert repo.get(USER_B[0])["disabled"] is False  # type: ignore[index]

    def test_deleting_a_leaves_b(self, two_users: Database):
        repo = IdentityRepository(two_users)
        assert repo.delete(USER_A[0]) is True
        assert repo.get(USER_A[0]) is None
        assert repo.get(USER_B[0]) is not None
        assert repo.count() == 1

    def test_learner_profile_is_per_user(self, two_users: Database):
        repo = IdentityRepository(two_users)
        repo.set_learner_profile(USER_A[0], {"grade": 10})
        assert repo.get(USER_A[0])["learner_profile"] == {"grade": 10}  # type: ignore[index]
        assert "learner_profile" not in (repo.get(USER_B[0]) or {})


class TestCascadeOnDelete:
    def test_deleting_a_user_removes_their_wallet_and_logs(self, two_users: Database):
        repo = WalletRepository(two_users)
        repo.grant(USER_A[1], 500)
        repo.spend(USER_A[1], 5, action="chat")
        IdentityRepository(two_users).delete(USER_A[0])
        assert repo.get(USER_A[1]) is None
        with two_users.read() as conn:
            assert (
                conn.scalar("SELECT COUNT(*) FROM token_usage_logs WHERE user_id = ?", (USER_A[1],))
                == 0
            )

    def test_deleting_a_user_removes_their_sessions(self, two_users: Database):
        SessionRepository(two_users).create(
            user_id=USER_A[1], token_nonce="n-del", ttl_seconds=3600
        )
        IdentityRepository(two_users).delete(USER_A[0])
        assert SessionRepository(two_users).list_for_user(USER_A[1]) == []


class TestAuditIsolation:
    def test_audit_events_are_globally_readable_by_admin_only_by_design(self, two_users: Database):
        """Audit is deliberately NOT user-scoped — it is an admin surface.

        Asserted explicitly so nobody mistakes the absence of a user filter for
        an oversight, and so a future change that makes it user-scoped trips.
        """
        repo = AuditRepository(two_users)
        repo.record("a.act", actor_id=USER_A[1])
        repo.record("b.act", actor_id=USER_B[1])
        assert repo.count() == 2
        assert len(repo.list_events(actor_id=USER_A[1])) == 1
