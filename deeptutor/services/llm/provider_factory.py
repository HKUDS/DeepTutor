"""Factory for services-layer provider runtime objects."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import contextlib
import hashlib
import json
import threading
from typing import Any

from deeptutor.services.llm.config import LLMConfig, get_llm_config
from deeptutor.services.llm.provider_core.base import GenerationSettings, LLMProvider
from deeptutor.services.provider_registry import effective_backend, find_by_name

_PROVIDER_POOL_MAXSIZE = 2
_provider_pool: "OrderedDict[tuple[Any, ...], LLMProvider]" = OrderedDict()
_provider_pool_lock = threading.RLock()


def _secret_fingerprint(value: str | list[str] | None) -> str:
    if not value:
        return ""
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _provider_cache_key(config: LLMConfig, loop: asyncio.AbstractEventLoop) -> tuple[Any, ...]:
    headers = json.dumps(config.extra_headers or {}, sort_keys=True, separators=(",", ":"))
    return (
        loop,
        config.provider_name or config.binding,
        config.provider_mode,
        config.model,
        _secret_fingerprint(config.api_key),
        config.effective_url or config.base_url or "",
        config.api_version or "",
        headers,
        config.wire_api,
        config.api_format,
        config.temperature,
        config.max_tokens,
        config.reasoning_effort,
    )


def _build_runtime_provider(llm_config: LLMConfig) -> LLMProvider:
    """Construct one provider, importing only the selected backend SDK."""
    provider_name = llm_config.provider_name or llm_config.binding
    api_key = llm_config.get_api_key()
    spec = find_by_name(provider_name)
    backend = effective_backend(spec, llm_config.api_format)
    if backend == "openai_compat" and provider_name == "openai" and llm_config.api_version:
        # An OpenAI profile carrying an api_version is an Azure deployment typed
        # under the generic vendor. The agentic client has always sent those to
        # the Azure SDK; the services path must make the same call.
        backend = "azure_openai"

    if backend == "openai_codex":
        from deeptutor.services.llm.provider_core.openai_codex_provider import (
            OpenAICodexProvider,
        )

        provider: LLMProvider = OpenAICodexProvider(default_model=llm_config.model)
    elif backend == "github_copilot":
        from deeptutor.services.llm.provider_core.github_copilot_provider import (
            GitHubCopilotProvider,
        )

        provider = GitHubCopilotProvider(default_model=llm_config.model)
    elif backend == "codebuddy":
        from deeptutor.services.llm.provider_core.codebuddy_http_provider import (
            build_codebuddy_provider,
        )

        provider = build_codebuddy_provider(
            api_key=api_key or None,
            default_model=llm_config.model,
        )
    elif backend == "azure_openai":
        from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=api_key,
            api_base=llm_config.effective_url or llm_config.base_url or "",
            default_model=llm_config.model,
            extra_headers=llm_config.extra_headers or None,
            api_version=llm_config.api_version,
        )
    elif backend == "anthropic":
        from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=api_key or None,
            api_base=llm_config.effective_url or llm_config.base_url or None,
            default_model=llm_config.model,
            extra_headers=llm_config.extra_headers or None,
            supports_prompt_caching=bool(spec and spec.supports_prompt_caching),
        )
    else:
        from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=llm_config.api_key or None,
            api_base=llm_config.effective_url or llm_config.base_url or None,
            default_model=llm_config.model,
            extra_headers=llm_config.extra_headers or None,
            spec=spec,
            provider_name=provider_name,
            wire_api=llm_config.wire_api,
        )

    provider.generation = GenerationSettings(
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens,
        reasoning_effort=llm_config.reasoning_effort,
    )
    return provider


def _schedule_close(provider: LLMProvider, loop: asyncio.AbstractEventLoop) -> None:
    async def _close() -> None:
        with contextlib.suppress(Exception):
            await provider.aclose()

    loop.create_task(_close())


def get_runtime_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Return a small event-loop-local pool entry for the supplied config.

    A provider owns an SDK HTTP connection pool. Recreating it for every token
    request steadily raises the process high-water mark and forfeits keep-alive.
    Calls made outside an event loop remain uncached for cross-loop safety.
    """
    llm_config = config or get_llm_config()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _build_runtime_provider(llm_config)

    key = _provider_cache_key(llm_config, loop)
    with _provider_pool_lock:
        cached = _provider_pool.get(key)
        if cached is not None:
            _provider_pool.move_to_end(key)
            return cached

        provider = _build_runtime_provider(llm_config)
        _provider_pool[key] = provider
        _provider_pool.move_to_end(key)
        while len(_provider_pool) > _PROVIDER_POOL_MAXSIZE:
            _, evicted = _provider_pool.popitem(last=False)
            _schedule_close(evicted, loop)
        return provider


async def close_runtime_provider_pool() -> None:
    """Close every pooled SDK client during shutdown or config reload."""
    with _provider_pool_lock:
        providers = list(_provider_pool.values())
        _provider_pool.clear()
    if providers:
        await asyncio.gather(*(provider.aclose() for provider in providers), return_exceptions=True)


def reset_runtime_provider_pool() -> None:
    """Clear the pool from synchronous cache-invalidation call sites."""
    with _provider_pool_lock:
        providers = list(_provider_pool.values())
        _provider_pool.clear()
    if not providers:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        for provider in providers:
            with contextlib.suppress(Exception):
                asyncio.run(provider.aclose())
        return
    for provider in providers:
        _schedule_close(provider, loop)


def runtime_provider_pool_size() -> int:
    """Expose the bounded size for diagnostics and regression tests."""
    with _provider_pool_lock:
        return len(_provider_pool)


__all__ = [
    "close_runtime_provider_pool",
    "get_runtime_provider",
    "reset_runtime_provider_pool",
    "runtime_provider_pool_size",
]
