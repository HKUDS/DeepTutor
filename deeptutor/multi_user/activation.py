"""One-time activation credentials for migrated Learning Accounts."""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
import os
import secrets
import time
from typing import Any
import uuid

from .identity import get_user, save_user
from .paths import SYSTEM_ROOT

ACTIVATIONS_FILE = SYSTEM_ROOT / "auth" / "learning_activations.json"


def _read() -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(ACTIVATIONS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(value: dict[str, dict[str, Any]]) -> None:
    ACTIVATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVATIONS_FILE.parent / f".{ACTIVATIONS_FILE.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ACTIVATIONS_FILE)
    finally:
        tmp.unlink(missing_ok=True)


def _digest(username: str, code: str) -> str:
    return sha256(f"deeptutor-learning-activation-v1|{username}|{code}".encode()).hexdigest()


def issue_activation(username: str, *, ttl_days: int = 7) -> str:
    code = secrets.token_urlsafe(18)
    rows = _read()
    rows[username] = {
        "code_hash": _digest(username, code),
        "expires_at": time.time() + ttl_days * 86400,
        "used_at": 0.0,
    }
    _write(rows)
    return code


def activate(username: str, code: str, password_hash: str) -> bool:
    rows = _read()
    row = rows.get(username)
    if (
        not isinstance(row, dict)
        or float(row.get("used_at") or 0) > 0
        or float(row.get("expires_at") or 0) < time.time()
        or not hmac.compare_digest(str(row.get("code_hash") or ""), _digest(username, code))
    ):
        return False
    existing = get_user(username)
    if existing is None or str(existing.get("role") or "user") != "user":
        return False
    save_user(username, password_hash, role="user")
    row["used_at"] = time.time()
    _write(rows)
    return True


__all__ = ["ACTIVATIONS_FILE", "activate", "issue_activation"]
