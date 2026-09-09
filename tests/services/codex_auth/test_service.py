from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from deeptutor.services.codex_auth import service as service_module
from deeptutor.services.codex_auth.contracts import (
    CatalogSnapshot,
    CodexAuthError,
    CodexCredentials,
    CodexModel,
)
from deeptutor.services.codex_auth.oauth import OAuthCallbackResult
from deeptutor.services.codex_auth.service import (
    CODEX_PROFILE_ID,
    MANAGED_BY,
    CodexOAuthService,
    codex_model_id,
    parse_oauth_callback_url,
    remove_codex_catalog,
    ssh_forward_command,
    sync_codex_catalog,
)
from deeptutor.services.codex_auth.storage import CodexCredentialStore
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config


def test_each_user_gets_their_own_codex_credential_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A Codex token authorizes one person's ChatGPT plan, so it is never pooled.

    Resolving other accounts to the administrator's directory would run an
    entire deployment on a single subscription. Asserted on the *live* seam
    (``_codex_secrets_root``): ``_codex_user_root`` is now only the location a
    pre-existing login is relocated from, so pinning it would leave this
    guarantee unguarded.
    """
    from deeptutor.multi_user import paths as paths_module
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths_module, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths_module, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths_module, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths_module, "_path_services", {})
    monkeypatch.setattr(service_module, "_RELOCATED_SECRET_ROOTS", set())

    as_admin = service_module._codex_secrets_root()
    scope = UserScope(kind="user", user_id="u_ada", root=admin_root / "users" / "u_ada")
    token = set_current_user(CurrentUser(id="u_ada", username="ada", role="user", scope=scope))
    try:
        as_learner = service_module._codex_secrets_root()
    finally:
        reset_current_user(token)

    assert as_admin != as_learner
    assert as_learner.name == "u_ada"
    # Who owns a scope is decided in multi_user.paths, not here: codex_auth must
    # never reach for the admin root — or learn what a partner is — itself.
    assert not hasattr(service_module, "get_admin_path_service")
    assert not hasattr(service_module, "PARTNER_USER_PREFIX")


def test_partner_turn_inherits_its_owner_codex_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A partner has a workspace but no account, so it borrows its owner's token.

    Before #711 the credential store followed the partner scope to
    ``data/partners/<id>/workspace/user``, found nothing, and failed in 0s.
    """
    from deeptutor.multi_user import paths as paths_module
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.services.partners.scope import partner_user

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths_module, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths_module, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths_module, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths_module, "_path_services", {})
    monkeypatch.setattr(service_module, "_RELOCATED_SECRET_ROOTS", set())

    as_admin = service_module._codex_secrets_root()
    token = set_current_user(partner_user("ada"))
    try:
        assert service_module._codex_secrets_root() == as_admin
        assert service_module._codex_user_root() == admin_root / "user"
    finally:
        reset_current_user(token)


def test_ssh_forward_command_maps_callback_to_frontend_port() -> None:
    assert (
        ssh_forward_command(1457, 4782) == "ssh -N -L 1457:127.0.0.1:4782 <ssh-user>@<server-host>"
    )


@pytest.mark.parametrize("callback_forward_port", [0, 65_536, True, "3782"])
def test_callback_forward_port_must_be_a_valid_integer(
    tmp_path: Path,
    callback_forward_port: object,
) -> None:
    store = CodexCredentialStore(tmp_path)
    model_catalog, _original = _seeded_service(tmp_path)

    with pytest.raises(ValueError):
        CodexOAuthService(
            store,
            FakeCatalog(_snapshot("live")),
            model_catalog,
            oauth_client=FakeOAuthClient(),
            callback_forward_port=callback_forward_port,  # type: ignore[arg-type]
        )


def test_service_singleton_reads_frontend_port_only_when_created(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings_calls = 0
    captured: dict[str, Any] = {}

    def load_settings() -> dict[str, int]:
        nonlocal settings_calls
        settings_calls += 1
        return {"frontend_port": 4782}

    class CapturingService:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(service_module, "_SERVICE_INSTANCES", {})
    monkeypatch.setattr(service_module, "_codex_secrets_root", lambda: tmp_path)
    monkeypatch.setattr(service_module, "load_system_settings", load_settings)
    monkeypatch.setattr(service_module, "CodexCredentialStore", lambda _root: object())
    monkeypatch.setattr(
        service_module,
        "CodexModelCatalog",
        lambda _store, *, http: object(),
    )
    monkeypatch.setattr(service_module, "CodexOAuthClient", lambda _http: object())
    # A sign-in publishes into the OWNER's catalog, never the shared one that
    # ``get_model_catalog_service`` resolves an ordinary user to (#781).
    monkeypatch.setattr(service_module, "_owner_model_catalog_service", lambda: object())
    monkeypatch.setattr(service_module, "CodexOAuthService", CapturingService)

    first = service_module.get_codex_oauth_service()
    second = service_module.get_codex_oauth_service()

    assert first is second
    assert settings_calls == 1
    assert captured["callback_forward_port"] == 4782


def _model(
    slug: str,
    *,
    display_name: str | None = None,
    priority: int = 1,
    supported_reasoning_levels: tuple[str, ...] = ("medium", "high"),
    context_window: int | None = None,
    max_context_window: int | None = None,
) -> CodexModel:
    return CodexModel(
        slug=slug,
        display_name=display_name or slug,
        priority=priority,
        visibility="list",
        default_reasoning_level="medium",
        supported_reasoning_levels=supported_reasoning_levels,
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
        context_window=context_window,
        max_context_window=max_context_window,
    )


def _snapshot(
    source: str,
    *models: CodexModel,
) -> CatalogSnapshot:
    return CatalogSnapshot(
        models=models,
        source=source,  # type: ignore[arg-type]
        fetched_at=1_000,
        etag='"v1"',
        generation=1,
        account_hash="account-hash",
    )


def _seeded_service(tmp_path: Path) -> tuple[ModelCatalogService, dict]:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    original = service.load()
    llm = original["services"]["llm"]
    llm["profiles"] = [
        {
            "id": "llm-profile-existing",
            "name": "Existing",
            "binding": "siliconflow",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "existing-key",
            "models": [
                {
                    "id": "llm-model-existing",
                    "name": "DeepSeek V3",
                    "model": "deepseek-ai/DeepSeek-V3",
                },
                {
                    "id": "llm-model-backup",
                    "name": "Backup",
                    "model": "backup-model",
                },
            ],
        }
    ]
    llm["active_profile_id"] = "llm-profile-existing"
    llm["active_model_id"] = "llm-model-existing"
    saved = service.save(original)
    return service, saved


def _selection(catalog: dict) -> dict[str, str | None]:
    llm = catalog["services"]["llm"]
    return {
        "profile_id": llm.get("active_profile_id"),
        "model_id": llm.get("active_model_id"),
    }


def _managed_profile(catalog: dict) -> dict:
    return next(
        profile
        for profile in catalog["services"]["llm"]["profiles"]
        if profile.get("managed_by") == MANAGED_BY
    )


def test_sync_publishes_a_read_only_owner_bound_codex_profile(tmp_path: Path) -> None:
    service, _original = _seeded_service(tmp_path)

    result = sync_codex_catalog(
        service,
        _snapshot(
            "live",
            _model(
                "gpt-5.6-sol",
                context_window=272_000,
                max_context_window=272_000,
            ),
            _model("gpt-5.6-terra", priority=2),
        ),
    )

    profile = _managed_profile(result.catalog)
    assert profile["id"] == CODEX_PROFILE_ID
    assert profile["binding"] == "openai_codex"
    assert profile["api_key"] == ""
    assert profile["read_only"] is True
    # Owner-bound stops grants from lending this ChatGPT plan to other accounts.
    assert profile["owner_bound"] is True
    assert [model["model"] for model in profile["models"]] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    ]
    assert profile["models"][0]["context_window"] == "272000"
    assert profile["models"][0]["context_window_source"] == "metadata"


def test_sync_binds_the_managed_profile_without_storing_the_raw_account_id(
    tmp_path: Path,
) -> None:
    service, _original = _seeded_service(tmp_path)

    result = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol")),
        account_id="account-123",
    )

    profile = _managed_profile(result.catalog)
    assert profile["codex_account_binding"] == hashlib.sha256(b"account-123").hexdigest()
    assert "account-123" not in json.dumps(profile)


def test_sync_uses_max_context_window_when_current_window_is_missing(tmp_path: Path) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")

    result = sync_codex_catalog(
        service,
        _snapshot(
            "live",
            _model("gpt-5.6-sol", max_context_window=272_000),
        ),
    )

    model = _managed_profile(result.catalog)["models"][0]
    assert model["context_window"] == "272000"
    assert model["context_window_source"] == "metadata"


def test_signing_in_never_replaces_a_model_the_operator_already_chose(
    tmp_path: Path,
) -> None:
    """Connecting a provider must not silently repoint everyone's chats."""
    service, original = _seeded_service(tmp_path)

    result = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    assert result.activated is False
    assert _selection(result.catalog) == _selection(original)


def test_signing_in_activates_codex_only_when_no_model_is_configured(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")

    result = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    assert result.activated is True
    assert _selection(result.catalog) == {
        "profile_id": CODEX_PROFILE_ID,
        "model_id": codex_model_id("gpt-5.6-sol"),
    }


def test_refresh_replaces_only_managed_models(tmp_path: Path) -> None:
    service, _original = _seeded_service(tmp_path)
    first = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol"), _model("old-model")),
    )
    existing_profile = deepcopy(
        next(
            profile
            for profile in first.catalog["services"]["llm"]["profiles"]
            if profile["id"] == "llm-profile-existing"
        )
    )

    refreshed = sync_codex_catalog(service, _snapshot("live", _model("new-model")))

    assert [model["model"] for model in _managed_profile(refreshed.catalog)["models"]] == [
        "new-model"
    ]
    assert (
        next(
            profile
            for profile in refreshed.catalog["services"]["llm"]["profiles"]
            if profile["id"] == "llm-profile-existing"
        )
        == existing_profile
    )


def test_refresh_preserves_a_supported_reasoning_override_for_the_same_model(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    initial = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol"), _model("gpt-5.6-terra")),
        account_id="account-a",
    )
    profile = _managed_profile(initial.catalog)
    profile["models"][0]["reasoning_effort"] = "high"
    service.save(initial.catalog)

    refreshed = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-terra"), _model("gpt-5.6-sol")),
        account_id="account-a",
    )

    efforts = {
        model["model"]: model.get("reasoning_effort")
        for model in _managed_profile(refreshed.catalog)["models"]
    }
    assert efforts == {"gpt-5.6-terra": None, "gpt-5.6-sol": "high"}
    assert resolve_llm_runtime_config(catalog=refreshed.catalog).reasoning_effort == "high"


def test_account_switch_does_not_carry_a_reasoning_override(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    initial = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol")),
        account_id="account-a",
    )
    _managed_profile(initial.catalog)["models"][0]["reasoning_effort"] = "high"
    service.save(initial.catalog)

    switched = sync_codex_catalog(
        service,
        _snapshot("live", _model("gpt-5.6-sol")),
        account_id="account-b",
    )

    profile = _managed_profile(switched.catalog)
    assert "reasoning_effort" not in profile["models"][0]
    assert profile["codex_account_binding"] == hashlib.sha256(b"account-b").hexdigest()


def test_refresh_drops_a_reasoning_override_the_model_no_longer_supports(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    initial = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))
    profile = _managed_profile(initial.catalog)
    profile["models"][0]["reasoning_effort"] = "high"
    service.save(initial.catalog)

    refreshed = sync_codex_catalog(
        service,
        _snapshot(
            "live",
            _model("gpt-5.6-sol", supported_reasoning_levels=("medium",)),
        ),
    )

    model = _managed_profile(refreshed.catalog)["models"][0]
    assert "reasoning_effort" not in model


def test_refresh_keeps_the_canonical_profile_override_when_removing_duplicates(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    initial = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))
    canonical = _managed_profile(initial.catalog)
    canonical["models"][0]["reasoning_effort"] = "medium"
    duplicate = deepcopy(canonical)
    duplicate["id"] = f"{CODEX_PROFILE_ID}-duplicate"
    duplicate["models"][0]["reasoning_effort"] = "high"
    initial.catalog["services"]["llm"]["profiles"].append(duplicate)
    service.save(initial.catalog)

    refreshed = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    managed = [
        profile
        for profile in refreshed.catalog["services"]["llm"]["profiles"]
        if profile.get("managed_by") == MANAGED_BY
    ]
    assert len(managed) == 1
    assert managed[0]["models"][0]["reasoning_effort"] == "medium"


def test_refresh_ignores_an_override_with_a_non_string_model_identity(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    initial = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))
    stale = _managed_profile(initial.catalog)["models"][0]
    stale["model"] = []
    stale["reasoning_effort"] = "high"
    service.save(initial.catalog)

    refreshed = sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    model = _managed_profile(refreshed.catalog)["models"][0]
    assert model["model"] == "gpt-5.6-sol"
    assert "reasoning_effort" not in model


def test_refresh_repoints_a_selection_whose_model_left_the_account(tmp_path: Path) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    sync_codex_catalog(service, _snapshot("live", _model("retired-model")))

    refreshed = sync_codex_catalog(service, _snapshot("live", _model("current-model")))

    assert _selection(refreshed.catalog) == {
        "profile_id": CODEX_PROFILE_ID,
        "model_id": codex_model_id("current-model"),
    }


def test_logout_removes_the_managed_profile_and_clears_its_selection(
    tmp_path: Path,
) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    removed = remove_codex_catalog(service)

    assert removed["services"]["llm"]["profiles"] == []
    assert _selection(removed) == {"profile_id": None, "model_id": None}


def test_logout_leaves_another_providers_selection_untouched(tmp_path: Path) -> None:
    service, original = _seeded_service(tmp_path)
    sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    removed = remove_codex_catalog(service)

    assert _selection(removed) == _selection(original)
    assert not any(
        profile.get("managed_by") == MANAGED_BY
        for profile in removed["services"]["llm"]["profiles"]
    )


def test_catalog_sync_does_not_touch_neighboring_history_file(tmp_path: Path) -> None:
    history = tmp_path / "chat-history.json"
    history.write_text('{"model":"old"}', encoding="utf-8")
    service, _original = _seeded_service(tmp_path)

    sync_codex_catalog(service, _snapshot("live", _model("gpt-5.6-sol")))

    assert history.read_text(encoding="utf-8") == '{"model":"old"}'


class FakeCallback:
    port = 1455

    def __init__(self, error: CodexAuthError | None = None) -> None:
        self._result: asyncio.Future[OAuthCallbackResult] = (
            asyncio.get_running_loop().create_future()
        )
        self.error = error
        self.expected_state: str | None = None

    async def wait(self, timeout: float) -> OAuthCallbackResult:
        if self.error is not None:
            raise self.error
        return await asyncio.wait_for(asyncio.shield(self._result), timeout)

    async def cancel(self) -> None:
        if not self._result.done():
            self._result.set_exception(
                CodexAuthError("login_cancelled", "Codex sign-in was cancelled.", 409)
            )

    def submit(self, result: OAuthCallbackResult) -> None:
        if self._result.done():
            raise CodexAuthError(
                "login_not_active",
                "Codex sign-in is not waiting for a callback.",
                409,
            )
        self._result.set_result(result)

    def complete(self, authorize_url: str, *, code: str = "authorization-code") -> None:
        state = parse_qs(urlsplit(authorize_url).query)["state"][0]
        self.submit(OAuthCallbackResult(code=code, state=state, error=None))

    def complete_with_state(self, state: str) -> None:
        self.submit(OAuthCallbackResult(code="authorization-code", state=state, error=None))


class FakeOAuthClient:
    def __init__(self) -> None:
        self.exchange_payload: dict[str, Any] = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "id_token": "new-id",
            "account_id": "account-123",
            "expires_in": 3_600,
        }
        self.refresh_payload: dict[str, Any] = {
            "access_token": "refreshed-access",
            "refresh_token": "refreshed-refresh",
            "id_token": "refreshed-id",
            "account_id": "account-123",
            "expires_in": 3_600,
        }
        self.exchange_error: CodexAuthError | None = None
        self.revoke_error: CodexAuthError | None = None
        self.refresh_started: asyncio.Event | None = None
        self.refresh_release: asyncio.Event | None = None
        self.refresh_calls = 0

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        verifier: str,
    ) -> dict[str, Any]:
        del code, redirect_uri, verifier
        if self.exchange_error is not None:
            raise self.exchange_error
        return dict(self.exchange_payload)

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        del refresh_token
        self.refresh_calls += 1
        if self.refresh_started is not None:
            self.refresh_started.set()
        if self.refresh_release is not None:
            await self.refresh_release.wait()
        return dict(self.refresh_payload)

    async def revoke(self, credentials: CodexCredentials) -> None:
        del credentials
        if self.revoke_error is not None:
            raise self.revoke_error


class FakeCatalog:
    def __init__(
        self,
        snapshot: CatalogSnapshot,
        error: CodexAuthError | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.error = error
        self.calls: list[tuple[int, bool]] = []
        self.invalidated = False
        self.get_started: asyncio.Event | None = None
        self.get_release: asyncio.Event | None = None

    async def get(
        self,
        credentials: CodexCredentials,
        force: bool,
    ) -> CatalogSnapshot:
        self.calls.append((credentials.generation, force))
        if self.get_started is not None:
            self.get_started.set()
        if self.get_release is not None:
            await self.get_release.wait()
        if self.error is not None:
            raise self.error
        return self.snapshot

    async def invalidate(self) -> None:
        self.invalidated = True


def _stored_credentials(
    token: str = "old",
    *,
    expires_at: int = 10_000,
    account_id: str = "account-123",
) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token=f"{token}-access",
        refresh_token=f"{token}-refresh",
        id_token=f"{token}-id",
        account_id=account_id,
        expires_at=expires_at,
        generation=0,
    )


async def _oauth_service(
    tmp_path: Path,
    *,
    callback_error: CodexAuthError | None = None,
    catalog_error: CodexAuthError | None = None,
    clock: list[int] | None = None,
    callback_forward_port: int = 3_782,
) -> tuple[
    CodexOAuthService,
    FakeCallback,
    FakeOAuthClient,
    FakeCatalog,
    CodexCredentialStore,
    ModelCatalogService,
]:
    callback = FakeCallback(callback_error)
    oauth = FakeOAuthClient()
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    catalog = FakeCatalog(snapshot, catalog_error)
    store = CodexCredentialStore(tmp_path)
    model_catalog, _original = _seeded_service(tmp_path)

    async def callback_factory(expected_state: str) -> FakeCallback:
        callback.expected_state = expected_state
        return callback

    service = CodexOAuthService(
        store,
        catalog,
        model_catalog,
        oauth_client=oauth,
        callback_factory=callback_factory,
        clock=(lambda: (clock or [1_000])[0]),
        callback_forward_port=callback_forward_port,
    )
    return service, callback, oauth, catalog, store, model_catalog


async def _wait_until_terminal(service: CodexOAuthService) -> dict[str, Any]:
    for _ in range(100):
        status = service.public_status()
        if status["operation_state"] in {
            "completed",
            "cancelled",
            "expired",
            "failed",
        }:
            return status
        await asyncio.sleep(0)
    raise AssertionError("Codex login operation did not finish")


def _bound_reasoning_service(
    tmp_path: Path,
    snapshot: CatalogSnapshot,
) -> tuple[CodexOAuthService, ModelCatalogService]:
    model_catalog, _original = _seeded_service(tmp_path)
    store = CodexCredentialStore(tmp_path / "secrets")
    credentials = _stored_credentials()
    store.commit_credentials(credentials, expected_generation=0)
    sync_codex_catalog(
        model_catalog,
        snapshot,
        account_id=credentials.account_id,
    )
    return (
        CodexOAuthService(
            store,
            FakeCatalog(snapshot),
            model_catalog,
            oauth_client=FakeOAuthClient(),
        ),
        model_catalog,
    )


@pytest.mark.asyncio
async def test_owner_sets_supported_reasoning_effort_on_their_managed_model(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol"), _model("gpt-5.6-terra"))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    synced = model_catalog.load()
    llm = synced["services"]["llm"]
    llm["active_profile_id"] = CODEX_PROFILE_ID
    llm["active_model_id"] = codex_model_id("gpt-5.6-sol")
    model_catalog.save(synced)

    status = await service.set_reasoning_effort("gpt-5.6-sol", "high")

    catalog = model_catalog.load()
    models = _managed_profile(catalog)["models"]
    assert models[0]["reasoning_effort"] == "high"
    assert "reasoning_effort" not in models[1]
    assert status["models"] == [
        {
            "model": "gpt-5.6-sol",
            "name": "gpt-5.6-sol",
            "supported_reasoning_levels": ["medium", "high"],
            "reasoning_effort": "high",
        },
        {
            "model": "gpt-5.6-terra",
            "name": "gpt-5.6-terra",
            "supported_reasoning_levels": ["medium", "high"],
            "reasoning_effort": None,
        },
    ]
    assert resolve_llm_runtime_config(catalog=catalog).reasoning_effort == "high"


@pytest.mark.asyncio
async def test_runtime_validation_accepts_any_effort_for_a_bound_model(tmp_path: Path) -> None:
    """Effort is a per-request knob, not part of what binds a config to a token.

    Rejecting a request whose effort differs from the stored default would fail
    every caller that varies it for a single turn.
    """
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, _model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    token = await service.get_token()

    for effort in ("high", "low", None):
        service.validate_runtime_profile(token, "gpt-5.6-sol", effort)


@pytest.mark.asyncio
async def test_runtime_validation_rejects_a_model_outside_the_profile(tmp_path: Path) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, _model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    token = await service.get_token()

    with pytest.raises(CodexAuthError) as exc_info:
        service.validate_runtime_profile(token, "some-other-model", None)

    assert exc_info.value.code == "codex_catalog_unavailable"
    assert exc_info.value.http_status == 409


@pytest.mark.asyncio
async def test_a_profile_predating_the_account_binding_still_works(tmp_path: Path) -> None:
    """Absent is legacy, not "someone else's".

    Managed profiles published before ``codex_account_binding`` existed carry
    no such key. Reading that as a mismatch would lock every account that
    signed in before it shipped out of Codex entirely.
    """
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    token = await service.get_token()

    catalog = model_catalog.load()
    _managed_profile(catalog).pop("codex_account_binding", None)
    model_catalog.save(catalog)

    service.validate_runtime_profile(token, "gpt-5.6-sol", None)


@pytest.mark.asyncio
async def test_a_profile_bound_to_another_account_is_still_refused(tmp_path: Path) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    token = await service.get_token()

    catalog = model_catalog.load()
    _managed_profile(catalog)["codex_account_binding"] = "another-account-binding"
    model_catalog.save(catalog)

    with pytest.raises(CodexAuthError) as exc_info:
        service.validate_runtime_profile(token, "gpt-5.6-sol", None)

    assert exc_info.value.http_status == 409


def test_profile_binding_matches_only_current_credentials(tmp_path: Path) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    profile = _managed_profile(model_catalog.load())
    matcher = getattr(service, "profile_matches_current_account", None)

    assert callable(matcher)
    assert matcher(profile) is True
    profile["codex_account_binding"] = "stale-account-binding"
    assert matcher(profile) is False


@pytest.mark.asyncio
async def test_owner_cannot_set_an_unsupported_reasoning_effort(tmp_path: Path) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol", supported_reasoning_levels=("medium",)))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    before = model_catalog.load()

    with pytest.raises(CodexAuthError) as exc_info:
        await service.set_reasoning_effort("gpt-5.6-sol", "high")

    assert exc_info.value.code == "reasoning_effort_unsupported"
    assert exc_info.value.http_status == 422
    assert model_catalog.load() == before


@pytest.mark.asyncio
async def test_owner_can_restore_provider_default_reasoning_effort(tmp_path: Path) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    synced = model_catalog.load()
    _managed_profile(synced)["models"][0]["reasoning_effort"] = "high"
    model_catalog.save(synced)

    status = await service.set_reasoning_effort("gpt-5.6-sol", None)

    model = _managed_profile(model_catalog.load())["models"][0]
    assert "reasoning_effort" not in model
    assert status["models"][0]["reasoning_effort"] is None


@pytest.mark.asyncio
async def test_owner_cannot_update_a_model_outside_their_managed_profile(tmp_path: Path) -> None:
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service, model_catalog = _bound_reasoning_service(tmp_path, snapshot)
    before = model_catalog.load()

    with pytest.raises(CodexAuthError) as exc_info:
        await service.set_reasoning_effort("deepseek-ai/DeepSeek-V3", "high")

    assert exc_info.value.code == "codex_model_not_found"
    assert exc_info.value.http_status == 404
    assert model_catalog.load() == before


@pytest.mark.asyncio
async def test_reasoning_effort_requires_a_managed_codex_profile(tmp_path: Path) -> None:
    model_catalog, _original = _seeded_service(tmp_path)
    snapshot = _snapshot("live", _model("gpt-5.6-sol"))
    service = CodexOAuthService(
        CodexCredentialStore(tmp_path / "secrets"),
        FakeCatalog(snapshot),
        model_catalog,
        oauth_client=FakeOAuthClient(),
    )
    before = model_catalog.load()

    with pytest.raises(CodexAuthError) as exc_info:
        await service.set_reasoning_effort("gpt-5.6-sol", "high")

    assert exc_info.value.code == "codex_catalog_unavailable"
    assert exc_info.value.http_status == 409
    assert model_catalog.load() == before


@pytest.mark.asyncio
async def test_successful_live_login_keeps_the_existing_model_selection(
    tmp_path: Path,
) -> None:
    service, callback, _oauth, _catalog, _store, model_catalog = await _oauth_service(
        tmp_path,
        callback_forward_port=4_782,
    )
    original_selection = _selection(model_catalog.load())

    started = await service.start_login()
    duplicate = await service.start_login()
    callback.complete(started["authorize_url"])
    status = await _wait_until_terminal(service)

    assert duplicate == started
    assert callback.expected_state == parse_qs(urlsplit(started["authorize_url"]).query)["state"][0]
    assert status["connection"] == "connected"
    assert status["operation_state"] == "completed"
    assert status["authorize_url"] is None
    assert status["expires_in"] is None
    assert status["catalog_source"] == "live"
    # Codex is published but not activated, so it reports no active model of its
    # own and the deployment keeps running on whatever was already selected.
    assert status["active_model"] is None
    assert status["activated"] is False
    assert _selection(model_catalog.load()) == original_selection
    assert started["callback_port"] == 1455
    assert started["callback_forward_port"] == 4782
    assert started["redirect_uri"] == "http://localhost:1455/auth/callback"
    assert (
        started["ssh_forward_command"] == "ssh -N -L 1455:127.0.0.1:4782 <ssh-user>@<server-host>"
    )
    assert set(started) == {
        "operation_id",
        "authorize_url",
        "expires_in",
        "callback_port",
        "callback_forward_port",
        "redirect_uri",
        "ssh_forward_command",
    }


@pytest.mark.asyncio
async def test_callback_broker_keeps_waiting_after_wrong_state_then_completes(
    tmp_path: Path,
) -> None:
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    started = await service.start_login()
    expected_state = parse_qs(urlsplit(started["authorize_url"]).query)["state"][0]

    with pytest.raises(CodexAuthError) as exc_info:
        await service.receive_callback(
            code="do-not-accept",
            state="wrong-state",
            error=None,
        )

    assert exc_info.value.code == "state_mismatch"
    assert exc_info.value.http_status == 400
    assert service.public_status()["operation_state"] == "waiting"

    await service.receive_callback(
        code="authorization-code",
        state=expected_state,
        error=None,
    )
    status = await _wait_until_terminal(service)
    assert status["operation_state"] == "completed"


@pytest.mark.asyncio
async def test_callback_delivery_finds_the_login_that_owns_the_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A callback must reach the account that started the login, not the default root.

    The browser hits ``/auth/callback`` on the far end of its own tunnel, so the
    request carries no session and cannot name a user. Routing by the OAuth
    state is what keeps a non-administrator's sign-in from being delivered to
    the default root instead.
    """
    default_root = tmp_path / "user"
    member_root = tmp_path / "users" / "member"
    default_root.mkdir(parents=True)
    member_root.mkdir(parents=True)
    default_service, *_ = await _oauth_service(default_root)
    member_service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(member_root)
    monkeypatch.setattr(
        service_module,
        "_SERVICE_INSTANCES",
        {str(default_root): default_service, str(member_root): member_service},
    )

    started = await member_service.start_login()
    member_state = parse_qs(urlsplit(started["authorize_url"]).query)["state"][0]

    await service_module.deliver_codex_oauth_callback(
        code="authorization-code",
        state=member_state,
        error=None,
    )

    status = await _wait_until_terminal(member_service)
    assert status["operation_state"] == "completed"
    assert default_service.public_status()["operation_state"] is None


@pytest.mark.asyncio
async def test_callback_delivery_rejects_a_state_no_login_owns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    monkeypatch.setattr(service_module, "_SERVICE_INSTANCES", {str(tmp_path): service})
    await service.start_login()

    with pytest.raises(CodexAuthError) as exc_info:
        await service_module.deliver_codex_oauth_callback(
            code="do-not-accept",
            state="wrong-state",
            error=None,
        )

    assert exc_info.value.code == "state_mismatch"
    assert exc_info.value.http_status == 400
    assert service.public_status()["operation_state"] == "waiting"
    await service.cancel_login()


@pytest.mark.asyncio
async def test_callback_delivery_rejects_when_nothing_is_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    monkeypatch.setattr(service_module, "_SERVICE_INSTANCES", {str(tmp_path): service})

    with pytest.raises(CodexAuthError) as exc_info:
        await service_module.deliver_codex_oauth_callback(
            code="authorization-code",
            state="untrusted-state",
            error=None,
        )

    assert exc_info.value.code == "login_not_active"
    assert exc_info.value.http_status == 409


@pytest.mark.asyncio
async def test_callback_broker_rejects_when_no_login_is_active(tmp_path: Path) -> None:
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)

    with pytest.raises(CodexAuthError) as exc_info:
        await service.receive_callback(
            code="authorization-code",
            state="untrusted-state",
            error=None,
        )

    assert exc_info.value.code == "login_not_active"
    assert exc_info.value.http_status == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_state", ["snowman-\u2603", "a" * 129])
async def test_callback_broker_rejects_malformed_state_without_ending_login(
    tmp_path: Path,
    invalid_state: str,
) -> None:
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    await service.start_login()

    with pytest.raises(CodexAuthError) as exc_info:
        await service.receive_callback(
            code="do-not-accept",
            state=invalid_state,
            error=None,
        )

    assert exc_info.value.code == "state_mismatch"
    assert exc_info.value.http_status == 400
    assert service.public_status()["operation_state"] == "waiting"
    await service.cancel_login()


@pytest.mark.asyncio
async def test_background_callback_unicode_state_has_stable_error(
    tmp_path: Path,
) -> None:
    service, callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    await service.start_login()

    callback.complete_with_state("snowman-\u2603")
    status = await _wait_until_terminal(service)

    assert status["operation_state"] == "failed"
    assert status["error_code"] == "state_mismatch"


@pytest.mark.asyncio
async def test_login_status_keeps_callback_metadata_without_exposing_secrets(
    tmp_path: Path,
) -> None:
    clock = [1_000]
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(
        tmp_path,
        callback_error=CodexAuthError(
            "login_timeout",
            "Codex sign-in timed out.",
            408,
        ),
        clock=clock,
        callback_forward_port=4_782,
    )

    started = await service.start_login()
    waiting = service.public_status()
    clock[0] += 17
    later_waiting = service.public_status()
    timed_out = await _wait_until_terminal(service)

    assert waiting["operation_state"] == "waiting"
    assert waiting["authorize_url"] == started["authorize_url"]
    assert waiting["expires_in"] == started["expires_in"]
    assert later_waiting["authorize_url"] == started["authorize_url"]
    assert later_waiting["expires_in"] == started["expires_in"] - 17
    assert timed_out["operation_state"] == "expired"
    for status in (waiting, timed_out):
        assert status["callback_port"] == started["callback_port"] == 1455
        assert status["callback_forward_port"] == started["callback_forward_port"] == 4782
        assert (
            status["redirect_uri"]
            == started["redirect_uri"]
            == "http://localhost:1455/auth/callback"
        )
    assert timed_out["authorize_url"] is None
    assert timed_out["expires_in"] is None

    forbidden_fields = {
        "state_secret",
        "pkce",
        "verifier",
        "access_token",
        "refresh_token",
        "account_id",
        "email",
    }
    for payload in (started, waiting, timed_out):
        serialized = json.loads(json.dumps(payload))
        assert forbidden_fields.isdisjoint(serialized)


@pytest.mark.asyncio
async def test_catalog_failure_keeps_auth_but_not_selection(tmp_path: Path) -> None:
    service, callback, _oauth, _catalog, store, model_catalog = await _oauth_service(
        tmp_path,
        catalog_error=CodexAuthError(
            "catalog_unavailable",
            "The Codex model catalog is unavailable.",
            503,
        ),
    )
    original_selection = _selection(model_catalog.load())

    started = await service.start_login()
    callback.complete(started["authorize_url"])
    status = await _wait_until_terminal(service)

    assert status["connection"] == "connected"
    assert status["operation_state"] == "failed"
    assert status["error_code"] == "catalog_unavailable"
    assert _selection(model_catalog.load()) == original_selection
    assert store.load_credentials() is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("has_previous_credentials", [True, False])
async def test_account_switch_retires_old_catalog_before_fetching_new_models(
    tmp_path: Path,
    has_previous_credentials: bool,
) -> None:
    service, callback, oauth, catalog, store, model_catalog = await _oauth_service(tmp_path)
    if has_previous_credentials:
        store.commit_credentials(
            _stored_credentials(account_id="account-a"),
            expected_generation=0,
        )
    fallback_selection = _selection(model_catalog.load())
    account_a = sync_codex_catalog(
        model_catalog,
        _snapshot("account-a", _model("gpt-5.6-sol")),
        account_id="account-a",
    ).catalog
    profile = _managed_profile(account_a)
    profile["models"][0]["reasoning_effort"] = "high"
    llm = account_a["services"]["llm"]
    llm["active_profile_id"] = profile["id"]
    llm["active_model_id"] = profile["models"][0]["id"]
    model_catalog.save(account_a)

    oauth.exchange_payload["account_id"] = "account-b"
    catalog.snapshot = _snapshot("account-b", _model("gpt-5.6-sol"))
    catalog.get_started = asyncio.Event()
    catalog.get_release = asyncio.Event()

    started = await service.start_login()
    callback.complete(started["authorize_url"])
    await asyncio.wait_for(catalog.get_started.wait(), timeout=1)

    current = store.load_credentials()
    assert current is not None
    assert current.account_id == "account-b"
    during_fetch = model_catalog.load()
    assert not any(
        profile.get("managed_by") == MANAGED_BY
        for profile in during_fetch["services"]["llm"]["profiles"]
    )
    assert _selection(during_fetch) == fallback_selection

    catalog.get_release.set()
    status = await _wait_until_terminal(service)
    assert status["operation_state"] == "completed"


@pytest.mark.asyncio
async def test_failed_account_switch_rejects_a_stale_reasoning_write(
    tmp_path: Path,
) -> None:
    service, callback, oauth, catalog, store, model_catalog = await _oauth_service(tmp_path)
    store.commit_credentials(
        _stored_credentials(account_id="account-a"),
        expected_generation=0,
    )
    account_a = _snapshot("account-a", _model("account-a-only"))
    sync_codex_catalog(
        model_catalog,
        account_a,
        account_id="account-a",
    )
    oauth.exchange_payload["account_id"] = "account-b"
    catalog.error = CodexAuthError(
        "catalog_unavailable",
        "The Codex model catalog is unavailable.",
        503,
    )

    started = await service.start_login()
    callback.complete(started["authorize_url"])
    status = await _wait_until_terminal(service)
    before = model_catalog.load()

    current = store.load_credentials()
    assert current is not None
    assert current.account_id == "account-b"
    assert status["operation_state"] == "failed"
    assert status["models"] == []
    assert not any(
        profile.get("managed_by") == MANAGED_BY for profile in before["services"]["llm"]["profiles"]
    )
    with pytest.raises(CodexAuthError) as exc_info:
        await service.set_reasoning_effort("account-a-only", "high")
    assert exc_info.value.code == "codex_catalog_unavailable"
    assert model_catalog.load() == before


@pytest.mark.asyncio
async def test_unbound_managed_profile_is_hidden_and_read_only_until_refresh(
    tmp_path: Path,
) -> None:
    model_catalog, _original = _seeded_service(tmp_path)
    snapshot = _snapshot("legacy", _model("gpt-5.6-sol"))
    sync_codex_catalog(model_catalog, snapshot)
    store = CodexCredentialStore(tmp_path / "credentials")
    store.commit_credentials(_stored_credentials(), expected_generation=0)
    service = CodexOAuthService(
        store,
        FakeCatalog(snapshot),
        model_catalog,
        oauth_client=FakeOAuthClient(),
    )
    before = model_catalog.load()

    with pytest.raises(CodexAuthError) as exc_info:
        await service.set_reasoning_effort("gpt-5.6-sol", "high")

    assert exc_info.value.code == "codex_catalog_unavailable"
    assert service.public_status()["models"] == []
    assert model_catalog.load() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["state", "timeout", "exchange"])
async def test_login_failures_do_not_overwrite_old_credentials(
    tmp_path: Path,
    failure: str,
) -> None:
    callback_error = (
        CodexAuthError("login_timeout", "Codex sign-in timed out.", 408)
        if failure == "timeout"
        else None
    )
    service, callback, oauth, _catalog, store, _models = await _oauth_service(
        tmp_path,
        callback_error=callback_error,
    )
    old = store.commit_credentials(_stored_credentials(), expected_generation=0)
    if failure == "exchange":
        oauth.exchange_error = CodexAuthError(
            "token_exchange_failed",
            "Codex sign-in could not be completed.",
            502,
        )

    started = await service.start_login()
    if failure == "state":
        callback.complete_with_state("wrong-state")
    elif failure == "exchange":
        callback.complete(started["authorize_url"])
    status = await _wait_until_terminal(service)

    loaded = store.load_credentials()
    assert loaded is not None
    assert loaded.access_token == old.access_token
    assert status["operation_state"] == ("expired" if failure == "timeout" else "failed")
    assert status["authorize_url"] is None
    assert status["expires_in"] is None


@pytest.mark.asyncio
async def test_cancel_login_preserves_existing_credentials(tmp_path: Path) -> None:
    service, _callback, _oauth, _catalog, store, _models = await _oauth_service(tmp_path)
    old = store.commit_credentials(_stored_credentials(), expected_generation=0)

    await service.start_login()
    status = await service.cancel_login()

    loaded = store.load_credentials()
    assert loaded is not None
    assert loaded.access_token == old.access_token
    assert status["operation_state"] == "cancelled"
    assert status["authorize_url"] is None
    assert status["expires_in"] is None


@pytest.mark.asyncio
async def test_get_token_refreshes_inside_five_minute_window(tmp_path: Path) -> None:
    clock = [1_000]
    service, _callback, oauth, _catalog, store, _models = await _oauth_service(
        tmp_path,
        clock=clock,
    )
    store.commit_credentials(
        _stored_credentials(expires_at=1_200),
        expected_generation=0,
    )

    token = await service.get_token()

    assert oauth.refresh_calls == 1
    assert token.access_token == "refreshed-access"
    assert token.generation == 2


@pytest.mark.asyncio
async def test_refresh_rejects_changed_account_without_overwriting(tmp_path: Path) -> None:
    clock = [1_000]
    service, _callback, oauth, _catalog, store, _models = await _oauth_service(
        tmp_path,
        clock=clock,
    )
    original = store.commit_credentials(
        _stored_credentials(expires_at=1_200),
        expected_generation=0,
    )
    oauth.refresh_payload["account_id"] = "different-account"

    with pytest.raises(CodexAuthError) as exc_info:
        await service.get_token()

    assert exc_info.value.code == "account_changed"
    loaded = store.load_credentials()
    assert loaded is not None
    assert loaded.access_token == original.access_token


@pytest.mark.asyncio
async def test_late_refresh_cannot_resurrect_logged_out_credentials(tmp_path: Path) -> None:
    clock = [1_000]
    service, _callback, oauth, _catalog, store, _models = await _oauth_service(
        tmp_path,
        clock=clock,
    )
    committed = store.commit_credentials(
        _stored_credentials(expires_at=1_200),
        expected_generation=0,
    )
    oauth.refresh_started = asyncio.Event()
    oauth.refresh_release = asyncio.Event()

    refresh_task = asyncio.create_task(service.get_token())
    await oauth.refresh_started.wait()
    store.clear_credentials(expected_generation=committed.generation)
    oauth.refresh_release.set()

    with pytest.raises(CodexAuthError) as exc_info:
        await refresh_task
    assert exc_info.value.code == "generation_changed"
    assert store.load_credentials() is None


@pytest.mark.asyncio
async def test_logout_rejected_while_inference_is_active(tmp_path: Path) -> None:
    service, _callback, _oauth, _catalog, store, _models = await _oauth_service(tmp_path)
    store.commit_credentials(_stored_credentials(), expected_generation=0)

    async with service.inference_guard():
        with pytest.raises(CodexAuthError) as exc_info:
            await service.logout()

    assert exc_info.value.code == "inference_in_progress"
    assert store.load_credentials() is not None


@pytest.mark.asyncio
async def test_logout_cannot_be_undone_by_inflight_model_refresh(
    tmp_path: Path,
) -> None:
    service, _callback, _oauth, catalog, store, model_catalog = await _oauth_service(tmp_path)
    store.commit_credentials(_stored_credentials(), expected_generation=0)
    catalog.get_started = asyncio.Event()
    catalog.get_release = asyncio.Event()

    refresh_task = asyncio.create_task(service.refresh_models())
    await catalog.get_started.wait()
    logout_task = asyncio.create_task(service.logout())
    await asyncio.sleep(0)
    catalog.get_release.set()
    await asyncio.gather(refresh_task, logout_task)

    assert store.load_credentials() is None
    assert not any(
        profile.get("managed_by") == MANAGED_BY
        for profile in model_catalog.load()["services"]["llm"]["profiles"]
    )


@pytest.mark.asyncio
async def test_revoke_failure_does_not_block_local_logout_and_restore(
    tmp_path: Path,
) -> None:
    service, _callback, oauth, _catalog, store, model_catalog = await _oauth_service(tmp_path)
    committed = store.commit_credentials(_stored_credentials(), expected_generation=0)
    original = model_catalog.load()
    sync_codex_catalog(model_catalog, _snapshot("live", _model("gpt-5.6-sol")))
    oauth.revoke_error = CodexAuthError(
        "token_revoke_failed",
        "Codex authentication could not be revoked remotely.",
        502,
    )

    status = await service.logout()

    assert status["connection"] == "disconnected"
    assert store.current_generation() == committed.generation + 1
    assert store.load_credentials() is None
    assert _selection(model_catalog.load()) == _selection(original)


@pytest.mark.asyncio
async def test_restarted_service_restores_connection_without_operation_or_secrets(
    tmp_path: Path,
) -> None:
    service, _callback, oauth, catalog, store, model_catalog = await _oauth_service(tmp_path)
    del service
    committed = store.commit_credentials(
        CodexCredentials(
            schema_version=1,
            access_token="top-secret-access",
            refresh_token="top-secret-refresh",
            id_token="top-secret-id",
            account_id="full-account-secret",
            expires_at=10_000,
            generation=0,
        ),
        expected_generation=0,
    )
    store.save_catalog_cache(
        CatalogSnapshot(
            models=(_model("gpt-5.6-sol"),),
            source="live",
            fetched_at=1_000,
            etag=None,
            generation=committed.generation,
            account_hash="hash-only",
        ).to_dict()
    )
    restarted = CodexOAuthService(
        store,
        catalog,
        model_catalog,
        oauth_client=oauth,
        callback_factory=lambda _state: None,  # type: ignore[arg-type,return-value]
        clock=lambda: 1_000,
    )

    status = restarted.public_status()
    serialized = json.dumps(status)

    assert status["connection"] == "connected"
    assert status["operation_id"] is None
    assert status["operation_state"] is None
    assert status["callback_port"] is None
    assert status["callback_forward_port"] is None
    assert status["redirect_uri"] is None
    assert status["authorize_url"] is None
    assert status["expires_in"] is None
    assert "top-secret" not in serialized
    assert "full-account-secret" not in serialized


@pytest.mark.asyncio
async def test_recover_after_unauthorized_forces_refresh_for_next_request(
    tmp_path: Path,
) -> None:
    service, _callback, oauth, _catalog, store, _models = await _oauth_service(tmp_path)
    committed = store.commit_credentials(
        _stored_credentials(expires_at=10_000),
        expected_generation=0,
    )

    await service.recover_after_unauthorized(committed.generation)

    assert oauth.refresh_calls == 1
    assert store.load_credentials().access_token == "refreshed-access"  # type: ignore[union-attr]


_REDIRECT_URI = "http://localhost:1455/auth/callback"


@pytest.mark.parametrize(
    "pasted",
    [
        "http://localhost:1455/auth/callback?code=c&state=s&code=c2",
        "http://localhost:1455/auth/callback?state=s",
        "http://localhost:9999/auth/callback?code=c&state=s",
        "http://evil.example/auth/callback?code=c&state=s",
        "http://localhost:1455/somewhere-else?code=c&state=s",
        "localhost:1455/auth/callback?code=c&state=s",
        "not a url at all",
    ],
)
def test_a_pasted_address_that_is_not_this_logins_callback_is_refused(pasted: str) -> None:
    """The recovery form takes a string off the user's clipboard.

    Anything that is not the callback this process registered — another host,
    another port, another path, a repeated OAuth parameter, or no result at
    all — is refused before the code reaches the exchange.
    """
    with pytest.raises(CodexAuthError) as exc_info:
        parse_oauth_callback_url(pasted, _REDIRECT_URI)

    assert exc_info.value.code == "callback_url_invalid"
    assert exc_info.value.http_status == 400


def test_a_pasted_callback_yields_its_oauth_result() -> None:
    assert parse_oauth_callback_url(
        f"  {_REDIRECT_URI}?code=the-code&state=the-state  ", _REDIRECT_URI
    ) == ("the-code", "the-state", None)
    assert parse_oauth_callback_url(f"{_REDIRECT_URI}?error=access_denied", _REDIRECT_URI) == (
        None,
        None,
        "access_denied",
    )


@pytest.mark.asyncio
async def test_a_docker_user_finishes_a_login_by_pasting_the_callback_address(
    tmp_path: Path,
) -> None:
    """#1252: the browser reaches the callback address, the container does not.

    The loopback listener runs inside the container and the standard compose
    file does not publish its port, so the redirect dead-ends in the browser
    and the sign-in waits until it expires. Pasting the address back finishes
    the same exchange, with the same state check.
    """
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    started = await service.start_login()
    state = parse_qs(urlsplit(started["authorize_url"]).query)["state"][0]

    await service.complete_login_with_callback_url(
        f"{started['redirect_uri']}?code=authorization-code&state={state}"
    )

    assert (await _wait_until_terminal(service))["operation_state"] == "completed"


@pytest.mark.asyncio
async def test_a_callback_for_someone_elses_login_does_not_complete_this_one(
    tmp_path: Path,
) -> None:
    """The endpoint is authenticated, so it finishes the caller's own sign-in.

    A state minted for another account's login is not a credential this
    account may spend, and the address is not fetched to find out whose it is.
    """
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)
    started = await service.start_login()

    with pytest.raises(CodexAuthError) as exc_info:
        await service.complete_login_with_callback_url(
            f"{started['redirect_uri']}?code=authorization-code&state=another-accounts-state"
        )

    assert exc_info.value.code == "state_mismatch"
    assert service.public_status()["operation_state"] == "waiting"
    await service.cancel_login()


@pytest.mark.asyncio
async def test_pasting_a_callback_with_no_login_waiting_is_a_conflict(tmp_path: Path) -> None:
    service, _callback, _oauth, _catalog, _store, _models = await _oauth_service(tmp_path)

    with pytest.raises(CodexAuthError) as exc_info:
        await service.complete_login_with_callback_url(f"{_REDIRECT_URI}?code=c&state=s")

    assert exc_info.value.code == "login_not_active"
    assert exc_info.value.http_status == 409
