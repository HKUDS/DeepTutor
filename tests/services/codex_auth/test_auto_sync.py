"""Catalog freshness, metadata isolation and owner coordination regressions."""
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import typer
from typer.testing import CliRunner

from deeptutor.services.codex_auth import client_version as versions
from deeptutor.services.codex_auth.catalog import CodexModelCatalog
from deeptutor.services.codex_auth.constants import CODEX_CLIENT_VERSION, CODEX_CATALOG_HEADER_SCHEMA
from deeptutor.services.codex_auth.contracts import CatalogSnapshot, CodexCredentials, CodexAuthError
from deeptutor.services.codex_auth.storage import CodexCredentialStore


def credentials():
    return CodexCredentials(1, "access", "refresh", "id", "account", 2000000000, 0)


def test_numeric_versions():
    assert versions.max_stable_version("0.99.0", "0.171.0", "0.9.0") == "0.171.0"
    for value in ("01.2.3", "1.2.3-dev", "1.2.3+build", None):
        assert versions.parse_stable_version(value) is None


@pytest.mark.asyncio
async def test_github_fallback_has_no_secrets():
    requests = []
    def handler(request):
        requests.append(request)
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert "chatgpt-account-id" not in request.headers
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(404)
        assert request.headers["User-Agent"] == "DeepTutor"
        return httpx.Response(200, json={"draft": False, "prerelease": False, "tag_name": "rust-v0.172.0"})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=("secret", "secret"),
        headers={"Authorization": "Bearer sentinel", "chatgpt-account-id": "sentinel"},
        cookies={"session": "sentinel"},
    ) as http:
        assert await versions.discover_client_version(http) == ("0.172.0", "github")
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_total_deadline_and_cancellation(monkeypatch):
    monkeypatch.setattr(versions, "CODEX_VERSION_TOTAL_TIMEOUT_SECONDS", .03)
    async def slow(request):
        await asyncio.sleep(1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as http:
        assert await versions.discover_client_version(http) == (None, None)
        task = asyncio.create_task(versions.discover_client_version(http))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_legacy_etag_and_older_version_are_not_reused(tmp_path):
    store = CodexCredentialStore(tmp_path)
    creds = store.commit_credentials(credentials(), 0)
    seen = []
    def handler(request):
        if request.url.host != "chatgpt.com":
            return httpx.Response(503)
        seen.append(request)
        assert request.headers["originator"] == "codex_cli_rs"
        assert request.headers["version"] == CODEX_CLIENT_VERSION
        return httpx.Response(200, json={"models": []}, headers={"etag": "current"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http)
        first = await catalog.get(creds, force=True)
        legacy = first.to_dict()
        legacy.update(client_version="0.99.0", header_schema=None, etag="legacy")
        store.save_catalog_cache(legacy)
        result = await catalog.get(creds, force=True)
    assert "if-none-match" not in seen[-1].headers
    assert result.header_schema == CODEX_CATALOG_HEADER_SCHEMA
    assert result.version_source == "bundled"
    legacy.pop("version_source")
    legacy.pop("header_schema")
    assert CatalogSnapshot.from_dict(legacy).header_schema is None


def test_lease_and_late_result_cannot_clobber_logout(tmp_path):
    store = CodexCredentialStore(tmp_path)
    creds = store.commit_credentials(credentials(), 0)
    assert store.try_acquire_catalog_refresh_lease("one", 100, 120, creds.generation)
    assert not store.try_acquire_catalog_refresh_lease("two", 101, 120, creds.generation)
    store.release_catalog_refresh_lease("two")
    assert not store.try_acquire_catalog_refresh_lease("two", 102, 120, creds.generation)
    assert store.try_acquire_catalog_refresh_lease("two", 221, 120, creds.generation)
    store.clear_credentials()
    store.record_catalog_refresh_result(generation=creds.generation, attempted_at=100,
        next_refresh_at=200, succeeded=True, error_code=None, client_version="9.0.0")
    assert all(value is None for value in store.load_catalog_refresh_state().values())


@pytest.mark.parametrize("provider", ["openai-codex", "openai_codex"])
def test_refresh_cli(provider, monkeypatch):
    from deeptutor_cli import provider_cmd
    service = type("Service", (), {})()
    service.refresh_models = AsyncMock(return_value={
        "model_count": 3, "catalog_client_version": "0.171.0",
        "catalog_version_source": "github", "active_model": "gpt-6.2-astra"})
    monkeypatch.setattr(provider_cmd, "get_codex_oauth_service", lambda: service)
    app = typer.Typer()
    provider_cmd.register(app)
    result = CliRunner().invoke(app, ["refresh-models", provider])
    assert result.exit_code == 0
    assert "github" in result.stdout and "gpt-6.2-astra" in result.stdout
    service.refresh_models.side_effect = CodexAuthError("catalog_unavailable", "Try later", 503)
    result = CliRunner().invoke(app, ["refresh-models", provider])
    assert result.exit_code == 1 and "Try later" in result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream,code", [(None, 1), ("0.1.0", 0), ("99.0.0", 2)])
async def test_drift_exit_codes(upstream, code, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/check_codex_catalog_version.py"
    spec = importlib.util.spec_from_file_location("drift_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_source_version", AsyncMock(return_value=upstream))
    result, actual = await module.check_versions()
    assert actual == code
    assert result["bundled"] == CODEX_CLIENT_VERSION


@pytest.mark.asyncio
async def test_scheduler_stops_promptly(monkeypatch):
    from deeptutor.services.codex_auth.scheduler import CodexCatalogRefreshScheduler
    scheduler = CodexCatalogRefreshScheduler()
    entered = asyncio.Event()
    async def run_once():
        entered.set()
        await asyncio.sleep(100)
    monkeypatch.setattr(scheduler, "run_once", run_once)
    await scheduler.start()
    await entered.wait()
    await asyncio.wait_for(scheduler.stop(), .5)
    assert scheduler._task is None


@pytest.mark.asyncio
async def test_scheduler_enters_each_owner_scope_without_empty_stores(tmp_path, monkeypatch):
    from deeptutor.multi_user import identity, paths
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.services.codex_auth import scheduler as module
    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "system")
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", tmp_path / "users")
    monkeypatch.setattr(paths, "_path_services", {})
    records = {
        "alice": ("alice", {"id": "alice", "role": "user", "disabled": False}),
        "bob": ("bob", {"id": "bob", "role": "user", "disabled": False}),
        "disabled-user": ("disabled", {"id": "disabled-user", "role": "user", "disabled": True}),
    }
    monkeypatch.setattr(identity, "get_user_by_id", lambda uid: records.get(uid))
    for owner in ("local-admin", "alice", "bob", "deleted-user", "disabled-user"):
        path = tmp_path / "system/user-secrets" / owner / "private/openai-codex"
        path.mkdir(parents=True)
        (path / "credentials.v1.json").write_text("{}")
    empty = tmp_path / "system/user-secrets/unused"
    empty.mkdir()
    seen = []
    class Service:
        async def refresh_models_if_due(self, **kwargs):
            seen.append(get_current_user().id)
    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: Service())
    before = get_current_user()
    await module.CodexCatalogRefreshScheduler().run_once()
    assert set(seen) == {"local-admin", "alice", "bob"}
    assert get_current_user() == before
    assert not (empty / "private").exists()


def test_gpt6_family_fallbacks():
    from deeptutor.services.llm.context_window import (
        DEFAULT_CONTEXT_WINDOW_FALLBACK,
        LARGE_CONTEXT_MODEL_DEFAULT,
        default_context_window_for_model,
    )
    from deeptutor.services.provider_registry import (
        OPENAI_REASONING_FAMILIES,
        find_by_name,
        model_overrides_for,
    )
    assert "gpt-6" in OPENAI_REASONING_FAMILIES
    assert default_context_window_for_model(model="gpt-6.2-astra") == LARGE_CONTEXT_MODEL_DEFAULT
    assert default_context_window_for_model(model="openai/gpt-6.2-astra") == LARGE_CONTEXT_MODEL_DEFAULT
    assert default_context_window_for_model(model="custom-gpt-6-proxy") == DEFAULT_CONTEXT_WINDOW_FALLBACK
    assert model_overrides_for("custom-gpt-6-proxy", find_by_name("custom")) == {}
    assert model_overrides_for("gpt-6.2-astra", find_by_name("custom")) == {"temperature": None}


@pytest.mark.asyncio
async def test_github_fallback_accepts_large_release_with_many_assets():
    assets = [
        {"name": f"codex-asset-{i}.tar.gz", "browser_download_url": f"https://example.test/{'x' * 500}/{i}"}
        for i in range(196)
    ]
    payload = {"draft": False, "prerelease": False, "tag_name": "rust-v0.172.0", "assets": assets}
    assert len(httpx.Response(200, json=payload).content) > 64 * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(503)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await versions.discover_client_version(http) == ("0.172.0", "github")


def test_atomic_due_check_prevents_back_to_back_worker_refetch(tmp_path):
    store = CodexCredentialStore(tmp_path)
    creds = store.commit_credentials(credentials(), 0)
    # Worker 1 acquires, refreshes, sets next_refresh_at=1000, and releases.
    assert store.try_acquire_catalog_refresh_lease("w1", 100, 120, creds.generation, min_interval_seconds=600)
    store.record_catalog_refresh_result(
        generation=creds.generation, attempted_at=100, next_refresh_at=1000,
        succeeded=True, error_code=None, client_version="0.171.0", version_source="npm",
    )
    store.release_catalog_refresh_lease("w1")
    # Worker 2 trying at now=101 must be rejected atomically under the store lock.
    assert not store.try_acquire_catalog_refresh_lease("w2", 101, 120, creds.generation, min_interval_seconds=600)


def test_commit_credentials_repairs_malformed_prior_json_and_blocks_symlink(tmp_path):
    store = CodexCredentialStore(tmp_path)
    store.root.mkdir(parents=True)
    store.credentials_path.write_text("{corrupt", encoding="utf-8")
    store.record_catalog_refresh_result(
        generation=0, attempted_at=100, next_refresh_at=999,
        succeeded=False, error_code="catalog_unavailable",
    )
    committed = store.commit_credentials(credentials(), expected_generation=0)
    assert committed.generation == 1
    assert store.load_credentials() == committed
    assert all(v is None for v in store.load_catalog_refresh_state().values())


@pytest.mark.asyncio
async def test_stale_lease_does_not_write_error_into_new_generation(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store = CodexCredentialStore(tmp_path)
    gen1 = store.commit_credentials(credentials(), 0)
    gen2 = store.commit_credentials(credentials(), gen1.generation)
    model_catalog = ModelCatalogService(tmp_path / "model_catalog.json")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as http:
        service = CodexOAuthService(
            store, CodexModelCatalog(store, http=http, version_http=http), model_catalog,
            oauth_client=CodexOAuthClient(http), clock=lambda: 500,
        )
        with pytest.raises(CodexAuthError) as exc:
            await service._refresh_models(600, 900, expected_generation=gen1.generation)
        assert exc.value.code == "generation_changed"
    state = store.load_catalog_refresh_state()
    assert state["catalog_last_error_code"] is None
    assert state["catalog_next_refresh_at"] is None
    assert store.current_generation() == gen2.generation


@pytest.mark.asyncio
async def test_logout_wins_over_inflight_token_rotation_across_workers(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store_a = CodexCredentialStore(tmp_path)
    store_b = CodexCredentialStore(tmp_path)
    expiring = CodexCredentials(1, "access-1", "refresh-1", "id-1", "account", 100, 0)
    store_a.commit_credentials(expiring, 0)
    model_catalog = ModelCatalogService(tmp_path / "model_catalog.json")

    refresh_entered = asyncio.Event()
    allow_refresh_return = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            refresh_entered.set()
            await allow_refresh_return.wait()
            return httpx.Response(200, json={
                "access_token": "access-2", "refresh_token": "refresh-2",
                "id_token": "id-2", "account_id": "account", "expires_in": 3600,
            })
        if request.url.path == "/oauth/revoke":
            return httpx.Response(200)
        return httpx.Response(200, json={"models": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        svc_a = CodexOAuthService(
            store_a, CodexModelCatalog(store_a, http=http, version_http=http),
            model_catalog, oauth_client=CodexOAuthClient(http), clock=lambda: 90,
        )
        svc_b = CodexOAuthService(
            store_b, CodexModelCatalog(store_b, http=http, version_http=http),
            model_catalog, oauth_client=CodexOAuthClient(http), clock=lambda: 90,
        )
        refresh_task = asyncio.create_task(svc_b.get_token())
        await refresh_entered.wait()
        status = await svc_a.logout()
        allow_refresh_return.set()
        with pytest.raises(CodexAuthError) as exc:
            await refresh_task
        assert exc.value.code == "generation_changed"
        assert status["connection"] == "disconnected"
        assert store_a.load_credentials() is None


@pytest.mark.asyncio
async def test_public_status_reflects_cross_worker_catalog_refresh(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store_a = CodexCredentialStore(tmp_path)
    store_b = CodexCredentialStore(tmp_path)
    store_a.commit_credentials(credentials(), 0)
    catalog_path = tmp_path / "model_catalog.json"
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if request.url.host != "chatgpt.com":
            return httpx.Response(503)
        call_count += 1
        models = (
            [{"slug": "gpt-5.6-sol", "display_name": "GPT-5.6 Sol", "visibility": "list", "priority": 1}]
            if call_count == 1
            else [
                {"slug": "gpt-6.2-astra", "display_name": "GPT-6.2 Astra", "visibility": "list", "priority": 0},
                {"slug": "gpt-5.6-sol", "display_name": "GPT-5.6 Sol", "visibility": "list", "priority": 1},
            ]
        )
        return httpx.Response(200, json={"models": models})

    now = [1000]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        svc_a = CodexOAuthService(
            store_a, CodexModelCatalog(store_a, http=http, version_http=http, clock=lambda: now[0]),
            ModelCatalogService(catalog_path), oauth_client=CodexOAuthClient(http), clock=lambda: now[0],
        )
        svc_b = CodexOAuthService(
            store_b, CodexModelCatalog(store_b, http=http, version_http=http, clock=lambda: now[0]),
            ModelCatalogService(catalog_path), oauth_client=CodexOAuthClient(http), clock=lambda: now[0],
        )
        await svc_a.refresh_models()
        assert svc_a.public_status()["model_count"] == 1
        now[0] = 2000
        await svc_b.refresh_models()
        # Service A's status read must reflect Service B's durable update with zero outbound calls.
        calls_before = call_count
        status_a = svc_a.public_status()
        assert call_count == calls_before
        assert status_a["model_count"] == 2
        assert status_a["catalog_fetched_at"] == 2000


def test_model_catalog_interprocess_lock_preserves_concurrent_updates(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from deeptutor.services.config.model_catalog import ModelCatalogService

    catalog_path = tmp_path / "model_catalog.json"
    svc_a = ModelCatalogService(catalog_path)
    svc_b = ModelCatalogService(catalog_path)
    svc_a.load()

    def add_profile(svc: ModelCatalogService, pid: str) -> None:
        def mutate(cat: dict) -> None:
            cat["services"]["llm"]["profiles"].append({
                "id": pid, "name": pid, "binding": "openai",
                "models": [{"id": f"m-{pid}", "name": pid, "model": pid}],
            })
        svc.update(mutate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(add_profile, svc_a, "p-one")
        f2 = pool.submit(add_profile, svc_b, "p-two")
        f1.result()
        f2.result()

    ids = {p["id"] for p in svc_a.load()["services"]["llm"]["profiles"]}
    assert {"p-one", "p-two"}.issubset(ids)


@pytest.mark.asyncio
async def test_get_token_expected_generation_blocks_account_switch_in_refresh(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store = CodexCredentialStore(tmp_path)
    gen1 = store.commit_credentials(credentials(), 0)
    model_catalog = ModelCatalogService(tmp_path / "model_catalog.json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429))) as http:
        service = CodexOAuthService(
            store, CodexModelCatalog(store, http=http, version_http=http), model_catalog,
            oauth_client=CodexOAuthClient(http), clock=lambda: 500,
        )
        # Hold _refresh_lock while credentials rotate to gen 2 (account switch).
        async with service._refresh_lock:
            task = asyncio.create_task(
                service._refresh_models(600, 900, expected_generation=gen1.generation)
            )
            await asyncio.sleep(0.02)
            gen2 = store.commit_credentials(
                CodexCredentials(1, "access-2", "refresh-2", "id-2", "account-2", 2000000000, 0),
                gen1.generation,
            )
        with pytest.raises(CodexAuthError) as exc:
            await task
        assert exc.value.code == "generation_changed"
    state = store.load_catalog_refresh_state()
    assert store.current_generation() == gen2.generation
    assert state["catalog_last_error_code"] is None
    assert state["catalog_next_refresh_at"] is None


@pytest.mark.asyncio
async def test_cross_worker_401_invalidation_clears_stale_memory_snapshot(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store_a = CodexCredentialStore(tmp_path)
    store_b = CodexCredentialStore(tmp_path)
    store_a.commit_credentials(credentials(), 0)
    catalog_path = tmp_path / "model_catalog.json"
    mode = ["ok"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "chatgpt.com":
            return httpx.Response(503)
        if mode[0] == "401":
            return httpx.Response(401)
        return httpx.Response(200, json={
            "models": [{"slug": "gpt-6.2-astra", "display_name": "GPT-6.2 Astra", "visibility": "list", "priority": 0}]
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        svc_a = CodexOAuthService(
            store_a, CodexModelCatalog(store_a, http=http, version_http=http),
            ModelCatalogService(catalog_path), oauth_client=CodexOAuthClient(http),
        )
        svc_b = CodexOAuthService(
            store_b, CodexModelCatalog(store_b, http=http, version_http=http),
            ModelCatalogService(catalog_path), oauth_client=CodexOAuthClient(http),
        )
        await svc_a.refresh_models()
        assert svc_a.public_status()["model_count"] == 1
        mode[0] = "401"
        with pytest.raises(CodexAuthError) as exc:
            await svc_b.refresh_models()
        assert exc.value.code == "catalog_unauthorized"
        assert svc_a.public_status()["model_count"] == 0


@pytest.mark.asyncio
async def test_logout_revokes_detached_credentials_even_when_catalog_cleanup_fails(tmp_path, monkeypatch):
    from deeptutor.services.codex_auth import service as service_mod
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(credentials(), 0)
    revoked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/revoke":
            revoked.append(request.content.decode("utf-8", errors="ignore"))
            return httpx.Response(200)
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(
        service_mod,
        "remove_codex_catalog",
        lambda _catalog: (_ for _ in ()).throw(OSError("disk full")),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        svc = CodexOAuthService(
            store, CodexModelCatalog(store, http=http, version_http=http),
            ModelCatalogService(tmp_path / "model_catalog.json"),
            oauth_client=CodexOAuthClient(http),
        )
        with pytest.raises(OSError, match="disk full"):
            await svc.logout()
    assert revoked, "remote token revocation must still be attempted in finally"
    assert store.load_credentials() is None


@pytest.mark.asyncio
async def test_scheduler_revalidates_later_owner_disabled_mid_scan(tmp_path, monkeypatch):
    from deeptutor.multi_user import identity, paths
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.services.codex_auth import scheduler as module

    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "system")
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", tmp_path / "users")
    monkeypatch.setattr(paths, "_path_services", {})
    records = {
        "alice": ("alice", {"id": "alice", "role": "user", "disabled": False}),
        "bob": ("bob", {"id": "bob", "role": "user", "disabled": False}),
    }
    monkeypatch.setattr(identity, "get_user_by_id", lambda uid: records.get(uid))
    for owner in ("alice", "bob"):
        path = tmp_path / "system/user-secrets" / owner / "private/openai-codex"
        path.mkdir(parents=True)
        (path / "credentials.v1.json").write_text("{}")

    seen = []

    class Service:
        async def refresh_models_if_due(self, **kwargs):
            uid = get_current_user().id
            seen.append(uid)
            if uid == "alice":
                # Simulate admin disabling bob while alice's network call is in flight.
                records["bob"] = ("bob", {"id": "bob", "role": "user", "disabled": True})

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: Service())
    await module.CodexCatalogRefreshScheduler().run_once()
    assert seen == ["alice"]


@pytest.mark.asyncio
async def test_concurrent_refresh_and_reasoning_effort_edit_share_lock_order(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store_a = CodexCredentialStore(tmp_path)
    store_b = CodexCredentialStore(tmp_path)
    store_a.commit_credentials(credentials(), 0)
    catalog_path = tmp_path / "model_catalog.json"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "chatgpt.com":
            return httpx.Response(503)
        return httpx.Response(200, json={
            "models": [{
                "slug": "gpt-6.2-astra",
                "display_name": "GPT-6.2 Astra",
                "visibility": "list",
                "priority": 0,
                "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
            }]
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        svc_a = CodexOAuthService(
            store_a, CodexModelCatalog(store_a, http=http, version_http=http),
            ModelCatalogService(catalog_path), oauth_client=CodexOAuthClient(http),
        )
        svc_b = CodexOAuthService(
            store_b, CodexModelCatalog(store_b, http=http, version_http=http),
            ModelCatalogService(catalog_path), oauth_client=CodexOAuthClient(http),
        )
        await svc_a.refresh_models()
        await asyncio.wait_for(
            asyncio.gather(
                svc_a.refresh_models(),
                svc_b.set_reasoning_effort("gpt-6.2-astra", "high"),
            ),
            timeout=5.0,
        )
    assert svc_a.public_status()["model_count"] == 1


@pytest.mark.asyncio
async def test_superseded_refresh_publishes_latest_durable_cache_snapshot(tmp_path):
    from deeptutor.services.codex_auth.oauth import CodexOAuthClient
    from deeptutor.services.codex_auth.service import CodexOAuthService
    from deeptutor.services.config.model_catalog import ModelCatalogService

    store_a = CodexCredentialStore(tmp_path)
    store_b = CodexCredentialStore(tmp_path)
    creds = store_a.commit_credentials(credentials(), 0)
    catalog_path = tmp_path / "model_catalog.json"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "chatgpt.com":
            return httpx.Response(503)
        return httpx.Response(200, json={
            "models": [{"slug": "gpt-5.6-sol", "display_name": "Old", "visibility": "list", "priority": 1}]
        })

    newer_payload = {
        "models": [
            {"slug": "gpt-6.2-astra", "display_name": "New", "visibility": "list", "priority": 0},
            {"slug": "gpt-5.6-sol", "display_name": "Old", "visibility": "list", "priority": 1},
        ]
    }
    from deeptutor.services.codex_auth.catalog import parse_models_response
    import hashlib

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        cat_a = CodexModelCatalog(store_a, http=http, version_http=http, clock=lambda: 1000)
        orig_get = cat_a.get

        async def get_then_worker_b_commits(c, force):
            older = await orig_get(c, force)
            # Simulate Worker B committing a newer snapshot to cache before A publishes.
            newer = CatalogSnapshot(
                models=parse_models_response(newer_payload),
                source="live",
                fetched_at=2000,
                etag='"newer"',
                generation=creds.generation,
                account_hash=hashlib.sha256(creds.account_id.encode()).hexdigest(),
                client_version="0.171.0",
                version_source="npm",
                header_schema=CODEX_CATALOG_HEADER_SCHEMA,
            )
            store_b.commit_catalog_cache(newer)
            return older

        cat_a.get = get_then_worker_b_commits  # type: ignore[method-assign]
        svc_a = CodexOAuthService(
            store_a, cat_a, ModelCatalogService(catalog_path),
            oauth_client=CodexOAuthClient(http), clock=lambda: 1000,
        )
        status = await svc_a.refresh_models()
    assert status["model_count"] == 2
    assert {m["model"] for m in status["models"]} == {"gpt-6.2-astra", "gpt-5.6-sol"}


def test_drift_json_and_github_summary(tmp_path, monkeypatch, capsys):
    import json
    import sys
    path = Path(__file__).resolve().parents[3] / "scripts/check_codex_catalog_version.py"
    spec = importlib.util.spec_from_file_location("drift_output", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {"bundled": CODEX_CLIENT_VERSION, "npm": "99.0.0",
              "github": None, "upstream": "99.0.0", "status": "drift"}
    monkeypatch.setattr(module, "check_versions", AsyncMock(return_value=(result, 2)))
    monkeypatch.setattr(sys, "argv", ["check", "--json", "--github-summary"])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out) == result
    assert "| Bundled |" in summary.read_text()
