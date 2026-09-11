"""Revocable device credentials for local learner accounts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import threading
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_text

from .identity import get_user_by_id
from .paths import SYSTEM_ROOT

DEVICE_CREDENTIALS_FILE = SYSTEM_ROOT / "auth" / "device_credentials.json"
HEARTBEAT_TIMEOUT_SECONDS = 5 * 60
MAX_PIN_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 15 * 60
MIN_DAILY_LIMIT_MINUTES = 5
MAX_DAILY_LIMIT_MINUTES = 24 * 60

_DEVICE_WRITE_LOCK = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hash_pairing_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _hash_session_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _canonical_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    credential_id = str(value.get("id") or f"dc_{uuid4().hex}")
    user_id = str(value.get("user_id") or "")
    pairing_hash = str(value.get("pairing_code_hash") or "")
    pin_hash = str(value.get("pin_hash") or "")
    expires_at = _parse_iso(value.get("expires_at"))
    daily_limit = value.get("daily_limit_minutes")
    if not user_id or not pairing_hash or not pin_hash or expires_at is None:
        return None
    if not isinstance(daily_limit, int) or not (
        MIN_DAILY_LIMIT_MINUTES <= daily_limit <= MAX_DAILY_LIMIT_MINUTES
    ):
        return None
    revoked_at = _parse_iso(value.get("revoked_at"))
    last_heartbeat = _parse_iso(value.get("last_heartbeat_at"))
    used_seconds = value.get("used_seconds", 0)
    if not isinstance(used_seconds, int) or used_seconds < 0:
        used_seconds = 0
    usage_day = str(value.get("usage_day") or "")
    if usage_day and not _valid_usage_day(usage_day):
        usage_day = ""
    failed_pin_attempts = value.get("failed_pin_attempts", 0)
    if not isinstance(failed_pin_attempts, int) or failed_pin_attempts < 0:
        failed_pin_attempts = 0
    pin_locked_until = _parse_iso(value.get("pin_locked_until"))
    return {
        "id": credential_id,
        "user_id": user_id,
        "device_name": str(value.get("device_name") or "Device")[:80],
        "pairing_code_hash": pairing_hash,
        "pin_hash": pin_hash,
        "created_at": str(value.get("created_at") or ""),
        "expires_at": _iso(expires_at),
        "daily_limit_minutes": daily_limit,
        "last_login_at": str(value.get("last_login_at") or ""),
        "last_heartbeat_at": _iso(last_heartbeat) if last_heartbeat else "",
        "usage_day": usage_day,
        "used_seconds": min(used_seconds, daily_limit * 60),
        "session_nonce_hash": str(value.get("session_nonce_hash") or ""),
        "failed_pin_attempts": min(failed_pin_attempts, MAX_PIN_ATTEMPTS),
        "pin_locked_until": _iso(pin_locked_until) if pin_locked_until else "",
        "revoked_at": _iso(revoked_at) if revoked_at else None,
        "revoked_by": str(value.get("revoked_by") or "") if revoked_at else "",
    }


def _valid_usage_day(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _load_records() -> list[dict[str, Any]]:
    try:
        loaded = json.loads(DEVICE_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in loaded:
        record = _canonical_record(value)
        if record is None or record["id"] in seen:
            continue
        seen.add(record["id"])
        records.append(record)
    return records


def _write_records(records: list[dict[str, Any]]) -> None:
    DEVICE_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        DEVICE_CREDENTIALS_FILE,
        json.dumps(records, indent=2, ensure_ascii=False),
    )


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key
        not in {
            "pairing_code_hash",
            "pin_hash",
            "session_nonce_hash",
            "failed_pin_attempts",
            "pin_locked_until",
        }
    }


def _active_account(user_id: str) -> tuple[str, dict[str, Any]] | None:
    account = get_user_by_id(user_id)
    if account is None:
        return None
    username, record = account
    if str(record.get("role") or "user") != "user" or bool(record.get("disabled")):
        return None
    if str(record.get("preset") or "standard") != "learner":
        return None
    return username, record


def _usage_for(record: dict[str, Any], now: datetime) -> tuple[str, int]:
    current_day = now.date().isoformat()
    if record["usage_day"] != current_day:
        return current_day, 0
    return current_day, int(record["used_seconds"])


def _is_usable(record: dict[str, Any], now: datetime) -> bool:
    if record["revoked_at"] is not None:
        return False
    expires_at = _parse_iso(record["expires_at"])
    if expires_at is None or expires_at <= now:
        return False
    if _active_account(record["user_id"]) is None:
        return False
    _usage_day, used_seconds = _usage_for(record, now)
    if used_seconds >= record["daily_limit_minutes"] * 60:
        return False
    last_heartbeat = _parse_iso(record["last_heartbeat_at"])
    if last_heartbeat is None:
        return False
    elapsed = (now - last_heartbeat).total_seconds()
    return 0 <= elapsed <= HEARTBEAT_TIMEOUT_SECONDS


def _charge_previous_lease(record: dict[str, Any], now: datetime) -> None:
    """Account for an active lease before a same-day re-login rotates it."""
    usage_day, used_seconds = _usage_for(record, now)
    last_heartbeat = _parse_iso(record["last_heartbeat_at"])
    elapsed = 0
    if last_heartbeat is not None and last_heartbeat.date() == now.date():
        elapsed = min(
            max(int((now - last_heartbeat).total_seconds()), 0),
            HEARTBEAT_TIMEOUT_SECONDS,
        )
    record["usage_day"] = usage_day
    record["used_seconds"] = min(
        used_seconds + elapsed,
        record["daily_limit_minutes"] * 60,
    )


def issue_device_credential(
    *,
    user_id: str,
    device_name: str,
    expires_at: datetime,
    daily_limit_minutes: int,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Create a credential and return its public view, code, and one-time PIN."""

    current = now or utc_now()
    if _active_account(user_id) is None:
        raise ValueError("Device credentials require an active learner account.")
    if expires_at <= current:
        raise ValueError("Device credential expiry must be in the future.")
    if expires_at - current > timedelta(days=365):
        raise ValueError("Device credential expiry cannot exceed 365 days.")
    if not (MIN_DAILY_LIMIT_MINUTES <= daily_limit_minutes <= MAX_DAILY_LIMIT_MINUTES):
        raise ValueError("Daily limit must be between 5 and 1440 minutes.")
    device = device_name.strip() or "Device"
    if len(device) > 80:
        raise ValueError("Device name cannot exceed 80 characters.")

    from deeptutor.services.auth import hash_password

    pairing_code = f"dc_{secrets.token_urlsafe(24)}"
    pin = f"{secrets.randbelow(1_000_000):06d}"
    record = {
        "id": f"dc_{uuid4().hex}",
        "user_id": user_id,
        "device_name": device,
        "pairing_code_hash": _hash_pairing_code(pairing_code),
        "pin_hash": hash_password(pin),
        "created_at": _iso(current),
        "expires_at": _iso(expires_at),
        "daily_limit_minutes": daily_limit_minutes,
        "last_login_at": "",
        "last_heartbeat_at": "",
        "usage_day": "",
        "used_seconds": 0,
        "session_nonce_hash": "",
        "failed_pin_attempts": 0,
        "pin_locked_until": "",
        "revoked_at": None,
        "revoked_by": "",
    }
    with _DEVICE_WRITE_LOCK:
        records = _load_records()
        records.append(record)
        _write_records(records)
    return _public_record(record), pairing_code, pin


def list_device_credentials(
    *, user_id: str | None = None, include_revoked: bool = False
) -> list[dict[str, Any]]:
    return [
        _public_record(record)
        for record in _load_records()
        if (include_revoked or record["revoked_at"] is None)
        and (user_id is None or record["user_id"] == user_id)
    ]


def begin_device_session(
    pairing_code: str, pin: str, now: datetime | None = None
) -> tuple[dict[str, Any], str, str, str, str] | None:
    """Verify a code and PIN, then start a bounded heartbeat session."""

    current = now or utc_now()
    pairing_hash = _hash_pairing_code(pairing_code)
    from deeptutor.services.auth import verify_password

    with _DEVICE_WRITE_LOCK:
        records = _load_records()
        record = next(
            (item for item in records if item["pairing_code_hash"] == pairing_hash),
            None,
        )
        if record is None or not secrets.compare_digest(record["pairing_code_hash"], pairing_hash):
            return None
        account = _active_account(record["user_id"])
        if account is None:
            return None
        if record["revoked_at"] is not None:
            return None
        expires_at = _parse_iso(record["expires_at"])
        if expires_at is None or expires_at <= current:
            return None
        locked_until = _parse_iso(record["pin_locked_until"])
        if locked_until is not None and locked_until > current:
            return None
        if not verify_password(pin, record["pin_hash"]):
            record["failed_pin_attempts"] += 1
            if record["failed_pin_attempts"] >= MAX_PIN_ATTEMPTS:
                record["pin_locked_until"] = _iso(current + timedelta(seconds=PIN_LOCKOUT_SECONDS))
            _write_records(records)
            return None
        record["failed_pin_attempts"] = 0
        record["pin_locked_until"] = ""
        _charge_previous_lease(record, current)
        if record["used_seconds"] >= record["daily_limit_minutes"] * 60:
            _write_records(records)
            return None
        session_nonce = secrets.token_urlsafe(32)
        record["session_nonce_hash"] = _hash_session_nonce(session_nonce)
        record["last_login_at"] = _iso(current)
        record["last_heartbeat_at"] = _iso(current)
        _write_records(records)
        username, user_record = account
        return (
            _public_record(record),
            username,
            str(user_record.get("role") or "user"),
            record["user_id"],
            session_nonce,
        )


def validate_device_token(user_id: str, credential_id: str, session_nonce: str) -> bool:
    record = next(
        (item for item in _load_records() if item["id"] == credential_id),
        None,
    )
    return (
        record is not None
        and record["user_id"] == user_id
        and bool(session_nonce)
        and secrets.compare_digest(
            record["session_nonce_hash"],
            _hash_session_nonce(session_nonce),
        )
        and _is_usable(record, utc_now())
    )


def heartbeat_device_credential(
    credential_id: str,
    *,
    user_id: str,
    session_nonce: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Advance daily usage and refresh the server heartbeat lease."""

    current = now or utc_now()
    with _DEVICE_WRITE_LOCK:
        records = _load_records()
        record = next(
            (item for item in records if item["id"] == credential_id),
            None,
        )
        nonce_matches = bool(record and session_nonce) and secrets.compare_digest(
            record["session_nonce_hash"],
            _hash_session_nonce(session_nonce),
        )
        if (
            record is None
            or record["user_id"] != user_id
            or not nonce_matches
            or not _is_usable(record, current)
        ):
            raise ValueError("Device credential is not active.")

        last_heartbeat = _parse_iso(record["last_heartbeat_at"])
        if last_heartbeat is None:
            raise ValueError("Device credential is not active.")
        elapsed = int((current - last_heartbeat).total_seconds())
        usage_day, used_seconds = _usage_for(record, current)
        record["usage_day"] = usage_day
        record["used_seconds"] = min(
            used_seconds + max(elapsed, 0),
            record["daily_limit_minutes"] * 60,
        )
        record["last_heartbeat_at"] = _iso(current)
        _write_records(records)
        limit_seconds = record["daily_limit_minutes"] * 60
        view = _public_record(record)
        view["remaining_seconds"] = max(limit_seconds - record["used_seconds"], 0)
        view["limit_reached"] = record["used_seconds"] >= limit_seconds
        return view


def revoke_device_credential(
    credential_id: str, *, revoked_by: str, now: datetime | None = None
) -> dict[str, Any] | None:
    current = now or utc_now()
    with _DEVICE_WRITE_LOCK:
        records = _load_records()
        for record in records:
            if record["id"] != credential_id:
                continue
            if record["revoked_at"] is None:
                record["revoked_at"] = _iso(current)
                record["revoked_by"] = revoked_by
                _write_records(records)
            return _public_record(record)
    return None


def revoke_device_credentials_for_user(
    user_id: str, *, revoked_by: str, now: datetime | None = None
) -> int:
    """Revoke every active device credential and session for one learner."""

    current = now or utc_now()
    with _DEVICE_WRITE_LOCK:
        records = _load_records()
        changed = 0
        for record in records:
            if record["user_id"] != user_id or record["revoked_at"] is not None:
                continue
            record["revoked_at"] = _iso(current)
            record["revoked_by"] = revoked_by
            record["session_nonce_hash"] = ""
            changed += 1
        if changed:
            _write_records(records)
    return changed


__all__ = [
    "DEVICE_CREDENTIALS_FILE",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "MAX_PIN_ATTEMPTS",
    "PIN_LOCKOUT_SECONDS",
    "begin_device_session",
    "heartbeat_device_credential",
    "issue_device_credential",
    "list_device_credentials",
    "revoke_device_credential",
    "revoke_device_credentials_for_user",
    "validate_device_token",
]
