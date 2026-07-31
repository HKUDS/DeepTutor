"""Owner-scoped encrypted storage for user-supplied provider credentials.

BYOK secrets are deliberately kept outside grants, model catalogs and user
workspaces.  The vault exposes metadata for HTTP/UI callers and a separate
secret read used only by an already-authorized runtime resolver.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import threading
from typing import Any
from uuid import uuid4

from . import paths

_SCHEMA_VERSION = 1
_SERVICES = frozenset({"llm", "embedding", "mineru"})
_USER_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_-]{1,64}$")
_thread_lock = threading.RLock()


class ByokVaultError(RuntimeError):
    """Base class for user-facing vault failures."""


class ByokVaultUnavailable(ByokVaultError):
    """The deployment has not supplied a usable encryption key."""


class ByokVaultConflict(ByokVaultError):
    """A profile was changed by another request."""


class ByokProfileNotFound(ByokVaultError):
    """The requested profile does not exist for the current owner."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not _USER_ID_RE.fullmatch(value):
        raise ValueError("Invalid BYOK owner id")
    return value


def _assert_safe_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ByokVaultError("Unsafe BYOK storage path")


def _assert_safe_file(path: Path) -> None:
    _assert_safe_directory(path.parent)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ByokVaultError("Unsafe BYOK storage path")


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode, follow_symlinks=False)
    except (NotImplementedError, TypeError):
        os.chmod(path, mode)


@contextmanager
def _locked_file(path: Path) -> Iterator[None]:
    """Serialize mutations across threads and worker processes."""
    _assert_safe_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_directory(path.parent)
    with path.open("a+b") as handle:
        _chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _assert_safe_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_directory(path.parent)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
        _chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    _assert_safe_file(path)
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ByokVaultError("Stored BYOK data is corrupt") from exc
    if not isinstance(payload, dict):
        raise ByokVaultError("Stored BYOK data is invalid")
    return payload


def _decode_master_key() -> tuple[str, bytes] | None:
    """Read the deployment key without ever persisting it.

    Operators may provide a 32-byte base64/hex value or a secret string.  A
    string is SHA-256-derived so a Docker secret copied with a trailing newline
    remains usable after trimming.  The key id changes when the configured
    value changes, which makes future keyring rotation possible.
    """
    raw = os.getenv("DEEPTUTOR_BYOK_MASTER_KEY", "").strip()
    key_file = os.getenv("DEEPTUTOR_BYOK_MASTER_KEY_FILE", "").strip()
    if not raw and key_file:
        try:
            raw = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ByokVaultUnavailable("BYOK master key file is not readable") from exc
    if not raw:
        return None

    key: bytes | None = None
    try:
        candidate = bytes.fromhex(raw)
        if len(candidate) == 32:
            key = candidate
    except ValueError:
        pass
    if key is None:
        try:
            candidate = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            if len(candidate) == 32:
                key = candidate
        except (ValueError, base64.binascii.Error):
            pass
    if key is None:
        key = hashlib.sha256(raw.encode("utf-8")).digest()
    return hashlib.sha256(key).hexdigest()[:16], key


def _encrypt(secret: str, *, aad: str) -> dict[str, str]:
    key_info = _decode_master_key()
    if key_info is None:
        raise ByokVaultUnavailable("BYOK is unavailable because no master key is configured")
    key_id, key = key_info
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - packaging failure
        raise ByokVaultUnavailable("BYOK encryption support is not installed") from exc
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), aad.encode("utf-8"))
    return {
        "key_id": key_id,
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }


def _decrypt(record: Mapping[str, Any], *, aad: str) -> str:
    key_info = _decode_master_key()
    if key_info is None:
        raise ByokVaultUnavailable("BYOK is unavailable because no master key is configured")
    key_id, key = key_info
    if str(record.get("key_id") or "") != key_id:
        raise ByokVaultUnavailable("BYOK credential key is not available in the current keyring")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = base64.urlsafe_b64decode(str(record["nonce"]))
        ciphertext = base64.urlsafe_b64decode(str(record["ciphertext"]))
        return AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8")).decode("utf-8")
    except (KeyError, ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ByokVaultUnavailable("BYOK credential cannot be decrypted") from exc


def _secret_field(service: str) -> str:
    if service not in _SERVICES:
        raise ValueError(f"Unsupported BYOK service: {service}")
    return "api_token" if service == "mineru" else "api_key"


def _fingerprint(profile_id: str, metadata: Mapping[str, Any]) -> str:
    stable = ":".join(
        [
            profile_id,
            str(metadata.get("service") or ""),
            str(metadata.get("provider") or ""),
            str(metadata.get("model") or ""),
            str(metadata.get("base_url") or ""),
        ]
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


class UserByokCredentialVault:
    """Encrypted, owner-scoped profile and preference store."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else paths.SYSTEM_ROOT / "byok"
        self.lock_path = self.root / "vault.lock"
        self.audit_path = self.root / "audit.jsonl"
        self._thread_lock = threading.RLock()

    def _user_root(self, user_id: str) -> Path:
        uid = _validate_user_id(user_id)
        root = self.root / uid
        self.root.mkdir(parents=True, exist_ok=True)
        _assert_safe_directory(self.root)
        root.mkdir(parents=True, exist_ok=True)
        _assert_safe_directory(root)
        _chmod(self.root, stat.S_IRWXU)
        _chmod(root, stat.S_IRWXU)
        return root

    @contextmanager
    def _locked(self, user_id: str) -> Iterator[Path]:
        with self._thread_lock:
            user_root = self._user_root(user_id)
            with _locked_file(self.lock_path):
                yield user_root

    def _paths(self, user_root: Path) -> tuple[Path, Path]:
        return user_root / "profiles.v1.json", user_root / "state.v1.json"

    def _load_unlocked(self, user_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        profiles_path, state_path = self._paths(user_root)
        profiles = _read_json(profiles_path, {"schema_version": _SCHEMA_VERSION, "profiles": []})
        state = _read_json(
            state_path,
            {"schema_version": _SCHEMA_VERSION, "generation": 0, "preferences": {}},
        )
        raw_profiles = profiles.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ByokVaultError("Stored BYOK profiles are invalid")
        generation = state.get("generation", 0)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ByokVaultError("Stored BYOK state generation is invalid")
        return profiles, state

    @staticmethod
    def _metadata(profile: Mapping[str, Any]) -> dict[str, Any]:
        allowed = (
            "id",
            "service",
            "name",
            "provider",
            "model",
            "base_url",
            "dimension",
            "mode",
            "status",
            "created_at",
            "updated_at",
            "generation",
            "fingerprint",
        )
        return {key: profile[key] for key in allowed if key in profile}

    def _write_unlocked(
        self,
        user_root: Path,
        profiles: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> None:
        profiles_path, state_path = self._paths(user_root)
        _atomic_write_json(profiles_path, profiles)
        _atomic_write_json(state_path, state)

    def _append_audit(self, event: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _assert_safe_directory(self.root)
        _assert_safe_file(self.audit_path)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        _chmod(self.audit_path, stat.S_IRUSR | stat.S_IWUSR)

    def is_available(self) -> bool:
        try:
            return _decode_master_key() is not None
        except ByokVaultUnavailable:
            return False

    def list_profiles(self, user_id: str, *, service: str | None = None) -> list[dict[str, Any]]:
        with self._locked(user_id) as user_root:
            profiles, _state = self._load_unlocked(user_root)
            result = []
            for item in profiles["profiles"]:
                if not isinstance(item, dict):
                    continue
                if service and str(item.get("service") or "") != service:
                    continue
                result.append(self._metadata(item) | {"configured": "encrypted_secret" in item})
            return result

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        with self._locked(user_id) as user_root:
            _profiles, state = self._load_unlocked(user_root)
            preferences = state.get("preferences")
            return dict(preferences) if isinstance(preferences, dict) else {}

    def save_preferences(self, user_id: str, preferences: Mapping[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for service in _SERVICES:
            value = preferences.get(service)
            if not isinstance(value, Mapping):
                continue
            source = str(value.get("source") or "").strip()
            profile_id = str(value.get("profile_id") or "").strip()
            if source not in {"platform", "byok"}:
                raise ValueError("BYOK preference source must be platform or byok")
            clean[service] = {"source": source, **({"profile_id": profile_id} if profile_id else {})}
        with self._locked(user_id) as user_root:
            profiles, state = self._load_unlocked(user_root)
            state = {
                **state,
                "schema_version": _SCHEMA_VERSION,
                "generation": int(state.get("generation", 0)) + 1,
                "preferences": clean,
                "updated_at": _now(),
            }
            self._write_unlocked(user_root, profiles, state)
            self._append_audit({"at": _now(), "event": "preferences_updated", "user_id": user_id})
            return clean

    def save_profile(
        self,
        user_id: str,
        metadata: Mapping[str, Any],
        secret: str | None,
        *,
        profile_id: str | None = None,
        expected_generation: int | None = None,
    ) -> dict[str, Any]:
        service = str(metadata.get("service") or "").strip()
        if service not in _SERVICES:
            raise ValueError("BYOK service must be llm, embedding, or mineru")
        secret = str(secret or "")
        key = _secret_field(service)
        with self._locked(user_id) as user_root:
            profiles, state = self._load_unlocked(user_root)
            rows = [item for item in profiles["profiles"] if isinstance(item, dict)]
            existing = next((item for item in rows if item.get("id") == profile_id), None)
            current_generation = int(existing.get("generation", 0)) if existing else None
            if existing is not None and expected_generation is not None and current_generation != expected_generation:
                raise ByokVaultConflict("BYOK profile changed; reload and retry")
            if existing is None and profile_id:
                raise ByokProfileNotFound("BYOK profile not found")
            if not secret and existing is not None:
                old_generation = int(existing.get("generation", 0))
                old_aad = f"{_SCHEMA_VERSION}:{user_id}:{service}:{profile_id}:{old_generation}"
                encrypted = existing.get("encrypted_secret")
                if not isinstance(encrypted, Mapping):
                    raise ByokVaultError("BYOK profile has no encrypted secret")
                secret = _decrypt(encrypted, aad=old_aad)
            if not secret:
                raise ValueError("A BYOK secret is required")
            resolved_id = str(profile_id or f"p_{uuid4().hex}")
            next_generation = (current_generation or 0) + 1
            now = _now()
            clean = {
                "id": resolved_id,
                "service": service,
                "name": str(metadata.get("name") or "").strip()[:80],
                "provider": str(metadata.get("provider") or "").strip(),
                "model": str(metadata.get("model") or "").strip(),
                "base_url": str(metadata.get("base_url") or "").strip(),
                "dimension": int(metadata.get("dimension") or 0),
                "mode": str(metadata.get("mode") or ("cloud" if service == "mineru" else "")),
                "status": "configured",
                "created_at": str(existing.get("created_at") or now) if existing else now,
                "updated_at": now,
                "generation": next_generation,
            }
            aad = f"{_SCHEMA_VERSION}:{user_id}:{service}:{resolved_id}:{next_generation}"
            clean["encrypted_secret"] = _encrypt(secret, aad=aad)
            clean["fingerprint"] = _fingerprint(resolved_id, clean)
            if existing is None:
                rows.append(clean)
            else:
                index = rows.index(existing)
                rows[index] = clean
            next_state = {
                **state,
                "schema_version": _SCHEMA_VERSION,
                "generation": int(state.get("generation", 0)) + 1,
                "updated_at": now,
            }
            self._write_unlocked(
                user_root,
                {"schema_version": _SCHEMA_VERSION, "profiles": rows},
                next_state,
            )
            self._append_audit(
                {
                    "at": now,
                    "event": "profile_saved",
                    "user_id": user_id,
                    "service": service,
                    "profile_id": resolved_id,
                    "generation": next_generation,
                }
            )
            return self._metadata(clean) | {"configured": True}

    def delete_profile(
        self,
        user_id: str,
        profile_id: str,
        *,
        expected_generation: int | None = None,
    ) -> bool:
        with self._locked(user_id) as user_root:
            profiles, state = self._load_unlocked(user_root)
            rows = [item for item in profiles["profiles"] if isinstance(item, dict)]
            existing = next((item for item in rows if item.get("id") == profile_id), None)
            if existing is None:
                return False
            if expected_generation is not None and int(existing.get("generation", 0)) != expected_generation:
                raise ByokVaultConflict("BYOK profile changed; reload and retry")
            rows = [item for item in rows if item is not existing]
            next_state = {
                **state,
                "schema_version": _SCHEMA_VERSION,
                "generation": int(state.get("generation", 0)) + 1,
                "updated_at": _now(),
            }
            self._write_unlocked(
                user_root,
                {"schema_version": _SCHEMA_VERSION, "profiles": rows},
                next_state,
            )
            self._append_audit(
                {
                    "at": _now(),
                    "event": "profile_deleted",
                    "user_id": user_id,
                    "service": existing.get("service"),
                    "profile_id": profile_id,
                }
            )
            return True

    def load_secret(self, user_id: str, profile_id: str) -> tuple[dict[str, Any], str]:
        """Resolve a secret for trusted server-side runtime code only."""
        with self._locked(user_id) as user_root:
            profiles, _state = self._load_unlocked(user_root)
            profile = next(
                (item for item in profiles["profiles"] if isinstance(item, dict) and item.get("id") == profile_id),
                None,
            )
            if profile is None:
                raise ByokProfileNotFound("BYOK profile not found")
            service = str(profile.get("service") or "")
            encrypted = profile.get("encrypted_secret")
            if not isinstance(encrypted, Mapping):
                raise ByokVaultError("BYOK profile has no encrypted secret")
            generation = int(profile.get("generation", 0))
            aad = f"{_SCHEMA_VERSION}:{user_id}:{service}:{profile_id}:{generation}"
            secret = _decrypt(encrypted, aad=aad)
            return self._metadata(profile), secret


def get_user_byok_vault() -> UserByokCredentialVault:
    return UserByokCredentialVault()


__all__ = [
    "ByokProfileNotFound",
    "ByokVaultConflict",
    "ByokVaultError",
    "ByokVaultUnavailable",
    "UserByokCredentialVault",
    "get_user_byok_vault",
]
