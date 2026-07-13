from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.provider_runtime import (
    ResolvedEmbeddingConfig,
    ResolvedLLMConfig,
)
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.embedding import client as embedding_client_module
from deeptutor.services.embedding import config as embedding_config_module
from deeptutor.services.llm import client as llm_client_module
from deeptutor.services.llm import config as llm_config_module


class _FakeEmbeddingAdapter:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def embed(self, request):
        return type("EmbeddingResponse", (), {"embeddings": [[] for _ in request.texts]})()


class _FakeCatalogService:
    def __init__(self, catalog: dict[str, Any]):
        self._catalog = deepcopy(catalog)

    def save(self, catalog: dict[str, Any]) -> dict[str, Any]:
        self._catalog = deepcopy(catalog)
        return deepcopy(self._catalog)

    def load(self) -> dict[str, Any]:
        return deepcopy(self._catalog)

    def apply(self, catalog: dict[str, Any]) -> dict[str, Any]:
        current = self.save(catalog)
        return {
            "catalog_path": "memory://model_catalog.json",
            "services": list(current["services"]),
        }


def _build_catalog(
    *,
    llm_model: str,
    llm_base_url: str,
    llm_api_key: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_api_key: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile-default",
                "active_model_id": "llm-model-default",
                "profiles": [
                    {
                        "id": "llm-profile-default",
                        "name": "Default LLM Endpoint",
                        "binding": "openai",
                        "base_url": llm_base_url,
                        "api_key": llm_api_key,
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "llm-model-default",
                                "name": llm_model,
                                "model": llm_model,
                            }
                        ],
                    }
                ],
            },
            "embedding": {
                "active_profile_id": "embedding-profile-default",
                "active_model_id": "embedding-model-default",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": embedding_base_url,
                        "api_key": embedding_api_key,
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": embedding_model,
                                "model": embedding_model,
                                "dimension": "1536",
                            }
                        ],
                    }
                ],
            },
            "search": {
                "active_profile_id": None,
                "profiles": [],
            },
        },
    }


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    service: _FakeCatalogService,
) -> None:
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(
        embedding_client_module,
        "_resolve_adapter_class",
        lambda _binding: _FakeEmbeddingAdapter,
    )

    def _resolve_llm_runtime_config() -> ResolvedLLMConfig:
        catalog = service.load()
        profile = catalog["services"]["llm"]["profiles"][0]
        model = profile["models"][0]
        return ResolvedLLMConfig(
            model=model["model"],
            provider_name=profile["binding"],
            provider_mode="standard",
            binding_hint=profile["binding"],
            binding=profile["binding"],
            api_key=profile["api_key"],
            base_url=profile["base_url"],
            effective_url=profile["base_url"],
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
        )

    def _resolve_embedding_runtime_config() -> ResolvedEmbeddingConfig:
        catalog = service.load()
        profile = catalog["services"]["embedding"]["profiles"][0]
        model = profile["models"][0]
        return ResolvedEmbeddingConfig(
            model=model["model"],
            provider_name=profile["binding"],
            provider_mode="standard",
            binding_hint=profile["binding"],
            binding=profile["binding"],
            api_key=profile["api_key"],
            base_url=profile["base_url"],
            effective_url=profile["base_url"],
            api_version=None,
            extra_headers={},
            dimension=int(model["dimension"]),
            request_timeout=60,
            batch_size=10,
        )

    monkeypatch.setattr(
        llm_config_module,
        "resolve_llm_runtime_config",
        _resolve_llm_runtime_config,
    )
    monkeypatch.setattr(
        embedding_config_module,
        "resolve_embedding_runtime_config",
        _resolve_embedding_runtime_config,
    )


@pytest.mark.asyncio
async def test_network_settings_roundtrip_normalizes_cors_origins(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    service.save_system({"backend_port": 8001, "frontend_port": 3782})
    service.save_auth({"enabled": True, "cookie_secure": True})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    payload = settings_router.NetworkSettingsUpdate(
        backend_port=8101,
        frontend_port=3882,
        public_api_base="https://api.example.com/deeptutor",
        cors_origins=["app.example.com; https://learn.example.com/path"],
    )

    response = await settings_router.update_network_settings(payload)

    assert response["settings"]["backend_port"] == 8101
    assert response["settings"]["public_api_base"] == "https://api.example.com/deeptutor"
    assert response["settings"]["cors_origins"] == [
        "http://app.example.com",
        "https://learn.example.com",
    ]
    assert response["effective"]["cors_mode"] == "explicit"
    assert response["auth"]["cross_site_cookie_ready"] is True


@pytest.mark.asyncio
async def test_mineru_settings_roundtrip_redacts_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    payload = settings_router.MinerUSettingsUpdate(
        mode="cloud",
        api_base_url="https://mineru.net/",
        api_token="secret-token",
        model_version="vlm",
    )
    response = await settings_router.update_mineru_settings(payload)

    # The raw token never leaves the backend; only a boolean flag does.
    assert response["api_token_set"] is True
    assert "api_token" not in response["settings"]
    assert response["settings"]["mode"] == "cloud"
    assert response["settings"]["api_base_url"] == "https://mineru.net"
    assert response["settings"]["model_version"] == "vlm"
    # Persisted on disk under the canonical key.
    assert service.load_mineru()["api_token"] == "secret-token"


@pytest.mark.asyncio
async def test_mineru_token_tristate_keep_then_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)
    service.save_mineru({"mode": "cloud", "api_token": "keep-me"})

    # api_token=None → keep the stored token.
    await settings_router.update_mineru_settings(
        settings_router.MinerUSettingsUpdate(mode="cloud", api_token=None)
    )
    assert service.load_mineru()["api_token"] == "keep-me"

    # api_token="" → explicitly clear it.
    await settings_router.update_mineru_settings(
        settings_router.MinerUSettingsUpdate(mode="cloud", api_token="")
    )
    assert service.load_mineru()["api_token"] == ""


@pytest.mark.asyncio
async def test_mineru_test_connection_reports_missing_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    result = await settings_router.test_mineru_connection(
        settings_router.MinerUSettingsUpdate(mode="cloud", api_token="")
    )
    assert result["ok"] is False
    assert "token" in result["message"].lower()


@pytest.mark.asyncio
async def test_mineru_payload_includes_local_cli_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from deeptutor.services.parsing.engines.mineru import backend as mineru_backend

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(
        mineru_backend,
        "local_cli_probe",
        lambda *a: {"found": True, "command": "mineru", "path": "/env/bin/mineru"},
    )

    payload = await settings_router.get_mineru_settings()
    assert payload["local_cli"] == {
        "found": True,
        "command": "mineru",
        "path": "/env/bin/mineru",
    }


@pytest.mark.asyncio
async def test_mineru_test_connection_local_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from deeptutor.services.parsing.engines.mineru import backend as mineru_backend

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    # CLI present → ok with version detail.
    monkeypatch.setattr(
        mineru_backend,
        "local_cli_probe",
        lambda *a: {"found": True, "command": "mineru", "path": "/env/bin/mineru"},
    )
    monkeypatch.setattr(mineru_backend, "local_cli_version", lambda cmd: "mineru, version 2.5.0")
    result = await settings_router.test_mineru_connection(
        settings_router.MinerUSettingsUpdate(mode="local")
    )
    assert result["ok"] is True
    assert "2.5.0" in result["message"]

    # CLI absent → actionable failure message.
    monkeypatch.setattr(
        mineru_backend, "local_cli_probe", lambda *a: {"found": False, "command": "", "path": ""}
    )
    result = await settings_router.test_mineru_connection(
        settings_router.MinerUSettingsUpdate(mode="local")
    )
    assert result["ok"] is False
    assert "not found" in result["message"].lower()

    # Bad configured path → message points at the path, not at PATH install.
    monkeypatch.setattr(
        mineru_backend,
        "local_cli_probe",
        lambda *a: {"found": False, "command": "", "path": "/bad/mineru", "source": "configured"},
    )
    result = await settings_router.test_mineru_connection(
        settings_router.MinerUSettingsUpdate(mode="local", local_cli_path="/bad/mineru")
    )
    assert result["ok"] is False
    assert "/bad/mineru" in result["message"]


@pytest.mark.asyncio
async def test_mineru_models_download_start_requires_downloader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.parsing.engines.mineru import models as mineru_models

    monkeypatch.setattr(
        mineru_models, "resolve_models_downloader", lambda p: {"found": False, "path": ""}
    )
    result = await settings_router.start_mineru_models_download(
        settings_router.MinerUModelDownloadPayload()
    )
    assert result["ok"] is False
    assert "not found" in result["message"].lower()

    # Configured CLI without a sibling downloader → message names the path.
    monkeypatch.setattr(
        mineru_models,
        "resolve_models_downloader",
        lambda p: {"found": False, "path": "/env/bin/mineru-models-download"},
    )
    result = await settings_router.start_mineru_models_download(
        settings_router.MinerUModelDownloadPayload(local_cli_path="/env/bin/mineru")
    )
    assert result["ok"] is False
    assert "/env/bin/mineru-models-download" in result["message"]


@pytest.mark.asyncio
async def test_mineru_models_download_start_and_status_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.parsing.engines.mineru import models as mineru_models

    calls: dict[str, object] = {}

    class _FakeManager:
        def start(self, **kwargs):
            calls.update(kwargs)
            return {"ok": True, "message": ""}

        def status(self, cursor=0):
            return {"state": "running", "lines": ["l1"], "next_cursor": 1, "message": ""}

        def cancel(self):
            return {"ok": True, "message": ""}

    monkeypatch.setattr(
        mineru_models,
        "resolve_models_downloader",
        lambda p: {"found": True, "path": "/env/bin/mineru-models-download"},
    )
    monkeypatch.setattr(mineru_models, "get_model_download_manager", lambda: _FakeManager())

    result = await settings_router.start_mineru_models_download(
        settings_router.MinerUModelDownloadPayload(
            model_type="all", source="modelscope", endpoint="https://hf-mirror.com"
        )
    )
    assert result["ok"] is True
    assert calls["downloader"] == "/env/bin/mineru-models-download"
    assert calls["model_type"] == "all"
    assert calls["source"] == "modelscope"

    status = await settings_router.mineru_models_download_status(cursor=0)
    assert status["lines"] == ["l1"]
    cancel = await settings_router.cancel_mineru_models_download()
    assert cancel["ok"] is True


def test_embedding_provider_choices_use_full_endpoint_urls() -> None:
    embedding = {item["value"]: item for item in settings_router._provider_choices()["embedding"]}

    assert embedding["openrouter"]["base_url"] == "https://openrouter.ai/api/v1/embeddings"
    assert embedding["ollama"]["base_url"] == "http://localhost:11434/api/embed"
    assert embedding["openai"]["base_url"] == "https://api.openai.com/v1/embeddings"
    assert "custom_openai_sdk" not in embedding


@pytest.mark.asyncio
async def test_get_llm_options_returns_redacted_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://llm.example/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://emb.example/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    response = await settings_router.get_llm_options()

    assert response["active"] == {
        "profile_id": "llm-profile-default",
        "model_id": "llm-model-default",
    }
    assert response["options"][0]["model"] == "gpt-4o-mini"
    assert "api_key" not in response["options"][0]
    assert "base_url" not in response["options"][0]


@pytest.fixture(autouse=True)
def _reset_runtime_state() -> None:
    llm_config_module.clear_llm_config_cache()
    llm_client_module.reset_llm_client()
    embedding_client_module.reset_embedding_client()
    yield
    llm_config_module.clear_llm_config_cache()
    llm_client_module.reset_llm_client()
    embedding_client_module.reset_embedding_client()


@pytest.mark.asyncio
async def test_update_catalog_invalidates_runtime_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    initial_catalog = _build_catalog(
        llm_model="gpt-old",
        llm_base_url="https://old-llm.example/v1",
        llm_api_key="old-llm-key",
        embedding_model="text-embedding-old",
        embedding_base_url="https://old-embedding.example/v1/embeddings",
        embedding_api_key="old-embedding-key",
    )
    updated_catalog = _build_catalog(
        llm_model="gpt-new",
        llm_base_url="https://new-llm.example/v1",
        llm_api_key="new-llm-key",
        embedding_model="text-embedding-new",
        embedding_base_url="https://new-embedding.example/v1/embeddings",
        embedding_api_key="new-embedding-key",
    )
    service = _FakeCatalogService(initial_catalog)
    _patch_runtime(monkeypatch, service)

    old_llm_config = llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    response = await settings_router.update_catalog(
        settings_router.CatalogPayload(catalog=updated_catalog)
    )

    new_llm_config = llm_config_module.get_llm_config()
    new_llm_client = llm_client_module.get_llm_client()
    new_embedding_client = embedding_client_module.get_embedding_client()

    assert response == {"catalog": updated_catalog}
    assert old_llm_config.model == "gpt-old"
    assert new_llm_config.model == "gpt-new"
    assert new_llm_config.base_url == "https://new-llm.example/v1"
    assert new_llm_config is not old_llm_config
    assert new_llm_client is not old_llm_client
    assert new_llm_client.config.model == "gpt-new"
    assert new_embedding_client is not old_embedding_client
    assert new_embedding_client.config.model == "text-embedding-new"
    assert new_embedding_client.config.base_url == "https://new-embedding.example/v1/embeddings"


@pytest.mark.asyncio
async def test_apply_catalog_invalidates_runtime_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    initial_catalog = _build_catalog(
        llm_model="gpt-before-apply",
        llm_base_url="https://before-apply-llm.example/v1",
        llm_api_key="before-apply-llm-key",
        embedding_model="text-embedding-before-apply",
        embedding_base_url="https://before-apply-embedding.example/v1/embeddings",
        embedding_api_key="before-apply-embedding-key",
    )
    applied_catalog = _build_catalog(
        llm_model="gpt-after-apply",
        llm_base_url="https://after-apply-llm.example/v1",
        llm_api_key="after-apply-llm-key",
        embedding_model="text-embedding-after-apply",
        embedding_base_url="https://after-apply-embedding.example/v1/embeddings",
        embedding_api_key="after-apply-embedding-key",
    )
    service = _FakeCatalogService(initial_catalog)
    _patch_runtime(monkeypatch, service)

    llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    response = await settings_router.apply_catalog(
        settings_router.CatalogPayload(catalog=applied_catalog)
    )

    new_llm_config = llm_config_module.get_llm_config()
    new_llm_client = llm_client_module.get_llm_client()
    new_embedding_client = embedding_client_module.get_embedding_client()

    assert response["catalog"] == applied_catalog
    assert response["runtime"]["catalog_path"]
    assert new_llm_config.model == "gpt-after-apply"
    assert new_llm_client is not old_llm_client
    assert new_llm_client.config.base_url == "https://after-apply-llm.example/v1"
    assert new_embedding_client is not old_embedding_client
    assert new_embedding_client.config.model == "text-embedding-after-apply"


@pytest.mark.asyncio
async def test_enabled_tools_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    # Default state — no file yet, so the loader emits the full toggleable set.
    assert set(settings_router.get_enabled_optional_tools()) == set(
        settings_router.USER_TOGGLEABLE_TOOL_NAMES
    )

    # PUT a partial set; unknown tool names get filtered out.
    update = settings_router.EnabledToolsUpdate(
        enabled_tools=["web_search", "reason", "not_a_real_tool"]
    )
    response = await settings_router.update_enabled_tools(update)
    assert response == {"enabled_optional_tools": ["web_search", "reason"]}
    assert settings_router.get_enabled_optional_tools() == ["web_search", "reason"]

    # Empty selection is a valid "all off" state.
    response = await settings_router.update_enabled_tools(
        settings_router.EnabledToolsUpdate(enabled_tools=[])
    )
    assert response == {"enabled_optional_tools": []}
    assert settings_router.get_enabled_optional_tools() == []


@pytest.mark.asyncio
async def test_complete_tour_invalidates_runtime_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    initial_catalog = _build_catalog(
        llm_model="gpt-before-tour",
        llm_base_url="https://before-tour-llm.example/v1",
        llm_api_key="before-tour-llm-key",
        embedding_model="text-embedding-before-tour",
        embedding_base_url="https://before-tour-embedding.example/v1/embeddings",
        embedding_api_key="before-tour-embedding-key",
    )
    completed_catalog = _build_catalog(
        llm_model="gpt-after-tour",
        llm_base_url="https://after-tour-llm.example/v1",
        llm_api_key="after-tour-llm-key",
        embedding_model="text-embedding-after-tour",
        embedding_base_url="https://after-tour-embedding.example/v1/embeddings",
        embedding_api_key="after-tour-embedding-key",
    )
    service = _FakeCatalogService(initial_catalog)
    _patch_runtime(monkeypatch, service)

    tour_cache = tmp_path / ".tour_cache.json"
    tour_cache.write_text('{"status": "running"}', encoding="utf-8")
    monkeypatch.setattr(settings_router, "TOUR_CACHE", tour_cache)

    llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    response = await settings_router.complete_tour(
        settings_router.TourCompletePayload(catalog=completed_catalog)
    )

    new_llm_config = llm_config_module.get_llm_config()
    new_llm_client = llm_client_module.get_llm_client()
    new_embedding_client = embedding_client_module.get_embedding_client()
    cache = tour_cache.read_text(encoding="utf-8")

    assert response["runtime"]["catalog_path"]
    assert response["status"] == "completed"
    assert new_llm_config.model == "gpt-after-tour"
    assert new_llm_client is not old_llm_client
    assert new_embedding_client is not old_embedding_client
    assert '"status": "completed"' in cache


@pytest.mark.asyncio
async def test_fetch_models_returns_picker_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.llm.factory as factory_module

    async def _fake_fetch(binding: str, base_url: str, api_key: str | None = None):
        assert binding == "openai"  # "OpenAI" is normalized to lowercase
        assert base_url == "https://api.example.com/v1"
        assert api_key == "sk-x"
        return ["gpt-4o", "gpt-4o-mini"]

    monkeypatch.setattr(factory_module, "fetch_models", _fake_fetch)

    response = await settings_router.fetch_models_from_provider(
        settings_router.FetchModelsPayload(
            binding="OpenAI", base_url="https://api.example.com/v1", api_key="sk-x"
        )
    )

    assert response == {
        "models": [
            {"id": "gpt-4o", "name": "gpt-4o"},
            {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
        ]
    }


@pytest.mark.asyncio
async def test_fetch_models_requires_base_url() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.fetch_models_from_provider(
            settings_router.FetchModelsPayload(base_url="   ")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_fetch_models_maps_provider_error_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    import deeptutor.services.llm.factory as factory_module

    async def _boom(binding: str, base_url: str, api_key: str | None = None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(factory_module, "fetch_models", _boom)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.fetch_models_from_provider(
            settings_router.FetchModelsPayload(binding="custom", base_url="https://x/v1")
        )
    assert exc_info.value.status_code == 502
