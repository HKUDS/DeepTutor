"""Per-device session registry.

Phase 2 revokes sessions only in bulk: ``bump_token_version`` invalidates every
token for an account. That is correct but blunt — a student cannot log out one
stolen laptop while staying logged in on their phone.

This table adds the per-device dimension *without* changing the token format or
invalidating the Phase 2 mechanism. A token is valid when:

1. its ``tv`` claim equals the account's ``token_version`` (Phase 2 rule), and
2. if a session row exists for its nonce, that row is neither revoked nor
   expired.

Rule 2 is opt-in: a token with no session row is still valid. That keeps
deployments that never populate the table working exactly as before, so adding
the table cannot lock anyone out.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

from deeptutor.db.connection import Database

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        user_id: str,
        token_nonce: str,
        ttl_seconds: int,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        moment = _now()
        session = {
            "id": f"s_{uuid.uuid4().hex}",
            "user_id": user_id,
            "token_nonce": token_nonce,
            "user_agent": (user_agent or "")[:512] or None,
            "ip_address": (ip_address or "")[:64] or None,
            "created_at": moment.isoformat(),
            "last_seen_at": moment.isoformat(),
            "expires_at": (moment + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_sessions (id, user_id, token_nonce, user_agent, "
                "ip_address, created_at, last_seen_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session["id"],
                    session["user_id"],
                    session["token_nonce"],
                    session["user_agent"],
                    session["ip_address"],
                    session["created_at"],
                    session["last_seen_at"],
                    session["expires_at"],
                ),
            )
        return session

    def is_valid(self, token_nonce: str, *, now: datetime | None = None) -> bool:
        """True when no row exists (opt-in) or the row is live."""
        moment = now or _now()
        with self._db.read() as conn:
            row = conn.query_one(
                "SELECT revoked_at, expires_at FROM user_sessions WHERE token_nonce = ?",
                (token_nonce,),
            )
        if row is None:
            return True
        if row.get("revoked_at"):
            return False
        expires = row.get("expires_at")
        if isinstance(expires, str):
            try:
                return datetime.fromisoformat(expires) > moment
            except ValueError:
                return False
        return bool(expires and expires > moment)

    def touch(self, token_nonce: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE user_sessions SET last_seen_at = ? WHERE token_nonce = ?",
                (_now().isoformat(), token_nonce),
            )

    def revoke(self, token_nonce: str) -> bool:
        with self._db.transaction() as conn:
            return (
                conn.execute(
                    "UPDATE user_sessions SET revoked_at = ? "
                    "WHERE token_nonce = ? AND revoked_at IS NULL",
                    (_now().isoformat(), token_nonce),
                )
                == 1
            )

    def revoke_all_for_user(self, user_id: str) -> int:
        with self._db.transaction() as conn:
            return conn.execute(
                "UPDATE user_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (_now().isoformat(), user_id),
            )

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            return conn.query(
                "SELECT id, user_agent, ip_address, created_at, last_seen_at, "
                "expires_at, revoked_at FROM user_sessions WHERE user_id = ? "
                "ORDER BY last_seen_at DESC",
                (user_id,),
            ).rows

    def purge_dead(self, *, older_than_days: int = 30) -> int:
        """Drop expired/revoked rows so the table does not grow forever."""
        cutoff = (_now() - timedelta(days=older_than_days)).isoformat()
        with self._db.transaction() as conn:
            return conn.execute(
                "DELETE FROM user_sessions WHERE expires_at < ? "
                "OR (revoked_at IS NOT NULL AND revoked_at < ?)",
                (cutoff, cutoff),
            )
