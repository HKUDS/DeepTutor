"""Image-generation adapter registry.

Adapters are stateless singletons keyed by the ``adapter`` field on the resolved
config. The OpenAI-compatible adapter covers OpenAI, Volcengine Ark Seedream and
compatible gateways; register bespoke providers by adding new keys here.
"""

from __future__ import annotations

from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.imagegen.adapters.chat_completions import ChatCompletionsImagegenAdapter
from deeptutor.services.imagegen.adapters.openai_compat import OpenAICompatImagegenAdapter
from deeptutor.services.imagegen.base import BaseImagegenAdapter

IMAGEGEN_ADAPTERS: dict[str, BaseImagegenAdapter] = {
    # OpenAI Images API shape (OpenAI, Volcengine Seedream, compatible gateways).
    "openai_compat": OpenAICompatImagegenAdapter(),
    # Chat-completions image output (OpenRouter Flux / Gemini image, …).
    "chat_completions": ChatCompletionsImagegenAdapter(),
}


def get_imagegen_adapter(name: str) -> BaseImagegenAdapter:
    adapter = IMAGEGEN_ADAPTERS.get(name or "openai_compat")
    if adapter is None:
        raise GenerationProviderError(f"Unsupported imagegen adapter: {name!r}")
    return adapter


__all__ = ["IMAGEGEN_ADAPTERS", "get_imagegen_adapter"]
