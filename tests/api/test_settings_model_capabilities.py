"""Provider choices carry API formats; the capability-defaults endpoint."""

from __future__ import annotations

import pytest

from deeptutor.api.routers import settings as settings_router


def test_llm_provider_choices_expose_api_formats_and_legacy_status() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["custom"]["api_formats"] == ["auto", "openai_chat", "openai_responses", "anthropic"]
    assert llm["custom"]["default_api_format"] == "auto"
    assert llm["custom"]["status"] == "supported"
    assert llm["openai"]["api_formats"] == ["auto", "openai_chat", "openai_responses"]
    assert llm["anthropic"]["api_formats"] == ["anthropic"]
    assert llm["azure_openai"]["api_formats"] == []
    # Vendors serving a second protocol at a different endpoint say where.
    assert llm["minimax"]["base_urls"]["anthropic"] == "https://api.minimax.io/anthropic"
    assert llm["minimax"]["base_urls"]["auto"] == "https://api.minimax.io/v1"
    # Legacy entries stay listed for stored catalogs but are flagged.
    assert llm["custom_anthropic"]["status"] == "legacy"
    assert llm["minimax_anthropic"]["status"] == "legacy"
    # The task service is the LLM's shape.
    assert settings_router._provider_choices()["task"] is settings_router._provider_choices()[
        "llm"
    ] or (settings_router._provider_choices()["task"] == settings_router._provider_choices()["llm"])


@pytest.mark.asyncio
async def test_model_capabilities_endpoint_reports_table_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_router, "_require_settings_admin", lambda: None)

    local = await settings_router.resolve_model_capabilities(
        settings_router.ModelCapabilitiesQuery(binding="ollama", model="llama3")
    )
    assert local == {
        "binding": "ollama",
        "model": "llama3",
        "defaults": {"tools": False, "vision": False, "json_output": True},
    }

    vision = await settings_router.resolve_model_capabilities(
        settings_router.ModelCapabilitiesQuery(binding="openai", model="gpt-4o")
    )
    assert vision["defaults"] == {"tools": True, "vision": True, "json_output": True}
