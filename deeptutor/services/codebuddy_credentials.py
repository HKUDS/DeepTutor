"""Read the CodeBuddy desktop/CLI login state without the Agent SDK.

CodeBuddy's IDE plugin and CLI share a single OAuth session file whose name
matches ``authentication.id`` in the CLI's ``product.json``
(``Tencent-Cloud.coding-copilot``). Reading it lets DeepTutor call the
CodeBuddy cloud over plain HTTP the same way the Codex and Copilot providers
do, which keeps the ~130 MB Agent SDK (a bundled headless CLI binary) optional.

The cloud speaks OpenAI ``/chat/completions`` under ``<endpoint>/v2`` and only
needs ``Authorization: Bearer <accessToken>``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
import gzip
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlsplit

_AUTH_FILE_NAME = "Tencent-Cloud.coding-copilot.info"
_AUTH_SUBPATH = ("CodeBuddyExtension", "Data", "Public", "auth")

OVERSEAS_ENDPOINT = "https://www.codebuddy.ai"
INTERNAL_ENDPOINT = "https://copilot.tencent.com"
API_PATH_PREFIX = "/v2"

# Accounts on the China deployment authenticate against copilot.tencent.com;
# the overseas deployment uses www.codebuddy.ai. The model catalogs differ.
_INTERNAL_DOMAIN_HINTS = ("codebuddy.cn", "workbuddy.cn", "copilot.tencent.com")

_EXPIRY_SKEW_SECONDS = 300.0
_REFRESH_PATH = "/v2/auth/token/refresh"
_ACCOUNTS_PATH = "/v2/accounts"

# Used when no cached product config is available. Overseas ids are different,
# but ``default`` resolves on both deployments.
FALLBACK_MODEL_CATALOG = ("default",)


class CodeBuddyAuthUnavailable(RuntimeError):
    """No usable CodeBuddy login state could be found or refreshed."""


@dataclass(frozen=True)
class CodeBuddyCredentials:
    """A CodeBuddy OAuth session read from the shared auth file."""

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    refresh_expires_at: float = 0.0
    user_id: str = ""
    user_label: str = ""
    domain: str = ""
    source: Path | None = None

    @property
    def api_base(self) -> str:
        return resolve_api_base(self.domain)

    def is_expired(self, skew: float = _EXPIRY_SKEW_SECONDS) -> bool:
        if not self.expires_at:
            return False
        return time.time() >= self.expires_at - skew

    def can_refresh(self) -> bool:
        if not self.refresh_token:
            return False
        if not self.refresh_expires_at:
            return True
        return time.time() < self.refresh_expires_at


def _auth_search_dirs() -> list[Path]:
    """Candidate directories holding the shared auth file, per platform.

    These are the same three locations the CodeBuddy CLI lists as its own
    credential paths.
    """
    home = Path.home()
    roots: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(Path(local))
        roots.append(home / "AppData" / "Local")
    elif sys.platform == "darwin":
        roots.append(home / "Library" / "Application Support")
    else:
        data_home = os.environ.get("XDG_DATA_HOME")
        if data_home:
            roots.append(Path(data_home))
        roots.append(home / ".local" / "share")
    return [root.joinpath(*_AUTH_SUBPATH) for root in roots]


def find_auth_file() -> Path | None:
    override = os.environ.get("DEEPTUTOR_CODEBUDDY_AUTH_FILE")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    for directory in _auth_search_dirs():
        candidate = directory / _AUTH_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    # The auth file stores epoch milliseconds.
    return number / 1000.0 if number > 1e11 else number


def load_credentials() -> CodeBuddyCredentials | None:
    """Return the current login state, or ``None`` when not signed in."""
    path = find_auth_file()
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    auth = payload.get("auth")
    account = payload.get("account")
    if not isinstance(auth, dict):
        return None
    token = auth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    account = account if isinstance(account, dict) else {}

    label = ""
    for field in ("nickname", "uin", "uid"):
        value = account.get(field)
        if value:
            label = str(value)
            break

    return CodeBuddyCredentials(
        access_token=token,
        refresh_token=str(auth.get("refreshToken") or ""),
        expires_at=_as_float(auth.get("expiresAt")),
        refresh_expires_at=_as_float(auth.get("refreshExpiresAt")),
        user_id=str(account.get("uid") or ""),
        user_label=label,
        domain=str(auth.get("domain") or ""),
        source=path,
    )


def resolve_api_base(domain: str = "") -> str:
    """Return the ``/v2`` API base for the account's deployment."""
    override = os.environ.get("CODEBUDDY_BASE_URL")
    if override:
        base = override.rstrip("/")
        return base if base.endswith(API_PATH_PREFIX) else base + API_PATH_PREFIX

    environment = (os.environ.get("CODEBUDDY_INTERNET_ENVIRONMENT") or "").strip().lower()
    if environment in {"internal", "ioa"}:
        return INTERNAL_ENDPOINT + API_PATH_PREFIX

    cached = cached_product_endpoint()
    if cached:
        return cached.rstrip("/") + API_PATH_PREFIX

    hint = domain.lower()
    if any(marker in hint for marker in _INTERNAL_DOMAIN_HINTS):
        return INTERNAL_ENDPOINT + API_PATH_PREFIX
    return OVERSEAS_ENDPOINT + API_PATH_PREFIX


# ----------------------------------------------------------------------
# Cached product config (endpoint + model catalog)
# ----------------------------------------------------------------------


def _local_storage_dir() -> Path:
    return Path.home() / ".codebuddy" / "local_storage"


def _iter_cached_product_configs() -> list[dict[str, Any]]:
    """Decode the CLI's cached product configs.

    Entries are JSON strings; large ones wrap gzip+base64 payloads.
    """
    directory = _local_storage_dir()
    if not directory.is_dir():
        return []
    configs: list[dict[str, Any]] = []
    for path in sorted(directory.glob("entry_*.info")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, str):
            continue
        try:
            decoded = json.loads(gzip.decompress(base64.b64decode(raw)).decode("utf-8"))
        except Exception:  # noqa: BLE001 - opaque cache blob, skip on any failure
            continue
        if isinstance(decoded, dict) and decoded.get("models"):
            configs.append(decoded)
    return configs


#: Hosts the cached product config may name. That file belongs to another
#: application, so anything able to write under this account's home can choose
#: where the bearer token is sent — and ``startswith("http")`` accepts plain
#: HTTP to an arbitrary host. An operator who needs a different deployment sets
#: ``CODEBUDDY_BASE_URL``, which ``resolve_api_base`` honours before consulting
#: the cache at all.
_TRUSTED_ENDPOINT_HOSTS = frozenset(
    host
    for host in (
        urlsplit(OVERSEAS_ENDPOINT).hostname,
        urlsplit(INTERNAL_ENDPOINT).hostname,
    )
    if host
)


def _is_trusted_endpoint(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    return parts.scheme == "https" and (parts.hostname or "") in _TRUSTED_ENDPOINT_HOSTS


def cached_product_endpoint() -> str | None:
    for config in _iter_cached_product_configs():
        endpoint = config.get("endpoint")
        if isinstance(endpoint, str) and _is_trusted_endpoint(endpoint):
            return endpoint
    return None


def cached_model_catalog() -> list[str]:
    """Return the model ids the CLI last cached for this deployment."""
    models: list[str] = []
    for config in _iter_cached_product_configs():
        for entry in config.get("models") or []:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if isinstance(model_id, str) and model_id and model_id not in models:
                models.append(model_id)
        if models:
            break
    return models


# ----------------------------------------------------------------------
# Token refresh / account probe
# ----------------------------------------------------------------------


async def refresh_credentials(credentials: CodeBuddyCredentials) -> CodeBuddyCredentials:
    """Exchange the refresh token for a new access token."""
    if not credentials.can_refresh():
        raise CodeBuddyAuthUnavailable(
            "CodeBuddy session expired and cannot be refreshed. Sign in again in the "
            "CodeBuddy IDE plugin or run `codebuddy` and enter `/login`."
        )

    import httpx

    base = credentials.api_base.removesuffix(API_PATH_PREFIX)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=20.0)) as client:
        response = await client.post(
            base + _REFRESH_PATH,
            json={"refreshToken": credentials.refresh_token},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
        )
    if response.status_code >= 400:
        raise CodeBuddyAuthUnavailable(
            "CodeBuddy token refresh failed "
            f"({response.status_code}). Sign in again in the CodeBuddy IDE plugin "
            "or run `codebuddy` and enter `/login`."
        )

    payload = response.json()
    auth = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(auth, dict) and isinstance(auth.get("auth"), dict):
        auth = auth["auth"]
    if not isinstance(auth, dict):
        auth = payload if isinstance(payload, dict) else {}

    token = auth.get("accessToken")
    if not isinstance(token, str) or not token:
        raise CodeBuddyAuthUnavailable("CodeBuddy token refresh returned no access token.")

    return replace(
        credentials,
        access_token=token,
        refresh_token=str(auth.get("refreshToken") or credentials.refresh_token),
        expires_at=_as_float(auth.get("expiresAt")) or credentials.expires_at,
        refresh_expires_at=(
            _as_float(auth.get("refreshExpiresAt")) or credentials.refresh_expires_at
        ),
    )


async def probe_account(credentials: CodeBuddyCredentials) -> str | None:
    """Validate the session and return a display label, or ``None`` if invalid.

    ``/v2/accounts`` is a free call, unlike a completion request.
    """
    import httpx

    base = credentials.api_base.removesuffix(API_PATH_PREFIX)
    headers = {"Authorization": f"Bearer {credentials.access_token}"}
    if credentials.user_id:
        headers["X-User-Id"] = credentials.user_id
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=15.0)) as client:
            response = await client.get(base + _ACCOUNTS_PATH, headers=headers)
    except Exception:  # noqa: BLE001 - network failure is not an auth failure
        return credentials.user_label or None
    if response.status_code >= 400:
        return None

    try:
        accounts = (response.json().get("data") or {}).get("accounts") or []
    except (ValueError, AttributeError):
        return credentials.user_label or None
    for account in accounts:
        if not isinstance(account, dict):
            continue
        if credentials.user_id and account.get("uid") != credentials.user_id:
            continue
        for field in ("nickname", "uin", "uid"):
            value = account.get(field)
            if value:
                return str(value)
    return credentials.user_label or None


__all__ = [
    "CodeBuddyAuthUnavailable",
    "CodeBuddyCredentials",
    "FALLBACK_MODEL_CATALOG",
    "cached_model_catalog",
    "cached_product_endpoint",
    "find_auth_file",
    "load_credentials",
    "probe_account",
    "refresh_credentials",
    "resolve_api_base",
]
