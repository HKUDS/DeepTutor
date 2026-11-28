"""Per-owner "bring your own key" provider credentials — storage foundation.

An ordinary user may store their own LLM provider API key for themselves.
The key is one *person's* secret, so — exactly like the Codex OAuth token —
it never enters a model catalog file, shared or per-user. It lives only under
``data/system/user-secrets/<owner>/private/personal-providers/``, the one
branch of the tree the sandbox runner does not mount (see
:func:`deeptutor.multi_user.paths.get_owner_secrets_dir`). The owner-bound
catalog profile that later surfaces this provider carries an empty
``api_key`` and is withheld from grants by
:func:`deeptutor.multi_user.model_access.is_owner_bound`.

This module is the storage + policy foundation only. It persists credentials,
redacts them at the API boundary, gates the feature behind a default-off
deployment policy, and refuses base URLs that point back at the deployment.
It does not wire the key into inference or surface a selectable model; that
is the next slice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from typing import Any

_SCHEMA_VERSION = 1

#: Provider backends a personal key may target. Curated, not free-form: the
#: runtime dispatches by binding, so only backends the next slice will wire
#: are accepted here. ``openai_compat`` is the generic OpenAI-compatible
#: backend (see ``deeptutor.services.provider_registry``).
PERSONAL_PROVIDER_BINDINGS = frozenset({"openai_compat"})

_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class PersonalProviderError(Exception):
    """A personal-provider operation failed, with an API-safe message."""

    def __init__(self, code: str, public_message: str, http_status: int = 400) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.http_status = http_status


def personal_providers_enabled() -> bool:
    """Deployment policy gate. Off by default; an admin opts a deployment in."""
    from deeptutor.services.config.runtime_settings import load_system_settings

    return bool(load_system_settings().get("allow_personal_providers", False))


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _unsafe_path() -> PersonalProviderError:
    return PersonalProviderError(
        "unsafe_storage_path",
        "Personal provider storage uses an unsafe filesystem path.",
        500,
    )


def _assert_safe_directory(path: Path) -> None:
    if path.is_symlink() or _is_reparse_point(path):
        raise _unsafe_path()
    if path.exists() and not path.is_dir():
        raise _unsafe_path()


def _assert_safe_regular_path(path: Path) -> None:
    _assert_safe_directory(path.parent)
    if path.is_symlink() or _is_reparse_point(path):
        raise _unsafe_path()
    if path.exists() and not path.is_file():
        raise _unsafe_path()


def _atomic_write_secret(path: Path, payload: dict[str, Any]) -> None:
    _assert_safe_regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


class PersonalProviderStore:
    """Owner-private credential files below an explicitly supplied secrets root.

    The root is the owner's ``user-secrets`` directory, resolved by the caller
    so a credential and the account that owns it can never disagree. Each
    provider is one ``<id>.v1.json`` file holding the key; nothing here is
    written into a workspace subtree the sandbox shares.
    """

    def __init__(self, owner_root: Path) -> None:
        self.root = Path(owner_root) / "private" / "personal-providers"
        self._lock = threading.Lock()

    def _path(self, provider_id: str) -> Path:
        return self.root / f"{provider_id}.v1.json"

    def _ensure_root(self) -> None:
        private_root = self.root.parent
        private_root.mkdir(parents=True, exist_ok=True)
        _assert_safe_directory(private_root)
        self.root.mkdir(exist_ok=True)
        _assert_safe_directory(self.root)
        os.chmod(private_root, stat.S_IRWXU)
        os.chmod(self.root, stat.S_IRWXU)

    def list_records(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.root.exists():
                return []
            _assert_safe_directory(self.root)
            records: list[dict[str, Any]] = []
            for path in sorted(self.root.glob("*.v1.json")):
                _assert_safe_regular_path(path)
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PersonalProviderError(
                        "credential_corrupt",
                        "Stored personal provider credentials are invalid.",
                        500,
                    ) from exc
                if isinstance(payload, dict):
                    records.append(payload)
            return records

    def put_record(self, provider_id: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_root()
            _atomic_write_secret(self._path(provider_id), record)

    def delete_record(self, provider_id: str) -> bool:
        with self._lock:
            path = self._path(provider_id)
            _assert_safe_regular_path(path)
            if not path.exists():
                return False
            path.unlink()
            return True


def _redacted_record(provider_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """The API-safe view: everything about a provider except its key."""
    return {
        "id": provider_id,
        "label": str(record.get("label") or provider_id),
        "binding": str(record.get("binding") or ""),
        "base_url": str(record.get("base_url") or ""),
        "has_key": bool(record.get("api_key")),
    }


class PersonalProviderService:
    """Policy-gated, owner-scoped credential management with redacted reads."""

    def __init__(self, store: PersonalProviderStore) -> None:
        self._store = store

    def _require_enabled(self) -> None:
        if not personal_providers_enabled():
            raise PersonalProviderError(
                "personal_providers_disabled",
                "Personal providers are not enabled on this deployment.",
                403,
            )

    def list_public(self) -> list[dict[str, Any]]:
        self._require_enabled()
        rows: list[dict[str, Any]] = []
        for record in self._store.list_records():
            provider_id = str(record.get("id") or "")
            if provider_id:
                rows.append(_redacted_record(provider_id, record))
        return rows

    async def save(
        self,
        provider_id: str,
        *,
        api_key: str,
        base_url: str,
        binding: str = "openai_compat",
        label: str = "",
    ) -> dict[str, Any]:
        self._require_enabled()
        if not _PROVIDER_ID_RE.fullmatch(provider_id):
            raise PersonalProviderError("invalid_provider_id", "Invalid provider id.")
        normalized_binding = str(binding or "").strip().lower().replace("-", "_")
        if normalized_binding not in PERSONAL_PROVIDER_BINDINGS:
            raise PersonalProviderError(
                "unsupported_binding",
                "This provider type cannot be used with a personal key.",
            )
        key = str(api_key or "").strip()
        if not key:
            raise PersonalProviderError("missing_api_key", "An API key is required.")
        url = str(base_url or "").strip()
        await _validate_base_url(url)
        record = {
            "schema_version": _SCHEMA_VERSION,
            "id": provider_id,
            "binding": normalized_binding,
            "base_url": url,
            "api_key": key,
            "label": str(label or "").strip()[:120],
        }
        self._store.put_record(provider_id, record)
        return _redacted_record(provider_id, record)

    def delete(self, provider_id: str) -> dict[str, Any]:
        self._require_enabled()
        if not _PROVIDER_ID_RE.fullmatch(provider_id):
            raise PersonalProviderError("invalid_provider_id", "Invalid provider id.")
        removed = self._store.delete_record(provider_id)
        return {"id": provider_id, "removed": removed}


async def _validate_base_url(url: str) -> None:
    """A user-supplied base URL must not be able to aim the app process inward.

    Reuses the self-service MCP guard (``strict=True``): loopback, private and
    cloud-metadata ranges are refused. Resolved off the event loop because the
    check does blocking DNS.
    """
    from deeptutor.services.mcp.network import validate_mcp_url_async

    ok, message = await validate_mcp_url_async(url, strict=True)
    if not ok:
        raise PersonalProviderError("base_url_not_allowed", message or "Invalid base URL.")


_SERVICE_INSTANCES: dict[str, PersonalProviderService] = {}
_SERVICE_LOCK = threading.Lock()


def get_personal_provider_service() -> PersonalProviderService:
    """The service for the account owning the current scope.

    Owner resolution is shared with the credential store via
    :func:`get_owner_secrets_dir`, so a partner turn lands on the directory of
    the human who owns it and a credential can never be keyed to one account
    while written under another.
    """
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    secrets_root = get_owner_secrets_dir()
    key = str(secrets_root)
    with _SERVICE_LOCK:
        service = _SERVICE_INSTANCES.get(key)
        if service is None:
            service = PersonalProviderService(PersonalProviderStore(secrets_root))
            _SERVICE_INSTANCES[key] = service
        return service


__all__ = [
    "PERSONAL_PROVIDER_BINDINGS",
    "PersonalProviderError",
    "PersonalProviderService",
    "PersonalProviderStore",
    "get_personal_provider_service",
    "personal_providers_enabled",
]
