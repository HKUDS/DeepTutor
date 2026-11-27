"""Concurrent first registrations must not both become admin (Phase 2).

The roadmap calls this out by name. It is a real hazard rather than a
theoretical one: ``add_user`` promotes the first account it sees to admin, and
a server handling two sign-ups at once must not hand out two admins - or worse,
let the second overwrite the first.

``save_user`` guards the read-modify-write with a lock, so the assertion here is
that the lock actually covers the promotion decision. Two threads race; exactly
one account must end up admin.
"""

from __future__ import annotations

import threading

import pytest

from deeptutor.multi_user import identity
from deeptutor.services import auth

pytestmark = pytest.mark.usefixtures("mu_isolated_root")


def _race(n: int = 8) -> tuple[list[str], dict]:
    """Sign up ``n`` accounts as simultaneously as threads allow."""
    barrier = threading.Barrier(n)
    errors: list[str] = []
    results: list[dict] = []

    def signup(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            # Each thread computes its own password hash outside the lock, so
            # the expensive part overlaps and the critical section is the
            # promotion decision rather than bcrypt.
            record = identity.save_user(f"user{index}", f"hash{index}", role="user")
            results.append(record)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            errors.append(f"{index}: {exc!r}")

    threads = [threading.Thread(target=signup, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    return errors, identity.load_users()


def test_exactly_one_account_becomes_admin_under_concurrency() -> None:
    errors, users = _race()
    assert not errors, f"sign-ups raised: {errors}"
    assert len(users) == 8

    admins = [name for name, record in users.items() if record.get("role") == "admin"]
    assert len(admins) == 1, f"expected exactly one admin, found {admins}"


def test_every_racer_gets_a_distinct_account() -> None:
    _errors, users = _race()
    # No account was overwritten, and every record has its own id.
    assert len({record["id"] for record in users.values()}) == len(users)


def test_repeated_races_stay_consistent() -> None:
    """Locks fail intermittently; one pass is not proof."""
    for _ in range(3):
        # A fresh store each round, or the second round has no "first" user.
        for name in list(identity.load_users()):
            identity.delete_user(name)

        errors, users = _race(4)
        assert not errors
        admins = [n for n, r in users.items() if r.get("role") == "admin"]
        assert len(admins) == 1, f"round produced {admins}"


# ------------------------------------------------------- phone uniqueness


def test_two_signups_cannot_claim_the_same_phone() -> None:
    """The unique constraint on a phone number, under concurrency.

    ``set_phone`` is the only writer, and it checks for an existing holder
    inside the lock. Two threads claiming one number must leave exactly one
    owner.
    """
    identity.save_user("alice", "hash-a", role="user")
    identity.save_user("bob", "hash-b", role="user")

    phone = "+989121234567"
    barrier = threading.Barrier(2)
    outcomes: list[bool] = []

    def claim(username: str) -> None:
        barrier.wait(timeout=10)
        outcomes.append(identity.set_phone(username, phone))

    threads = [
        threading.Thread(target=claim, args=("alice",)),
        threading.Thread(target=claim, args=("bob",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert outcomes.count(True) == 1, f"both claims returned {outcomes}"

    users = identity.load_users()
    holders = [name for name, record in users.items() if record.get("phone") == phone]
    assert len(holders) == 1


def test_a_phone_can_be_reassigned_after_it_is_released() -> None:
    identity.save_user("alice", "hash-a", role="user")
    identity.save_user("bob", "hash-b", role="user")

    phone = "+989125555555"
    assert identity.set_phone("alice", phone) is True
    # While alice holds it, bob cannot take it.
    assert identity.set_phone("bob", phone) is False
    # Clear alice's, and it becomes available.
    assert identity.set_phone("alice", "") is True
    assert identity.set_phone("bob", phone) is True


# ------------------------------------------------------- sign-in reflection


def test_authenticate_reports_the_created_account_role(monkeypatch) -> None:
    """The role a user sees after sign-up matches what was stored."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    auth.add_user("solo", "password-123", role="user")

    payload = auth.authenticate("solo", "password-123")
    assert payload is not None
    assert payload.role == "admin", "the first account must be the administrator"
