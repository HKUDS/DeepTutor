"""OTP persistence — replaces ``data/system/auth/otp.json``.

The security properties are unchanged and are the reason the schema looks the
way it does (see ``deeptutor/multi_user/otp.py``):

* only ``sha256(salt || code)`` is stored — never the code
* one live code per phone number (the table's primary key is the phone)
* consumption deletes the row, making replay impossible
* attempts are counted on the row so a restart cannot reset the counter

Moving from a JSON file to a table *strengthens* two of these: the attempt
counter can no longer be lost by a concurrent write clobbering the file, and
consumption is a ``DELETE ... WHERE digest = ?`` whose ``rowcount`` is the
authoritative "did I consume it" answer. Two requests racing to use the same
code now produce exactly one success — the file store needed a process lock,
which only held inside one process.

Everything here is synchronous: the OTP call-sites are synchronous and running
inside FastAPI's threadpool, so an async repository would force a rewrite of
Phase 2 for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

from deeptutor.db.connection import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OtpRecord:
    """What is on disk for one phone number. Never contains the code."""

    phone: str
    salt: str
    digest: str
    expires_at: float
    attempts: int
    max_attempts: int
    last_sent_at: float
    window_started_at: float
    sends_in_window: int

    def as_store_dict(self) -> dict[str, Any]:
        """The exact shape ``otp._read_store()`` produced, for the callers."""
        return {
            "salt": self.salt,
            "digest": self.digest,
            "expires_at": self.expires_at,
            "attempts": self.attempts,
            "last_sent_at": self.last_sent_at,
            "window_started_at": self.window_started_at,
            "sends_in_window": self.sends_in_window,
        }


def _record_from_row(row: dict[str, Any]) -> OtpRecord:
    return OtpRecord(
        phone=str(row["phone_number"]),
        salt=str(row["salt"]),
        digest=str(row["digest"]),
        expires_at=float(row["expires_at"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        last_sent_at=float(row["last_sent_at"]),
        window_started_at=float(row["window_started_at"]),
        sends_in_window=int(row["sends_in_window"]),
    )


class OtpRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, phone: str) -> OtpRecord | None:
        with self._db.read() as conn:
            row = conn.query_one("SELECT * FROM otp_codes WHERE phone_number = ?", (phone,))
        return _record_from_row(row) if row else None

    def load_all(self) -> dict[str, dict[str, Any]]:
        """The whole store as ``{phone: record}``, matching ``_read_store()``."""
        with self._db.read() as conn:
            rows = conn.query("SELECT * FROM otp_codes").rows
        return {str(r["phone_number"]): _record_from_row(r).as_store_dict() for r in rows}

    def upsert(self, record: OtpRecord) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._db.transaction() as conn:
            existing = conn.query_one(
                "SELECT phone_number FROM otp_codes WHERE phone_number = ?", (record.phone,)
            )
            params = (
                record.salt,
                record.digest,
                record.expires_at,
                record.attempts,
                record.max_attempts,
                record.last_sent_at,
                record.window_started_at,
                record.sends_in_window,
            )
            if existing is not None:
                conn.execute(
                    "UPDATE otp_codes SET salt = ?, digest = ?, expires_at = ?, "
                    "attempts = ?, max_attempts = ?, last_sent_at = ?, "
                    "window_started_at = ?, sends_in_window = ? WHERE phone_number = ?",
                    (*params, record.phone),
                )
                return
            conn.execute(
                "INSERT INTO otp_codes (salt, digest, expires_at, attempts, max_attempts, "
                "last_sent_at, window_started_at, sends_in_window, phone_number, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*params, record.phone, now),
            )

    def consume(self, phone: str, digest: str) -> bool:
        """Delete the row iff the digest matches. The atomic single-use check.

        ``rowcount == 1`` means *this* call consumed the code. Any concurrent
        caller gets ``rowcount == 0`` and must be told the code is invalid —
        never retried, or the guarantee is gone.
        """
        with self._db.transaction() as conn:
            return (
                conn.execute(
                    "DELETE FROM otp_codes WHERE phone_number = ? AND digest = ?",
                    (phone, digest),
                )
                == 1
            )

    def record_attempt(self, phone: str, attempts: int) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE otp_codes SET attempts = ? WHERE phone_number = ?",
                (attempts, phone),
            )

    def delete(self, phone: str) -> bool:
        with self._db.transaction() as conn:
            return conn.execute("DELETE FROM otp_codes WHERE phone_number = ?", (phone,)) == 1

    def purge_expired(self, *, now: float | None = None) -> int:
        cutoff = time.time() if now is None else now
        with self._db.transaction() as conn:
            return conn.execute("DELETE FROM otp_codes WHERE expires_at < ?", (cutoff,))

    def backfill(self, store: dict[str, dict[str, Any]]) -> int:
        """Copy an ``otp.json`` payload. Expired entries are skipped, not revived."""
        now = time.time()
        written = 0
        for phone, raw in store.items():
            try:
                record = OtpRecord(
                    phone=str(phone),
                    salt=str(raw["salt"]),
                    digest=str(raw["digest"]),
                    expires_at=float(raw["expires_at"]),
                    attempts=int(raw.get("attempts") or 0),
                    max_attempts=5,
                    last_sent_at=float(raw.get("last_sent_at") or 0),
                    window_started_at=float(raw.get("window_started_at") or 0),
                    sends_in_window=int(raw.get("sends_in_window") or 0),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("skipping malformed otp record for %s: %s", phone, exc)
                continue
            if record.expires_at < now:
                continue  # expired codes are useless; do not carry them forward
            self.upsert(record)
            written += 1
        return written
