"""Runtime resolution of ``api_format`` and per-model capability overrides."""

from __future__ import annotations

from typing import Any

from deeptutor.runtime.agentic.client import can_use_native_tool_calling
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
from deeptutor.services.llm import provider_factory
from deeptutor.services.llm.capabilities import (
    catalog_capability_override,
    set_catalog_capability_overrides,
    supports_tools,
)
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider
from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider


def _catalog(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": profile["id"],
                "active_model_id": profile["models"][0]["id"],
                "profiles": [profile],
            },
            "embedding": {"active_profile_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def _profile(**overrides: Any) -> dict[str, Any]:
    profile = {
        "id": "llm-p",
        "name": "LLM",
        "binding": "custom",
        "base_url": "https://relay.example/v1",
        "api_key": "test-key",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "llm-m", "name": "m", "model": "some-model"}],
    }
    profile.update(overrides)
    return profile


def _runtime_config(resolved) -> LLMConfig:
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        wire_api=resolved.wire_api,
        api_format=resolved.api_format,
    )


def test_custom_endpoint_in_anthropic_format_gets_the_anthropic_backend() -> None:
    resolved = resolve_llm_runtime_config(
        catalog=_catalog(
            _profile(api_format="anthropic", base_url="https://relay.example/anthropic")
        )
    )
    assert resolved.provider_name == "custom"
    assert resolved.api_format == "anthropic"
    assert resolved.wire_api == "auto"

    provider = provider_factory._build_runtime_provider(_runtime_config(resolved))
    assert isinstance(provider, AnthropicProvider)


def test_legacy_custom_anthropic_binding_resolves_exactly_as_before() -> None:
    resolved = resolve_llm_runtime_config(
        catalog=_catalog(
            _profile(binding="custom_anthropic", base_url="https://relay.example/anthropic")
        )
    )
    assert resolved.provider_name == "custom_anthropic"
    assert resolved.api_format == "anthropic"
    assert isinstance(
        provider_factory._build_runtime_provider(_runtime_config(resolved)), AnthropicProvider
    )


def test_openai_responses_format_sets_wire_api() -> None:
    resolved = resolve_llm_runtime_config(catalog=_catalog(_profile(api_format="openai_responses")))
    assert resolved.wire_api == "responses"
    provider = provider_factory._build_runtime_provider(_runtime_config(resolved))
    assert isinstance(provider, OpenAICompatProvider)
    assert provider._wire_api == "responses"


def test_legacy_wire_api_still_drives_the_protocol() -> None:
    resolved = resolve_llm_runtime_config(catalog=_catalog(_profile(wire_api="responses")))
    assert resolved.api_format == "openai_responses"
    assert resolved.wire_api == "responses"


def test_minimax_anthropic_format_uses_the_vendor_anthropic_endpoint() -> None:
    resolved = resolve_llm_runtime_config(
        catalog=_catalog(_profile(binding="minimax", base_url="", api_format="anthropic"))
    )
    # The profile left base_url blank, so the vendor default for *this format*
    # is what the runtime should fall back to.
    provider = provider_factory._build_runtime_provider(_runtime_config(resolved))
    assert isinstance(provider, AnthropicProvider)


def test_openai_profile_with_api_version_is_an_azure_deployment() -> None:
    config = LLMConfig(
        model="deployment",
        api_key="k",
        base_url="https://example.openai.azure.com",
        binding="openai",
        provider_name="openai",
        api_version="2024-02-01",
    )
    assert isinstance(provider_factory._build_runtime_provider(config), AzureOpenAIProvider)


def test_model_capability_overrides_are_published_on_resolution() -> None:
    profile = _profile(binding="ollama", base_url="http://localhost:11434/v1", api_key="")
    profile["models"][0]["capabilities"] = {"tools": True, "vision": False}
    try:
        resolve_llm_runtime_config(catalog=_catalog(profile))
        assert catalog_capability_override("ollama", "some-model", "supports_tools") is True
        assert supports_tools("ollama", "some-model") is True
        # The agentic gate normally refuses tools on local servers; the
        # user's declaration is exactly what should override that.
        assert can_use_native_tool_calling(binding="ollama", model="some-model") is True
        assert can_use_native_tool_calling(binding="ollama", model="another-model") is False

        # Removing the override in the catalog removes it at runtime too.
        del profile["models"][0]["capabilities"]
        resolve_llm_runtime_config(catalog=_catalog(profile))
        assert catalog_capability_override("ollama", "some-model", "supports_tools") is None
        assert can_use_native_tool_calling(binding="ollama", model="some-model") is False
    finally:
        set_catalog_capability_overrides([])
