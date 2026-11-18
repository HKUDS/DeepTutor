"""Reserve, settle, refund: the money invariants.

A media job commits money before it produces anything, so the accounting is the
part that must be right even when everything else fails. These tests are written
against the invariants a finance person would state, not against the functions.
"""

from __future__ import annotations

import threading

import pytest

from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import accounting as A


def _user(db, user_id="u1", tokens=1000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=tokens)
    return user_id


def _wallet(db, user_id="u1"):
    return WalletRepository(db).get(user_id)


# ---------------------------------------------------------------------------
# The core invariant
# ---------------------------------------------------------------------------


def test_a_reservation_does_not_move_the_balance(db):
    """A hold is not a charge. The wallet's own invariant forbids faking it."""
    _user(db, "u1", tokens=1000)
    A.reserve(db, user_id="u1", tokens=400)

    assert _wallet(db, "u1")["tokens_remaining"] == 1000
    assert _wallet(db, "u1")["tokens_used"] == 0
    assert A.open_holds(db, "u1") == 400
    assert A.available_tokens(db, "u1") == 600


def test_available_is_remaining_minus_open_holds(db):
    _user(db, "u1", tokens=1000)
    A.reserve(db, user_id="u1", tokens=300)
    A.reserve(db, user_id="u1", tokens=200)

    assert A.available_tokens(db, "u1") == 500


def test_a_reservation_beyond_the_balance_is_refused(db):
    _user(db, "u1", tokens=100)
    with pytest.raises(A.QuotaExceeded):
        A.reserve(db, user_id="u1", tokens=200)


def test_a_second_reservation_cannot_overspend_the_same_tokens(db):
    """The bug a check-then-insert would produce, stated as a test."""
    _user(db, "u1", tokens=500)
    A.reserve(db, user_id="u1", tokens=400)
    with pytest.raises(A.QuotaExceeded):
        A.reserve(db, user_id="u1", tokens=400)


def test_a_user_with_no_wallet_cannot_reserve(db):
    """No wallet is zero, not unlimited: an unmetered path is a free tier."""
    IdentityRepository(db).save("nowallet", {"id": "nowallet", "hash": "x", "role": "user"})
    assert A.available_tokens(db, "nowallet") == 0
    with pytest.raises(A.QuotaExceeded):
        A.reserve(db, user_id="nowallet", tokens=1)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def test_settling_charges_the_actual_not_the_estimate(db):
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    A.settle(db, reservation_id=reservation["id"], actual_tokens=150)

    assert _wallet(db, "u1")["tokens_remaining"] == 850
    assert _wallet(db, "u1")["tokens_used"] == 150
    assert A.open_holds(db, "u1") == 0


def test_settling_for_zero_releases_the_hold_without_charging(db):
    """The cache-hit path: the work cost nothing, so the user pays nothing."""
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    result = A.settle(db, reservation_id=reservation["id"], actual_tokens=0, charge=False)

    assert result["state"] == A.SETTLED
    assert _wallet(db, "u1")["tokens_remaining"] == 1000
    assert A.open_holds(db, "u1") == 0


def test_settling_twice_does_not_double_charge(db):
    """A retried job settles again; that must be a no-op, not a second bill."""
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    A.settle(db, reservation_id=reservation["id"], actual_tokens=200)
    A.settle(db, reservation_id=reservation["id"], actual_tokens=200)

    assert _wallet(db, "u1")["tokens_remaining"] == 800


def test_settling_more_than_the_balance_charges_nothing(db):
    """If the balance moved during the job, the settle must not go negative."""
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    WalletRepository(db).spend("u1", 900, action="elsewhere")

    with pytest.raises(A.QuotaExceeded):
        A.settle(db, reservation_id=reservation["id"], actual_tokens=400)

    assert _wallet(db, "u1")["tokens_remaining"] == 100
    assert A.open_holds(db, "u1") == 400, "a failed settle must leave the hold intact"


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------


def test_refunding_releases_the_hold(db):
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    A.refund(db, reservation_id=reservation["id"])

    assert A.available_tokens(db, "u1") == 1000
    assert A.open_holds(db, "u1") == 0


def test_refunding_twice_is_idempotent(db):
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    first = A.refund(db, reservation_id=reservation["id"])
    second = A.refund(db, reservation_id=reservation["id"])

    assert first["state"] == second["state"] == A.REFUNDED
    assert A.available_tokens(db, "u1") == 1000


def test_a_settled_reservation_cannot_be_refunded_away(db):
    """Money that genuinely moved is not silently reversed.

    Crediting it back would give the user tokens they may already have spent
    elsewhere, and the ledger would no longer reconstruct the balance.
    """
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    A.settle(db, reservation_id=reservation["id"], actual_tokens=300)

    result = A.refund(db, reservation_id=reservation["id"])

    assert result["state"] == A.SETTLED
    assert _wallet(db, "u1")["tokens_remaining"] == 700


def test_a_refunded_reservation_cannot_be_settled(db):
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=400)
    A.refund(db, reservation_id=reservation["id"])

    with pytest.raises(A.StudioError) as exc:
        A.settle(db, reservation_id=reservation["id"], actual_tokens=100)
    assert exc.value.rule == "reservation_closed"
    assert _wallet(db, "u1")["tokens_remaining"] == 1000


# ---------------------------------------------------------------------------
# Job binding
# ---------------------------------------------------------------------------


def test_a_reservation_is_findable_by_its_job(db):
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=100)
    A.attach(db, reservation_id=reservation["id"], job_id="job_1")

    found = A.reservation_for_job(db, "job_1")
    assert found is not None and found["id"] == reservation["id"]


def test_a_closed_reservation_cannot_be_attached(db):
    _user(db, "u1", tokens=1000)
    reservation = A.reserve(db, user_id="u1", tokens=100)
    A.refund(db, reservation_id=reservation["id"])

    with pytest.raises(A.StudioError) as exc:
        A.attach(db, reservation_id=reservation["id"], job_id="job_1")
    assert exc.value.rule == "reservation_closed"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_the_balance_is_never_promised_twice(db):
    """The invariant, stated so it does not depend on thread scheduling.

    An earlier version of this test used threads and passed even with the
    atomicity deliberately broken, because SQLite serialises writers and the
    interleaving never happened. A test that cannot fail is not evidence, so
    this asserts the property directly: after *any* sequence of reserve calls,
    the open holds never exceed the balance, and every refusal is a refusal
    rather than an over-promise.
    """
    _user(db, "u1", tokens=500)
    granted: list[tuple] = []
    refused = 0
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def attempt() -> None:
        nonlocal refused
        barrier.wait(timeout=10)
        try:
            row = A.reserve(db, user_id="u1", tokens=200)
        except A.QuotaExceeded:
            with lock:
                refused += 1
        except Exception as exc:  # noqa: BLE001
            with lock:
                granted.append(("err", f"{type(exc).__name__}: {exc}"))
        else:
            with lock:
                granted.append(("ok", row["id"]))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    errors = [row for row in granted if row[0] == "err"]
    assert not errors, f"reservations raised: {errors}"
    assert len(granted) <= 2, f"over-promised the balance: {len(granted)} grants"
    assert refused >= 6, "the rest must be refused, not silently accepted"
    assert A.open_holds(db, "u1") == 200 * len(granted)
    assert A.open_holds(db, "u1") <= 500


def test_reserve_ignores_a_callers_cached_availability(db, monkeypatch):
    """The TOCTOU the threaded test could not provoke reliably.

    SQLite serialises writers, so eight threads never actually interleave and
    the race stays hidden -- an earlier version of this test passed even with
    the atomicity deliberately broken, which makes it worthless as evidence.

    So the stale read is simulated instead of raced: ``available_tokens`` is
    patched to report a generous figure. A correct ``reserve`` never consults
    it -- it recomputes inside its own transaction -- so the second reservation
    is still refused. A ``reserve`` that trusts any figure computed outside its
    transaction grants both and this fails.
    """
    _user(db, "u1", tokens=500)
    A.reserve(db, user_id="u1", tokens=400)

    monkeypatch.setattr(A, "available_tokens", lambda *a, **k: 10_000)

    with pytest.raises(A.QuotaExceeded):
        A.reserve(db, user_id="u1", tokens=400)

    assert A.open_holds(db, "u1") == 400
