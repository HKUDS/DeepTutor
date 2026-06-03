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


def test_settings_payload_models_accept_german_ui_language() -> None:
    assert settings_router.LanguageUpdate(language="de").language == "de"
    assert settings_router.UISettings(language="de").language == "de"


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
