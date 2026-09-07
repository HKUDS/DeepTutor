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
    # Same-account live comparison on 2026-09-06: 0.145.0 omits Astra;
    # official rust-v0.153.4 exposes it. Only model metadata is retained.
    old_payload = json.loads((FIXTURES / "models-response.json").read_text())
    astra = json.loads((FIXTURES / "astra-model.json").read_text())
    new_payload = {"models": [astra, *old_payload["models"]]}
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        version = request.url.params["client_version"]
        assert version in {"0.145.0", "0.153.4"}
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
        catalog = CodexModelCatalog(store, http=http, clock=lambda: 1_000)
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

        assert requests[0].headers["if-none-match"] == '"old-catalog"'
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
