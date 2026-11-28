"""GitHub device login and Copilot token exchange."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
import os
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import webbrowser

import httpx

from deeptutor.services.github_copilot_storage import (
    CopilotAuthState,
    GitHubCopilotStorage,
    GitHubToken,
    get_copilot_owner_scope,
    get_github_copilot_storage,
)

DEFAULT_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
DEFAULT_GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEFAULT_GITHUB_USER_URL = "https://api.github.com/user"
DEFAULT_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_COPILOT_BASE_URL = "https://api.githubcopilot.com"
GITHUB_COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_COPILOT_SCOPE = "read:user"
USER_AGENT = "DeepTutor/1"
EDITOR_VERSION = "vscode/1.99.0"
EDITOR_PLUGIN_VERSION = "copilot-chat/0.26.0"
_LONG_LIVED_TOKEN_SECONDS = 315_360_000
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_Origin = tuple[str, str, int | None]


@dataclass(frozen=True)
class CopilotAccess:
    token: str
    expires_at: float
    api_base: str


@dataclass(frozen=True)
class DeviceFlowPrompt:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    interval: int
    expires_in: int


def _resolve(env_var: str, default: str) -> str:
    value = os.environ.get(env_var)
    return value.strip() if value and value.strip() else default


def _parse_origin(url: str, *, allow_localhost_http: bool = False) -> _Origin | None:
    cleaned = (url or "").strip()
    if not cleaned:
        return None
    try:
        parts = urlsplit(cleaned)
    except ValueError:
        return None
    if parts.username or parts.password:
        return None
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return None
    scheme = parts.scheme.lower()
    if scheme == "https":
        pass
    elif scheme == "http" and allow_localhost_http and hostname in _LOCALHOST_HOSTS:
        pass
    else:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None
    return (scheme, hostname, port)


def _allowed_verification_origins(device_code_url: str) -> set[_Origin]:
    allowed: set[_Origin] = {("https", "github.com", None)}
    configured = _parse_origin(device_code_url, allow_localhost_http=True)
    if configured is not None:
        allowed.add(configured)
    return allowed


def _safe_verification_url(
    url: str,
    *,
    allowed_origins: set[_Origin],
    required_origin: _Origin | None = None,
) -> tuple[str, _Origin] | None:
    cleaned = (url or "").strip()
    origin = _parse_origin(cleaned, allow_localhost_http=True)
    if origin is None or origin not in allowed_origins:
        return None
    if required_origin is not None and origin != required_origin:
        return None
    return cleaned, origin


def _evict_owner_providers(owner_identity: str) -> None:
    """Evict only cached Copilot providers belonging to ``owner_identity``."""
    if not owner_identity:
        return
    try:
        from deeptutor.services.llm.provider_factory import evict_runtime_providers_for_owner

        evict_runtime_providers_for_owner(owner_identity)
    except Exception:  # noqa: BLE001 - best-effort cache invalidation
        pass
    try:
        from deeptutor.runtime.agentic.client import evict_agentic_clients_for_owner

        evict_agentic_clients_for_owner(owner_identity)
    except Exception:  # noqa: BLE001 - best-effort cache invalidation
        pass


async def _request_device_code(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    device_code_url: str,
) -> DeviceFlowPrompt:
    response = await client.post(
        device_code_url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        data={"client_id": client_id, "scope": GITHUB_COPILOT_SCOPE},
    )
    response.raise_for_status()
    payload = response.json()
    device_code = str(payload.get("device_code") or "").strip()
    user_code = str(payload.get("user_code") or "").strip()
    raw_uri = str(payload.get("verification_uri") or "").strip()
    raw_complete = str(payload.get("verification_uri_complete") or "").strip()
    allowed_origins = _allowed_verification_origins(device_code_url)

    primary = _safe_verification_url(raw_uri or raw_complete, allowed_origins=allowed_origins)
    if not device_code or not user_code or primary is None:
        raise RuntimeError("GitHub device authorization response was invalid.")
    verification_uri, primary_origin = primary

    verification_complete = verification_uri
    if raw_complete:
        complete_parsed = _safe_verification_url(
            raw_complete,
            allowed_origins=allowed_origins,
            required_origin=primary_origin,
        )
        if complete_parsed is None:
            raise RuntimeError("GitHub device verification URL origin mismatch.")
        verification_complete = complete_parsed[0]

    interval = max(1, int(payload.get("interval") or 5))
    expires_in = max(1, int(payload.get("expires_in") or 900))
    return DeviceFlowPrompt(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_complete,
        interval=interval,
        expires_in=expires_in,
    )


async def _fetch_github_account_id(
    client: httpx.AsyncClient,
    *,
    user_url: str,
    access_token: str,
) -> str | None:
    user = await client.get(
        user_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    user.raise_for_status()
    user_payload = user.json()
    account_id = user_payload.get("login") or user_payload.get("id")
    return str(account_id) if account_id else None


def load_github_token() -> GitHubToken | None:
    token = get_github_copilot_storage().load()
    if not token or not getattr(token, "access", None):
        return None
    return token


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
    }


async def login_github_copilot(
    print_fn: Callable[[str], None] | None = None,
) -> GitHubToken:
    """Run GitHub's device flow and persist the resulting OAuth token."""
    storage = get_github_copilot_storage()
    printer = print_fn or print
    timeout = httpx.Timeout(20.0, connect=20.0)
    client_id = _resolve("DEEPTUTOR_GITHUB_COPILOT_CLIENT_ID", GITHUB_COPILOT_CLIENT_ID)
    device_code_url = _resolve("DEEPTUTOR_GITHUB_DEVICE_CODE_URL", DEFAULT_GITHUB_DEVICE_CODE_URL)
    access_token_url = _resolve(
        "DEEPTUTOR_GITHUB_ACCESS_TOKEN_URL", DEFAULT_GITHUB_ACCESS_TOKEN_URL
    )
    user_url = _resolve("DEEPTUTOR_GITHUB_USER_URL", DEFAULT_GITHUB_USER_URL)

    cli_generation: int | None = None
    begin_cli_login = getattr(storage, "begin_cli_login", None)
    commit_token = getattr(storage, "commit_token", None)
    if callable(begin_cli_login) and callable(commit_token):
        cli_generation = await asyncio.to_thread(begin_cli_login)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=True,
    ) as client:
        prompt = await _request_device_code(
            client,
            client_id=client_id,
            device_code_url=device_code_url,
        )

        printer(f"Open: {prompt.verification_uri}")
        printer(f"Code: {prompt.user_code}")
        if prompt.verification_uri_complete:
            with suppress(webbrowser.Error, OSError):
                webbrowser.open(prompt.verification_uri_complete)

        deadline = time.monotonic() + prompt.expires_in
        current_interval = prompt.interval
        access_token = ""
        token_expires_in = _LONG_LIVED_TOKEN_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(current_interval)
            poll = await client.post(
                access_token_url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                data={
                    "client_id": client_id,
                    "device_code": prompt.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            poll.raise_for_status()
            poll_payload = poll.json()
            access_token = str(poll_payload.get("access_token") or "")
            if access_token:
                token_expires_in = int(poll_payload.get("expires_in") or _LONG_LIVED_TOKEN_SECONDS)
                break

            error = poll_payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                current_interval += 5
                continue
            if error == "expired_token":
                raise RuntimeError("GitHub device code expired. Please run login again.")
            if error == "access_denied":
                raise RuntimeError("GitHub device login was denied.")
            if error:
                raise RuntimeError(str(poll_payload.get("error_description") or error))
        else:
            raise RuntimeError("GitHub device login timed out.")

        account_id = await _fetch_github_account_id(
            client,
            user_url=user_url,
            access_token=access_token,
        )

    token = GitHubToken(
        access=access_token,
        expires=int((time.time() + token_expires_in) * 1000),
        account_id=account_id,
    )
    if cli_generation is not None and callable(commit_token):
        committed, _ = await asyncio.to_thread(
            commit_token,
            token,
            expected_generation=cli_generation,
        )
        if not committed:
            raise RuntimeError(
                "GitHub Copilot login was cancelled or superseded. Please run login again."
            )
    else:
        await asyncio.to_thread(storage.save, token)
    credentials_path = getattr(storage, "credentials_path", None)
    if credentials_path is not None:
        _evict_owner_providers(str(credentials_path))
    return token


async def exchange_copilot_token(github_token: str | None = None) -> CopilotAccess:
    """Exchange a GitHub OAuth token for a short-lived Copilot API token."""
    if not github_token:
        stored = await asyncio.to_thread(load_github_token)
        github_token = str(getattr(stored, "access", "") or "")
    if not github_token:
        raise RuntimeError(
            "GitHub Copilot is not logged in. Run: deeptutor provider login github-copilot"
        )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=20.0),
        follow_redirects=False,
        trust_env=True,
    ) as client:
        response = await client.get(
            _resolve("DEEPTUTOR_COPILOT_TOKEN_URL", DEFAULT_COPILOT_TOKEN_URL),
            headers=_github_headers(github_token),
        )
        response.raise_for_status()
        payload = response.json()

    token = str(payload.get("token") or "")
    if not token:
        raise RuntimeError("GitHub Copilot token exchange returned no token.")
    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        expires_at = time.time() + int(payload.get("refresh_in") or 1500)
    endpoints = payload.get("endpoints")
    api_base = (
        str(endpoints.get("api"))
        if isinstance(endpoints, dict) and endpoints.get("api")
        else _resolve("DEEPTUTOR_COPILOT_BASE_URL", DEFAULT_COPILOT_BASE_URL)
    )
    return CopilotAccess(token=token, expires_at=float(expires_at), api_base=api_base)


@dataclass(frozen=True)
class CopilotModel:
    id: str
    supported_endpoints: tuple[str, ...] | None = None


async def fetch_github_copilot_models(access: CopilotAccess) -> list[CopilotModel]:
    """Keep protocol metadata alongside IDs; omit explicitly unsupported models."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=20.0),
        follow_redirects=True,
        trust_env=True,
    ) as client:
        response = await client.get(
            f"{access.api_base.rstrip('/')}/models",
            headers={
                "Authorization": f"Bearer {access.token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Editor-Version": EDITOR_VERSION,
                "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
            },
        )
        response.raise_for_status()
        payload = response.json()

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    models: dict[str, CopilotModel] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        policy = row.get("policy")
        if (
            not isinstance(model_id, str)
            or not model_id
            or row.get("model_picker_enabled") is False
            or (isinstance(policy, dict) and policy.get("state") == "disabled")
        ):
            continue
        raw_endpoints = row.get("supported_endpoints")
        endpoints = None
        if raw_endpoints is not None:
            if not isinstance(raw_endpoints, list):
                continue
            endpoints = tuple(
                endpoint
                for endpoint in raw_endpoints
                if endpoint in ("/responses", "/chat/completions")
            )
            if not endpoints:
                continue
        models[model_id] = CopilotModel(model_id, endpoints)
    return list(models.values())


async def list_github_copilot_models() -> list[str]:
    access = await exchange_copilot_token()
    return [f"github-copilot/{model.id}" for model in await fetch_github_copilot_models(access)]


def _map_copilot_error_code(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPError):
        return "network_error"
    message = str(exc).lower()
    if "expired" in message or "timed out" in message or "timeout" in message:
        return "expired"
    if "denied" in message:
        return "access_denied"
    return "auth_failed"


def _status_payload(
    *,
    connection: str,
    operation_state: str | None = None,
    verification_uri: str | None = None,
    user_code: str | None = None,
    expires_at: float | None = None,
    account_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    # Invariant: never report "waiting" without an active authorizing prompt.
    if operation_state == "waiting" and (
        connection != "authorizing" or not verification_uri or not user_code
    ):
        operation_state = None
    return {
        "connection": connection,
        "operation_state": operation_state,
        "verification_uri": verification_uri,
        "user_code": user_code,
        "expires_at": expires_at,
        "account_id": account_id,
        "error_code": error_code,
    }


def _is_token_expired(token: GitHubToken, *, now_ms: int | None = None) -> bool:
    if token.expires <= 0:
        return False
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return token.expires <= current_ms


class GitHubCopilotAuthService:
    """Owner-scoped, cross-worker-safe coordinator for GitHub Copilot device login."""

    def __init__(self, storage: GitHubCopilotStorage) -> None:
        self._storage = storage
        self._state_lock = threading.Lock()
        self._active_generation: int | None = None
        self._active_loop: asyncio.AbstractEventLoop | None = None
        self._active_task: asyncio.Task[Any] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._last_status: dict[str, Any] = _status_payload(connection="disconnected")

    def public_status(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._last_status)

    def _record_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._state_lock:
            self._last_status = dict(payload)
        return payload

    def _local_task_orphaned(self, generation: int) -> bool:
        """True if this process launched ``generation`` and its loop/task died."""
        with self._state_lock:
            if self._active_generation != generation:
                return False
            loop = self._active_loop
            task = self._active_task
        if loop is not None and loop.is_closed():
            return True
        if task is not None and task.done():
            return True
        return False

    def _clear_local_task_if(self, generation: int | None = None) -> tuple[
        asyncio.AbstractEventLoop | None,
        asyncio.Task[Any] | None,
    ]:
        with self._state_lock:
            if generation is not None and self._active_generation != generation:
                return None, None
            loop = self._active_loop
            task = self._active_task
            self._active_generation = None
            self._active_loop = None
            self._active_task = None
            return loop, task

    def _build_status_from_durable(
        self,
        token: GitHubToken | None,
        state: CopilotAuthState,
    ) -> dict[str, Any]:
        now = time.time()

        # Active unexpired waiting device-flow prompt (visible across workers).
        if (
            state.operation_state == "waiting"
            and state.verification_uri
            and state.user_code
            and state.expires_at is not None
        ):
            if self._local_task_orphaned(state.generation):
                self._clear_local_task_if(state.generation)
                with suppress(RuntimeError, OSError):
                    _, state = self._storage.mark_flow_failed(
                        expected_generation=state.generation,
                        error_code="auth_failed",
                    )
            elif state.expires_at <= now:
                self._clear_local_task_if(state.generation)
                with suppress(RuntimeError, OSError):
                    _, state = self._storage.mark_flow_failed(
                        expected_generation=state.generation,
                        error_code="expired",
                    )
            else:
                return _status_payload(
                    connection="authorizing",
                    operation_state="waiting",
                    verification_uri=state.verification_uri,
                    user_code=state.user_code,
                    expires_at=state.expires_at,
                    account_id=token.account_id if token is not None else None,
                    error_code=None,
                )

        # In-flight start reservation that hasn't published a code yet.
        if (
            state.operation_state == "starting"
            and state.expires_at is not None
            and state.expires_at > now
            and not self._local_task_orphaned(state.generation)
        ):
            return _status_payload(
                connection="authorizing",
                operation_state=None,
                account_id=token.account_id if token is not None else None,
            )

        if token is not None:
            if _is_token_expired(token):
                return _status_payload(
                    connection="error",
                    operation_state="failed",
                    account_id=token.account_id,
                    error_code="expired",
                )
            if state.operation_state == "failed" and state.error_code:
                return _status_payload(
                    connection="connected",
                    operation_state="failed",
                    account_id=token.account_id,
                    error_code=state.error_code,
                )
            return _status_payload(
                connection="connected",
                operation_state="cancelled" if state.operation_state == "cancelled" else "completed",
                account_id=token.account_id,
                error_code=None,
            )

        if state.operation_state == "failed" and state.error_code:
            return _status_payload(
                connection="error",
                operation_state="failed",
                error_code=state.error_code,
            )
        if state.operation_state == "cancelled":
            return _status_payload(
                connection="disconnected",
                operation_state="cancelled",
            )
        return _status_payload(connection="disconnected")

    def _read_durable_status_sync(self) -> dict[str, Any]:
        try:
            token, state = self._storage.read_snapshot()
        except (RuntimeError, OSError):
            return _status_payload(
                connection="error",
                operation_state="failed",
                error_code="credentials_invalid",
            )
        return self._build_status_from_durable(token, state)

    async def status(self) -> dict[str, Any]:
        payload = await asyncio.to_thread(self._read_durable_status_sync)
        return self._record_status(payload)

    async def start_login(self) -> dict[str, Any]:
        try:
            reserved, state = await asyncio.to_thread(self._storage.reserve_device_flow)
        except (RuntimeError, OSError):
            return self._record_status(
                _status_payload(
                    connection="error",
                    operation_state="failed",
                    error_code="credentials_invalid",
                )
            )

        if not reserved:
            # Another call or worker already has an active unexpired prompt.
            return await self.status()

        generation = state.generation
        client_id = _resolve("DEEPTUTOR_GITHUB_COPILOT_CLIENT_ID", GITHUB_COPILOT_CLIENT_ID)
        device_code_url = _resolve("DEEPTUTOR_GITHUB_DEVICE_CODE_URL", DEFAULT_GITHUB_DEVICE_CODE_URL)
        access_token_url = _resolve(
            "DEEPTUTOR_GITHUB_ACCESS_TOKEN_URL", DEFAULT_GITHUB_ACCESS_TOKEN_URL
        )
        user_url = _resolve("DEEPTUTOR_GITHUB_USER_URL", DEFAULT_GITHUB_USER_URL)

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=20.0),
                follow_redirects=False,
                trust_env=True,
            ) as client:
                prompt = await _request_device_code(
                    client,
                    client_id=client_id,
                    device_code_url=device_code_url,
                )
        except asyncio.CancelledError:
            with suppress(RuntimeError, OSError):
                await asyncio.to_thread(
                    self._storage.mark_flow_failed,
                    expected_generation=generation,
                    error_code="auth_failed",
                )
            raise
        except Exception as exc:  # noqa: BLE001 - mapped to stable error code
            error_code = _map_copilot_error_code(exc)
            with suppress(RuntimeError, OSError):
                await asyncio.to_thread(
                    self._storage.mark_flow_failed,
                    expected_generation=generation,
                    error_code=error_code,
                )
            return await self.status()

        expires_at = time.time() + prompt.expires_in
        try:
            published, _ = await asyncio.to_thread(
                self._storage.publish_device_prompt,
                expected_generation=generation,
                verification_uri=prompt.verification_uri_complete or prompt.verification_uri,
                user_code=prompt.user_code,
                expires_at=expires_at,
            )
        except asyncio.CancelledError:
            self._schedule_orphan_cleanup(generation)
            raise
        except (RuntimeError, OSError):
            return self._record_status(
                _status_payload(
                    connection="error",
                    operation_state="failed",
                    error_code="credentials_invalid",
                )
            )

        if not published:
            # Cancelled or superseded while requesting the device code.
            return await self.status()

        loop = asyncio.get_running_loop()
        task = loop.create_task(
            self._poll_device_flow(
                prompt=prompt,
                generation=generation,
                client_id=client_id,
                access_token_url=access_token_url,
                user_url=user_url,
            )
        )
        with self._state_lock:
            self._active_generation = generation
            self._active_loop = loop
            self._active_task = task
            self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return await self.status()

    async def _cancel_local_task(self) -> None:
        loop, task = self._clear_local_task_if()
        if task is None or task.done():
            return
        current_loop = asyncio.get_running_loop()
        if loop is current_loop:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        elif loop is not None and not loop.is_closed():
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(task.cancel)

    async def cancel_login(self) -> dict[str, Any]:
        try:
            await asyncio.to_thread(self._storage.cancel_flow)
        except (RuntimeError, OSError):
            await self._cancel_local_task()
            return self._record_status(
                _status_payload(
                    connection="error",
                    operation_state="failed",
                    error_code="credentials_invalid",
                )
            )
        await self._cancel_local_task()
        return await self.status()

    async def logout(self) -> dict[str, Any]:
        try:
            await asyncio.to_thread(self._storage.clear_credentials)
        except (RuntimeError, OSError):
            await self._cancel_local_task()
            return self._record_status(
                _status_payload(
                    connection="error",
                    operation_state="failed",
                    error_code="credentials_invalid",
                )
            )
        await self._cancel_local_task()
        _evict_owner_providers(str(self._storage.credentials_path))
        return await self.status()

    def _schedule_orphan_cleanup(self, generation: int) -> None:
        """Mark ``generation`` failed (and bump generation) off the event loop."""
        storage = self._storage

        def _cleanup_thread() -> None:
            with suppress(RuntimeError, OSError):
                storage.mark_flow_failed(
                    expected_generation=generation,
                    error_code="auth_failed",
                )

        threading.Thread(target=_cleanup_thread, daemon=True).start()

    async def _generation_status(self, generation: int) -> str:
        try:
            state = await asyncio.to_thread(self._storage.read_state)
        except (RuntimeError, OSError):
            return "storage_error"
        return "active" if state.generation == generation else "superseded"

    async def _poll_device_flow(
        self,
        *,
        prompt: DeviceFlowPrompt,
        generation: int,
        client_id: str,
        access_token_url: str,
        user_url: str,
    ) -> None:
        deadline = time.monotonic() + prompt.expires_in
        current_interval = prompt.interval
        access_token = ""
        token_expires_in = _LONG_LIVED_TOKEN_SECONDS
        error_code: str | None = None
        account_id: str | None = None

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=20.0),
                follow_redirects=False,
                trust_env=True,
            ) as client:
                while time.monotonic() < deadline:
                    await asyncio.sleep(current_interval)
                    gen_status = await self._generation_status(generation)
                    if gen_status == "superseded":
                        return
                    if gen_status == "storage_error":
                        error_code = "credentials_invalid"
                        break
                    poll = await client.post(
                        access_token_url,
                        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                        data={
                            "client_id": client_id,
                            "device_code": prompt.device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                    poll.raise_for_status()
                    poll_payload = poll.json()
                    access_token = str(poll_payload.get("access_token") or "")
                    if access_token:
                        token_expires_in = int(
                            poll_payload.get("expires_in") or _LONG_LIVED_TOKEN_SECONDS
                        )
                        break

                    error = poll_payload.get("error")
                    if error == "authorization_pending":
                        continue
                    if error == "slow_down":
                        current_interval += 5
                        continue
                    if error == "expired_token":
                        error_code = "expired"
                        break
                    if error == "access_denied":
                        error_code = "access_denied"
                        break
                    if error:
                        error_code = "auth_failed"
                        break
                else:
                    error_code = "expired"

                if access_token and not error_code:
                    gen_status = await self._generation_status(generation)
                    if gen_status == "superseded":
                        return
                    if gen_status == "storage_error":
                        error_code = "credentials_invalid"
                    else:
                        account_id = await _fetch_github_account_id(
                            client,
                            user_url=user_url,
                            access_token=access_token,
                        )
        except asyncio.CancelledError:
            # Never block the event loop waiting on auth.lock; hand cleanup to a
            # worker thread (and await briefly if loop permits).
            try:
                await asyncio.shield(
                    asyncio.to_thread(
                        self._storage.mark_flow_failed,
                        expected_generation=generation,
                        error_code="auth_failed",
                    )
                )
            except BaseException:
                self._schedule_orphan_cleanup(generation)
            return
        except Exception as exc:  # noqa: BLE001 - mapped to stable error code
            error_code = _map_copilot_error_code(exc)

        try:
            if error_code or not access_token:
                await asyncio.to_thread(
                    self._storage.mark_flow_failed,
                    expected_generation=generation,
                    error_code=error_code or "auth_failed",
                )
            else:
                token = GitHubToken(
                    access=access_token,
                    expires=int((time.time() + token_expires_in) * 1000),
                    account_id=account_id,
                )
                committed, _ = await asyncio.to_thread(
                    self._storage.commit_token,
                    token,
                    expected_generation=generation,
                )
                if committed:
                    _evict_owner_providers(str(self._storage.credentials_path))
        except (RuntimeError, OSError):
            with suppress(RuntimeError, OSError):
                await asyncio.to_thread(
                    self._storage.mark_flow_failed,
                    expected_generation=generation,
                    error_code="credentials_invalid",
                )
            self._record_status(
                _status_payload(
                    connection="error",
                    operation_state="failed",
                    error_code="credentials_invalid",
                )
            )
            return
        finally:
            self._clear_local_task_if(generation)

        with suppress(Exception):
            await self.status()

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        with self._state_lock:
            self._tasks.discard(task)
            if self._active_task is task:
                self._active_task = None
                self._active_loop = None
                self._active_generation = None
        if not task.cancelled():
            with suppress(Exception):
                task.exception()


_auth_services_lock = threading.Lock()
_auth_services: dict[tuple[str, str], GitHubCopilotAuthService] = {}


def get_github_copilot_auth_service() -> GitHubCopilotAuthService:
    """Return the ``(runtime_home, owner_id)``-scoped GitHub Copilot auth service."""
    runtime_home, owner_id = get_copilot_owner_scope()
    storage = get_github_copilot_storage()
    key = (str(runtime_home), owner_id)
    with _auth_services_lock:
        service = _auth_services.get(key)
        if service is None:
            service = GitHubCopilotAuthService(storage)
            _auth_services[key] = service
        else:
            # Always keep the un-resolved storage path for this trusted scope so
            # symlink/reparse checks run on every operation.
            service._storage = storage
        return service


__all__ = [
    "CopilotAccess",
    "CopilotModel",
    "DeviceFlowPrompt",
    "GitHubCopilotAuthService",
    "exchange_copilot_token",
    "fetch_github_copilot_models",
    "get_github_copilot_auth_service",
    "get_github_copilot_storage",
    "list_github_copilot_models",
    "load_github_token",
    "login_github_copilot",
]
