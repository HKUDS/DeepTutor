"""OpenAI-compatible client factory and completion kwargs.

Lifted from chat's pipeline so any capability that wants a streaming LLM call
with tools can construct the same client + kwargs without re-implementing
provider gating, Azure detection, SSL bypass, or per-model token caps.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import hashlib
import inspect
import json
import threading
from types import SimpleNamespace
from typing import Any

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from deeptutor.services.config import load_system_settings
from deeptutor.services.llm import get_token_limit_kwargs, supports_tools
from deeptutor.services.llm.reasoning_params import (
    build_openai_compatible_reasoning_kwargs,
)
from deeptutor.services.provider_registry import find_by_name

# Providers that don't reliably support OpenAI function-calling. The loop
# still runs without tool schemas — the model just produces prose.
_NATIVE_TOOL_BLOCKED_BINDINGS: frozenset[str] = frozenset(
    {"anthropic", "claude", "ollama", "lm_studio", "vllm", "llama_cpp"}
)

# Native provider adapters whose backends speak OpenAI-style function calling
# end to end (schema serialization + tool-call parsing). Backends validated
# here get tools attached regardless of the binding blocklist above.
# Invariant: must be a subset of _NATIVE_ADAPTER_BUILDERS — every tool-gated
# backend needs an adapter branch, or tool schemas would be attached to a plain
# AsyncOpenAI client pointed at a non-OpenAI wire format. github_copilot is
# adapter-routed but deliberately excluded from this set.
_NATIVE_TOOL_BACKENDS: frozenset[str] = frozenset({"anthropic", "openai_codex", "codebuddy"})
_AGENTIC_CLIENT_POOL_MAXSIZE = 2
_agentic_client_pool: "OrderedDict[tuple[Any, ...], Any]" = OrderedDict()
_agentic_client_pool_lock = threading.RLock()


@dataclass(frozen=True)
class LLMClientConfig:
    """Provider-neutral handle for constructing an OpenAI-compatible client."""

    binding: str
    model: str | None
    api_key: str | None
    base_url: str | None
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    reasoning_effort: str | None = None


def _client_cache_key(
    config: LLMClientConfig,
    loop: asyncio.AbstractEventLoop,
    disable_ssl_verify: bool,
) -> tuple[Any, ...]:
    secret = hashlib.sha256((config.api_key or "").encode("utf-8")).hexdigest()[:16]
    headers = json.dumps(config.extra_headers or {}, sort_keys=True, separators=(",", ":"))
    return (
        loop,
        config.binding,
        config.model or "",
        secret,
        config.base_url or "",
        config.api_version or "",
        headers,
        disable_ssl_verify,
    )


def _build_openai_client(config: LLMClientConfig, *, disable_ssl_verify: bool) -> Any:
    default_headers = config.extra_headers or None
    spec = find_by_name(config.binding)
    if spec:
        native_adapter = _build_native_provider_adapter(config, spec)
        if native_adapter is not None:
            return native_adapter

    http_client = None
    if disable_ssl_verify:
        http_client = httpx.AsyncClient(verify=False)  # nosec B501
    if config.binding == "azure_openai" or (config.binding == "openai" and config.api_version):
        return AsyncAzureOpenAI(
            api_key=config.api_key or "sk-no-key-required",
            azure_endpoint=config.base_url,
            api_version=config.api_version,
            http_client=http_client,
            default_headers=default_headers,
        )
    return AsyncOpenAI(
        api_key=config.api_key or "sk-no-key-required",
        base_url=config.base_url or None,
        http_client=http_client,
        default_headers=default_headers,
    )


async def _close_client(client: Any) -> None:
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _schedule_client_close(client: Any, loop: asyncio.AbstractEventLoop) -> None:
    async def _close() -> None:
        with contextlib.suppress(Exception):
            await _close_client(client)

    loop.create_task(_close())


def build_openai_client(config: LLMClientConfig) -> Any:
    """Return a bounded, event-loop-local OpenAI-compatible client.

    The chat, research and question pipelines build this handle per turn.  The
    handle itself owns an HTTP connection pool, so reusing it is both faster
    and prevents a new allocator/socket high-water mark on every turn.
    """
    disable_ssl_verify = bool(load_system_settings()["disable_ssl_verify"])
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _build_openai_client(config, disable_ssl_verify=disable_ssl_verify)

    key = _client_cache_key(config, loop, disable_ssl_verify)
    with _agentic_client_pool_lock:
        cached = _agentic_client_pool.get(key)
        if cached is not None:
            _agentic_client_pool.move_to_end(key)
            return cached
        client = _build_openai_client(config, disable_ssl_verify=disable_ssl_verify)
        _agentic_client_pool[key] = client
        _agentic_client_pool.move_to_end(key)
        while len(_agentic_client_pool) > _AGENTIC_CLIENT_POOL_MAXSIZE:
            _, evicted = _agentic_client_pool.popitem(last=False)
            _schedule_client_close(evicted, loop)
        return client


async def close_agentic_client_pool() -> None:
    with _agentic_client_pool_lock:
        clients = list(_agentic_client_pool.values())
        _agentic_client_pool.clear()
    if clients:
        await asyncio.gather(*(_close_client(client) for client in clients), return_exceptions=True)


def reset_agentic_client_pool() -> None:
    with _agentic_client_pool_lock:
        clients = list(_agentic_client_pool.values())
        _agentic_client_pool.clear()
    if not clients:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        for client in clients:
            with contextlib.suppress(Exception):
                asyncio.run(_close_client(client))
        return
    for client in clients:
        _schedule_client_close(client, loop)


def agentic_client_pool_size() -> int:
    with _agentic_client_pool_lock:
        return len(_agentic_client_pool)


def _build_anthropic_adapter(config: LLMClientConfig, spec: Any) -> Any:
    from deeptutor.services.llm.provider_core import AnthropicProvider

    anthropic_provider = AnthropicProvider(
        api_key=config.api_key,
        api_base=config.base_url or spec.default_api_base or None,
        default_model=config.model or "claude-sonnet-4-20250514",
        extra_headers=config.extra_headers,
        supports_prompt_caching=spec.supports_prompt_caching,
    )
    return _ProviderOpenAIAdapter(anthropic_provider)


def _build_codex_adapter(config: LLMClientConfig, spec: Any) -> Any:
    from deeptutor.services.codex_auth.constants import CODEX_DEFAULT_MODEL_ID
    from deeptutor.services.llm.provider_core import OpenAICodexProvider

    oauth_provider = OpenAICodexProvider(
        default_model=config.model or CODEX_DEFAULT_MODEL_ID,
    )
    return _ProviderOpenAIAdapter(oauth_provider)


def _build_copilot_adapter(config: LLMClientConfig, spec: Any) -> Any:
    from deeptutor.services.llm.provider_core import GitHubCopilotProvider

    copilot_provider = GitHubCopilotProvider(
        default_model=config.model or "github-copilot/gpt-4.1",
    )
    return _ProviderOpenAIAdapter(copilot_provider)


def _build_codebuddy_adapter(config: LLMClientConfig, spec: Any) -> Any:
    from deeptutor.services.llm.provider_core.codebuddy_http_provider import (
        build_codebuddy_provider,
    )

    codebuddy_provider = build_codebuddy_provider(
        api_key=config.api_key,
        default_model=config.model or "codebuddy/hy3",
    )
    return _ProviderOpenAIAdapter(codebuddy_provider)


def _build_direct_openai_adapter(config: LLMClientConfig, spec: Any) -> Any:
    from deeptutor.services.llm.provider_core import OpenAICompatProvider

    provider = OpenAICompatProvider(
        api_key=config.api_key,
        api_base=config.base_url or spec.default_api_base or None,
        default_model=config.model or "gpt-5",
        extra_headers=config.extra_headers,
        spec=spec,
        provider_name=config.binding,
    )
    return _ProviderOpenAIAdapter(provider)


_NATIVE_ADAPTER_BUILDERS: dict[str, Callable[[LLMClientConfig, Any], Any]] = {
    "anthropic": _build_anthropic_adapter,
    "openai_codex": _build_codex_adapter,
    "github_copilot": _build_copilot_adapter,
    "codebuddy": _build_codebuddy_adapter,
}


def _build_native_provider_adapter(config: LLMClientConfig, spec: Any) -> Any | None:
    endpoint = (config.base_url or spec.default_api_base or "").lower()
    model = (config.model or "").lower()
    if (
        spec.name == "openai"
        and not config.api_version
        and "api.openai.com" in endpoint
        and any(token in model for token in ("gpt-5", "o1", "o3", "o4"))
    ):
        # Reuse the services provider: it already converts messages, tools,
        # streaming events and token limits for the Responses API.
        return _build_direct_openai_adapter(config, spec)
    builder = _NATIVE_ADAPTER_BUILDERS.get(spec.backend)
    return builder(config, spec) if builder else None


class _ProviderOpenAIAdapter:
    """OpenAI chat-completions facade backed by a native provider."""

    def __init__(self, provider: Any):
        self._provider = provider
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_completion))

    async def close(self) -> None:
        close = getattr(self._provider, "aclose", None)
        if callable(close):
            await close()

    async def _create_completion(self, **kwargs: Any) -> Any:
        stream = bool(kwargs.pop("stream", False))
        messages = kwargs.pop("messages", [])
        model = kwargs.pop("model", None)
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        temperature = kwargs.pop("temperature", 0.7)
        max_tokens = kwargs.pop("max_completion_tokens", None)
        if max_tokens is None:
            max_tokens = kwargs.pop("max_tokens", 4096)
        reasoning_effort = kwargs.pop("reasoning_effort", None)
        kwargs.pop("stream_options", None)

        if stream:
            return _ProviderOpenAIStream(
                provider=self._provider,
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                extra_kwargs=kwargs,
            )

        response = await self._provider.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            **kwargs,
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=response.content or "",
                        tool_calls=[
                            _openai_tool_call(tool_call, index=index)
                            for index, tool_call in enumerate(response.tool_calls or [])
                        ],
                    ),
                    finish_reason=(
                        "tool_calls" if response.tool_calls else response.finish_reason or "stop"
                    ),
                )
            ],
            usage=response.usage or None,
        )


class _ProviderOpenAIStream:
    def __init__(
        self,
        *,
        provider: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: Any,
        temperature: Any,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        extra_kwargs: dict[str, Any],
    ) -> None:
        self._provider = provider
        self._messages = messages
        self._tools = tools
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._tool_choice = tool_choice
        self._extra_kwargs = extra_kwargs
        self._queue: asyncio.Queue[Any] | None = None
        self._task: asyncio.Task[None] | None = None
        self._emitted_content = False

    def __aiter__(self) -> "_ProviderOpenAIStream":
        if self._queue is None:
            self._queue = asyncio.Queue()
            self._task = asyncio.create_task(self._run())
        return self

    async def __anext__(self) -> Any:
        if self._queue is None:
            self.__aiter__()
        assert self._queue is not None
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run(self) -> None:
        assert self._queue is not None

        async def _on_content_delta(text: str) -> None:
            if text:
                self._emitted_content = True
                await self._queue.put(_openai_stream_chunk(content=text))

        try:
            response = await self._provider.chat_stream(
                messages=self._messages,
                tools=self._tools,
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                reasoning_effort=self._reasoning_effort,
                tool_choice=self._tool_choice,
                on_content_delta=_on_content_delta,
                **self._extra_kwargs,
            )
            if response.content and not self._emitted_content:
                await self._queue.put(_openai_stream_chunk(content=response.content))
            for index, tool_call in enumerate(response.tool_calls or []):
                await self._queue.put(_openai_stream_chunk(tool_call=tool_call, index=index))
            await self._queue.put(
                _openai_stream_chunk(
                    finish_reason=(
                        "tool_calls" if response.tool_calls else response.finish_reason or "stop"
                    ),
                    usage=response.usage or None,
                )
            )
        except Exception as exc:
            await self._queue.put(exc)
        finally:
            await self._queue.put(None)


_AnthropicOpenAIAdapter = _ProviderOpenAIAdapter
_AnthropicOpenAIStream = _ProviderOpenAIStream


def _openai_tool_call(tool_call: Any, *, index: int) -> Any:
    function = SimpleNamespace(
        name=getattr(tool_call, "name", ""),
        arguments=json.dumps(getattr(tool_call, "arguments", {}) or {}, ensure_ascii=False),
    )
    return SimpleNamespace(
        index=index,
        id=getattr(tool_call, "id", ""),
        type="function",
        function=function,
    )


def _openai_stream_chunk(
    *,
    content: str | None = None,
    tool_call: Any | None = None,
    index: int = 0,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> Any:
    tool_calls = None
    if tool_call is not None:
        tool_calls = [_openai_tool_call(tool_call, index=index)]
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def build_completion_kwargs(
    *,
    temperature: float,
    model: str | None,
    max_tokens: int,
    binding: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Compose temperature + per-model token-limit kwargs into one dict."""
    kwargs: dict[str, Any] = {"temperature": temperature}
    if model:
        kwargs.update(get_token_limit_kwargs(model, max_tokens))
    kwargs.update(
        build_provider_extra_kwargs(
            binding=binding,
            model=model,
            reasoning_effort=reasoning_effort,
        )
    )
    return kwargs


def build_provider_extra_kwargs(
    *,
    binding: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    """Return provider-specific kwargs for raw OpenAI-compatible agent calls.

    Agentic pipelines stream directly through ``AsyncOpenAI`` so tests can
    inject scripted clients. This helper mirrors the small provider-normalized
    subset that is required before those raw calls: reasoning effort and
    provider-specific thinking flags.
    """
    spec = find_by_name(binding)
    return build_openai_compatible_reasoning_kwargs(
        spec=spec,
        binding=binding,
        model=model,
        reasoning_effort=reasoning_effort,
    )


def can_use_native_tool_calling(*, binding: str, model: str | None) -> bool:
    """Whether the current provider supports OpenAI-style function calling.

    Resolution order:

    1. Native provider adapters backed by Anthropic or OpenAI Codex support tools.
    2. Local OpenAI-compatible servers (Ollama, vLLM, LM Studio, llama.cpp,
       Lemonade, OVMS, …) and anything in ``_NATIVE_TOOL_BLOCKED_BINDINGS`` are
       opted out — tool support there depends on the loaded model and is
       unreliable, so the loop falls back to prose.
    3. An explicit ``supports_tools`` capability (provider- or model-level) wins.
    4. Otherwise a registered *cloud* OpenAI-compatible provider is assumed
       tool-capable — function calling is part of that API contract, matching
       the catch-all ``custom`` provider. This keeps newly added cloud
       providers working without a dedicated capability entry, instead of
       silently disabling native tools (the gap that affected e.g. SiliconFlow,
       Gemini, Zhipu, Qianfan, NVIDIA NIM and the Volc/BytePlus coding plans).
       To opt a cloud provider out, add its binding to
       ``_NATIVE_TOOL_BLOCKED_BINDINGS``.
    """
    spec = find_by_name(binding)
    if spec and spec.backend in _NATIVE_TOOL_BACKENDS:
        return True
    if binding in _NATIVE_TOOL_BLOCKED_BINDINGS or (spec and spec.is_local):
        return False
    if supports_tools(binding, model):
        return True
    return bool(spec and spec.backend == "openai_compat")
