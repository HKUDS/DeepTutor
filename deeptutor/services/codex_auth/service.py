"""Codex OAuth orchestration and managed model-catalog integration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import secrets
import shutil
import time
from typing import Any

import httpx

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.runtime_settings import load_system_settings

from .catalog import CodexModelCatalog
from .constants import (
    CODEX_CALLBACK_PATH,
    CODEX_CALLBACK_PORTS,
    CODEX_LOGIN_TIMEOUT_SECONDS,
)
from .contracts import (
    CatalogSnapshot,
    CodexAuthError,
    CodexCredentials,
    CodexModel,
    CodexToken,
    decode_codex_jwt,
)
from .oauth import (
    CodexOAuthClient,
    LoopbackCallback,
    OAuthCallbackResult,
    PkceCodes,
    build_authorize_url,
    generate_pkce,
    oauth_state_matches,
)
from .storage import CodexCredentialStore

logger = logging.getLogger(__name__)

MANAGED_BY = "openai_codex_oauth"
CODEX_PROFILE_ID = "llm-profile-openai-codex-managed"


@dataclass(frozen=True)
class CatalogSyncResult:
    catalog: dict[str, Any]
    activated: bool


@dataclass
class _LoginOperation:
    operation_id: str
    state_secret: str
    pkce: PkceCodes
    callback: Any
    redirect_uri: str
    authorize_url: str
    deadline: float
    expected_generation: int
    operation_state: str = "waiting"
    error_code: str | None = None
    activated: bool = False
    task: asyncio.Task[None] | None = None


def ssh_forward_command(callback_port: int, forward_port: int) -> str:
    return f"ssh -N -L {callback_port}:127.0.0.1:{forward_port} <ssh-user>@<server-host>"


def codex_model_id(slug: str) -> str:
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]
    return f"llm-model-openai-codex-{digest}"


def _managed_model(model: CodexModel) -> dict[str, Any]:
    managed = {
        "id": codex_model_id(model.slug),
        "name": model.display_name,
        "model": model.slug,
        "managed_by": MANAGED_BY,
        "codex_priority": model.priority,
        "codex_default_reasoning_level": model.default_reasoning_level,
        "codex_supported_reasoning_levels": list(model.supported_reasoning_levels),
        "codex_supports_reasoning_summary": model.supports_reasoning_summary,
        "codex_supports_parallel_tool_calls": model.supports_parallel_tool_calls,
        "codex_use_responses_lite": model.use_responses_lite,
    }
    context_window = model.context_window or model.max_context_window
    if context_window is not None:
        managed["context_window"] = str(context_window)
        managed["context_window_source"] = "metadata"
    return managed


def _managed_profile(snapshot: CatalogSnapshot) -> dict[str, Any]:
    return {
        "id": CODEX_PROFILE_ID,
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "base_url": "https://chatgpt.com/backend-api",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "managed_by": MANAGED_BY,
        "read_only": True,
        # A Codex token authorizes exactly one person's ChatGPT plan, so this
        # profile stays with the operator who signed in and is never shared with
        # other users through grants (see deeptutor/multi_user/model_access.py).
        "owner_bound": True,
        "models": [_managed_model(model) for model in snapshot.models],
    }


def sync_codex_catalog(
    catalog_service: ModelCatalogService,
    snapshot: CatalogSnapshot,
) -> CatalogSyncResult:
    """Publish the managed Codex profile into the shared model catalog.

    Choosing the active model stays the operator's call. The only automatic
    activation happens when the deployment has no active LLM at all, so a fresh
    install is usable right after sign-in without ever silently replacing a
    model somebody already picked.
    """
    profile = _managed_profile(snapshot)
    activated = False

    def mutate(catalog: dict[str, Any]) -> None:
        nonlocal activated
        llm = catalog["services"]["llm"]
        profiles = llm.setdefault("profiles", [])
        managed_indexes = [
            index
            for index, existing in enumerate(profiles)
            if existing.get("managed_by") == MANAGED_BY
        ]
        if managed_indexes:
            first_index = managed_indexes[0]
            profiles[:] = [
                existing for existing in profiles if existing.get("managed_by") != MANAGED_BY
            ]
            profiles.insert(min(first_index, len(profiles)), profile)
        else:
            profiles.append(profile)

        if not profile["models"]:
            return
        current_profile_id = llm.get("active_profile_id")
        if not current_profile_id:
            llm["active_profile_id"] = CODEX_PROFILE_ID
            llm["active_model_id"] = profile["models"][0]["id"]
            activated = True
        elif current_profile_id == CODEX_PROFILE_ID:
            valid_model_ids = {model["id"] for model in profile["models"]}
            if llm.get("active_model_id") not in valid_model_ids:
                llm["active_model_id"] = profile["models"][0]["id"]

    return CatalogSyncResult(catalog=catalog_service.update(mutate), activated=activated)


def remove_codex_catalog(catalog_service: ModelCatalogService) -> dict[str, Any]:
    """Drop the managed Codex profile and never leave a dangling selection."""

    def mutate(catalog: dict[str, Any]) -> None:
        llm = catalog["services"]["llm"]
        current_is_managed = llm.get("active_profile_id") == CODEX_PROFILE_ID
        llm["profiles"] = [
            profile
            for profile in llm.get("profiles", [])
            if profile.get("managed_by") != MANAGED_BY
        ]
        if current_is_managed:
            llm["active_profile_id"] = None
            llm["active_model_id"] = None

    return catalog_service.update(mutate)


class CodexOAuthService:
    """Coordinate independent Codex login, refresh, catalog sync, and logout."""

    _TERMINAL_STATES = {"completed", "cancelled", "expired", "failed"}

    def __init__(
        self,
        store: CodexCredentialStore,
        catalog: CodexModelCatalog,
        model_catalog: ModelCatalogService,
        *,
        oauth_client: CodexOAuthClient | None = None,
        callback_factory: Callable[[str], Awaitable[Any]] | None = None,
        clock: Callable[[], float] = time.time,
        callback_forward_port: int = 3782,
    ) -> None:
        if (
            isinstance(callback_forward_port, bool)
            or not isinstance(callback_forward_port, int)
            or not 1 <= callback_forward_port <= 65535
        ):
            raise ValueError("callback_forward_port must be between 1 and 65535")
        self._store = store
        self._catalog = catalog
        self._model_catalog = model_catalog
        self._callback_forward_port = callback_forward_port
        self._owned_http: httpx.AsyncClient | None = None
        if oauth_client is None:
            self._owned_http = httpx.AsyncClient(timeout=30)
            oauth_client = CodexOAuthClient(self._owned_http)
        self._oauth = oauth_client
        self._callback_factory = callback_factory or self._start_default_callback
        self._clock = clock
        self._operation: _LoginOperation | None = None
        self._last_snapshot: CatalogSnapshot | None = None
        self._operation_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._catalog_sync_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._active_inferences = 0
        self._logging_out = False

    @staticmethod
    async def _start_default_callback(expected_state: str) -> LoopbackCallback:
        return await LoopbackCallback.start(
            CODEX_CALLBACK_PORTS,
            expected_state=expected_state,
        )

    async def start_login(self) -> dict[str, Any]:
        async with self._operation_lock:
            if self._operation_is_active():
                return self._login_start_payload(self._operation)

            pkce = generate_pkce()
            state_secret = secrets.token_urlsafe(32)
            callback = await self._callback_factory(state_secret)
            redirect_uri = f"http://localhost:{callback.port}{CODEX_CALLBACK_PATH}"
            operation = _LoginOperation(
                operation_id=secrets.token_urlsafe(24),
                state_secret=state_secret,
                pkce=pkce,
                callback=callback,
                redirect_uri=redirect_uri,
                authorize_url=build_authorize_url(
                    redirect_uri=redirect_uri,
                    state=state_secret,
                    pkce=pkce,
                ),
                deadline=self._clock() + CODEX_LOGIN_TIMEOUT_SECONDS,
                expected_generation=self._store.current_generation(),
            )
            self._operation = operation
            operation.task = asyncio.create_task(self._run_login(operation))
            return self._login_start_payload(operation)

    def _login_start_payload(self, operation: _LoginOperation | None) -> dict[str, Any]:
        if operation is None:
            raise CodexAuthError(
                "login_not_started",
                "Codex sign-in has not been started.",
                409,
            )
        callback_port = operation.callback.port
        return {
            "operation_id": operation.operation_id,
            "authorize_url": operation.authorize_url,
            "expires_in": max(0, int(operation.deadline - self._clock())),
            "callback_port": callback_port,
            "callback_forward_port": self._callback_forward_port,
            "redirect_uri": operation.redirect_uri,
            "ssh_forward_command": ssh_forward_command(
                callback_port,
                self._callback_forward_port,
            ),
        }

    def _operation_is_active(self) -> bool:
        operation = self._operation
        return bool(
            operation is not None
            and operation.operation_state not in self._TERMINAL_STATES
            and (operation.task is None or not operation.task.done())
        )

    def awaits_callback_state(self, state: str | None) -> bool:
        """Whether this instance holds the active login that owns ``state``.

        Read without the operation lock: the caller only uses this to pick a
        recipient, and :meth:`receive_callback` revalidates under the lock.
        """
        operation = self._operation
        if operation is None or not self._operation_is_active():
            return False
        return oauth_state_matches(state, operation.state_secret)

    def awaits_callback(self) -> bool:
        """Whether this instance has a login waiting for a browser callback."""
        return self._operation is not None and self._operation_is_active()

    async def receive_callback(
        self,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> None:
        async with self._operation_lock:
            operation = self._operation
            if operation is None or not self._operation_is_active():
                raise CodexAuthError(
                    "login_not_active",
                    "Codex sign-in is not waiting for a callback.",
                    409,
                )
            if not oauth_state_matches(state, operation.state_secret):
                raise CodexAuthError(
                    "state_mismatch",
                    "Codex sign-in returned an invalid state.",
                    400,
                )
            operation.callback.submit(OAuthCallbackResult(code=code, state=state, error=error))

    async def _run_login(self, operation: _LoginOperation) -> None:
        try:
            callback = await operation.callback.wait(
                timeout=max(0, operation.deadline - self._clock())
            )
            self._validate_callback(callback, operation.state_secret)
            operation.operation_state = "exchanging"
            payload = await self._oauth.exchange_code(
                callback.code,
                operation.redirect_uri,
                operation.pkce.verifier,
            )
            credentials = self._credentials_from_payload(
                payload,
                expected_generation=operation.expected_generation,
            )
            committed = self._store.commit_credentials(
                credentials,
                expected_generation=operation.expected_generation,
            )
            operation.operation_state = "fetching_models"
            await self._catalog.invalidate()
            snapshot = await self._catalog.get(committed, force=True)
            async with self._catalog_sync_lock:
                sync_result = sync_codex_catalog(self._model_catalog, snapshot)
            self._last_snapshot = snapshot
            operation.activated = sync_result.activated
            operation.operation_state = "completed"
        except CodexAuthError as exc:
            operation.error_code = exc.code
            if exc.code == "login_cancelled":
                operation.operation_state = "cancelled"
            elif exc.code == "login_timeout":
                operation.operation_state = "expired"
            else:
                operation.operation_state = "failed"
        except asyncio.CancelledError:
            operation.error_code = "login_cancelled"
            operation.operation_state = "cancelled"
        except Exception:
            operation.error_code = "login_failed"
            operation.operation_state = "failed"

    @staticmethod
    def _validate_callback(
        callback: OAuthCallbackResult,
        expected_state: str,
    ) -> None:
        if callback.error is not None:
            code = (
                "authorization_denied"
                if callback.error == "access_denied"
                else "oauth_callback_failed"
            )
            raise CodexAuthError(code, "Codex sign-in was not authorized.", 401)
        if not oauth_state_matches(callback.state, expected_state):
            raise CodexAuthError(
                "state_mismatch",
                "Codex sign-in returned an invalid state.",
                400,
            )
        if not callback.code:
            raise CodexAuthError(
                "authorization_code_missing",
                "Codex sign-in did not return an authorization code.",
                400,
            )

    async def cancel_login(self) -> dict[str, Any]:
        async with self._operation_lock:
            operation = self._operation
            if not self._operation_is_active() or operation is None:
                return self.public_status()
            await operation.callback.cancel()
            await asyncio.sleep(0)
            if operation.task is not None and not operation.task.done():
                operation.task.cancel()
            task = operation.task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        return self.public_status()

    async def refresh_models(self) -> dict[str, Any]:
        async with self._catalog_sync_lock:
            token = await self.get_token()
            credentials = self._store.load_credentials()
            if credentials is None or credentials.generation != token.generation:
                raise CodexAuthError(
                    "authentication_changed",
                    "Codex authentication changed before models could be refreshed.",
                    409,
                )
            snapshot = await self._catalog.get(credentials, force=True)
            sync_codex_catalog(self._model_catalog, snapshot)
            self._last_snapshot = snapshot
            return self.public_status()

    async def get_token(self) -> CodexToken:
        async with self._refresh_lock:
            credentials = self._store.load_credentials()
            if credentials is None:
                raise CodexAuthError(
                    "authentication_required",
                    "Sign in to Codex before using this model.",
                    401,
                )
            if credentials.expires_at - int(self._clock()) > 300:
                return credentials.public_token()
            refreshed = await self._refresh_credentials(credentials)
            return refreshed.public_token()

    async def _refresh_credentials(
        self,
        credentials: CodexCredentials,
    ) -> CodexCredentials:
        payload = await self._oauth.refresh(credentials.refresh_token)
        refreshed = self._credentials_from_payload(
            payload,
            expected_generation=credentials.generation,
            fallback=credentials,
        )
        if refreshed.account_id != credentials.account_id:
            raise CodexAuthError(
                "account_changed",
                "Codex authentication returned a different account.",
                409,
            )
        committed = self._store.commit_credentials(
            refreshed,
            expected_generation=credentials.generation,
        )
        await self._catalog.invalidate()
        return committed

    async def recover_after_unauthorized(self, generation: int) -> None:
        async with self._refresh_lock:
            credentials = self._store.load_credentials()
            if credentials is None:
                raise CodexAuthError(
                    "authentication_required",
                    "Sign in to Codex before using this model.",
                    401,
                )
            if credentials.generation != generation:
                return
            await self._refresh_credentials(credentials)

    @asynccontextmanager
    async def inference_guard(self) -> AsyncIterator[None]:
        async with self._inference_lock:
            if self._logging_out:
                raise CodexAuthError(
                    "logout_in_progress",
                    "Codex sign-out is in progress.",
                    409,
                )
            self._active_inferences += 1
        try:
            yield
        finally:
            async with self._inference_lock:
                self._active_inferences -= 1

    async def logout(self) -> dict[str, Any]:
        async with self._inference_lock:
            if self._active_inferences:
                raise CodexAuthError(
                    "inference_in_progress",
                    "Stop active Codex generation before signing out.",
                    409,
                )
            self._logging_out = True
        try:
            await self.cancel_login()
            async with self._catalog_sync_lock:
                credentials = self._store.load_credentials()
                if credentials is not None:
                    try:
                        await self._oauth.revoke(credentials)
                    except Exception:
                        pass
                    self._store.clear_credentials(expected_generation=credentials.generation)
                else:
                    self._store.clear_credentials(
                        expected_generation=self._store.current_generation()
                    )
                remove_codex_catalog(self._model_catalog)
                try:
                    await self._catalog.invalidate()
                except Exception:
                    pass
                self._last_snapshot = None
                self._operation = None
                return self.public_status()
        finally:
            async with self._inference_lock:
                self._logging_out = False

    def public_status(self) -> dict[str, Any]:
        operation = self._operation
        credentials: CodexCredentials | None = None
        storage_error: str | None = None
        try:
            credentials = self._store.load_credentials()
        except CodexAuthError as exc:
            storage_error = exc.code

        active_operation = self._operation_is_active()
        if active_operation:
            connection = "authorizing"
        elif credentials is not None:
            connection = "connected"
        elif operation is not None and operation.operation_state == "failed":
            connection = "error"
        else:
            connection = "disconnected"

        snapshot = self._status_snapshot(credentials)
        return {
            "connection": connection,
            "operation_id": operation.operation_id if operation is not None else None,
            "operation_state": (operation.operation_state if operation is not None else None),
            "authorize_url": (
                operation.authorize_url if active_operation and operation is not None else None
            ),
            "expires_in": (
                max(0, int(operation.deadline - self._clock()))
                if active_operation and operation is not None
                else None
            ),
            "callback_port": (operation.callback.port if operation is not None else None),
            "callback_forward_port": (
                self._callback_forward_port if operation is not None else None
            ),
            "redirect_uri": operation.redirect_uri if operation is not None else None,
            "model_count": len(snapshot.models) if snapshot is not None else 0,
            "catalog_source": snapshot.source if snapshot is not None else None,
            "catalog_fetched_at": (snapshot.fetched_at if snapshot is not None else None),
            "active_model": self._active_codex_model(),
            "activated": (operation.activated if operation is not None else False),
            "error_code": (
                storage_error or (operation.error_code if operation is not None else None)
            ),
        }

    def _status_snapshot(
        self,
        credentials: CodexCredentials | None,
    ) -> CatalogSnapshot | None:
        if credentials is None:
            return None
        snapshot = self._last_snapshot
        if snapshot is not None and snapshot.generation == credentials.generation:
            return snapshot
        try:
            payload = self._store.load_catalog_cache()
            if payload is None:
                return None
            cached = CatalogSnapshot.from_dict(payload)
        except CodexAuthError:
            return None
        if cached.generation != credentials.generation:
            return None
        return cached

    def _active_codex_model(self) -> str | None:
        """Report the active model only while Codex itself is the active profile.

        Reporting the deployment-wide active model here would tell the operator
        "Codex is active: deepseek-chat" whenever another provider is selected.
        """
        catalog = self._model_catalog.load()
        llm = catalog.get("services", {}).get("llm", {})
        if llm.get("active_profile_id") != CODEX_PROFILE_ID:
            return None
        model = self._model_catalog.get_active_model(catalog, "llm")
        if model is None:
            return None
        value = model.get("model")
        return value if isinstance(value, str) and value else None

    def _credentials_from_payload(
        self,
        payload: dict[str, Any],
        *,
        expected_generation: int,
        fallback: CodexCredentials | None = None,
    ) -> CodexCredentials:
        access_token = self._required_token(
            payload.get("access_token"),
            fallback.access_token if fallback is not None else None,
        )
        refresh_token = self._required_token(
            payload.get("refresh_token"),
            fallback.refresh_token if fallback is not None else None,
        )
        id_token = self._required_token(
            payload.get("id_token"),
            fallback.id_token if fallback is not None else None,
        )

        account_id = self._first_nonempty_string(
            payload.get("account_id"),
            payload.get("chatgpt_account_id"),
        )
        expires_at = self._positive_int(payload.get("expires_at"))
        for token in (id_token, access_token):
            if account_id is not None and expires_at is not None:
                break
            try:
                claims = decode_codex_jwt(token)
            except CodexAuthError:
                continue
            account_id = account_id or claims.account_id
            expires_at = expires_at or claims.expires_at

        if account_id is None and fallback is not None:
            account_id = fallback.account_id
        if expires_at is None:
            expires_in = self._positive_int(payload.get("expires_in"))
            if expires_in is not None:
                expires_at = int(self._clock()) + expires_in
        if expires_at is None and fallback is not None:
            expires_at = fallback.expires_at
        if account_id is None or expires_at is None:
            raise CodexAuthError(
                "token_response_invalid",
                "Codex returned incomplete authentication data.",
                502,
            )

        return CodexCredentials(
            schema_version=1,
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            account_id=account_id,
            expires_at=expires_at,
            generation=expected_generation,
        )

    @staticmethod
    def _required_token(value: object, fallback: str | None) -> str:
        if isinstance(value, str) and value:
            return value
        if fallback:
            return fallback
        raise CodexAuthError(
            "token_response_invalid",
            "Codex returned incomplete authentication data.",
            502,
        )

    @staticmethod
    def _first_nonempty_string(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value


_SERVICE_INSTANCES: dict[str, CodexOAuthService] = {}
_RELOCATED_SECRET_ROOTS: set[str] = set()


def _codex_user_root() -> Path:
    """Resolve the user root of the account that owns the caller's scope.

    A Codex token is issued against one person's ChatGPT plan. Resolving other
    users to the administrator's root would run a whole deployment on a single
    subscription, so every account signs in for itself or does not use Codex.
    Owner resolution is what keeps that true while still letting a partner —
    a synthetic user with a workspace but no account — inherit the login of
    the person who owns it (#711).

    This is where the store used to live; :func:`_codex_secrets_root` is where
    it lives now, and this is only the location it is relocated from.
    """
    from deeptutor.multi_user.paths import get_owner_path_service

    return get_owner_path_service().get_user_root().resolve()


def _codex_secrets_root() -> Path:
    """Resolve the owner's secret root, moving an older login into it on first use.

    For a non-admin account the user root of :func:`_codex_user_root` sits
    inside the workspace subtree the sandbox runner mounts, so a refresh token
    stored there was readable by every other account's ``exec`` (the admin's own
    root was never mounted — only ``data/user/workspace`` is). ``data/system``
    is mounted for nobody, so the store now lives under the owner's directory
    there instead, keyed by the same owner resolution as before.
    """
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    secrets_root = get_owner_secrets_dir()
    key = str(secrets_root)
    if key not in _RELOCATED_SECRET_ROOTS:
        # Memoised only on success: a relocation that failed (a permission
        # problem, say) leaves the token in the exposed location, and retrying
        # on the next resolution is strictly better than deciding once per
        # process that the move is done.
        if _relocate_legacy_store(_codex_user_root(), secrets_root):
            _RELOCATED_SECRET_ROOTS.add(key)
    return secrets_root


def _relocate_legacy_store(user_root: Path, secrets_root: Path) -> bool:
    """Move a login out of the sandbox-visible tree by rename, never by copy.

    A copy would leave the plaintext refresh token exactly where the exposure
    was, so this relocates the whole store directory or does nothing at all: a
    login already at the safe location wins, and the stale one is reported for
    an operator to remove by hand, mirroring
    :func:`~deeptutor.multi_user.paths.migrate_legacy_multi_user_tree`.

    Returns whether the legacy location is now settled — i.e. whether there is
    nothing left to retry.
    """
    legacy = CodexCredentialStore(user_root)
    target = CodexCredentialStore(secrets_root).root
    try:
        # The legacy tree is inside a subtree other accounts' sandboxed exec can
        # write. Checking only the leaf is not enough: a symlinked ``private/``
        # would make this relocate *another* account's store into this owner's
        # secrets dir, where the server would then use it as their login.
        legacy.assert_safe_location()
    except CodexAuthError:
        logger.warning(
            "Refusing to relocate Codex credentials: %s is not a plain directory",
            legacy.root,
        )
        return True  # nothing we will ever move; do not retry
    if not legacy.root.is_dir():
        return True
    if target.exists():
        logger.warning(
            "Codex credentials already exist at %s; the sandbox-visible copy at "
            "%s was left untouched and should be removed by hand",
            target,
            legacy.root,
        )
        return True
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy.root), str(target))
    except OSError:
        # A failed copy leaves a partial target and an intact source; a failed
        # source cleanup leaves a complete target. Only the former is safe to
        # discard, and the credential file is what tells the two apart.
        if legacy.credentials_path.exists():
            shutil.rmtree(target, ignore_errors=True)
        logger.warning("Could not relocate Codex credentials %s -> %s", legacy.root, target)
        return False
    logger.info("Relocated Codex credentials out of the sandbox-visible tree: %s", target)
    return True


def _owner_model_catalog_service() -> ModelCatalogService:
    """The catalog a sign-in publishes its managed profile into.

    Deliberately NOT :func:`get_model_catalog_service`, which resolves an
    ordinary user to the *administrator's* catalog: a non-admin sign-in would
    then write their personal Codex profile into the shared catalog, where it
    would show up in the administrator's model list and in every other user's
    resolution path. Owner scope keys this to the same account as the
    credential store, so a login and its profile can never land in different
    places (#781).
    """
    from deeptutor.multi_user.personal_models import owner_catalog_service

    return owner_catalog_service()


def get_codex_oauth_service() -> CodexOAuthService:
    secrets_root = _codex_secrets_root()
    key = str(secrets_root)
    service = _SERVICE_INSTANCES.get(key)
    if service is None:
        callback_forward_port = load_system_settings()["frontend_port"]
        store = CodexCredentialStore(secrets_root)
        http = httpx.AsyncClient(timeout=30)
        catalog = CodexModelCatalog(store, http=http)
        service = CodexOAuthService(
            store,
            catalog,
            _owner_model_catalog_service(),
            oauth_client=CodexOAuthClient(http),
            callback_forward_port=callback_forward_port,
        )
        _SERVICE_INSTANCES[key] = service
    return service


async def deliver_codex_oauth_callback(
    code: str | None,
    state: str | None,
    error: str | None,
) -> None:
    """Hand a browser OAuth callback to whichever login is awaiting it.

    The browser reaches ``/auth/callback`` on its own loopback address — the
    far end of the user's tunnel — not on the DeepTutor Web origin, so the
    request carries no session and the per-user service instance behind
    :func:`get_codex_oauth_service` cannot be resolved from it. Resolving it
    anyway would land every callback on the default root and strand every
    non-administrator mid-login.

    The OAuth ``state`` is the identity instead: it is a secret this process
    minted for exactly one login, and it is compared in constant time. That is
    already the trust model the loopback listener uses.
    """
    for service in list(_SERVICE_INSTANCES.values()):
        if service.awaits_callback_state(state):
            await service.receive_callback(code, state, error)
            return
    if any(service.awaits_callback() for service in list(_SERVICE_INSTANCES.values())):
        raise CodexAuthError(
            "state_mismatch",
            "Codex sign-in returned an invalid state.",
            400,
        )
    raise CodexAuthError(
        "login_not_active",
        "Codex sign-in is not waiting for a callback.",
        409,
    )


__all__ = [
    "CODEX_PROFILE_ID",
    "MANAGED_BY",
    "CatalogSyncResult",
    "CodexOAuthService",
    "codex_model_id",
    "deliver_codex_oauth_callback",
    "get_codex_oauth_service",
    "remove_codex_catalog",
    "ssh_forward_command",
    "sync_codex_catalog",
]
