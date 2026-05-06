"""Factory for services-layer provider runtime objects."""

from __future__ import annotations

from deeptutor.services.llm.config import LLMConfig, get_llm_config
from deeptutor.services.llm.provider_core import (
    AnthropicProvider,
    AzureOpenAIProvider,
    GenerationSettings,
    GitHubCopilotProvider,
    LLMProvider,
    OpenAICodexProvider,
    OpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name


def get_runtime_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Build the authoritative services-layer provider for the supplied config."""
    llm_config = config or get_llm_config()
    provider_name = llm_config.provider_name or llm_config.binding
    spec = find_by_name(provider_name)
    backend = spec.backend if spec else "openai_compat"

    if backend == "openai_codex":
        provider: LLMProvider = OpenAICodexProvider(default_model=llm_config.model)
    elif backend == "github_copilot":
        provider = GitHubCopilotProvider(default_model=llm_config.model)
    elif backend == "azure_openai":
        provider = AzureOpenAIProvider(
            api_key=llm_config.api_key or "",
            api_base=llm_config.effective_url or llm_config.base_url or "",
            default_model=llm_config.model,
            extra_headers=llm_config.extra_headers or None,
        )
    elif backend == "anthropic":
        provider = AnthropicProvider(
            api_key=llm_config.api_key or None,
            api_base=llm_config.effective_url or llm_config.base_url or None,
            default_model=llm_config.model,
            extra_headers=llm_config.extra_headers or None,
            supports_prompt_caching=bool(spec and spec.supports_prompt_caching),
        )
    else:
        provider = OpenAICompatProvider(
            api_key=llm_config.api_key or None,
            api_base=llm_config.effective_url or llm_config.base_url or None,
            default_model=llm_config.model,
            extra_headers=llm_config.extra_headers or None,
            spec=spec,
            provider_name=provider_name,
        )

    provider.generation = GenerationSettings(
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens,
        reasoning_effort=llm_config.reasoning_effort,
    )
    return provider
