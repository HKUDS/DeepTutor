from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from deeptutor.services.codex_auth.catalog import CodexModelCatalog, parse_models_response
from deeptutor.services.codex_auth.contracts import CatalogSnapshot, CodexCredentials
from deeptutor.services.codex_auth.oauth import CodexOAuthClient
from deeptutor.services.codex_auth.service import (
    CODEX_PROFILE_ID,
    CodexOAuthService,
    codex_model_id,
    sync_codex_catalog,
)
from deeptutor.services.codex_auth.storage import CodexCredentialStore
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_refresh_discovers_version_gated_model_and_preserves_selection(
    tmp_path: Path,
) -> None:
    # The older 0.145.0 catalog omitted Astra; the current verified fallback
    # still exposes it when package-version discovery is unavailable.
    old_payload = json.loads((FIXTURES / "models-response.json").read_text())
    astra = json.loads((FIXTURES / "astra-model.json").read_text())
    new_payload = {"models": [astra, *old_payload["models"]]}
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(503)
        requests.append(request)
        version = request.url.params["client_version"]
        assert version in {"0.145.0", "0.156.1"}
        payload = old_payload if version == "0.145.0" else new_payload
        return httpx.Response(200, json=payload, headers={"etag": '"new-catalog"'})

    store = CodexCredentialStore(tmp_path)
    credentials = store.commit_credentials(
        CodexCredentials(
            schema_version=1,
            access_token="test-access",
            refresh_token="test-refresh",
            id_token="test-id",
            account_id="test-account",
            expires_at=2_000_000_000,
            generation=0,
        ),
        expected_generation=0,
    )
    model_catalog = ModelCatalogService(tmp_path / "model_catalog.json")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http, clock=lambda: 1_000)
        # Seed a still-fresh pre-upgrade cache and a user's selected model.
        previous = CatalogSnapshot(
            models=parse_models_response(old_payload),
            source="live",
            fetched_at=1_000,
            etag='"old-catalog"',
            generation=credentials.generation,
            account_hash=hashlib.sha256(credentials.account_id.encode()).hexdigest(),
        )
        store.save_catalog_cache(previous.to_dict())
        sync_codex_catalog(model_catalog, previous, account_id=credentials.account_id)
        service = CodexOAuthService(
            store, catalog, model_catalog, oauth_client=CodexOAuthClient(http), clock=lambda: 1_000
        )
        await service.set_reasoning_effort("gpt-5.6-sol", "high")
        before = model_catalog.load()
        status = await service.refresh_models()

        # Legacy caches have no request version, so their ETag cannot be reused.
        assert "if-none-match" not in requests[0].headers
        assert [m["model"] for m in status["models"]].count("gpt-6-astra") == 1
        refreshed = model_catalog.load()
        llm = refreshed["services"]["llm"]
        assert llm["active_model_id"] == before["services"]["llm"]["active_model_id"]
        profile = next(p for p in llm["profiles"] if p["id"] == CODEX_PROFILE_ID)
        assert {m["model"] for m in profile["models"]} == {"gpt-6-astra", "gpt-5.6-sol"}
        existing = next(m for m in profile["models"] if m["model"] == "gpt-5.6-sol")
        assert existing["reasoning_effort"] == "high"
        selected = next(m for m in profile["models"] if m["model"] == "gpt-6-astra")
        assert selected["name"] == astra["display_name"]
        assert selected["context_window"] == str(astra["context_window"])
        assert selected["codex_supported_reasoning_levels"] == [
            level["effort"] for level in astra["supported_reasoning_levels"]
        ]
        assert selected["codex_use_responses_lite"] is astra["use_responses_lite"]

        # The settings model card persists these two IDs when the user selects it.
        llm["active_profile_id"] = CODEX_PROFILE_ID
        llm["active_model_id"] = codex_model_id("gpt-6-astra")
        model_catalog.save(refreshed)
        await service.refresh_models()
        reopened = ModelCatalogService(model_catalog.path)
        loaded = reopened.load()
        resolved = resolve_llm_runtime_config(loaded, service=reopened)
        assert resolved.model == "gpt-6-astra"
        service.validate_runtime_profile(await service.get_token(), resolved.model)
        assert service.public_status()["active_model"] == "gpt-6-astra"
        assert [m["model"] for m in service.public_status()["models"]].count("gpt-6-astra") == 1


@pytest.mark.asyncio
async def test_refresh_discovers_sol_luna_and_later_listed_models(tmp_path: Path) -> None:
    old_payload = json.loads((FIXTURES / "models-response.json").read_text())
    returned_models = [
        {
            "slug": slug,
            "display_name": name,
            "visibility": "list",
            "priority": priority,
            "context_window": context_window,
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [{"effort": "medium"}, {"effort": "high"}],
        }
        for slug, name, priority, context_window in (
            ("gpt-6-sol", "GPT-6-Sol", 1, 280_000),
            ("gpt-6-luna", "GPT-6-Luna", 2, 300_000),
        )
    ]
    future_model = {
        "slug": "future-listed-model",
        "display_name": "Future listed model",
        "visibility": "list",
        "priority": 3,
        "context_window": 320_000,
        "supported_reasoning_levels": [{"effort": "low"}],
    }
    versions = iter(("0.156.1", "0.156.2"))
    requested_versions: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"name": "@openai/codex", "version": next(versions)})
        version = request.url.params["client_version"]
        requested_versions.append(version)
        assert "if-none-match" not in request.headers
        assert version in {"0.156.1", "0.156.2"}
        models = [*old_payload["models"], *returned_models]
        if version == "0.156.2":
            models.append(future_model)
        return httpx.Response(200, json={"models": models}, headers={"etag": '"catalog"'})

    store = CodexCredentialStore(tmp_path)
    credentials = store.commit_credentials(
        CodexCredentials(
            schema_version=1,
            access_token="test-access",
            refresh_token="test-refresh",
            id_token="test-id",
            account_id="test-account",
            expires_at=2_000_000_000,
            generation=0,
        ),
        expected_generation=0,
    )
    model_catalog = ModelCatalogService(tmp_path / "model_catalog.json")
    previous = CatalogSnapshot(
        models=parse_models_response(old_payload),
        source="live",
        fetched_at=1_000,
        etag='"old-catalog"',
        generation=credentials.generation,
        account_hash=hashlib.sha256(credentials.account_id.encode()).hexdigest(),
        client_version="0.153.4",
    )
    store.save_catalog_cache(previous.to_dict())
    sync_codex_catalog(model_catalog, previous, account_id=credentials.account_id)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        catalog = CodexModelCatalog(store, http=http, version_http=http, clock=lambda: 1_000)
        service = CodexOAuthService(
            store, catalog, model_catalog, oauth_client=CodexOAuthClient(http), clock=lambda: 1_000
        )
        await service.set_reasoning_effort("gpt-5.6-sol", "high")
        before = model_catalog.load()
        first = await service.refresh_models()
        first_models = [model["model"] for model in first["models"]]
        assert first_models.count("gpt-6-sol") == 1
        assert first_models.count("gpt-6-luna") == 1
        assert "future-listed-model" not in first_models

        saved = model_catalog.load()
        llm = saved["services"]["llm"]
        assert llm["active_model_id"] == before["services"]["llm"]["active_model_id"]
        profile = next(item for item in llm["profiles"] if item["id"] == CODEX_PROFILE_ID)
        for returned in returned_models:
            selected = next(item for item in profile["models"] if item["model"] == returned["slug"])
            assert selected["name"] == returned["display_name"]
            assert selected["context_window"] == str(returned["context_window"])
            assert selected["codex_supported_reasoning_levels"] == ["medium", "high"]
        existing = next(item for item in profile["models"] if item["model"] == "gpt-5.6-sol")
        assert existing["reasoning_effort"] == "high"

        second = await service.refresh_models()
        assert [model["model"] for model in second["models"]].count("future-listed-model") == 1
        assert requested_versions == ["0.156.1", "0.156.2"]
        reopened = ModelCatalogService(model_catalog.path).load()
        assert reopened["services"]["llm"]["active_model_id"] == llm["active_model_id"]
        profile = next(
            item
            for item in reopened["services"]["llm"]["profiles"]
            if item["id"] == CODEX_PROFILE_ID
        )
        assert {item["model"] for item in profile["models"]} == {
            "gpt-5.6-sol",
            "gpt-6-sol",
            "gpt-6-luna",
            "future-listed-model",
        }
