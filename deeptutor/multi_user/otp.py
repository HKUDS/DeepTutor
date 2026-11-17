"""OTP issue and verify for phone sign-up (Phase 2, D-005).

The security properties this module has to hold, and how each is enforced:

===========================  ==================================================
Property                     Mechanism
===========================  ==================================================
No plaintext code at rest    only ``sha256(salt || code)`` is stored
Single use                   record is deleted on successful verify
Expiry                       ``expires_at`` checked against the clock
Brute-force resistance       5 attempts, then the record is destroyed
Replay resistance            a used code cannot verify twice (deleted)
Timing safety                ``hmac.compare_digest`` on the digest
Resend pressure             60s cooldown, 5 sends per 15 minutes
No enumeration               unknown and known phones return the same shape
===========================  ==================================================

Storage is the same JSON-file pattern the rest of ``multi_user`` uses, behind a
lock, written atomically. Phase 3 moves this to PostgreSQL; the interface here
is the one it will keep, so the move is a swap of the storage functions and
nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
from typing import Callable

from . import paths
from .phone import mask_phone

#: Codes live two minutes. Long enough for a slow SMS route, short enough that
#: a leaked notification is stale before it can be used.
OTP_TTL_SECONDS = 120

#: Wrong guesses allowed before the code is burned.
OTP_MAX_ATTEMPTS = 5

#: Minimum gap between two sends to the same number.
OTP_RESEND_COOLDOWN_SECONDS = 60

#: Sends allowed per window, counted independently of the cooldown.
OTP_MAX_SENDS_PER_WINDOW = 5
OTP_SEND_WINDOW_SECONDS = 15 * 60

_LOCK = threading.Lock()


class OtpError(Exception):
    """Base class for OTP failures carrying a client-safe message."""


class OtpRateLimited(OtpError):
    """Too many sends, or a resend came too soon."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class OtpInvalid(OtpError):
    """The code was wrong, expired, already used, or never issued."""


def _hash_code(code: str, salt: str) -> str:
    """Digest of ``salt + code``. Salt is per-record, so two users issued the
    same six digits do not produce the same stored hash."""
    return hashlib.sha256(f"{salt}{code}".encode("utf-8")).hexdigest()


def generate_code() -> str:
    """Six digits from a CSPRNG.

    ``secrets`` and not ``random``: ``random`` is a Mersenne Twister seeded
    predictably enough that several hundred outputs reveal its state.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def _store_path():
    root = paths.SYSTEM_ROOT
    return root / "auth" / "otp.json"


def _read_store() -> dict[str, dict]:
    import json

    path = _store_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_store(store: dict[str, dict]) -> None:
    import json

    from deeptutor.services.file_io import atomic_write_text

    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(store, indent=2, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True, slots=True)
class IssuedOtp:
    """What a caller gets back after a successful issue.

    Deliberately excludes the code: the endpoint that issued it also sent it,
    and nothing downstream needs it.
    """

    phone: str
    expires_in: int
    resend_in: int


def issue_code(
    phone: str,
    *,
    send: Callable[[str, str], None],
    now: float | None = None,
    template: str = "کد ورود شما به درسیار: {code}",
) -> IssuedOtp:
    """Create and deliver a code for ``phone``.

    ``send`` is passed in rather than resolved here so tests can supply a
    recorder without patching a module global, and so the HTTP layer controls
    which provider a request uses.
    """
    now = time.time() if now is None else now

    with _LOCK:
        store = _read_store()
        record = store.get(phone)

        if record:
            last_sent = float(record.get("last_sent_at") or 0)
            elapsed = now - last_sent
            if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
                retry = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed) + 1
                raise OtpRateLimited(
                    f"Please wait {retry} seconds before requesting another code.",
                    retry_after=retry,
                )

            window_start = float(record.get("window_started_at") or now)
            sends = int(record.get("sends_in_window") or 0)
            if now - window_start < OTP_SEND_WINDOW_SECONDS:
                if sends >= OTP_MAX_SENDS_PER_WINDOW:
                    retry = int(OTP_SEND_WINDOW_SECONDS - (now - window_start)) + 1
                    raise OtpRateLimited(
                        "Too many codes requested. Try again later.",
                        retry_after=retry,
                    )
            else:
                # Window rolled over; start counting again from here.
                window_start = now
                sends = 0

        code = generate_code()
        salt = secrets.token_hex(16)

        store[phone] = {
            "salt": salt,
            "digest": _hash_code(code, salt),
            "expires_at": now + OTP_TTL_SECONDS,
            "attempts": 0,
            "last_sent_at": now,
            "window_started_at": float((record or {}).get("window_started_at") or now)
            if record
            and now - float(record.get("window_started_at") or now) < OTP_SEND_WINDOW_SECONDS
            else now,
            "sends_in_window": (sends if record else 0) + 1,
        }
        _write_store(store)

    # Outside the lock: a slow gateway must not block other numbers.
    send(phone, template.format(code=code))

    return IssuedOtp(
        phone=phone,
        expires_in=OTP_TTL_SECONDS,
        resend_in=OTP_RESEND_COOLDOWN_SECONDS,
    )


def verify_code(phone: str, code: str, *, now: float | None = None) -> None:
    """Consume ``code`` for ``phone`` or raise :class:`OtpInvalid`.

    On success the record is removed, which is what makes a code single-use.
    On a wrong guess the attempt counter is incremented, and the code is
    destroyed once it reaches the limit.
    """
    now = time.time() if now is None else now

    with _LOCK:
        store = _read_store()
        record = store.get(phone)

        if not record:
            raise OtpInvalid("The code is incorrect or has expired.")

        if now >= float(record.get("expires_at") or 0):
            store.pop(phone, None)
            _write_store(store)
            raise OtpInvalid("The code is incorrect or has expired.")

        attempts = int(record.get("attempts") or 0)
        if attempts >= OTP_MAX_ATTEMPTS:
            store.pop(phone, None)
            _write_store(store)
            raise OtpInvalid("Too many incorrect attempts. Request a new code.")

        salt = str(record.get("salt") or "")
        supplied = _hash_code(str(code or ""), salt)
        if not hmac.compare_digest(supplied, str(record.get("digest") or "")):
            attempts += 1
            if attempts >= OTP_MAX_ATTEMPTS:
                store.pop(phone, None)
            else:
                record["attempts"] = attempts
                store[phone] = record
            _write_store(store)
            raise OtpInvalid("The code is incorrect or has expired.")

        # Success: burn it before returning.
        store.pop(phone, None)
        _write_store(store)


def purge_expired(*, now: float | None = None) -> int:
    """Drop records whose expiry has passed. Returns the number removed.

    Called by the maintenance path and by tests. Not called per-request: an
    expired record is already rejected by :func:`verify_code`, so this is
    housekeeping rather than a security boundary.
    """
    now = time.time() if now is None else now
    with _LOCK:
        store = _read_store()
        dead = [phone for phone, rec in store.items() if now >= float(rec.get("expires_at") or 0)]
        for phone in dead:
            store.pop(phone, None)
        if dead:
            _write_store(store)
    return len(dead)


def describe(phone: str) -> str:
    """Redacted form for logs."""
    return mask_phone(phone)
