"""Services-layer provider runtime with lazy SDK-backed implementations."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest

if TYPE_CHECKING:
    from .anthropic_provider import AnthropicProvider
    from .azure_openai_provider import AzureOpenAIProvider
    from .codebuddy_http_provider import CodeBuddyHTTPProvider
    from .codebuddy_provider import CodeBuddyProvider
    from .github_copilot_provider import GitHubCopilotProvider
    from .openai_codex_provider import OpenAICodexProvider
    from .openai_compat_provider import OpenAICompatProvider

__all__ = [
    "AnthropicProvider",
    "AzureOpenAIProvider",
    "CodeBuddyHTTPProvider",
    "CodeBuddyProvider",
    "GenerationSettings",
    "GitHubCopilotProvider",
    "LLMProvider",
    "LLMResponse",
    "OpenAICodexProvider",
    "OpenAICompatProvider",
    "ToolCallRequest",
]


_LAZY_TYPES = {
    "AnthropicProvider": ("anthropic_provider", "AnthropicProvider"),
    "AzureOpenAIProvider": ("azure_openai_provider", "AzureOpenAIProvider"),
    "CodeBuddyHTTPProvider": ("codebuddy_http_provider", "CodeBuddyHTTPProvider"),
    "CodeBuddyProvider": ("codebuddy_provider", "CodeBuddyProvider"),
    "GitHubCopilotProvider": ("github_copilot_provider", "GitHubCopilotProvider"),
    "OpenAICodexProvider": ("openai_codex_provider", "OpenAICodexProvider"),
    "OpenAICompatProvider": ("openai_compat_provider", "OpenAICompatProvider"),
}


def __getattr__(name: str):
    target = _LAZY_TYPES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, class_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), class_name)
    globals()[name] = value
    return value
