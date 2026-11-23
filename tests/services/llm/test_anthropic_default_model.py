"""The Anthropic fallback model must be one Anthropic still serves.

claude-sonnet-4-20250514 was retired on 2026-06-15:
https://platform.claude.com/docs/en/about-claude/model-deprecations
"""

from __future__ import annotations

import pytest

pytest.importorskip("anthropic")

from deeptutor.runtime.agentic.client import LLMClientConfig, _build_anthropic_adapter
from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider
from deeptutor.services.provider_registry import find_by_name

RETIRED = {"claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-3-5-sonnet-20241022"}


def test_provider_default_model_is_served() -> None:
    assert AnthropicProvider(api_key="test-key").default_model not in RETIRED


def test_agentic_adapter_without_a_model_uses_the_provider_default() -> None:
    config = LLMClientConfig(binding="anthropic", model=None, api_key="test-key", base_url=None)
    adapter = _build_anthropic_adapter(config, find_by_name("anthropic"))
    assert adapter._provider.default_model == AnthropicProvider(api_key="test-key").default_model
