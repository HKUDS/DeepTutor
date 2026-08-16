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
from .paths import PROJECT_ROOT, SYSTEM_ROOT, migrate_legacy_multi_user_tree

logger = logging.getLogger(__name__)

# Serialises writes to USERS_FILE so a concurrent burst of /register requests
# cannot all see ``not users`` and each promote themselves to admin. Single-
# process FastAPI deployments (the ``deeptutor start`` launcher) are fully covered;
# multi-worker deployments still race and must rely on an external user store
# (e.g. PocketBase), which is documented in the multi-user README.
_USERS_WRITE_LOCK = threading.Lock()

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
            "avatar": "",
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
        "avatar": str(value.get("avatar") or ""),
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


def _env_bootstrap_admin() -> tuple[str, str]:
    """Return ``(username, password_hash)`` for the ``auth.json`` bootstrap admin.

    Both halves are required: the shipped default seeds a username with an
    empty hash, which cannot authenticate and therefore is not an admin. An
    empty tuple entry means "no bootstrap admin configured".

    :mod:`deeptutor.services.auth` is imported lazily because it imports this
    module. Its resolved globals — rather than a fresh settings read — are the
    source of truth on purpose: they are exactly the credentials
    ``authenticate()`` accepts, so the promotion gate in :func:`save_user` and
    the login path can never disagree about whether an admin already exists.
    """
    try:
        from deeptutor.services import auth as auth_service

        username = str(getattr(auth_service, "AUTH_USERNAME", "") or "")
        password_hash = str(getattr(auth_service, "AUTH_PASSWORD_HASH", "") or "")
    except Exception as exc:  # pragma: no cover - auth settings unavailable
        logger.warning("Could not resolve the bootstrap admin credentials: %s", exc)
        return "", ""
    if not username or not password_hash:
        return "", ""
    return username, password_hash


def _env_admin_record(password_hash: str) -> dict[str, Any]:
    """Build the in-memory record representing the bootstrap admin."""
    return {
        "id": "env-admin",
        "hash": password_hash,
        "role": "admin",
        "created_at": "",
        "disabled": False,
        "avatar": "",
    }


def load_users(  # nosec B107 - empty defaults mean "no env fallback supplied".
    env_username: str = "",
    env_password_hash: str = "",
) -> dict[str, dict[str, Any]]:
    """Load canonical users, migrating legacy records and env fallback in memory."""
    migrate_legacy_multi_user_tree()
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

    # The bootstrap admin is merged in whenever it is configured, not only when
    # the store is empty. Falling back to it only for an empty store locked the
    # operator who bootstrapped the deployment out of their own instance the
    # moment the first real account was written (#849). A stored record with the
    # same username wins, so the account can later be adopted into the store.
    # The merge is deliberately in-memory only; no write path passes the env
    # arguments, so the bootstrap hash is never persisted into ``users.json``
    # where a rotation of ``auth.json`` could no longer supersede it.
    if env_username and env_password_hash and env_username not in canonical:
        merged = {env_username: _env_admin_record(env_password_hash)}
        merged.update(canonical)
        return merged

    return canonical


def save_user(username: str, hashed_password: str, role: Role = "user") -> dict[str, Any]:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Read-modify-write must be atomic so concurrent first-time registrations
    # cannot each see an empty store and each promote themselves to admin.
    with _USERS_WRITE_LOCK:
        # Called without the env arguments on purpose: ``users`` is written back
        # to disk below, and the bootstrap admin must stay an in-memory overlay.
        users = load_users()
        env_username, _ = _env_bootstrap_admin()
        # A configured bootstrap admin counts as an existing account, so the
        # first account an operator creates from /admin/users is not silently
        # promoted — that endpoint documents role="user" (#849). Re-saving the
        # bootstrap admin's own username adopts it into the store instead, and
        # must keep the admin role.
        account_exists = bool(users) or (bool(env_username) and env_username != username)
        effective_role: Role = role if account_exists else "admin"
        existing = users.get(username) or {}
        record = {
            "id": str(existing.get("id") or new_user_id()),
            "hash": hashed_password,
            "role": effective_role,
            "created_at": str(existing.get("created_at") or utc_now()),
            "disabled": bool(existing.get("disabled", False)),
            "avatar": str(existing.get("avatar") or ""),
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
            "avatar": str(record.get("avatar") or ""),
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


def set_avatar(username: str, avatar: str) -> bool:
    """Update the avatar marker for an existing user. Returns True on success."""
    if not USERS_FILE.exists():
        return False
    with _USERS_WRITE_LOCK:
        users = load_users()
        if username not in users:
            return False
        users[username]["avatar"] = avatar
        _write_users(users)
    return True


# ---------------------------------------------------------------------------
# Avatar image files — stored next to the user store, keyed by user id
# ---------------------------------------------------------------------------

# Extensions are derived from server-side content sniffing, never from the
# uploaded filename, so this list is also the full set of files we may serve.
AVATAR_EXTENSIONS = ("png", "jpg", "webp")


def _avatar_dir() -> Path:
    # Resolved lazily so tests that monkeypatch AUTH_DIR keep avatars isolated.
    return AUTH_DIR / "avatars"


def get_avatar_file(user_id: str) -> Path | None:
    """Return the stored avatar image for ``user_id``, or None."""
    for ext in AVATAR_EXTENSIONS:
        candidate = _avatar_dir() / f"{user_id}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def save_avatar_file(user_id: str, data: bytes, ext: str) -> Path:
    """Atomically persist an avatar image, replacing any previous one."""
    if ext not in AVATAR_EXTENSIONS:
        raise ValueError(f"Unsupported avatar extension: {ext!r}")
    directory = _avatar_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{user_id}.{ext}"
    tmp = directory / f"{user_id}.{ext}.tmp"
    tmp.write_bytes(data)
    tmp.replace(target)
    # A re-upload may change the extension; drop stale siblings.
    for other in AVATAR_EXTENSIONS:
        if other != ext:
            (directory / f"{user_id}.{other}").unlink(missing_ok=True)
    return target


def delete_avatar_file(user_id: str) -> None:
    for ext in AVATAR_EXTENSIONS:
        (_avatar_dir() / f"{user_id}.{ext}").unlink(missing_ok=True)


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
    migrate_legacy_multi_user_tree()
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
            "Auth is enabled and no auth_secret file exists. Generated a stable local secret at %s.",
            SECRET_FILE,
        )
        return generated
    except Exception as exc:
        logger.warning("Failed to load/create auth secret at %s: %s", SECRET_FILE, exc)
        return secrets.token_hex(32)
