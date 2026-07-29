"""Email verification for public account registration.

The registration challenge is deliberately separate from ``users.json``:
pending accounts must not receive a workspace, a role, or a usable login
token before the mailbox owner proves control of the address.

Only a short-lived HMAC digest of the code is persisted. SQLite is used for
the challenge ledger because it is local, durable, and provides an atomic
``BEGIN IMMEDIATE`` boundary for one-time consumption. This store is not a
replacement for a shared user database when the application is run with
multiple workers or replicas.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
import smtplib
import sqlite3
import ssl
import time
from typing import Final

from deeptutor.multi_user import identity
from deeptutor.services.config import load_auth_settings

logger = logging.getLogger(__name__)

_SCHEMA_VERSION: Final[int] = 1
_CODE_DIGITS: Final[int] = 6
_WINDOW_SECONDS: Final[int] = 3600
_MAX_PENDING_ROWS: Final[int] = 10_000
_MAX_RATE_LIMIT_ROWS: Final[int] = 100_000
_DEFAULT_SMTP_TIMEOUT_SECONDS: Final[float] = 10.0


class EmailVerificationError(RuntimeError):
    """Base class for expected verification flow failures."""


class VerificationRateLimited(EmailVerificationError):
    """The email address or client IP has exceeded the send limit."""


class VerificationCooldown(EmailVerificationError):
    """A new code was requested before the resend cooldown elapsed."""


class VerificationUnavailable(EmailVerificationError):
    """SMTP is not configured sufficiently to send mail."""


@dataclass(frozen=True, slots=True)
class VerificationChallenge:
    email: str
    code: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    use_tls: bool
    use_ssl: bool
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender) and not (self.use_tls and self.use_ssl)


def normalize_email(value: str) -> str:
    """Return the canonical lookup form used by the local identity store."""
    return str(value or "").strip().casefold()


def _settings() -> dict[str, object]:
    return load_auth_settings()


def _int_setting(name: str, default: int) -> int:
    try:
        return int(_settings().get(name, default))
    except (TypeError, ValueError):
        return default


def _db_path() -> Path:
    # Resolve lazily so the multi-user test fixture and deployments that
    # relocate data/system/auth are respected after module import.
    return identity.AUTH_DIR / "email_verification.sqlite3"


def _open_db() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_registrations (
            email TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            code_digest TEXT NOT NULL,
            issued_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            client_ip TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_rate_limits (
            subject TEXT PRIMARY KEY,
            window_started REAL NOT NULL,
            sent_count INTEGER NOT NULL,
            last_sent_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO verification_meta(key, value) VALUES ('schema', ?)",
        (str(_SCHEMA_VERSION),),
    )
    return connection


def _auth_secret() -> bytes:
    # Import lazily to avoid services.auth -> identity -> verification cycles at
    # application startup. The stable identity secret also signs JWTs.
    from deeptutor.services import auth as auth_service

    secret = str(getattr(auth_service, "AUTH_SECRET", "") or "")
    if not secret:
        secret = identity.load_or_create_auth_secret()
    return secret.encode("utf-8")


def _code_digest(email: str, code: str, issued_at: float) -> str:
    message = f"{email}\x00{issued_at:.6f}\x00{code}".encode("utf-8")
    return hmac.new(_auth_secret(), message, hashlib.sha256).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(10**_CODE_DIGITS):0{_CODE_DIGITS}d}"


def _rate_limit_subject(
    connection: sqlite3.Connection,
    *,
    subject: str,
    now: float,
    limit: int,
    cooldown_seconds: int,
) -> None:
    row = connection.execute(
        "SELECT window_started, sent_count, last_sent_at "
        "FROM verification_rate_limits WHERE subject = ?",
        (subject,),
    ).fetchone()
    if row is None or now - float(row["window_started"]) >= _WINDOW_SECONDS:
        connection.execute(
            "INSERT OR REPLACE INTO verification_rate_limits "
            "(subject, window_started, sent_count, last_sent_at) VALUES (?, ?, 1, ?)",
            (subject, now, now),
        )
        return

    if int(row["sent_count"]) >= limit:
        raise VerificationRateLimited("Verification email rate limit exceeded")
    if now - float(row["last_sent_at"]) < cooldown_seconds:
        raise VerificationCooldown("Please wait before requesting another code")

    connection.execute(
        "UPDATE verification_rate_limits SET sent_count = sent_count + 1, "
        "last_sent_at = ? WHERE subject = ?",
        (now, subject),
    )


def _check_rate_limit_subject(
    connection: sqlite3.Connection,
    *,
    subject: str,
    now: float,
    limit: int,
    cooldown_seconds: int,
) -> None:
    """Check a limiter without consuming it, used before bcrypt work."""
    row = connection.execute(
        "SELECT window_started, sent_count, last_sent_at "
        "FROM verification_rate_limits WHERE subject = ?",
        (subject,),
    ).fetchone()
    if row is None or now - float(row["window_started"]) >= _WINDOW_SECONDS:
        return
    if int(row["sent_count"]) >= limit:
        raise VerificationRateLimited("Verification email rate limit exceeded")
    if now - float(row["last_sent_at"]) < cooldown_seconds:
        raise VerificationCooldown("Please wait before requesting another code")


def check_registration_rate_limit(email: str, client_ip: str) -> None:
    """Reject obvious abuse before doing the intentionally expensive bcrypt hash."""
    canonical_email = normalize_email(email)
    now = time.time()
    cooldown_seconds = _int_setting("verification_resend_cooldown_seconds", 60)
    email_limit = _int_setting("verification_max_per_email_hour", 5)
    ip_limit = _int_setting("verification_max_per_ip_hour", 30)
    safe_ip = str(client_ip or "")[:128]
    connection = _open_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        _check_rate_limit_subject(
            connection,
            subject=f"email:{canonical_email}",
            now=now,
            limit=email_limit,
            cooldown_seconds=cooldown_seconds,
        )
        _check_rate_limit_subject(
            connection,
            subject=f"ip:{safe_ip or 'unknown'}",
            now=now,
            limit=ip_limit,
            cooldown_seconds=cooldown_seconds,
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def issue_challenge(email: str, password_hash: str, client_ip: str) -> VerificationChallenge:
    """Persist one new challenge and return the plaintext code for delivery."""
    canonical_email = normalize_email(email)
    if not canonical_email or not password_hash:
        raise ValueError("email and password_hash are required")

    now = time.time()
    ttl_seconds = _int_setting("verification_code_ttl_minutes", 10) * 60
    cooldown_seconds = _int_setting("verification_resend_cooldown_seconds", 60)
    email_limit = _int_setting("verification_max_per_email_hour", 5)
    ip_limit = _int_setting("verification_max_per_ip_hour", 30)
    code = _new_code()
    expires_at = now + ttl_seconds
    digest = _code_digest(canonical_email, code, now)
    safe_ip = str(client_ip or "")[:128]

    connection = _open_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Keep the local anti-abuse ledger bounded even if an attacker rotates
        # through many addresses. Expired challenges and old limiter windows
        # are no longer useful for enforcement.
        connection.execute(
            "DELETE FROM pending_registrations WHERE expires_at <= ?", (now,)
        )
        connection.execute(
            "DELETE FROM verification_rate_limits WHERE last_sent_at <= ?",
            (now - 2 * _WINDOW_SECONDS,),
        )
        pending_count = int(
            connection.execute("SELECT COUNT(*) FROM pending_registrations").fetchone()[0]
        )
        rate_limit_count = int(
            connection.execute("SELECT COUNT(*) FROM verification_rate_limits").fetchone()[0]
        )
        if pending_count >= _MAX_PENDING_ROWS or rate_limit_count >= _MAX_RATE_LIMIT_ROWS:
            raise VerificationRateLimited("Verification service capacity reached")
        # Do not expose whether a mailbox belongs to a registered user here;
        # the router checks that separately and returns the same public result.
        _rate_limit_subject(
            connection,
            subject=f"email:{canonical_email}",
            now=now,
            limit=email_limit,
            cooldown_seconds=cooldown_seconds,
        )
        _rate_limit_subject(
            connection,
            subject=f"ip:{safe_ip or 'unknown'}",
            now=now,
            limit=ip_limit,
            cooldown_seconds=cooldown_seconds,
        )
        connection.execute(
            "INSERT OR REPLACE INTO pending_registrations "
            "(email, password_hash, code_digest, issued_at, expires_at, attempts, client_ip) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (canonical_email, password_hash, digest, now, expires_at, safe_ip),
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    return VerificationChallenge(canonical_email, code, expires_at)


def discard_challenge(email: str) -> None:
    connection = _open_db()
    try:
        connection.execute(
            "DELETE FROM pending_registrations WHERE email = ?", (normalize_email(email),)
        )
    finally:
        connection.close()


def consume_challenge(email: str, code: str) -> str | None:
    """Consume a valid code once and return the stored password hash."""
    canonical_email = normalize_email(email)
    supplied_code = str(code or "").strip()
    max_attempts = _int_setting("verification_max_attempts", 5)
    now = time.time()
    connection = _open_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT password_hash, code_digest, issued_at, expires_at, attempts "
            "FROM pending_registrations WHERE email = ?",
            (canonical_email,),
        ).fetchone()
        if row is None or now >= float(row["expires_at"]):
            if row is not None:
                connection.execute(
                    "DELETE FROM pending_registrations WHERE email = ?", (canonical_email,)
                )
            connection.execute("COMMIT")
            return None

        attempts = int(row["attempts"])
        expected = _code_digest(canonical_email, supplied_code, float(row["issued_at"]))
        if attempts >= max_attempts or not hmac.compare_digest(expected, row["code_digest"]):
            next_attempts = attempts + 1
            if next_attempts >= max_attempts:
                connection.execute(
                    "DELETE FROM pending_registrations WHERE email = ?", (canonical_email,)
                )
            else:
                connection.execute(
                    "UPDATE pending_registrations SET attempts = ? WHERE email = ?",
                    (next_attempts, canonical_email),
                )
            connection.execute("COMMIT")
            return None

        password_hash = str(row["password_hash"])
        connection.execute(
            "DELETE FROM pending_registrations WHERE email = ?", (canonical_email,)
        )
        connection.execute("COMMIT")
        return password_hash
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def smtp_config() -> SMTPConfig:
    def env_bool(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    try:
        port = int(os.getenv("DEEPTUTOR_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    try:
        timeout = float(os.getenv("DEEPTUTOR_SMTP_TIMEOUT_SECONDS", "10"))
    except ValueError:
        timeout = _DEFAULT_SMTP_TIMEOUT_SECONDS
    timeout = max(3.0, min(timeout, 30.0))
    username = os.getenv("DEEPTUTOR_SMTP_USERNAME", "").strip()
    sender = os.getenv("DEEPTUTOR_SMTP_FROM", "").strip() or username
    return SMTPConfig(
        host=os.getenv("DEEPTUTOR_SMTP_HOST", "").strip(),
        port=port if 1 <= port <= 65535 else 587,
        username=username,
        password=os.getenv("DEEPTUTOR_SMTP_PASSWORD", ""),
        sender=sender,
        use_tls=env_bool("DEEPTUTOR_SMTP_USE_TLS", True),
        use_ssl=env_bool("DEEPTUTOR_SMTP_USE_SSL", False),
        timeout_seconds=timeout,
    )


def send_verification_email(challenge: VerificationChallenge) -> None:
    """Send the code using a bounded synchronous SMTP call.

    The router runs this function in a worker thread so a slow mail provider
    cannot block the FastAPI event loop.
    """
    config = smtp_config()
    if not config.configured:
        raise VerificationUnavailable(
            "SMTP is not configured; set DEEPTUTOR_SMTP_HOST and DEEPTUTOR_SMTP_FROM"
        )

    remaining_minutes = max(1, int((challenge.expires_at - time.time()) // 60))
    message = EmailMessage()
    message["Subject"] = "DeepTutor 注册验证码 / Verification code"
    message["From"] = config.sender
    message["To"] = challenge.email
    message.set_content(
        "你的 DeepTutor 注册验证码是：{code}\n\n"
        "验证码 {minutes} 分钟内有效，最多可尝试 5 次。若不是你本人操作，请忽略此邮件。\n\n"
        "Your DeepTutor verification code is: {code}\n\n"
        "It expires in {minutes} minutes. If you did not request this, you can ignore this email."
        .format(code=challenge.code, minutes=remaining_minutes)
    )

    try:
        if config.use_ssl:
            with smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout_seconds
            ) as client:
                if config.username:
                    client.login(config.username, config.password)
                client.send_message(message)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds) as client:
                client.ehlo()
                if config.use_tls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                if config.username:
                    client.login(config.username, config.password)
                client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailVerificationError("SMTP delivery failed") from exc


def email_delivery_configured() -> bool:
    return smtp_config().configured


__all__ = [
    "EmailVerificationError",
    "SMTPConfig",
    "VerificationChallenge",
    "VerificationCooldown",
    "VerificationRateLimited",
    "VerificationUnavailable",
    "consume_challenge",
    "check_registration_rate_limit",
    "discard_challenge",
    "email_delivery_configured",
    "issue_challenge",
    "normalize_email",
    "send_verification_email",
    "smtp_config",
]
