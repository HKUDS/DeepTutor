"""Canonical identity store for the optional multi-user layer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import secrets
import threading
from typing import Any
from uuid import uuid4

from .models import Role

logger = logging.getLogger(__name__)

# Serialises writes to USERS_FILE so a concurrent burst of /register requests
# cannot all see ``not users`` and each promote themselves to admin. Single-
# process FastAPI deployments (the start_web.py launcher) are fully covered;
# multi-worker deployments still race and must rely on an external user store
# (e.g. PocketBase), which is documented in the multi-user README.
_USERS_WRITE_LOCK = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MULTI_USER_ROOT = PROJECT_ROOT / "multi-user"
SYSTEM_ROOT = MULTI_USER_ROOT / "_system"
AUTH_DIR = SYSTEM_ROOT / "auth"
USERS_FILE = AUTH_DIR / "users.json"
SECRET_FILE = AUTH_DIR / "auth_secret"
LEGACY_USERS_FILE = PROJECT_ROOT / "data" / "user" / "auth_users.json"
LEGACY_SECRET_FILE = PROJECT_ROOT / "data" / "user" / "auth_secret"


def new_user_id() -> str:
    return f"u_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_record(
    username: str,
    value: Any,
    *,
    default_role: Role = "user",
) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {
            "id": new_user_id(),
            "hash": value,
            "role": default_role,
            "created_at": utc_now(),
            "disabled": False,
        }
    if not isinstance(value, dict):
        return None
    hashed = str(value.get("hash") or value.get("password_hash") or "")
    if not hashed:
        return None
    role = str(value.get("role") or default_role)
    if role not in {"admin", "user"}:
        role = default_role
    return {
        "id": str(value.get("id") or new_user_id()),
        "hash": hashed,
        "role": role,
        "created_at": str(value.get("created_at") or utc_now()),
        "disabled": bool(value.get("disabled", False)),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


def _write_users(users: dict[str, dict[str, Any]]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _migrate_legacy_users() -> dict[str, dict[str, Any]] | None:
    if USERS_FILE.exists() or not LEGACY_USERS_FILE.exists():
        return None
    legacy = _read_json(LEGACY_USERS_FILE)
    users: dict[str, dict[str, Any]] = {}
    for username, value in legacy.items():
        role: Role = "admin" if not users else "user"
        if isinstance(value, dict) and str(value.get("role") or "") in {"admin", "user"}:
            role = str(value.get("role"))  # type: ignore[assignment]
        record = _canonical_record(username, value, default_role=role)
        if record is not None:
            users[str(username)] = record
    if users:
        _write_users(users)
        logger.info("Migrated auth users from %s to %s", LEGACY_USERS_FILE, USERS_FILE)
        return users
    return None


def _migrate_secret() -> None:
    if SECRET_FILE.exists() or not LEGACY_SECRET_FILE.exists():
        return
    try:
        secret = LEGACY_SECRET_FILE.read_text(encoding="utf-8").strip()
        if secret:
            SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            SECRET_FILE.write_text(secret, encoding="utf-8")
            try:
                SECRET_FILE.chmod(0o600)
            except OSError:
                pass
            logger.info("Migrated auth secret from %s to %s", LEGACY_SECRET_FILE, SECRET_FILE)
    except Exception as exc:
        logger.warning("Failed to migrate legacy auth secret: %s", exc)


def load_users(  # nosec B107 - empty defaults mean "no env fallback supplied".
    env_username: str = "",
    env_password_hash: str = "",
) -> dict[str, dict[str, Any]]:
    """Load canonical users, migrating legacy records and env fallback in memory."""
    users: dict[str, dict[str, Any]] | None = None
    if USERS_FILE.exists():
        users = _read_json(USERS_FILE)
    else:
        users = _migrate_legacy_users()

    if users is None:
        users = {}

    canonical: dict[str, dict[str, Any]] = {}
    changed = False
    for index, (username, value) in enumerate(users.items()):
        role: Role = "admin" if index == 0 else "user"
        if isinstance(value, dict) and str(value.get("role") or "") in {"admin", "user"}:
            role = str(value.get("role"))  # type: ignore[assignment]
        record = _canonical_record(str(username), value, default_role=role)
        if record is None:
            changed = True
            continue
        canonical[str(username)] = record
        changed = changed or record != value

    if USERS_FILE.exists() and changed:
        _write_users(canonical)

    if canonical:
        return canonical

    if env_username and env_password_hash:
        return {
            env_username: {
                "id": "env-admin",
                "hash": env_password_hash,
                "role": "admin",
                "created_at": "",
                "disabled": False,
            }
        }

    return {}


def save_user(username: str, hashed_password: str, role: Role = "user") -> dict[str, Any]:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Read-modify-write must be atomic so concurrent first-time registrations
    # cannot each see an empty store and each promote themselves to admin.
    with _USERS_WRITE_LOCK:
        users = load_users()
        effective_role: Role = "admin" if not users else role
        existing = users.get(username) or {}
        record = {
            "id": str(existing.get("id") or new_user_id()),
            "hash": hashed_password,
            "role": effective_role,
            "created_at": str(existing.get("created_at") or utc_now()),
            "disabled": bool(existing.get("disabled", False)),
        }
        users[username] = record
        _write_users(users)
    return record


def list_user_info(  # nosec B107 - empty defaults mean "no env fallback supplied".
    env_username: str = "",
    env_password_hash: str = "",
) -> list[dict[str, Any]]:
    return [
        {
            "id": record.get("id", ""),
            "username": username,
            "role": record.get("role", "user"),
            "created_at": record.get("created_at", ""),
            "disabled": bool(record.get("disabled", False)),
        }
        for username, record in load_users(env_username, env_password_hash).items()
    ]


def get_user(username: str) -> dict[str, Any] | None:
    return load_users().get(username)


def get_user_by_id(user_id: str) -> tuple[str, dict[str, Any]] | None:
    for username, record in load_users().items():
        if str(record.get("id") or "") == user_id:
            return username, record
    return None


def delete_user(username: str) -> bool:
    if not USERS_FILE.exists():
        return False
    users = load_users()
    if username not in users:
        return False
    users.pop(username, None)
    _write_users(users)
    return True


def set_role(username: str, role: Role) -> bool:
    if role not in {"admin", "user"}:
        raise ValueError("role must be 'admin' or 'user'")
    if not USERS_FILE.exists():
        return False
    users = load_users()
    if username not in users:
        return False
    users[username]["role"] = role
    _write_users(users)
    return True


def load_or_create_auth_secret() -> str:
    _migrate_secret()
    try:
        if SECRET_FILE.exists():
            existing = SECRET_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_hex(32)
        SECRET_FILE.write_text(generated, encoding="utf-8")
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass
        logger.warning(
            "AUTH_ENABLED=true but AUTH_SECRET is not set. Generated a stable local secret at %s.",
            SECRET_FILE,
        )
        return generated
    except Exception as exc:
        logger.warning("Failed to load/create auth secret at %s: %s", SECRET_FILE, exc)
        return secrets.token_hex(32)
