"""OpenAI-compatible client factory and completion kwargs.

Lifted from chat's pipeline so any capability that wants a streaming LLM call
with tools can construct the same client + kwargs without re-implementing
provider gating, Azure detection, SSL bypass, or per-model token caps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
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


def build_openai_client(config: LLMClientConfig) -> Any:
    """Construct an ``AsyncOpenAI`` / ``AsyncAzureOpenAI`` client."""
    default_headers = config.extra_headers or None
    spec = find_by_name(config.binding)
    if spec and spec.backend == "anthropic":
        from deeptutor.services.llm.provider_core import AnthropicProvider

        anthropic_provider = AnthropicProvider(
            api_key=config.api_key,
            api_base=config.base_url or spec.default_api_base or None,
            default_model=config.model or "claude-sonnet-4-20250514",
            extra_headers=config.extra_headers,
            supports_prompt_caching=spec.supports_prompt_caching,
        )
        return _AnthropicOpenAIAdapter(anthropic_provider)
    if spec and spec.backend == "openai_codex":
        from deeptutor.services.llm.provider_core import OpenAICodexProvider

        oauth_provider = OpenAICodexProvider(
            default_model=config.model or "openai-codex/gpt-5.1-codex",
        )
        return _AnthropicOpenAIAdapter(oauth_provider)

    http_client = None
    if load_system_settings()["disable_ssl_verify"]:
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


class _AnthropicOpenAIAdapter:
    """OpenAI chat-completions facade backed by the native Anthropic provider."""

    def __init__(self, provider: Any):
        self._provider = provider
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_completion))

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
            return _AnthropicOpenAIStream(
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
                    finish_reason=response.finish_reason or "stop",
                )
            ],
            usage=response.usage or None,
        )


class _AnthropicOpenAIStream:
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

    def __aiter__(self) -> "_AnthropicOpenAIStream":
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
                    finish_reason=response.finish_reason or "stop",
                    usage=response.usage or None,
                )
            )
        except Exception as exc:
            await self._queue.put(exc)
        finally:
            await self._queue.put(None)


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
    """Whether the current provider supports OpenAI-style function calling."""
    if not supports_tools(binding, model):
        return False
    spec = find_by_name(binding)
    if spec and spec.backend == "anthropic":
        return True
    return binding not in _NATIVE_TOOL_BLOCKED_BINDINGS
