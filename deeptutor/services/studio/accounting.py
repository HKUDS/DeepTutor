"""Reserve, settle and refund the cost of a media job.

Why this is not just ``WalletRepository.spend``
----------------------------------------------
Chat spends tokens as it generates them: the model returns, the tokens are
known, the charge is written. A media job is the opposite shape -- the cost is
unknown at submit, the work takes minutes, and it can be cancelled or fail after
the provider has already been paid.

Charging at submit makes a cancelled job cost money nobody received. Charging at
the end lets a broken queue run up an unbounded bill with nothing recorded while
it happens. So the model here is an authorisation, not a purchase:

* **reserve** holds an estimate against the balance without moving it;
* **settle** charges the actual cost and releases the remainder;
* **refund** releases everything, for a failure or a cancellation.

The hold is a row in ``media_reservations`` and not a field on the wallet
because ``user_wallets`` carries ``CHECK (tokens_remaining = tokens_total -
tokens_used)``. A hold written into ``tokens_used`` would either violate that
invariant or have to be netted out of ``tokens_total``, and either way every
other reader of the wallet would be looking at a number that means two
different things.

What admission actually guarantees
----------------------------------
``available_tokens`` is ``tokens_remaining - open reservations``. That is the
only number an admission decision may use, and it is computed **inside the same
transaction that writes the reservation**, so two concurrent submits cannot both
pass a check only one of them can afford. Reading the balance and then writing
a hold in two steps would reintroduce exactly the race Phase 6 fixed in exam
submission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from deeptutor.db.connection import Database

#: Reservation states. Open holds count against the balance; the other two do
#: not, which is why they are terminal and one-way.
OPEN = "open"
SETTLED = "settled"
REFUNDED = "refunded"


class StudioError(RuntimeError):
    """A studio rule was violated."""

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


class QuotaExceeded(StudioError):
    """The caller cannot afford this job."""

    def __init__(self, detail: str, *, field: str = "tokens") -> None:
        super().__init__("insufficient_quota", detail, field=field)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True)
class Admission:
    """The outcome of asking whether a job may run."""

    allowed: bool
    reason: str
    available: int
    required: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "available": self.available,
            "required": self.required,
        }


def available_tokens(db: Database, user_id: str) -> int:
    """Tokens this user can still commit, net of open reservations.

    A user with no wallet is treated as having nothing rather than as unlimited:
    an unmetered path is a free tier that nobody chose.
    """
    with db.read() as conn:
        wallet = conn.query_one(
            "SELECT tokens_remaining FROM user_wallets WHERE user_id = ?", (user_id,)
        )
        held = conn.scalar(
            "SELECT COALESCE(SUM(reserved_tokens), 0) FROM media_reservations "
            "WHERE user_id = ? AND state = 'open'",
            (user_id,),
        )
    remaining = int((wallet or {}).get("tokens_remaining") or 0)
    return max(0, remaining - int(held or 0))


def check_admission(db: Database, user_id: str, *, required: int) -> Admission:
    """Whether *required* tokens are available, and if not, why."""
    available = available_tokens(db, user_id)
    if required <= 0:
        return Admission(True, "no cost", available, required)
    if available < required:
        return Admission(
            False,
            f"need {required} tokens, {available} available after open holds",
            available,
            required,
        )
    return Admission(True, "ok", available, required)


def reserve(
    db: Database,
    *,
    user_id: str,
    tokens: int,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Hold *tokens* against the caller's balance, or refuse.

    The availability check and the insert happen in **one transaction**, which
    is the whole point: a check-then-insert across two transactions is a race,
    and the loser would be a job that runs and cannot be paid for.
    """
    if tokens < 0:
        raise StudioError("invalid_reservation", "a reservation cannot be negative")

    reservation_id = _new_id("rsv")
    stamp = _now()
    with db.transaction() as conn:
        wallet = conn.query_one(
            "SELECT tokens_remaining FROM user_wallets WHERE user_id = ?", (user_id,)
        )
        remaining = int((wallet or {}).get("tokens_remaining") or 0)
        held = conn.scalar(
            "SELECT COALESCE(SUM(reserved_tokens), 0) FROM media_reservations "
            "WHERE user_id = ? AND state = 'open'",
            (user_id,),
        )
        available = max(0, remaining - int(held or 0))
        if available < tokens:
            raise QuotaExceeded(
                f"need {tokens} tokens, {available} available after open holds"
            )
        conn.execute(
            "INSERT INTO media_reservations "
            "(id, user_id, job_id, reserved_tokens, settled_tokens, state, created_at, settled_at) "
            "VALUES (?, ?, ?, ?, NULL, 'open', ?, NULL)",
            (reservation_id, user_id, job_id, tokens, stamp),
        )
    return get_reservation(db, reservation_id)


def get_reservation(db: Database, reservation_id: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.query_one(
            "SELECT * FROM media_reservations WHERE id = ?", (reservation_id,)
        )
    if row is None:
        raise StudioError("reservation_not_found", f"no reservation {reservation_id!r}")
    return dict(row)


def attach(db: Database, *, reservation_id: str, job_id: str) -> dict[str, Any]:
    """Bind an open reservation to the job it pays for.

    Reservations are taken *before* the job exists (nothing is enqueued before
    the money is committed), so the job id has to be written afterwards. A hold
    that never gets a job id is invisible to settle and refund, which turns it
    into a permanent charge against the user's balance.
    """
    with db.transaction() as conn:
        row = conn.query_one(
            "SELECT state FROM media_reservations WHERE id = ?", (reservation_id,)
        )
        if row is None:
            raise StudioError("reservation_not_found", f"no reservation {reservation_id!r}")
        if row["state"] != OPEN:
            raise StudioError(
                "reservation_closed",
                f"reservation is {row['state']!r}; cannot attach a job to it",
            )
        conn.execute(
            "UPDATE media_reservations SET job_id = ? WHERE id = ?",
            (job_id, reservation_id),
        )
    return get_reservation(db, reservation_id)


def reservation_for_job(db: Database, job_id: str) -> dict[str, Any] | None:
    with db.read() as conn:
        row = conn.query_one(
            "SELECT * FROM media_reservations WHERE job_id = ? AND state = 'open' "
            "ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        )
    return dict(row) if row else None


def settle(
    db: Database,
    *,
    reservation_id: str,
    actual_tokens: int,
    charge: bool = True,
) -> dict[str, Any]:
    """Charge the real cost and release the rest of the hold.

    ``charge=False`` settles at zero: the asset was reused from cache, so the
    hold is released without spending anything. Kept as a distinct call rather
    than "settle for 0" so the ledger says *why* nothing was charged.

    Idempotent: a second settle of an already-settled reservation changes
    nothing and returns the existing row, because a retried job must not
    double-bill.
    """
    if actual_tokens < 0:
        raise StudioError("invalid_settlement", "a settlement cannot be negative")

    with db.transaction() as conn:
        row = conn.query_one(
            "SELECT * FROM media_reservations WHERE id = ?", (reservation_id,)
        )
        if row is None:
            raise StudioError("reservation_not_found", f"no reservation {reservation_id!r}")
        if row["state"] == REFUNDED:
            raise StudioError(
                "reservation_closed",
                "this reservation was refunded; it cannot be settled",
            )
        if row["state"] == SETTLED:
            return dict(row)

        charged = int(actual_tokens) if charge else 0
        if charged:
            # The wallet is the source of truth for what has been spent. The
            # conditional update is what makes an overdraw a 402-shaped error
            # rather than a CHECK violation surfacing as a 500.
            changed = conn.execute(
                "UPDATE user_wallets SET tokens_used = tokens_used + ?, "
                "tokens_remaining = tokens_remaining - ?, updated_at = ? "
                "WHERE user_id = ? AND tokens_remaining >= ?",
                (charged, charged, _now(), row["user_id"], charged),
            )
            if changed != 1:
                raise QuotaExceeded(
                    f"cannot settle {charged} tokens: the balance moved during the job"
                )
            conn.execute(
                "INSERT INTO token_usage_logs (id, user_id, action, book_id, prompt_tokens, "
                "completion_tokens, total_tokens, cost_toman, created_at) "
                "VALUES (?, ?, 'media_job', NULL, 0, ?, ?, 0, ?)",
                (_new_id("tu"), row["user_id"], charged, charged, _now()),
            )

        conn.execute(
            "UPDATE media_reservations SET state = 'settled', settled_tokens = ?, "
            "settled_at = ? WHERE id = ?",
            (charged, _now(), reservation_id),
        )
        updated = conn.query_one(
            "SELECT * FROM media_reservations WHERE id = ?", (reservation_id,)
        )
    return dict(updated)


def refund(db: Database, *, reservation_id: str, reason: str = "") -> dict[str, Any]:
    """Release a hold without charging. For failure and cancellation.

    Idempotent, and safe on a reservation that was already settled: settling
    means money genuinely moved, and refunding it here would credit tokens the
    user may already have spent elsewhere. A settled reservation is left alone
    and the caller is told, rather than silently reversed.
    """
    with db.transaction() as conn:
        row = conn.query_one(
            "SELECT * FROM media_reservations WHERE id = ?", (reservation_id,)
        )
        if row is None:
            raise StudioError("reservation_not_found", f"no reservation {reservation_id!r}")
        if row["state"] == REFUNDED:
            return dict(row)
        if row["state"] == SETTLED:
            # Not an error the caller should retry: it is a statement that the
            # work completed and was paid for.
            return dict(row)

        conn.execute(
            "UPDATE media_reservations SET state = 'refunded', settled_tokens = 0, "
            "settled_at = ? WHERE id = ?",
            (_now(), reservation_id),
        )
        updated = conn.query_one(
            "SELECT * FROM media_reservations WHERE id = ?", (reservation_id,)
        )
    return dict(updated)


def open_holds(db: Database, user_id: str) -> int:
    """Tokens currently held for this user. Used by the dashboard."""
    with db.read() as conn:
        held = conn.scalar(
            "SELECT COALESCE(SUM(reserved_tokens), 0) FROM media_reservations "
            "WHERE user_id = ? AND state = 'open'",
            (user_id,),
        )
    return int(held or 0)


__all__ = [
    "Admission",
    "OPEN",
    "QuotaExceeded",
    "REFUNDED",
    "SETTLED",
    "StudioError",
    "attach",
    "available_tokens",
    "check_admission",
    "get_reservation",
    "open_holds",
    "refund",
    "reservation_for_job",
    "reserve",
    "settle",
]
