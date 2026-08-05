"""Factory selection of the explicit-protocol unified adapter (MOD-02)."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core.unified import HttpTransport, UnifiedLLMAdapter
from deeptutor.services.llm.provider_core.unified.adapter import build_unified_adapter


def _config(**overrides) -> LLMConfig:
    base = {
        "model": "gpt-5.6",
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "effective_url": "https://example.invalid/v1",
        "binding": "openai",
        "provider_name": "openai",
        "api_protocol": "auto",
        "strict_protocol": False,
    }
    base.update(overrides)
    return LLMConfig(**base)


class TestBuildUnifiedAdapter:
    def test_explicit_protocol_selects_unified_adapter(self) -> None:
        config = _config(
            api_protocol="openai_responses",
            strict_protocol=True,
        )
        adapter = build_unified_adapter(config)
        assert isinstance(adapter, UnifiedLLMAdapter)
        assert adapter.protocol == "openai_responses"
        assert adapter.strict_protocol is True
        assert adapter.default_model == "gpt-5.6"
        assert isinstance(adapter.transport, HttpTransport)

    def test_auto_falls_back_to_resolved_protocol(self) -> None:
        config = _config(api_protocol="auto", resolved_api_protocol="anthropic_messages")
        adapter = build_unified_adapter(config)
        assert adapter.protocol == "anthropic_messages"

    def test_auto_with_no_resolution_defaults_to_chat_completions(self) -> None:
        config = _config(api_protocol="auto", resolved_api_protocol="")
        adapter = build_unified_adapter(config)
        assert adapter.protocol == "openai_chat_completions"


class TestRuntimeFactory:
    def test_explicit_protocol_routes_to_unified_adapter(self) -> None:
        from deeptutor.services.llm.provider_factory import _build_runtime_provider

        config = _config(api_protocol="openai_chat_completions", strict_protocol=True)
        provider = _build_runtime_provider(config)
        assert isinstance(provider, UnifiedLLMAdapter)
        assert provider.protocol == "openai_chat_completions"

    def test_auto_keeps_legacy_openai_provider(self) -> None:
        from deeptutor.services.llm.provider_core.openai_compat_provider import (
            OpenAICompatProvider,
        )
        from deeptutor.services.llm.provider_factory import _build_runtime_provider

        config = _config(api_protocol="auto")
        provider = _build_runtime_provider(config)
        assert not isinstance(provider, UnifiedLLMAdapter)
        assert isinstance(provider, OpenAICompatProvider)

    def test_explicit_responses_routes_azure_to_specialized_provider(self) -> None:
        from deeptutor.services.llm.provider_core.azure_openai_provider import (
            AzureOpenAIProvider,
        )
        from deeptutor.services.llm.provider_factory import _build_runtime_provider

        config = _config(
            api_protocol="openai_responses",
            strict_protocol=True,
            provider_name="azure_openai",
            binding="azure_openai",
            base_url="https://example.openai.azure.com",
            effective_url="https://example.openai.azure.com",
        )
        provider = _build_runtime_provider(config)
        assert isinstance(provider, AzureOpenAIProvider)
        assert not isinstance(provider, UnifiedLLMAdapter)
        assert provider.api_protocol == "openai_responses"
        assert provider.strict_protocol is True
        # Azure-specific /openai/v1 normalization is preserved, not routed
        # through the generic adapter's URL join.
        assert str(provider._client.base_url).endswith("/openai/v1/")
        import asyncio

        asyncio.run(provider.aclose())


class TestHttpTransportUrl:
    def test_normalizes_v1_suffix(self) -> None:
        assert HttpTransport("https://api.openai.com/v1")._url("/v1/responses") == (
            "https://api.openai.com/v1/responses"
        )
        assert HttpTransport("https://api.anthropic.com")._url("/v1/messages") == (
            "https://api.anthropic.com/v1/messages"
        )
        assert HttpTransport("")._url("/v1/chat/completions") == "/v1/chat/completions"
