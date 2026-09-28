"""Security state for private-to-public session handoff.

Pairing codes and tickets are represented only by SHA-256 fingerprints in
SQLite. A short-lived JWE carries the credential between the two public POST
calls, so the deployment-private database never contains a plaintext bearer
token.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from jose import jwe
from jose.exceptions import JWEError, JWSError

from .identity import AUTH_DIR, load_or_create_auth_secret

CODE_LIFETIME_SECONDS = 300
TICKET_LIFETIME_SECONDS = 120
MAX_CODE_ATTEMPTS = 5
CREATE_RATE_LIMIT = (5, 60)
STATE_RETENTION_SECONDS = 600

_DB_FILENAME = "session_handoff.sqlite3"


class HandoffError(Exception):
    """A controlled handoff failure that is safe to expose generically."""


class HandoffRejected(HandoffError):
    """The code/ticket is absent, malformed, expired, or already used."""


class HandoffRateLimited(HandoffError):
    """The caller exceeded a handoff rate limit."""


@dataclass(frozen=True)
class HandoffRecord:
    code: str
    ticket: str
    public_origin: str
    expires_at: int


def _normalized_hostname(hostname: str) -> str:
    if not hostname or len(hostname) > 253:
        raise HandoffError("Invalid host")
    if any(ch.isspace() or ord(ch) < 0x20 or ch == "\x7f" for ch in hostname):
        raise HandoffError("Invalid host")
    try:
        return hostname.rstrip(".").lower()
    except UnicodeError as exc:
        raise HandoffError("Invalid host") from exc


def canonical_host(value: str, *, default_port: int | None = None) -> str:
    """Canonicalize an HTTP Host value without accepting path-like input."""

    raw = value.strip()
    if not raw or "/" in raw or "?" in raw or "#" in raw or "@" in raw:
        raise HandoffError("Invalid host")
    try:
        parsed = urlsplit(f"//{raw}", allow_fragments=False)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise HandoffError("Invalid host") from exc
    if not hostname:
        raise HandoffError("Invalid host")
    host = _normalized_hostname(hostname)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise HandoffError("Invalid host") from exc
    else:
        host = str(address)
    if port is None:
        port = default_port
    if port is not None and port != default_port:
        host = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return host


def is_loopback_host(host: str) -> bool:
    if host.startswith("["):
        host = host.split("]", 1)[0][1:]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost"
    return address.is_loopback


def public_origin(value: str) -> str:
    """Validate and canonicalize the HTTPS origin to which a ticket is bound."""

    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise HandoffError("Public origin must use HTTPS") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HandoffError("Public origin must use HTTPS")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise HandoffError("Public origin must not contain a path or credentials")
    host = canonical_host(parsed.netloc, default_port=443)
    if is_loopback_host(host):
        raise HandoffError("Public origin cannot be loopback")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise HandoffError("Public origin hostname is invalid")
    else:
        if not address.is_global:
            raise HandoffError("Public origin must use a public address")
    if port is not None and port != 443:
        return urlunsplit(("https", host, "", "", ""))
    return urlunsplit(("https", host, "", "", ""))


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _jwe_key(secret: str | None = None) -> bytes:
    material = secret or load_or_create_auth_secret()
    if not material:
        raise HandoffError("Handoff encryption key is unavailable")
    return hashlib.sha256(material.encode("utf-8")).digest()


def encrypt_ticket_payload(payload: dict[str, Any], *, secret: str | None = None) -> str:
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    try:
        token = jwe.encrypt(
            plaintext,
            _jwe_key(secret),
            algorithm="dir",
            encryption="A256GCM",
        )
        return token.decode("ascii") if isinstance(token, bytes) else token
    except (JWSError, ValueError) as exc:
        raise HandoffError("Could not protect the handoff ticket") from exc


def decrypt_ticket_payload(token: str, *, secret: str | None = None) -> dict[str, Any]:
    try:
        plaintext = jwe.decrypt(token, _jwe_key(secret))
        payload = json.loads(plaintext)
    except (JWEError, JWSError, ValueError, TypeError, json.JSONDecodeError):
        raise HandoffRejected("Invalid handoff ticket") from None
    if not isinstance(payload, dict):
        raise HandoffRejected("Invalid handoff ticket")
    return payload


class SessionHandoffStore:
    """SQLite-backed atomic code/ticket state with owner-only permissions."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or AUTH_DIR / _DB_FILENAME

    def _connect(self) -> sqlite3.Connection:
        parent_existed = self.db_path.parent.exists()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(self.db_path.parent, 0o700)
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS handoff_records (
                code_hash TEXT PRIMARY KEY,
                ticket_hash TEXT NOT NULL UNIQUE,
                encrypted_ticket TEXT NOT NULL,
                public_host TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                code_consumed_at INTEGER,
                ticket_consumed_at INTEGER,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS handoff_expiry_idx
                ON handoff_records(expires_at);
            CREATE TABLE IF NOT EXISTS handoff_rate_limits (
                bucket TEXT PRIMARY KEY,
                window_start INTEGER NOT NULL,
                count INTEGER NOT NULL
            );
            """
        )
        try:
            os.chmod(self.db_path, 0o600)
            os.chmod(self.db_path.parent, 0o700)
        except FileNotFoundError:  # pragma: no cover - dropped concurrently
            pass

    def _cleanup(self, connection: sqlite3.Connection, now: int) -> None:
        connection.execute(
            "DELETE FROM handoff_records WHERE expires_at + ? < ?",
            (STATE_RETENTION_SECONDS, now),
        )
        connection.execute(
            "DELETE FROM handoff_rate_limits WHERE window_start + 3600 < ?",
            (now,),
        )

    @staticmethod
    def _check_rate(
        connection: sqlite3.Connection,
        bucket: str,
        limit: tuple[int, int],
        now: int,
    ) -> None:
        count, window_seconds = limit
        window_start = now - (now % window_seconds)
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO handoff_rate_limits(bucket, window_start, count)
                VALUES (?, ?, 0)
                ON CONFLICT(bucket) DO UPDATE SET
                    window_start=excluded.window_start,
                    count=CASE
                        WHEN handoff_rate_limits.window_start != excluded.window_start
                        THEN 0 ELSE handoff_rate_limits.count
                    END
                """,
                (bucket, window_start),
            )
            connection.execute(
                "UPDATE handoff_rate_limits SET count=count+1 WHERE bucket=?",
                (bucket,),
            )
            row = connection.execute(
                "SELECT count FROM handoff_rate_limits WHERE bucket=?",
                (bucket,),
            ).fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        if int(row["count"]) > count:
            raise HandoffRateLimited("Too many handoff requests")

    def _rate_limit(
        self,
        bucket: str,
        limit: tuple[int, int],
        *,
        now: int | None,
    ) -> None:
        current = int(time.time() if now is None else now)
        with self._connect() as connection:
            self._initialize(connection)
            self._check_rate(connection, bucket, limit, current)

    def create(
        self,
        *,
        encrypted_ticket: str,
        ticket_hash: str,
        public_host: str,
        now: int | None = None,
        code_lifetime: int = CODE_LIFETIME_SECONDS,
        rate_key: str = "unknown",
    ) -> HandoffRecord:
        current = int(time.time() if now is None else now)
        self._rate_limit(f"create:{rate_key}", CREATE_RATE_LIMIT, now=now)
        code = secrets.token_urlsafe(32)
        expires_at = current + code_lifetime
        with self._connect() as connection:
            self._initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._cleanup(connection, current)
                connection.execute(
                    """
                    INSERT INTO handoff_records(
                        code_hash, ticket_hash, encrypted_ticket, public_host,
                        expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hash_secret(code),
                        ticket_hash,
                        encrypted_ticket,
                        public_host,
                        expires_at,
                        current,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return HandoffRecord(code, encrypted_ticket, public_host, expires_at)

    def exchange(
        self,
        *,
        code: str,
        public_host: str,
        now: int | None = None,
    ) -> str:
        current = int(time.time() if now is None else now)
        # An anonymous caller can submit arbitrary codes. A shared host/global
        # quota would let a few bad requests lock out every legitimate handoff
        # on that site. Codes are 256-bit secrets, looked up by hash; a bogus
        # code costs one indexed lookup and cannot guess a valid record.
        code_hash = hash_secret(code)
        with self._connect() as connection:
            self._initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._cleanup(connection, current)
                row = connection.execute(
                    """
                    SELECT encrypted_ticket, public_host, expires_at,
                           code_consumed_at, failed_attempts
                      FROM handoff_records WHERE code_hash=?
                    """,
                    (code_hash,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    raise HandoffRejected("Invalid pairing code")
                if row["code_consumed_at"] is not None:
                    connection.commit()
                    raise HandoffRejected("Invalid pairing code")
                if row["expires_at"] <= current:
                    connection.execute(
                        "DELETE FROM handoff_records WHERE code_hash=?", (code_hash,)
                    )
                    connection.commit()
                    raise HandoffRejected("Invalid pairing code")
                if row["public_host"] != public_host:
                    attempts = int(row["failed_attempts"]) + 1
                    if attempts >= MAX_CODE_ATTEMPTS:
                        connection.execute(
                            "DELETE FROM handoff_records WHERE code_hash=?", (code_hash,)
                        )
                    else:
                        connection.execute(
                            "UPDATE handoff_records SET failed_attempts=? WHERE code_hash=?",
                            (attempts, code_hash),
                        )
                    connection.commit()
                    raise HandoffRejected("Pairing code is not valid for this site")
                claims = decrypt_ticket_payload(str(row["encrypted_ticket"]))
                claims["exp"] = current + TICKET_LIFETIME_SECONDS
                fresh_ticket = encrypt_ticket_payload(claims)
                connection.execute(
                    """
                    UPDATE handoff_records
                       SET code_consumed_at=?, failed_attempts=0,
                           encrypted_ticket=?, ticket_hash=?
                     WHERE code_hash=? AND code_consumed_at IS NULL
                    """,
                    (current, fresh_ticket, hash_secret(fresh_ticket), code_hash),
                )
                connection.commit()
            except HandoffError:
                connection.rollback()
                raise
            except Exception:
                connection.rollback()
                raise
        return fresh_ticket

    def consume_ticket(
        self,
        *,
        ticket: str,
        public_host: str,
        now: int | None = None,
    ) -> str:
        current = int(time.time() if now is None else now)
        # As with exchange, a shared quota here would let anonymous invalid
        # tickets prevent every user on this public host from signing in.
        ticket_hash = hash_secret(ticket)
        with self._connect() as connection:
            self._initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._cleanup(connection, current)
                row = connection.execute(
                    """
                    SELECT encrypted_ticket, public_host, expires_at,
                           ticket_consumed_at, code_consumed_at
                      FROM handoff_records WHERE ticket_hash=?
                    """,
                    (ticket_hash,),
                ).fetchone()
                if (
                    row is None
                    or row["ticket_consumed_at"] is not None
                    or row["code_consumed_at"] is None
                    or row["code_consumed_at"] + TICKET_LIFETIME_SECONDS <= current
                ):
                    if row is not None:
                        connection.execute(
                            "DELETE FROM handoff_records WHERE ticket_hash=?",
                            (ticket_hash,),
                        )
                    connection.commit()
                    raise HandoffRejected("Invalid handoff ticket")
                if row["public_host"] != public_host:
                    connection.commit()
                    raise HandoffRejected("Handoff ticket is not valid for this site")
                if str(row["encrypted_ticket"]) != ticket:
                    connection.commit()
                    raise HandoffRejected("Invalid handoff ticket")
                connection.execute(
                    """
                    UPDATE handoff_records
                       SET ticket_consumed_at=?
                     WHERE ticket_hash=? AND ticket_consumed_at IS NULL
                    """,
                    (current, ticket_hash),
                )
                connection.commit()
            except HandoffError:
                connection.rollback()
                raise
            except Exception:
                connection.rollback()
                raise
        return ticket


_DEFAULT_STORE: SessionHandoffStore | None = None


def get_session_handoff_store() -> SessionHandoffStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SessionHandoffStore()
    return _DEFAULT_STORE


def reset_session_handoff_store_for_tests() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = None
