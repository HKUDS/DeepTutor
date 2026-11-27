"""Wallet, payment and token-usage persistence.

The money invariants live here *and* in the schema, deliberately duplicated:

* ``CHECK (tokens_remaining = tokens_total - tokens_used)`` — the database
  refuses an inconsistent wallet even if a future code path computes it wrong.
* :meth:`WalletRepository.spend` is a conditional ``UPDATE ... WHERE
  tokens_remaining >= ?`` — the balance check and the decrement are one
  statement, so two concurrent requests cannot both pass the check and overdraw.

The second point is the acceptance criterion "transaction and unique
constraints for wallet". A read-then-write in Python would pass a single-thread
test and lose money under load.

Payment idempotency
-------------------
``uq_payment_provider_authority`` means a gateway callback replayed three times
finds the same row. :meth:`settle_payment` transitions ``pending -> paid``
conditionally, so the second call is a no-op returning ``False`` — the quota is
granted exactly once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

from deeptutor.db.connection import Database, DatabaseError

logger = logging.getLogger(__name__)


class WalletRepositoryError(RuntimeError):
    """A wallet operation violated an invariant."""


class InsufficientBalance(WalletRepositoryError):
    """Not enough tokens for the requested spend."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WalletRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- wallet -------------------------------------------------------------

    def ensure(self, user_id: str, *, plan_code: str | None = None) -> dict[str, Any]:
        """Create the wallet row if absent, then return it."""
        now = _now().isoformat()
        with self._db.transaction() as conn:
            existing = conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
            if existing is not None:
                return existing
            conn.execute(
                "INSERT INTO user_wallets (user_id, plan_code, tokens_total, tokens_used, "
                "tokens_remaining, storage_used_bytes, storage_quota_bytes, updated_at) "
                "VALUES (?, ?, 0, 0, 0, 0, 0, ?)",
                (user_id, plan_code, now),
            )
            row = conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
        if row is None:  # pragma: no cover - defensive
            raise WalletRepositoryError("wallet disappeared after insert")
        return row

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self._db.read() as conn:
            return conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))

    def grant(
        self,
        user_id: str,
        tokens: int,
        *,
        duration_days: int | None = None,
        plan_code: str | None = None,
        storage_quota_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Add tokens. Idempotency is the *caller's* job (see settle_payment)."""
        if tokens < 0:
            raise WalletRepositoryError("grant amount cannot be negative")
        self.ensure(user_id, plan_code=plan_code)
        now = _now()
        sets = ["tokens_total = tokens_total + ?", "tokens_remaining = tokens_remaining + ?"]
        params: list[Any] = [tokens, tokens]
        if plan_code is not None:
            sets.append("plan_code = ?")
            params.append(plan_code)
        if duration_days is not None:
            sets.append("plan_started_at = COALESCE(plan_started_at, ?)")
            params.append(now.isoformat())
            sets.append("plan_expires_at = ?")
            params.append((now + timedelta(days=duration_days)).isoformat())
        if storage_quota_bytes is not None:
            sets.append("storage_quota_bytes = ?")
            params.append(storage_quota_bytes)
        sets.append("updated_at = ?")
        params.append(now.isoformat())
        params.append(user_id)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE user_wallets SET {', '.join(sets)} WHERE user_id = ?", tuple(params)
            )
            row = conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
        if row is None:  # pragma: no cover
            raise WalletRepositoryError("wallet missing after grant")
        return row

    def spend(
        self,
        user_id: str,
        tokens: int,
        *,
        action: str,
        book_id: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_toman: int = 0,
    ) -> dict[str, Any]:
        """Charge *tokens* and log the spend, atomically.

        The decrement is conditional on the balance, so an overdraw attempt
        returns ``InsufficientBalance`` instead of driving the balance negative
        (which the CHECK constraint would reject anyway, but as a 500 rather
        than a 402).
        """
        if tokens < 0:
            raise WalletRepositoryError("spend amount cannot be negative")
        now = _now().isoformat()
        with self._db.transaction() as conn:
            wallet = conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
            if wallet is None:
                raise WalletRepositoryError(f"no wallet for user {user_id}")
            if tokens > 0:
                changed = conn.execute(
                    "UPDATE user_wallets SET tokens_used = tokens_used + ?, "
                    "tokens_remaining = tokens_remaining - ?, updated_at = ? "
                    "WHERE user_id = ? AND tokens_remaining >= ?",
                    (tokens, tokens, now, user_id, tokens),
                )
                if changed != 1:
                    raise InsufficientBalance(f"user {user_id} cannot spend {tokens} tokens")
            log_id = f"tu_{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO token_usage_logs (id, user_id, action, book_id, prompt_tokens, "
                "completion_tokens, total_tokens, cost_toman, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    log_id,
                    user_id,
                    action,
                    book_id,
                    prompt_tokens,
                    completion_tokens,
                    tokens,
                    cost_toman,
                    now,
                ),
            )
            updated = conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
        if updated is None:  # pragma: no cover
            raise WalletRepositoryError("wallet missing after spend")
        return updated

    def add_storage(self, user_id: str, delta: int) -> dict[str, Any]:
        """Adjust storage usage by *delta* (negative on delete)."""
        if delta < 0:
            return self._storage_delta(user_id, delta, floor_zero=True)
        row = self.get(user_id)
        if row is None:
            raise WalletRepositoryError(f"no wallet for user {user_id}")
        quota = int(row.get("storage_quota_bytes") or 0)
        used = int(row.get("storage_used_bytes") or 0)
        if quota > 0 and used + delta > quota:
            raise WalletRepositoryError("storage quota exceeded")
        return self._storage_delta(user_id, delta, floor_zero=False)

    def _storage_delta(self, user_id: str, delta: int, *, floor_zero: bool) -> dict[str, Any]:
        now = _now().isoformat()
        expression = "MAX(0, storage_used_bytes + ?)" if floor_zero else "storage_used_bytes + ?"
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE user_wallets SET storage_used_bytes = {expression}, updated_at = ? "
                "WHERE user_id = ?",
                (delta, now, user_id),
            )
            row = conn.query_one("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,))
        if row is None:  # pragma: no cover
            raise WalletRepositoryError(f"no wallet for user {user_id}")
        return row

    # -- payments -----------------------------------------------------------

    def create_payment(
        self,
        *,
        user_id: str,
        plan_code: str,
        plan_name: str,
        amount_toman: int,
        tokens_granted: int,
        duration_days: int,
        provider: str,
        authority: str | None = None,
    ) -> dict[str, Any]:
        """Open a pending payment.

        If ``authority`` is supplied and already exists for this provider, the
        existing row is returned — the idempotency key doing its job before any
        money moves.
        """
        if authority:
            with self._db.read() as conn:
                existing = conn.query_one(
                    "SELECT * FROM payment_transactions WHERE provider = ? AND authority = ?",
                    (provider, authority),
                )
            if existing is not None:
                return existing
        payment_id = f"pay_{uuid.uuid4().hex}"
        now = _now().isoformat()
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO payment_transactions (id, user_id, plan_code, plan_name, "
                    "amount_toman, tokens_granted, duration_days, provider, authority, "
                    "status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                    (
                        payment_id,
                        user_id,
                        plan_code,
                        plan_name,
                        amount_toman,
                        tokens_granted,
                        duration_days,
                        provider,
                        authority,
                        now,
                    ),
                )
        except DatabaseError:
            if authority:
                with self._db.read() as conn:
                    existing = conn.query_one(
                        "SELECT * FROM payment_transactions WHERE provider = ? AND authority = ?",
                        (provider, authority),
                    )
                if existing is not None:
                    return existing
            raise
        with self._db.read() as conn:
            row = conn.query_one("SELECT * FROM payment_transactions WHERE id = ?", (payment_id,))
        if row is None:  # pragma: no cover
            raise WalletRepositoryError("payment vanished after insert")
        return row

    def settle_payment(
        self,
        *,
        provider: str,
        authority: str,
        ref_id: str | None = None,
        storage_quota_bytes: int | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Mark a pending payment paid and grant its quota, exactly once.

        Returns ``(granted, payment)``. ``granted`` is False when the payment was
        already settled — the caller should treat that as success, not error,
        because it means a retried callback arrived.
        """
        now = _now()
        with self._db.transaction() as conn:
            row = conn.query_one(
                "SELECT * FROM payment_transactions WHERE provider = ? AND authority = ?",
                (provider, authority),
            )
            if row is None:
                return (False, None)
            changed = conn.execute(
                "UPDATE payment_transactions SET status = 'paid', ref_id = ?, paid_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (ref_id, now.isoformat(), str(row["id"])),
            )
            if changed != 1:
                settled = conn.query_one(
                    "SELECT * FROM payment_transactions WHERE id = ?", (str(row["id"]),)
                )
                return (False, settled)
        self.grant(
            str(row["user_id"]),
            int(row["tokens_granted"]),
            duration_days=int(row["duration_days"]),
            plan_code=str(row["plan_code"]),
            storage_quota_bytes=storage_quota_bytes,
        )
        with self._db.read() as conn:
            settled = conn.query_one(
                "SELECT * FROM payment_transactions WHERE id = ?", (str(row["id"]),)
            )
        return (True, settled)

    def list_payments(self, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            return conn.query(
                "SELECT * FROM payment_transactions WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).rows

    def usage_summary(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            return conn.query(
                "SELECT action, prompt_tokens, completion_tokens, total_tokens, "
                "cost_toman, created_at FROM token_usage_logs WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).rows
