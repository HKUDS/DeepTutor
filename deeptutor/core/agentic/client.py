"""OpenAI-compatible client factory and completion kwargs.

Lifted from chat's pipeline so any capability that wants a streaming LLM call
with tools can construct the same client + kwargs without re-implementing
provider gating, Azure detection, SSL bypass, or per-model token caps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from deeptutor.services.config import load_system_settings
from deeptutor.services.llm import get_token_limit_kwargs, supports_tools
from deeptutor.services.provider_registry import find_by_name

# Providers that don't reliably support OpenAI function-calling. The loop
# still runs without tool schemas — the model just produces prose.
_NATIVE_TOOL_BLOCKED_BINDINGS: frozenset[str] = frozenset(
    {"anthropic", "claude", "ollama", "lm_studio", "vllm", "llama_cpp"}
)
_THINKING_STYLE_MAP = {
    "thinking_type": lambda enabled: {"thinking": {"type": "enabled" if enabled else "disabled"}},
    "enable_thinking": lambda enabled: {"enable_thinking": enabled},
    "reasoning_split": lambda enabled: {"reasoning_split": enabled},
}
_THINKING_DISABLED_BY_DEFAULT: tuple[tuple[str, str], ...] = (("deepseek", "deepseek-v4-flash"),)


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


def _is_anthropic_backend(binding: str | None) -> bool:
    """Check if the binding uses the Anthropic API format."""
    if not binding:
        return False
    spec = find_by_name(binding)
    return spec is not None and spec.backend == "anthropic"


def build_openai_client(config: LLMClientConfig) -> Any:
    """Construct an ``AsyncOpenAI`` / ``AsyncAzureOpenAI`` client.

    For Anthropic-backend providers (``custom_anthropic``, etc.), returns an
    adapter that routes through the services-layer ``AnthropicProvider`` while
    exposing the same ``.chat.completions.create()`` interface that
    ``labeled_step`` expects.
    """
    if _is_anthropic_backend(config.binding):
        return _AnthropicOpenAIAdapter(config)

    http_client = None
    if load_system_settings()["disable_ssl_verify"]:
        http_client = httpx.AsyncClient(verify=False)  # nosec B501
    default_headers = config.extra_headers or None
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


# ---------------------------------------------------------------------------
# Anthropic → OpenAI streaming adapter
# ---------------------------------------------------------------------------


class _ToolCallFunction:
    """Mimics ``openai.types.chat.chat_completion_chunk.ChoiceDeltaToolCallFunction``."""

    __slots__ = ("name", "arguments")

    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCallDelta:
    """Mimics ``openai.types.chat.chat_completion_chunk.ChoiceDeltaToolCall``."""

    __slots__ = ("index", "id", "function")

    def __init__(
        self, index: int, id: str | None = None, function: _ToolCallFunction | None = None
    ) -> None:
        self.index = index
        self.id = id
        self.function = function


class _ChunkDelta:
    """Mimics ``openai.types.chat.ChatCompletionChunkChoice.Delta``."""

    __slots__ = ("content", "tool_calls", "reasoning_content")

    def __init__(
        self,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list[_ToolCallDelta] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class _ChunkChoice:
    """Mimics ``openai.types.chat.ChatCompletionChunkChoice``."""

    __slots__ = ("delta", "finish_reason")

    def __init__(
        self, delta: _ChunkDelta, finish_reason: str | None = None
    ) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    """Mimics ``openai.types.chat.ChatCompletionChunk``."""

    __slots__ = ("choices", "usage")

    def __init__(
        self, choices: list[_ChunkChoice], usage: Any = None
    ) -> None:
        self.choices = choices
        self.usage = usage


class _UsageInfo:
    """Minimal usage info compatible with what UsageTracker expects."""

    __slots__ = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class _AnthropicStreamResponse:
    """Async iterator that yields OpenAI-format chunks from an
    AnthropicProvider streaming call."""

    def __init__(
        self,
        provider: Any,
        messages: list[dict[str, Any]],
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        reasoning_effort: str | None,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> None:
        self._provider = provider
        self._messages = messages
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._tools = tools
        self._tool_choice = tool_choice
        self._queue: asyncio.Queue[_Chunk | BaseException | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        try:
            async def _on_content(chunk: str) -> None:
                if chunk:
                    await self._queue.put(
                        _Chunk([_ChunkChoice(_ChunkDelta(content=chunk))])
                    )

            async def _on_reasoning(chunk: str) -> None:
                if chunk:
                    await self._queue.put(
                        _Chunk([_ChunkChoice(_ChunkDelta(reasoning_content=chunk))])
                    )

            response = await self._provider.chat_stream_with_retry(
                messages=self._messages,
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                reasoning_effort=self._reasoning_effort,
                tools=self._tools,
                tool_choice=self._tool_choice,
                on_content_delta=_on_content,
                on_reasoning_delta=_on_reasoning,
            )

            # AnthropicProvider catches exceptions internally and returns
            # LLMResponse(finish_reason="error"). Re-raise so the caller
            # (labeled_step) sees the same behavior as the OpenAI SDK.
            if getattr(response, "finish_reason", None) == "error":
                error_msg = getattr(response, "content", None) or "LLM request failed"
                raise RuntimeError(error_msg)

            # Emit tool_calls from the final response as OpenAI-format deltas.
            # Anthropic doesn't stream tool_call deltas — they arrive in the
            # final message. Emit them as complete chunks so labeled_step can
            # parse them the same way as OpenAI-streamed tool calls.
            tool_calls = getattr(response, "tool_calls", None) or []
            if tool_calls:
                import json

                tc_deltas: list[_ToolCallDelta] = []
                for idx, tc in enumerate(tool_calls):
                    args_str = json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else "{}"
                    tc_deltas.append(
                        _ToolCallDelta(
                            index=idx,
                            id=tc.id,
                            function=_ToolCallFunction(name=tc.name, arguments=args_str),
                        )
                    )
                await self._queue.put(
                    _Chunk([_ChunkChoice(_ChunkDelta(tool_calls=tc_deltas))])
                )

            usage_dict = getattr(response, "usage", None) or {}
            usage_obj = None
            if usage_dict:
                usage_obj = _UsageInfo(
                    prompt_tokens=usage_dict.get("prompt_tokens", 0),
                    completion_tokens=usage_dict.get("completion_tokens", 0),
                )
            finish_reason = getattr(response, "finish_reason", "stop") or "stop"
            if finish_reason == "tool_calls":
                finish_reason = "tool_calls"
            await self._queue.put(
                _Chunk(
                    [_ChunkChoice(_ChunkDelta(), finish_reason=finish_reason)],
                    usage=usage_obj,
                )
            )
        except Exception as exc:
            await self._queue.put(exc)
        finally:
            await self._queue.put(None)

    def __aiter__(self):
        self._task = asyncio.create_task(self._run())
        return self

    async def __anext__(self) -> _Chunk:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


class _CompletionsNamespace:
    """Mimics ``client.chat.completions``."""

    def __init__(self, config: LLMClientConfig) -> None:
        self._config = config

    async def create(self, **kwargs: Any) -> _AnthropicStreamResponse:
        from deeptutor.services.llm.config import LLMConfig
        from deeptutor.services.llm.provider_factory import get_runtime_provider

        llm_config = LLMConfig(
            model=self._config.model or "",
            api_key=self._config.api_key or "",
            base_url=self._config.base_url,
            effective_url=self._config.base_url,
            binding=self._config.binding,
            provider_name=self._config.binding,
            api_version=self._config.api_version,
            extra_headers=self._config.extra_headers or {},
            reasoning_effort=self._config.reasoning_effort,
        )
        provider = get_runtime_provider(llm_config)

        messages = kwargs.get("messages", [])
        model = kwargs.get("model") or self._config.model
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice")

        resp = _AnthropicStreamResponse(
            provider=provider,
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=self._config.reasoning_effort,
            tools=tools,
            tool_choice=tool_choice,
        )
        return resp


class _ChatNamespace:
    """Mimics ``client.chat``."""

    def __init__(self, config: LLMClientConfig) -> None:
        self.completions = _CompletionsNamespace(config)


class _AnthropicOpenAIAdapter:
    """Drop-in replacement for ``AsyncOpenAI`` that routes through
    the services-layer ``AnthropicProvider``.

    Only the streaming path (``client.chat.completions.create(stream=True)``)
    is implemented — enough for the agentic loop in ``labeled_step``.
    """

    def __init__(self, config: LLMClientConfig) -> None:
        self.chat = _ChatNamespace(config)


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


def _disable_thinking_by_default(binding: str | None, model: str | None) -> bool:
    normalized_model = (model or "").strip().lower()
    normalized_binding = (binding or "").strip().lower()
    return any(
        normalized_binding == provider and pattern in normalized_model
        for provider, pattern in _THINKING_DISABLED_BY_DEFAULT
    )


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
    model_name = model or ""
    resolved_effort = reasoning_effort
    if resolved_effort is None and spec and spec.reasoning_model_patterns:
        model_lower = model_name.lower()
        if any(pattern.lower() in model_lower for pattern in spec.reasoning_model_patterns):
            resolved_effort = "high"

    semantic_effort: str | None = None
    if isinstance(resolved_effort, str):
        semantic_effort = resolved_effort.lower()
        if semantic_effort == "minimum":
            semantic_effort = "minimal"

    wire_effort = resolved_effort
    if spec and spec.name == "dashscope" and semantic_effort == "minimal":
        wire_effort = "minimum"

    kwargs: dict[str, Any] = {}
    if wire_effort and not (spec and spec.thinking_style and semantic_effort == "minimal"):
        kwargs["reasoning_effort"] = wire_effort

    if spec and spec.thinking_style and resolved_effort is not None:
        thinking_enabled = semantic_effort != "minimal"
        extra = _THINKING_STYLE_MAP.get(spec.thinking_style, lambda _enabled: None)(
            thinking_enabled
        )
        if extra:
            kwargs.setdefault("extra_body", {}).update(extra)
    elif spec and spec.thinking_style and _disable_thinking_by_default(spec.name, model_name):
        extra = _THINKING_STYLE_MAP.get(spec.thinking_style, lambda _enabled: None)(False)
        if extra:
            kwargs.setdefault("extra_body", {}).update(extra)
    return kwargs


def can_use_native_tool_calling(*, binding: str, model: str | None) -> bool:
    """Whether the current provider supports OpenAI-style function calling."""
    if not supports_tools(binding, model):
        return False
    return binding not in _NATIVE_TOOL_BLOCKED_BINDINGS
