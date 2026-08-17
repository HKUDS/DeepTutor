from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.config.provider_runtime import (
    ResolvedEmbeddingConfig,
    ResolvedLLMConfig,
)
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.embedding import client as embedding_client_module
from deeptutor.services.embedding import config as embedding_config_module
from deeptutor.services.llm import client as llm_client_module
from deeptutor.services.llm import config as llm_config_module


def test_load_ui_settings_migrates_legacy_language_to_response_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings_file = tmp_path / "interface.json"
    settings_file.write_text('{"theme": "snow", "language": "zh"}', encoding="utf-8")
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    settings = settings_router.load_ui_settings()

    assert settings["language"] == "zh"
    assert settings["response_language"] == "zh"


def test_both_readers_of_interface_json_agree_on_a_legacy_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The router and the service must read the same file the same way.

    ``interface.json`` has two readers: ``interface_settings.get_ui_settings``
    (used by the turn path) and the router's ``load_ui_settings`` (which layers
    the API's superset of defaults on top). They resolve the language pair
    through one shared helper precisely so a legacy file can't mean different
    things depending on which one asked.
    """
    from deeptutor.services.settings import interface_settings

    settings_file = tmp_path / "interface.json"
    settings_file.write_text('{"theme": "dark", "language": "zh"}', encoding="utf-8")
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)
    monkeypatch.setattr(interface_settings, "_interface_settings_file", lambda: settings_file)

    from_router = settings_router.load_ui_settings()
    from_service = interface_settings.get_ui_settings()

    for field in ("language", "response_language"):
        assert from_router[field] == from_service[field] == "zh"


@pytest.mark.asyncio
async def test_ui_languages_are_persisted_independently(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    response = await settings_router.update_ui_settings(
        settings_router.UISettingsUpdate(theme="snow", language="en", response_language="zh")
    )

    assert response["language"] == "en"
    assert response["response_language"] == "zh"


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


class _FakeCodexOAuthService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start_login(self) -> dict[str, Any]:
        self.calls.append("start")
        return {
            "operation_id": "operation-1",
            "authorize_url": "https://auth.openai.com/oauth/authorize?state=opaque",
            "expires_in": 300,
        }

    def public_status(self) -> dict[str, Any]:
        self.calls.append("status")
        return {
            "connection": "connected",
            "operation_id": None,
            "operation_state": None,
            "model_count": 1,
            "catalog_source": "live",
            "catalog_fetched_at": 1_000,
            "active_model": "gpt-5.6-sol",
            "activated": False,
            "error_code": None,
        }

    async def cancel_login(self) -> dict[str, Any]:
        self.calls.append("cancel")
        return self.public_status()

    async def logout(self) -> dict[str, Any]:
        self.calls.append("logout")
        return self.public_status()

    async def refresh_models(self) -> dict[str, Any]:
        self.calls.append("refresh")
        return self.public_status()


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


def _managed_codex_profile(
    supported: list[str],
    reasoning_effort: str | None = None,
    *,
    account_binding: str | None = "account-binding",
) -> dict[str, Any]:
    model = {
        "id": "llm-model-openai-codex-sol",
        "name": "GPT 5.6 Sol",
        "model": "gpt-5.6-sol",
        "context_window": "128000",
        "context_window_source": "metadata",
        "codex_supported_reasoning_levels": supported,
    }
    if reasoning_effort is not None:
        model["reasoning_effort"] = reasoning_effort
    profile = {
        "id": "llm-profile-openai-codex-managed",
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "base_url": "https://chatgpt.com/backend-api",
        "api_key": "",
        "managed_by": "openai_codex_oauth",
        "read_only": True,
        "models": [model],
    }
    if account_binding is not None:
        profile["codex_account_binding"] = account_binding
    return profile


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
async def test_chat_attachment_settings_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    service.save_system({"backend_port": 8001, "frontend_port": 3782})
    monkeypatch.setattr(settings_router, "get_runtime_settings_service", lambda: service)

    initial = await settings_router.get_chat_attachment_settings()
    assert initial["settings"]["max_file_mb"] == 20
    assert initial["effective"]["max_file_bytes"] == 20 * 1024 * 1024

    payload = settings_router.ChatAttachmentSettingsUpdate(
        max_file_mb=100,
        max_total_mb=200,
        max_chars_per_doc=400_000,
        max_chars_total=300_000,
    )
    response = await settings_router.update_chat_attachment_settings(payload)

    assert response["settings"]["max_file_mb"] == 100
    assert response["settings"]["max_total_mb"] == 200
    assert response["effective"]["max_total_bytes"] == 200 * 1024 * 1024
    # WS frame ceiling covers the base64-inflated total.
    assert response["effective"]["ws_max_size"] > (200 * 1024 * 1024 * 4) // 3
    # Other system.json keys survive the partial update.
    stored = service.load_system(include_process_overrides=False)
    assert stored["backend_port"] == 8001
    assert stored["chat_attachment_max_chars_per_doc"] == 400_000


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


def test_llm_provider_choices_include_atlascloud() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["atlascloud"]["label"] == "Atlas Cloud"
    assert llm["atlascloud"]["base_url"] == "https://api.atlascloud.ai/v1"


def test_llm_provider_choices_include_novita() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["novita"]["label"] == "Novita AI"
    assert llm["novita"]["base_url"] == "https://api.novita.ai/openai"


def test_llm_provider_choices_include_edenai() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["edenai"]["label"] == "Eden AI"
    assert llm["edenai"]["base_url"] == "https://api.edenai.run/v3"


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


@pytest.mark.asyncio
async def test_get_settings_never_returns_catalog_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://llm.example/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://emb.example/v1/embeddings",
        embedding_api_key="emb-key",
    )
    catalog["services"]["llm"]["profiles"][0]["extra_headers"] = {"Authorization": "Bearer secret"}
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    response = await settings_router.get_settings()

    llm_profile = response["catalog"]["services"]["llm"]["profiles"][0]
    embedding_profile = response["catalog"]["services"]["embedding"]["profiles"][0]
    assert llm_profile["api_key"] == settings_router.CATALOG_SECRET_MASK
    assert llm_profile["extra_headers"]["Authorization"] == settings_router.CATALOG_SECRET_MASK
    assert embedding_profile["api_key"] == settings_router.CATALOG_SECRET_MASK
    assert "secret-key" not in json.dumps(response)
    assert "emb-key" not in json.dumps(response)


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

    assert response == {"catalog": settings_router.redact_catalog_secrets(updated_catalog)}
    assert service.load() == updated_catalog
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

    assert response["catalog"] == settings_router.redact_catalog_secrets(applied_catalog)
    assert service.load() == applied_catalog
    assert response["runtime"]["catalog_path"]
    assert new_llm_config.model == "gpt-after-apply"
    assert new_llm_client is not old_llm_client
    assert new_llm_client.config.base_url == "https://after-apply-llm.example/v1"
    assert new_embedding_client is not old_embedding_client
    assert new_embedding_client.config.model == "text-embedding-after-apply"


@pytest.mark.asyncio
async def test_update_catalog_restores_masked_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    current = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://llm.example/v1",
        llm_api_key="stored-llm-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://emb.example/v1/embeddings",
        embedding_api_key="stored-embedding-key",
    )
    service = _FakeCatalogService(current)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(settings_router, "_invalidate_runtime_caches", lambda: None)
    draft = settings_router.redact_catalog_secrets(current)
    draft["services"]["llm"]["profiles"][0]["name"] = "Renamed"

    response = await settings_router.update_catalog(settings_router.CatalogPayload(catalog=draft))

    saved = service.load()
    assert saved["services"]["llm"]["profiles"][0]["api_key"] == "stored-llm-key"
    assert saved["services"]["embedding"]["profiles"][0]["api_key"] == ("stored-embedding-key")
    assert response["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == (
        settings_router.CATALOG_SECRET_MASK
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "apply"])
@pytest.mark.parametrize(
    ("supported", "requested", "expected"),
    [
        (["medium"], "high", None),
        (["medium", "high"], "high", "high"),
        (["medium", "high"], None, None),
    ],
)
async def test_catalog_writes_preserve_current_managed_codex_metadata(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    supported: list[str],
    requested: str | None,
    expected: str | None,
) -> None:
    current = _build_catalog(
        llm_model="gpt-standard",
        llm_base_url="https://llm.example/v1",
        llm_api_key="llm-key",
        embedding_model="text-embedding-current",
        embedding_base_url="https://embedding.example/v1/embeddings",
        embedding_api_key="",
    )
    managed_profile = _managed_codex_profile(
        supported,
        reasoning_effort="medium" if requested is None else None,
    )
    managed_model = managed_profile["models"][0]
    current["services"]["llm"]["profiles"].append(managed_profile)
    current["services"]["llm"]["active_profile_id"] = managed_profile["id"]
    current["services"]["llm"]["active_model_id"] = managed_model["id"]
    service = _FakeCatalogService(current)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(settings_router, "_invalidate_runtime_caches", lambda: None)

    stale_draft = deepcopy(current)
    stale_draft["services"]["embedding"]["profiles"][0]["name"] = "Unsaved edit"
    stale_model = stale_draft["services"]["llm"]["profiles"][1]["models"][0]
    stale_model["context_window"] = "272000"
    stale_model["codex_supported_reasoning_levels"] = ["medium", "high", "xhigh"]
    if requested is not None:
        stale_model["reasoning_effort"] = requested
    else:
        stale_model.pop("reasoning_effort", None)
    payload = settings_router.CatalogPayload(catalog=stale_draft)

    if operation == "save":
        await settings_router.update_catalog(payload)
    else:
        await settings_router.apply_catalog(payload)

    stored = service.load()
    stored_model = stored["services"]["llm"]["profiles"][1]["models"][0]
    assert stored_model["context_window"] == "128000"
    assert stored_model["codex_supported_reasoning_levels"] == supported
    assert stored_model.get("reasoning_effort") == expected
    assert stored["services"]["embedding"]["profiles"][0]["name"] == "Unsaved edit"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "apply"])
@pytest.mark.parametrize(
    ("current_binding", "proposed_binding"),
    [
        ("account-b-binding", "account-a-binding"),
        (None, None),
    ],
)
async def test_catalog_write_rejects_unbound_or_cross_account_codex_reasoning_changes(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    current_binding: str | None,
    proposed_binding: str | None,
) -> None:
    current = _build_catalog(
        llm_model="gpt-standard",
        llm_base_url="https://llm.example/v1",
        llm_api_key="llm-key",
        embedding_model="text-embedding-current",
        embedding_base_url="https://embedding.example/v1/embeddings",
        embedding_api_key="",
    )
    current_profile = _managed_codex_profile(
        ["medium", "high"],
        reasoning_effort="medium",
        account_binding=current_binding,
    )
    current["services"]["llm"]["profiles"].append(current_profile)
    service = _FakeCatalogService(current)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(settings_router, "_invalidate_runtime_caches", lambda: None)

    stale_draft = deepcopy(current)
    stale_profile = stale_draft["services"]["llm"]["profiles"][1]
    if proposed_binding is None:
        stale_profile.pop("codex_account_binding", None)
    else:
        stale_profile["codex_account_binding"] = proposed_binding
    stale_profile["models"][0]["reasoning_effort"] = "high"
    payload = settings_router.CatalogPayload(catalog=stale_draft)

    if operation == "save":
        await settings_router.update_catalog(payload)
    else:
        await settings_router.apply_catalog(payload)

    stored_profile = service.load()["services"]["llm"]["profiles"][1]
    assert stored_profile.get("codex_account_binding") == current_binding
    assert stored_profile["models"][0]["reasoning_effort"] == "medium"


@pytest.mark.asyncio
@pytest.mark.parametrize("current_has_managed", [True, False])
async def test_catalog_write_uses_current_managed_codex_profile_presence(
    monkeypatch: pytest.MonkeyPatch,
    current_has_managed: bool,
) -> None:
    base = _build_catalog(
        llm_model="gpt-standard",
        llm_base_url="https://llm.example/v1",
        llm_api_key="llm-key",
        embedding_model="text-embedding-current",
        embedding_base_url="https://embedding.example/v1/embeddings",
        embedding_api_key="",
    )
    current = deepcopy(base)
    stale_draft = deepcopy(base)
    managed_profile = _managed_codex_profile(["medium", "high"])
    if current_has_managed:
        current["services"]["llm"]["profiles"].append(managed_profile)
    else:
        stale_draft["services"]["llm"]["profiles"].append(managed_profile)
    service = _FakeCatalogService(current)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(settings_router, "_invalidate_runtime_caches", lambda: None)

    await settings_router.update_catalog(settings_router.CatalogPayload(catalog=stale_draft))

    managed = [
        profile
        for profile in service.load()["services"]["llm"]["profiles"]
        if profile.get("managed_by") == "openai_codex_oauth"
    ]
    assert bool(managed) is current_has_managed


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "apply"])
async def test_incomplete_catalog_write_preserves_the_current_managed_codex_profile(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    current = _build_catalog(
        llm_model="gpt-standard",
        llm_base_url="https://llm.example/v1",
        llm_api_key="llm-key",
        embedding_model="text-embedding-current",
        embedding_base_url="https://embedding.example/v1/embeddings",
        embedding_api_key="",
    )
    managed_profile = _managed_codex_profile(
        ["medium", "high"],
        reasoning_effort="medium",
        account_binding="current-account-binding",
    )
    current["services"]["llm"]["profiles"].append(managed_profile)
    service = _FakeCatalogService(current)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(settings_router, "_invalidate_runtime_caches", lambda: None)
    payload = settings_router.CatalogPayload(catalog={"version": 1})

    if operation == "save":
        await settings_router.update_catalog(payload)
    else:
        await settings_router.apply_catalog(payload)

    stored_profiles = service.load()["services"]["llm"]["profiles"]
    assert stored_profiles == [managed_profile]


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
async def test_fetch_models_resolves_masked_key_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.services.llm.factory as factory_module

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://llm.example/v1",
        llm_api_key="stored-secret",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://emb.example/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    async def _fake_fetch(binding: str, base_url: str, api_key: str | None = None):
        assert (binding, base_url, api_key) == (
            "openai",
            "https://llm.example/v1",
            "stored-secret",
        )
        return ["gpt-4o-mini"]

    monkeypatch.setattr(factory_module, "fetch_models", _fake_fetch)

    response = await settings_router.fetch_models_from_provider(
        settings_router.FetchModelsPayload(
            binding="openai",
            base_url="https://llm.example/v1",
            api_key=settings_router.CATALOG_SECRET_MASK,
            profile_id="llm-profile-default",
        )
    )

    assert response == {"models": [{"id": "gpt-4o-mini", "name": "gpt-4o-mini"}]}


@pytest.mark.asyncio
async def test_fetch_models_requires_base_url() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.fetch_models_from_provider(
            settings_router.FetchModelsPayload(base_url="   ")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_fetch_models_allows_codebuddy_without_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.services.llm.factory as factory_module

    async def _fake_fetch(binding: str, base_url: str, api_key: str | None = None):
        assert (binding, base_url, api_key) == ("codebuddy", "", None)
        return ["hy3", "glm-5.2"]

    monkeypatch.setattr(factory_module, "fetch_models", _fake_fetch)

    response = await settings_router.fetch_models_from_provider(
        settings_router.FetchModelsPayload(binding="codebuddy")
    )

    assert response == {
        "models": [
            {"id": "hy3", "name": "hy3"},
            {"id": "glm-5.2", "name": "glm-5.2"},
        ]
    }


@pytest.mark.asyncio
async def test_codebuddy_auth_routes_use_admin_scoped_service(monkeypatch) -> None:
    class FakeService:
        async def status(self):
            return {"connection": "connected"}

        async def start_login(self):
            return {"connection": "authorizing"}

        async def cancel_login(self):
            return {"connection": "disconnected"}

        async def logout(self):
            return {"connection": "disconnected", "user_label": None}

    monkeypatch.setattr(settings_router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(settings_router, "get_codebuddy_auth_service", lambda: FakeService())

    assert await settings_router.get_codebuddy_auth_status() == {"connection": "connected"}
    assert await settings_router.start_codebuddy_auth() == {"connection": "authorizing"}
    assert await settings_router.cancel_codebuddy_auth() == {"connection": "disconnected"}
    assert await settings_router.logout_codebuddy_auth() == {
        "connection": "disconnected",
        "user_label": None,
    }


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


@pytest.mark.asyncio
async def test_update_ui_settings_preserves_theme_and_language_when_code_block_update_omits_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Given: stored appearance settings differ from the UI defaults.
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)
    settings_router.save_ui_settings(
        {
            **settings_router.DEFAULT_UI_SETTINGS,
            "theme": "dark",
            "language": "zh",
        }
    )

    # When: a code-block-only partial update arrives.
    response = await settings_router.update_ui_settings(
        settings_router.UISettingsUpdate(code_block_theme="dracula")
    )

    # Then: omitted appearance settings remain unchanged while the patch persists.
    persisted = settings_router.load_ui_settings()
    assert response["theme"] == "dark"
    assert response["language"] == "zh"
    assert persisted["code_block_theme"] == "dracula"


@pytest.mark.asyncio
async def test_get_ui_settings_returns_persisted_interface_preferences(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)
    settings_router.save_ui_settings(
        {
            **settings_router.DEFAULT_UI_SETTINGS,
            "theme": "dark",
            "language": "zh",
        }
    )

    response = await settings_router.get_ui_settings()

    assert response["theme"] == "dark"
    assert response["language"] == "zh"


def test_codex_provider_choice_is_advertised_as_oauth() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["openai_codex"] == {
        "value": "openai_codex",
        "label": "OpenAI Codex",
        "base_url": "https://chatgpt.com/backend-api",
        "auth_mode": "oauth",
    }
    # API-key providers keep the same shape, so the frontend never special-cases
    # a missing field.
    assert llm["openai"]["auth_mode"] == "api_key"


@pytest.mark.asyncio
async def test_codex_oauth_status_is_reachable_by_an_ordinary_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex OAuth is personal, not administrative (#781).

    This route used to be administrator-gated, which left ordinary users with
    no path to Codex at all: an owner-bound profile is never grantable, so
    they could neither be given one nor sign in for themselves. Everything it
    touches — credential store, model catalog, callback route — resolves from
    owner scope, so it is the caller's own login either way. The full
    authorization contract, including the partner refusal that replaced the
    admin gate, lives in ``tests/api/test_codex_oauth_scope.py``.
    """
    fake = _FakeCodexOAuthService()
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: SimpleNamespace(id="u_alice", is_admin=False),
    )
    monkeypatch.setattr(
        settings_router,
        "get_codex_oauth_service",
        lambda: fake,
        raising=False,
    )

    assert await settings_router.get_openai_codex_oauth_status() == fake.public_status()


@pytest.mark.asyncio
async def test_codex_oauth_routes_return_only_public_service_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCodexOAuthService()
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: SimpleNamespace(id="root", is_admin=True),
    )
    monkeypatch.setattr(
        settings_router,
        "get_codex_oauth_service",
        lambda: fake,
        raising=False,
    )

    started = await settings_router.start_openai_codex_oauth()
    status_payload = await settings_router.get_openai_codex_oauth_status()
    cancelled = await settings_router.cancel_openai_codex_oauth()
    refreshed = await settings_router.refresh_openai_codex_models()
    logged_out = await settings_router.logout_openai_codex_oauth()

    assert set(started) == {"operation_id", "authorize_url", "expires_in"}
    assert (
        "token"
        not in json.dumps([started, status_payload, cancelled, refreshed, logged_out]).lower()
    )
    assert fake.calls == [
        "start",
        "status",
        "cancel",
        "status",
        "refresh",
        "status",
        "logout",
        "status",
    ]


@pytest.mark.asyncio
async def test_codex_oauth_error_maps_to_sanitized_http_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    class FailingService:
        async def start_login(self) -> dict[str, Any]:
            raise CodexAuthError(
                "token_exchange_failed",
                "Codex sign-in could not be completed.",
                502,
            )

    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: SimpleNamespace(id="root", is_admin=True),
    )
    monkeypatch.setattr(
        settings_router,
        "get_codex_oauth_service",
        lambda: FailingService(),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.start_openai_codex_oauth()

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == {
        "code": "token_exchange_failed",
        "message": "Codex sign-in could not be completed.",
    }


@pytest.mark.asyncio
async def test_update_ui_settings_persists_explicit_theme_and_language_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Given: stored appearance settings differ from the values being reset.
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)
    settings_router.save_ui_settings(
        {
            **settings_router.DEFAULT_UI_SETTINGS,
            "theme": "dark",
            "language": "zh",
        }
    )

    # When: the frontend explicitly provides the full-model default values.
    await settings_router.update_ui_settings(
        settings_router.UISettingsUpdate(theme="snow", language="en")
    )

    # Then: explicit values persist instead of being mistaken for omitted fields.
    persisted = settings_router.load_ui_settings()
    assert persisted["theme"] == "snow"
    assert persisted["language"] == "en"


def test_get_ui_settings_is_public_without_auth(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Auth pages bootstrap the interface language *before* a session exists.

    Regression for #760: the app shell fetches GET /api/v1/settings/ui on the
    /register and /login pages, which have no session. When the endpoint sat
    behind the ``_auth`` dependency it returned 401, the bootstrap silently
    bailed out, and the auth pages stayed English even with the persisted
    language set to zh. The read lives on ``public_router`` so it is reachable
    anonymously (it only exposes non-sensitive UI preferences).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)
    settings_router.save_ui_settings(
        {
            **settings_router.DEFAULT_UI_SETTINGS,
            "theme": "dark",
            "language": "zh",
        }
    )

    app = FastAPI()
    app.include_router(settings_router.public_router, prefix="/api/v1/settings")

    client = TestClient(app)
    response = client.get("/api/v1/settings/ui")

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "zh"
    assert payload["theme"] == "dark"


def test_auth_disabled_settings_endpoint_does_not_expose_provider_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #857: local-admin mode is not a secret-viewing mode."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import auth as auth_router

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://llm.example/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://emb.example/v1/embeddings",
        embedding_api_key="emb-key",
    )
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)
    monkeypatch.setattr(
        settings_router,
        "get_model_catalog_service",
        lambda: _FakeCatalogService(catalog),
    )

    app = FastAPI()
    app.include_router(
        settings_router.router,
        prefix="/api/v1/settings",
        dependencies=[Depends(auth_router.require_auth)],
    )

    response = TestClient(app).get("/api/v1/settings")

    assert response.status_code == 200
    serialized = response.text
    assert "secret-key" not in serialized
    assert "emb-key" not in serialized
    assert settings_router.CATALOG_SECRET_MASK in serialized


def test_public_ui_read_omits_deployment_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The anonymous read must not enumerate what the deployment turned on.

    ``ui`` also carries sidebar_nav_order, enabled_optional_tools and
    chat_response_timeout. Those describe the deployment rather than the
    visitor, so the pre-session projection stops at theme + language and the
    rest stays behind auth on GET /settings.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)
    settings_router.save_ui_settings(
        {
            **settings_router.DEFAULT_UI_SETTINGS,
            "language": "zh",
            "enabled_optional_tools": ["rag", "web_search"],
            "chat_response_timeout": 900,
        }
    )

    app = FastAPI()
    app.include_router(settings_router.public_router, prefix="/api/v1/settings")

    payload = TestClient(app).get("/api/v1/settings/ui").json()

    assert set(payload) == set(settings_router.PRESESSION_UI_FIELDS)
    assert "enabled_optional_tools" not in payload
    assert "chat_response_timeout" not in payload
    assert "sidebar_nav_order" not in payload


def test_get_ui_settings_not_registered_on_gated_router() -> None:
    """The public read is not duplicated on the auth-gated settings router.

    The write (PUT /ui) stays auth-gated; only the anonymous read moved to
    ``public_router``.
    """
    gated_methods = {
        method
        for route in settings_router.router.routes
        for method in (getattr(route, "methods", None) or ())
        if getattr(route, "path", "") == "/ui"
    }
    assert "GET" not in gated_methods, f"GET /ui must not be on the gated router: {gated_methods}"
    assert "PUT" in gated_methods
