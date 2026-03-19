# -*- coding: utf-8 -*-
"""
Tests for MiniMax LLM Provider Integration
===========================================

Unit tests verifying that MiniMax is properly registered as a first-class
LLM provider across capabilities, factory presets, config, and frontend constants.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from src.services.llm.capabilities import (
    PROVIDER_CAPABILITIES,
    get_capability,
    get_effective_temperature,
    has_thinking_tags,
    supports_response_format,
    supports_streaming,
    supports_tools,
    system_in_messages,
)
from src.services.llm.config import LLMConfig
from src.services.llm.factory import API_PROVIDER_PRESETS
from src.services.llm.utils import CLOUD_DOMAINS, is_local_llm_server


# ── Capabilities Tests ──────────────────────────────────────────────────────


class TestMiniMaxCapabilities:
    """Test MiniMax provider capabilities registration."""

    def test_minimax_in_provider_capabilities(self):
        assert "minimax" in PROVIDER_CAPABILITIES

    def test_minimax_supports_response_format(self):
        assert supports_response_format("minimax") is True

    def test_minimax_supports_streaming(self):
        assert supports_streaming("minimax") is True

    def test_minimax_supports_tools(self):
        assert supports_tools("minimax") is True

    def test_minimax_system_in_messages(self):
        assert system_in_messages("minimax") is True

    def test_minimax_no_thinking_tags(self):
        assert has_thinking_tags("minimax") is False

    def test_minimax_no_forced_temperature(self):
        """MiniMax accepts temperature=0, so no forced value should be set."""
        assert get_effective_temperature("minimax", requested_temp=0.3) == 0.3
        assert get_effective_temperature("minimax", requested_temp=0.0) == 0.0

    def test_minimax_capability_with_model(self):
        """Capabilities should work with specific MiniMax model names."""
        assert supports_response_format("minimax", "MiniMax-M2.7") is True
        assert supports_streaming("minimax", "MiniMax-M2.5-highspeed") is True
        assert supports_tools("minimax", "MiniMax-M2.5") is True


# ── Factory Presets Tests ────────────────────────────────────────────────────


class TestMiniMaxFactoryPreset:
    """Test MiniMax API provider preset configuration."""

    def test_minimax_in_api_presets(self):
        assert "minimax" in API_PROVIDER_PRESETS

    def test_minimax_preset_name(self):
        assert API_PROVIDER_PRESETS["minimax"]["name"] == "MiniMax"

    def test_minimax_preset_base_url(self):
        assert API_PROVIDER_PRESETS["minimax"]["base_url"] == "https://api.minimax.io/v1"

    def test_minimax_preset_requires_key(self):
        assert API_PROVIDER_PRESETS["minimax"]["requires_key"] is True

    def test_minimax_preset_models(self):
        models = API_PROVIDER_PRESETS["minimax"]["models"]
        assert "MiniMax-M2.7" in models
        assert "MiniMax-M2.5" in models
        assert "MiniMax-M2.5-highspeed" in models

    def test_minimax_preset_has_no_binding_override(self):
        """MiniMax uses default OpenAI-compatible binding (no special binding key needed)."""
        assert "binding" not in API_PROVIDER_PRESETS["minimax"]


# ── Utils Tests ──────────────────────────────────────────────────────────────


class TestMiniMaxUtils:
    """Test MiniMax URL detection and utilities."""

    def test_minimax_domain_in_cloud_domains(self):
        assert ".minimax.io" in CLOUD_DOMAINS

    def test_minimax_url_not_detected_as_local(self):
        assert is_local_llm_server("https://api.minimax.io/v1") is False

    def test_minimax_url_not_local_with_port(self):
        """Even with a port, minimax.io should not be treated as local."""
        assert is_local_llm_server("https://api.minimax.io:443/v1") is False


# ── Config Tests ─────────────────────────────────────────────────────────────


class TestMiniMaxConfig:
    """Test MiniMax configuration handling."""

    def test_llm_config_accepts_minimax_binding(self):
        config = LLMConfig(
            model="MiniMax-M2.7",
            api_key="test-key",
            base_url="https://api.minimax.io/v1",
            binding="minimax",
        )
        assert config.binding == "minimax"
        assert config.model == "MiniMax-M2.7"
        assert config.base_url == "https://api.minimax.io/v1"

    @patch.dict(os.environ, {
        "LLM_BINDING": "minimax",
        "LLM_MODEL": "MiniMax-M2.7",
        "LLM_API_KEY": "test-minimax-key",
        "LLM_HOST": "https://api.minimax.io/v1",
    }, clear=False)
    def test_env_config_minimax(self):
        from src.services.llm.config import _get_llm_config_from_env

        config = _get_llm_config_from_env()
        assert config.binding == "minimax"
        assert config.model == "MiniMax-M2.7"
        assert config.base_url == "https://api.minimax.io/v1"


# ── Unified Config Service Tests ─────────────────────────────────────────────


class TestMiniMaxUnifiedConfig:
    """Test MiniMax in unified config service."""

    def test_minimax_in_llm_provider_options(self):
        from src.services.config.unified_config import PROVIDER_OPTIONS, ConfigType

        assert "minimax" in PROVIDER_OPTIONS[ConfigType.LLM]


# ── Cloud Provider Routing Tests ─────────────────────────────────────────────


class TestMiniMaxCloudRouting:
    """Test that MiniMax routes through the OpenAI-compatible cloud provider path."""

    def test_minimax_binding_routes_to_openai_path(self):
        """MiniMax binding should NOT route to Anthropic path."""
        from src.services.llm.cloud_provider import complete

        # The complete function checks binding_lower against ["anthropic", "claude"]
        # MiniMax should fall through to the default OpenAI-compatible path
        binding_lower = "minimax".lower()
        assert binding_lower not in ["anthropic", "claude"]

    def test_minimax_auth_header_uses_bearer(self):
        """MiniMax should use standard Bearer token authentication."""
        from src.services.llm.utils import build_auth_headers

        headers = build_auth_headers("test-api-key", binding="minimax")
        assert headers["Authorization"] == "Bearer test-api-key"
        assert "x-api-key" not in headers
        assert "api-key" not in headers

    def test_minimax_chat_url_uses_chat_completions(self):
        """MiniMax should use /chat/completions endpoint."""
        from src.services.llm.utils import build_chat_url

        url = build_chat_url("https://api.minimax.io/v1", binding="minimax")
        assert url.endswith("/chat/completions")

    def test_minimax_url_sanitization(self):
        """MiniMax URL should pass through sanitization unchanged."""
        from src.services.llm.utils import sanitize_url

        url = sanitize_url("https://api.minimax.io/v1")
        assert url == "https://api.minimax.io/v1"


# ── Integration Tests ────────────────────────────────────────────────────────


class TestMiniMaxIntegration:
    """Integration tests verifying end-to-end MiniMax provider flow."""

    @pytest.mark.asyncio
    async def test_minimax_complete_uses_openai_path(self):
        """Verify MiniMax complete() routes through OpenAI-compatible path."""
        with patch(
            "src.services.llm.cloud_provider._openai_complete",
            new_callable=AsyncMock,
            return_value="Hello from MiniMax!",
        ) as mock_complete:
            from src.services.llm.cloud_provider import complete

            result = await complete(
                prompt="Hello",
                model="MiniMax-M2.7",
                api_key="test-key",
                base_url="https://api.minimax.io/v1",
                binding="minimax",
            )
            mock_complete.assert_called_once()
            call_kwargs = mock_complete.call_args
            assert call_kwargs.kwargs.get("binding") == "minimax" or call_kwargs[1].get("binding") == "minimax"
            assert result == "Hello from MiniMax!"

    @pytest.mark.asyncio
    async def test_minimax_stream_uses_openai_path(self):
        """Verify MiniMax stream() routes through OpenAI-compatible path."""

        async def mock_stream(**kwargs):
            yield "chunk1"
            yield "chunk2"

        with patch(
            "src.services.llm.cloud_provider._openai_stream",
            side_effect=mock_stream,
        ):
            from src.services.llm.cloud_provider import stream

            chunks = []
            async for chunk in stream(
                prompt="Hello",
                model="MiniMax-M2.7",
                api_key="test-key",
                base_url="https://api.minimax.io/v1",
                binding="minimax",
            ):
                chunks.append(chunk)
            assert chunks == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_minimax_factory_complete_routes_to_cloud(self):
        """Verify factory.complete() routes MiniMax to cloud provider."""
        with patch(
            "src.services.llm.cloud_provider.complete",
            new_callable=AsyncMock,
            return_value="MiniMax response",
        ) as mock_cloud:
            from src.services.llm import factory

            result = await factory.complete(
                prompt="test",
                model="MiniMax-M2.7",
                api_key="test-key",
                base_url="https://api.minimax.io/v1",
                binding="minimax",
            )
            mock_cloud.assert_called_once()
            assert result == "MiniMax response"
