from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from deeptutor.services.codex_auth.constants import CODEX_CLIENT_VERSION
from deeptutor.services.codex_auth.contracts import (
    CatalogSnapshot,
    CodexAuthError,
    CodexCredentials,
    CodexModel,
)
from deeptutor.services.codex_auth.oauth import OAuthCallbackResult
from deeptutor.services.codex_auth.service import (
    CODEX_PROFILE_ID,
    CodexOAuthService,
    sync_codex_catalog,
)
from deeptutor.services.codex_auth.storage import CodexCredentialStore
from deeptutor.services.config.model_catalog import ModelCatalogService

pytestmark = pytest.mark.asyncio


def _model(slug: str) -> CodexModel:
    return CodexModel(
        slug=slug,
        display_name=slug,
        priority=1,
        visibility="list",
        default_reasoning_level="medium",
        supported_reasoning_levels=("medium",),
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
    )


def _credentials(account_id: str = "account-123", generation: int = 1) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id=account_id,
        expires_at=2_000_000_000,
        generation=generation,
    )


def _snapshot(
    credentials: CodexCredentials,
    client_version: str,
) -> CatalogSnapshot:
    return CatalogSnapshot(
        models=(_model("gpt-5.6-sol"),),
        source="live",
        fetched_at=1_000,
        etag='"catalog-v1"',
        generation=credentials.generation,
        account_hash=hashlib.sha256(credentials.account_id.encode()).hexdigest(),
        client_version=client_version,
    )


class FakeDiscovery:
    def __init__(self, result: str | None = None, error: CodexAuthError | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def discover(self) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeCatalog:
    def __init__(
        self,
        snapshot: CatalogSnapshot,
        errors: list[CodexAuthError] | None = None,
        store: CodexCredentialStore | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.errors = list(errors or [])
        self.versions: list[str] = []
        self.saved_snapshots: list[dict] = []
        self._store = store

    async def get(
        self,
        credentials: CodexCredentials,
        force: bool,
        client_version: str | None = None,
    ) -> CatalogSnapshot:
        del force
        assert client_version is not None
        self.versions.append(client_version)
        if self.errors:
            raise self.errors.pop(0)
        if client_version != self.snapshot.client_version:
            snapshot = CatalogSnapshot(
                models=self.snapshot.models,
                source=self.snapshot.source,
                fetched_at=self.snapshot.fetched_at,
                etag=self.snapshot.etag,
                generation=self.snapshot.generation,
                account_hash=self.snapshot.account_hash,
                client_version=client_version,
            )
            self.snapshot = snapshot
            self._save(snapshot)
            return snapshot
        self._save(self.snapshot)
        return self.snapshot

    def _save(self, snapshot: CatalogSnapshot) -> None:
        self.saved_snapshots.append(snapshot.to_dict())
        if self._store is not None:
            self._store.save_catalog_cache(
                snapshot.to_dict(),
                expected_generation=snapshot.generation,
            )

    async def invalidate(self) -> None:
        return None


class FakeCallback:
    def __init__(self) -> None:
        self.port = 1455
        self._result: asyncio.Future = asyncio.get_running_loop().create_future()
        self.expected_state: str | None = None

    async def wait(self, timeout: float):
        return await asyncio.wait_for(asyncio.shield(self._result), timeout)

    async def cancel(self) -> None:
        if not self._result.done():
            self._result.cancel()

    def complete(self) -> None:
        self._result.set_result(
            OAuthCallbackResult(
                code="authorization-code",
                state=self.expected_state,
                error=None,
            )
        )


class FakeOAuth:
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        verifier: str,
    ) -> dict:
        del code, redirect_uri, verifier
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "id_token": "new-id",
            "account_id": "account-123",
            "expires_in": 3_600,
        }


def _store(tmp_path: Path) -> tuple[CodexCredentialStore, CodexCredentials]:
    store = CodexCredentialStore(tmp_path / "secrets")
    credentials = store.commit_credentials(_credentials(generation=0), expected_generation=0)
    return store, credentials


def _model_catalog(tmp_path: Path) -> ModelCatalogService:
    model_catalog = ModelCatalogService(tmp_path / "model-catalog.json")
    sync_codex_catalog(model_catalog, _snapshot(_credentials(), CODEX_CLIENT_VERSION))
    return model_catalog


def _service(
    store: CodexCredentialStore,
    catalog: FakeCatalog,
    discovery: FakeDiscovery,
    model_catalog: ModelCatalogService,
    *,
    callback_factory=None,
) -> CodexOAuthService:
    return CodexOAuthService(
        store,
        catalog,  # type: ignore[arg-type]
        model_catalog,
        oauth_client=FakeOAuth(),  # type: ignore[arg-type]
        version_discovery=discovery,  # type: ignore[arg-type]
        callback_factory=callback_factory,
    )


async def test_refresh_uses_discovered_version_and_persists_it_after_success(
    tmp_path: Path,
) -> None:
    store, credentials = _store(tmp_path)
    discovery = FakeDiscovery("9.8.7")
    catalog = FakeCatalog(_snapshot(credentials, "9.8.7"), store=store)
    service = _service(store, catalog, discovery, _model_catalog(tmp_path))

    await service.refresh_models()

    assert catalog.versions == ["9.8.7"]
    assert discovery.calls == 1
    binding = hashlib.sha256(credentials.account_id.encode()).hexdigest()
    assert store.load_client_version(binding) == "9.8.7"
    assert store.load_catalog_cache()["client_version"] == "9.8.7"


async def test_discovery_failure_falls_back_before_the_built_in_version(
    tmp_path: Path,
) -> None:
    store, credentials = _store(tmp_path)
    binding = hashlib.sha256(credentials.account_id.encode()).hexdigest()
    store.record_client_version(
        binding,
        "1.2.3",
        expected_generation=credentials.generation,
    )
    discovery = FakeDiscovery(error=CodexAuthError("client_version_timeout", "timed out", 504))
    catalog = FakeCatalog(_snapshot(credentials, "1.2.3"))
    service = _service(store, catalog, discovery, _model_catalog(tmp_path))

    await service.refresh_models()

    assert catalog.versions == ["1.2.3"]
    assert store.load_client_version(binding) == "1.2.3"


async def test_version_rejection_retries_previous_version_at_most_once(
    tmp_path: Path,
) -> None:
    store, credentials = _store(tmp_path)
    binding = hashlib.sha256(credentials.account_id.encode()).hexdigest()
    store.record_client_version(
        binding,
        "1.2.3",
        expected_generation=credentials.generation,
    )
    discovery = FakeDiscovery("9.9.9")
    catalog = FakeCatalog(
        _snapshot(credentials, "1.2.3"),
        errors=[
            CodexAuthError("catalog_version_rejected", "version rejected", 400),
        ],
    )
    service = _service(store, catalog, discovery, _model_catalog(tmp_path))

    await service.refresh_models()

    assert catalog.versions == ["9.9.9", "1.2.3"]
    assert store.load_client_version(binding) == "1.2.3"


async def test_rate_limit_is_not_mistaken_for_version_incompatibility(
    tmp_path: Path,
) -> None:
    store, credentials = _store(tmp_path)
    discovery = FakeDiscovery("9.9.9")
    catalog = FakeCatalog(
        _snapshot(credentials, "9.9.9"),
        errors=[
            CodexAuthError("catalog_rate_limited", "rate limited", 429),
        ],
    )
    service = _service(store, catalog, discovery, _model_catalog(tmp_path))

    with pytest.raises(CodexAuthError) as exc_info:
        await service.refresh_models()

    assert exc_info.value.code == "catalog_rate_limited"
    assert catalog.versions == ["9.9.9"]


async def test_status_and_inference_do_not_discover_a_version(tmp_path: Path) -> None:
    store, committed = _store(tmp_path)
    discovery = FakeDiscovery("9.8.7")
    service = _service(
        store,
        FakeCatalog(_snapshot(committed, "9.8.7")),
        discovery,
        _model_catalog(tmp_path),
    )

    service.public_status()
    async with service.inference_guard():
        pass

    assert discovery.calls == 0


async def test_login_discovers_and_publishes_the_stable_version(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path / "secrets")
    discovery = FakeDiscovery("9.8.7")
    catalog = FakeCatalog(_snapshot(_credentials(), "9.8.7"), store=store)
    model_catalog = ModelCatalogService(tmp_path / "model-catalog.json")
    callback = FakeCallback()

    async def callback_factory(_state: str) -> FakeCallback:
        callback.expected_state = _state
        return callback

    service = _service(
        store,
        catalog,
        discovery,
        model_catalog,
        callback_factory=callback_factory,
    )

    started = await service.start_login()
    callback.complete()
    status = await _wait_until_terminal(service)

    assert status["operation_state"] == "completed", status
    assert catalog.versions == ["9.8.7"]
    assert any(
        profile["id"] == CODEX_PROFILE_ID
        for profile in model_catalog.load()["services"]["llm"]["profiles"]
    )
    assert started["operation_id"] == status["operation_id"]


async def test_late_cache_or_history_write_cannot_cross_generations(
    tmp_path: Path,
) -> None:
    store, credentials = _store(tmp_path)
    binding = hashlib.sha256(credentials.account_id.encode()).hexdigest()
    store.commit_credentials(
        _credentials(generation=credentials.generation),
        expected_generation=credentials.generation,
    )

    with pytest.raises(CodexAuthError) as cache_error:
        store.save_catalog_cache(
            _snapshot(credentials, "9.8.7").to_dict(),
            expected_generation=credentials.generation,
        )
    with pytest.raises(CodexAuthError) as history_error:
        store.record_client_version(
            binding,
            "9.8.7",
            expected_generation=credentials.generation,
        )

    assert cache_error.value.code == "generation_changed"
    assert history_error.value.code == "generation_changed"
    assert store.load_catalog_cache() is None


async def test_logout_clears_account_version_history(tmp_path: Path) -> None:
    store, credentials = _store(tmp_path)
    binding = hashlib.sha256(credentials.account_id.encode()).hexdigest()
    store.record_client_version(
        binding,
        "1.2.3",
        expected_generation=credentials.generation,
    )
    service = _service(
        store,
        FakeCatalog(_snapshot(credentials, "1.2.3")),
        FakeDiscovery(),
        _model_catalog(tmp_path),
    )

    await service.logout()

    assert store.load_client_version(binding) is None
    assert store.load_catalog_cache() is None


async def test_same_account_credential_renewal_preserves_history(tmp_path: Path) -> None:
    store, credentials = _store(tmp_path)
    binding = hashlib.sha256(credentials.account_id.encode()).hexdigest()
    store.record_client_version(
        binding,
        "1.2.3",
        expected_generation=credentials.generation,
    )
    renewed = store.commit_credentials(
        _credentials(generation=credentials.generation),
        expected_generation=credentials.generation,
    )

    assert renewed.generation == credentials.generation + 1
    assert store.load_client_version(binding) == "1.2.3"


async def _wait_until_terminal(service: CodexOAuthService) -> dict:
    for _ in range(100):
        status = service.public_status()
        if status["operation_state"] in {"completed", "cancelled", "expired", "failed"}:
            return status
        await asyncio.sleep(0)
    raise AssertionError("login did not finish")
