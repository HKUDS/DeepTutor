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
                        # FT-05: a saved profile carries an explicit protocol;
                        # `auto` is reserved for untouched legacy migration.
                        "api_protocol": "openai_chat_completions",
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
async def test_get_settings_redacts_api_keys_and_exposes_protocols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: SimpleNamespace(is_admin=True),
    )

    payload = await settings_router.get_settings()

    llm_profile = payload["catalog"]["services"]["llm"]["profiles"][0]
    emb_profile = payload["catalog"]["services"]["embedding"]["profiles"][0]
    assert llm_profile["api_key"] == ""
    assert llm_profile["api_key_set"] is True
    assert emb_profile["api_key"] == ""
    assert emb_profile["api_key_set"] is True
    # The three explicit protocols are the selectable new/edit choices; `auto`
    # is a legacy-compatibility state and is not offered as a normal option.
    assert [p["value"] for p in payload["protocols"]["llm"]] == [
        "openai_chat_completions",
        "openai_responses",
        "anthropic_messages",
    ]


@pytest.mark.asyncio
async def test_update_catalog_rejects_invalid_api_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    catalog["services"]["llm"]["profiles"][0]["api_protocol"] = "bogus"
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=catalog))
    assert exc_info.value.status_code == 422
    assert "bogus" in str(exc_info.value.detail)


def _add_new_llm_profile(catalog: dict[str, Any]) -> dict[str, Any]:
    """Append a brand-new LLM profile (no api_protocol) to a catalog copy."""
    incoming = deepcopy(catalog)
    incoming["services"]["llm"]["profiles"].append(
        {
            "id": "llm-profile-new",
            "name": "New Endpoint",
            "binding": "openai",
            "base_url": "https://new.example.com/v1",
            "api_key": "",
            "api_key_set": False,
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-model-new", "name": "gpt-x", "model": "gpt-x"}],
        }
    )
    return incoming


@pytest.mark.asyncio
async def test_update_catalog_rejects_new_llm_profile_without_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newly created profile must select an explicit protocol — a missing
    api_protocol must not normalize silently to ``auto`` (FT-05)."""
    from fastapi import HTTPException

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _add_new_llm_profile(catalog)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)
    # Nothing persisted.
    assert "llm-profile-new" not in {p["id"] for p in service.load()["services"]["llm"]["profiles"]}


@pytest.mark.asyncio
async def test_apply_catalog_rejects_new_llm_profile_without_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The apply path enforces the same explicit-protocol contract."""
    from fastapi import HTTPException

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _add_new_llm_profile(catalog)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.apply_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_catalog_rejects_edited_legacy_auto_profile_without_explicit_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy ``auto`` profile whose connection settings changed must pick an
    explicit protocol instead of silently staying on ``auto`` (FT-05)."""
    from fastapi import HTTPException

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    # The stored profile is a migrated legacy ``auto`` profile.
    catalog["services"]["llm"]["profiles"][0]["api_protocol"] = "auto"
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = deepcopy(catalog)
    # Substantive connection edit (base_url) while api_protocol stays "auto".
    incoming["services"]["llm"]["profiles"][0]["base_url"] = "https://changed.example.com/v1"
    incoming["services"]["llm"]["profiles"][0]["api_key"] = ""
    incoming["services"]["llm"]["profiles"][0]["api_key_set"] = True

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_catalog_allows_untouched_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An untouched legacy ``auto`` profile stays a valid compatibility state:
    a redacted PUT with no connection changes saves without an explicit
    protocol."""
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    catalog["services"]["llm"]["profiles"][0]["api_protocol"] = "auto"
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    redacted_incoming = deepcopy(catalog)
    for profile in redacted_incoming["services"]["llm"]["profiles"]:
        profile["api_key"] = ""
        profile["api_key_set"] = True

    response = await settings_router.update_catalog(
        settings_router.CatalogPayload(catalog=redacted_incoming)
    )

    assert "catalog" in response
    # Stored secret survived the redacted PUT.
    assert service.load()["services"]["llm"]["profiles"][0]["api_key"] == "secret-key"
    assert service.load()["services"]["llm"]["profiles"][0]["api_protocol"] == "auto"


def _legacy_auto_catalog() -> dict[str, Any]:
    """A migrated legacy LLM profile still on ``auto`` (compatibility state)."""
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    catalog["services"]["llm"]["profiles"][0]["api_protocol"] = "auto"
    return catalog


def _redact_llm_draft(catalog: dict[str, Any]) -> dict[str, Any]:
    """Simulate the UI's redacted draft: LLM api_key emptied + api_key_set flag."""
    incoming = deepcopy(catalog)
    for profile in incoming["services"]["llm"]["profiles"]:
        profile["api_key"] = ""
        profile["api_key_set"] = True
    return incoming


@pytest.mark.asyncio
async def test_update_catalog_rejects_api_key_replacement_on_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing the API key is a real edit (FT-05): ``auto`` must be rejected
    even when every other durable field matches the stored profile."""
    from fastapi import HTTPException

    service = _FakeCatalogService(_legacy_auto_catalog())
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _redact_llm_draft(_legacy_auto_catalog())
    incoming["services"]["llm"]["profiles"][0]["api_key"] = "sk-replacement"

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_catalog_rejects_api_key_clear_on_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly clearing the API key (api_key_set=false) is a real edit (FT-05):
    ``auto`` must be rejected even when every other durable field is untouched."""
    from fastapi import HTTPException

    service = _FakeCatalogService(_legacy_auto_catalog())
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _redact_llm_draft(_legacy_auto_catalog())
    incoming["services"]["llm"]["profiles"][0]["api_key_set"] = False

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_catalog_rejects_strict_protocol_only_edit_on_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggling ``strict_protocol`` is a real edit (FT-05): an otherwise untouched
    legacy ``auto`` profile must pick an explicit protocol."""
    from fastapi import HTTPException

    service = _FakeCatalogService(_legacy_auto_catalog())
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _redact_llm_draft(_legacy_auto_catalog())
    incoming["services"]["llm"]["profiles"][0]["strict_protocol"] = True

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_catalog_rejects_any_edit_when_strict_protocol_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile already on ``auto`` with ``strict_protocol=true`` must not remain
    on ``auto`` after any durable edit (FT-05): an unrelated metadata edit still
    forces an explicit protocol."""
    from fastapi import HTTPException

    catalog = _legacy_auto_catalog()
    catalog["services"]["llm"]["profiles"][0]["strict_protocol"] = True
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _redact_llm_draft(catalog)
    # The edit is metadata-only (name); api_protocol stays "auto" and
    # strict_protocol stays true — the pair must be rejected together.
    incoming["services"]["llm"]["profiles"][0]["name"] = "Renamed"

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "Renamed Endpoint"),  # display/name metadata
        ("base_url", "https://changed.example.com/v1"),  # connection edit
        ("api_version", "2026-01-01"),  # durable metadata
        ("extra_headers", {"X-Custom": "header"}),  # connection metadata
    ],
)
async def test_update_catalog_rejects_durable_field_edit_on_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    """Any durable field edit — metadata included — must reject ``auto`` (FT-05)."""
    from fastapi import HTTPException

    service = _FakeCatalogService(_legacy_auto_catalog())
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _redact_llm_draft(_legacy_auto_catalog())
    incoming["services"]["llm"]["profiles"][0][field] = value

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.update_catalog(settings_router.CatalogPayload(catalog=incoming))
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_catalog_allows_untouched_auto_profile_ignoring_probe_badge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capability-probe fields are probe-derived, not user edits (FT-05): an
    untouched legacy ``auto`` profile whose draft differs only in its probe badge
    still saves as ``auto`` and keeps the stored secret."""
    catalog = _legacy_auto_catalog()
    catalog["services"]["llm"]["profiles"][0]["capability_probe_status"] = "unknown"
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    incoming = _redact_llm_draft(catalog)
    # The in-flight Diagnostics draft carries a fresher probe badge; the badge
    # is stamped by the test runner and must not count as a substantive edit.
    incoming["services"]["llm"]["profiles"][0]["capability_probe_status"] = "probing"
    incoming["services"]["llm"]["profiles"][0]["capability_probe_at"] = "2026-08-04T00:00:00Z"
    incoming["services"]["llm"]["profiles"][0]["capability_probe_message"] = "probing"

    response = await settings_router.update_catalog(
        settings_router.CatalogPayload(catalog=incoming)
    )

    assert "catalog" in response
    saved = service.load()
    assert saved["services"]["llm"]["profiles"][0]["api_protocol"] == "auto"
    assert saved["services"]["llm"]["profiles"][0]["api_key"] == "secret-key"


@pytest.mark.asyncio
async def test_apply_catalog_allows_untouched_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The apply path preserves the compatibility state for an untouched legacy
    ``auto`` profile (redacted draft, no durable edits)."""
    service = _FakeCatalogService(_legacy_auto_catalog())
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    redacted_incoming = _redact_llm_draft(_legacy_auto_catalog())

    response = await settings_router.apply_catalog(
        settings_router.CatalogPayload(catalog=redacted_incoming)
    )

    assert "catalog" in response
    assert response["catalog"]["services"]["llm"]["profiles"][0]["api_protocol"] == "auto"
    # Stored secret survived the redacted apply.
    assert service.load()["services"]["llm"]["profiles"][0]["api_key"] == "secret-key"


@pytest.mark.asyncio
async def test_complete_tour_allows_untouched_legacy_auto_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """The tour-complete path preserves the compatibility state for an untouched
    legacy ``auto`` profile (redacted draft, no durable edits)."""
    service = _FakeCatalogService(_legacy_auto_catalog())
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    tour_cache = tmp_path / ".tour_cache.json"
    tour_cache.write_text('{"status": "running"}', encoding="utf-8")
    monkeypatch.setattr(settings_router, "TOUR_CACHE", tour_cache)

    redacted_incoming = _redact_llm_draft(_legacy_auto_catalog())

    response = await settings_router.complete_tour(
        settings_router.TourCompletePayload(catalog=redacted_incoming)
    )

    assert response["status"] == "completed"
    assert service.load()["services"]["llm"]["profiles"][0]["api_protocol"] == "auto"
    assert service.load()["services"]["llm"]["profiles"][0]["api_key"] == "secret-key"
    assert '"status": "completed"' in tour_cache.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_update_catalog_preserves_touched_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redacted PUT (api_key="" + api_key_set=true) keeps the stored key."""
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    redacted_incoming = deepcopy(catalog)
    for profile in redacted_incoming["services"]["llm"]["profiles"]:
        profile["api_key"] = ""
        profile["api_key_set"] = True

    await settings_router.update_catalog(settings_router.CatalogPayload(catalog=redacted_incoming))

    assert service.load()["services"]["llm"]["profiles"][0]["api_key"] == "secret-key"


@pytest.mark.asyncio
async def test_update_catalog_clears_secret_when_explicitly_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    cleared_incoming = deepcopy(catalog)
    for profile in cleared_incoming["services"]["llm"]["profiles"]:
        profile["api_key"] = ""
        profile["api_key_set"] = False

    await settings_router.update_catalog(settings_router.CatalogPayload(catalog=cleared_incoming))

    assert service.load()["services"]["llm"]["profiles"][0]["api_key"] == ""


@pytest.mark.asyncio
async def test_start_service_test_merges_stored_secret_without_returning_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics posts a redacted draft; the server must merge the stored
    tri-state secret before the probe runs and never echo it back."""
    stored = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-llm-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="secret-emb-key",
    )
    service = _FakeCatalogService(stored)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    captured: dict[str, Any] = {}

    class _FakeRunner:
        def start(self, service_name: str, catalog: dict[str, Any]):
            captured["service"] = service_name
            captured["catalog"] = catalog
            return SimpleNamespace(id="run-abc123")

    monkeypatch.setattr(settings_router, "get_config_test_runner", lambda: _FakeRunner())

    # Redacted draft, exactly what the UI posts: api_key="" + api_key_set=true.
    draft = deepcopy(stored)
    for service_name in ("llm", "embedding"):
        for profile in draft["services"][service_name]["profiles"]:
            profile["api_key"] = ""
            profile["api_key_set"] = True

    response = await settings_router.start_service_test(
        "llm", settings_router.CatalogPayload(catalog=draft)
    )

    # The runner received a fully merged catalog with the stored secrets.
    assert response == {"run_id": "run-abc123"}
    assert captured["service"] == "llm"
    merged_llm = captured["catalog"]["services"]["llm"]["profiles"][0]
    merged_emb = captured["catalog"]["services"]["embedding"]["profiles"][0]
    assert merged_llm["api_key"] == "secret-llm-key"
    assert merged_emb["api_key"] == "secret-emb-key"
    assert "api_key_set" not in merged_llm
    # The raw secret never appears in the response.
    assert "secret-llm-key" not in json.dumps(response)


@pytest.mark.asyncio
async def test_start_service_test_rejects_new_profile_without_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The diagnostics probe is a save-preview: a new LLM profile without an
    explicit protocol must be rejected before the probe starts."""
    from fastapi import HTTPException

    stored = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(stored)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(
        settings_router,
        "get_config_test_runner",
        lambda: (_ for _ in ()).throw(AssertionError("runner must not be reached")),
    )

    draft = _add_new_llm_profile(stored)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.start_service_test(
            "llm", settings_router.CatalogPayload(catalog=draft)
        )
    assert exc_info.value.status_code == 422
    assert "explicit API protocol" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_start_service_test_without_payload_uses_stored_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare POST (no draft) tests against the stored catalog as-is."""
    stored = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-llm-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
        embedding_api_key="secret-emb-key",
    )
    service = _FakeCatalogService(stored)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    captured: dict[str, Any] = {}

    class _FakeRunner:
        def start(self, service_name: str, catalog: dict[str, Any]):
            captured["catalog"] = catalog
            return SimpleNamespace(id="run-xyz789")

    monkeypatch.setattr(settings_router, "get_config_test_runner", lambda: _FakeRunner())

    response = await settings_router.start_service_test("llm", None)

    assert response == {"run_id": "run-xyz789"}
    assert captured["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "secret-llm-key"


@pytest.mark.asyncio
async def test_get_llm_options_returns_redacted_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret-key",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://api.example.com/v1/embeddings",
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

    # PUT persists the full catalog server-side but echoes a secret-redacted
    # view: api_key is replaced by an api_key_set flag.
    saved = service.load()
    assert saved["services"]["llm"]["profiles"][0]["api_key"] == "new-llm-key"
    assert saved["services"]["embedding"]["profiles"][0]["api_key"] == "new-embedding-key"
    response_llm = response["catalog"]["services"]["llm"]["profiles"][0]
    response_emb = response["catalog"]["services"]["embedding"]["profiles"][0]
    assert response_llm["api_key"] == ""
    assert response_llm["api_key_set"] is True
    assert response_emb["api_key"] == ""
    assert response_emb["api_key_set"] is True
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

    # The full catalog is persisted server-side; the echoed view is redacted.
    saved = service.load()
    assert saved["services"]["llm"]["profiles"][0]["api_key"] == "after-apply-llm-key"
    assert response["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == ""
    assert response["catalog"]["services"]["llm"]["profiles"][0]["api_key_set"] is True
    assert response["catalog"]["services"]["embedding"]["profiles"][0]["api_key"] == ""
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
async def test_codex_oauth_status_is_admin_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: SimpleNamespace(is_admin=False),
    )
    monkeypatch.setattr(
        settings_router,
        "get_codex_oauth_service",
        lambda: (_ for _ in ()).throw(AssertionError("service must not be accessed")),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.get_openai_codex_oauth_status()

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_codex_oauth_routes_return_only_public_service_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCodexOAuthService()
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: SimpleNamespace(is_admin=True),
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
        lambda: SimpleNamespace(is_admin=True),
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
