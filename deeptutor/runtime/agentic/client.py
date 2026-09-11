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
from dataclasses import dataclass, replace
import hashlib
import inspect
import json
import threading
from types import SimpleNamespace
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from deeptutor.services.config import load_system_settings
from deeptutor.services.keypool import KeyPool, primary_api_key
from deeptutor.services.llm import get_token_limit_kwargs, supports_tools
from deeptutor.services.llm.capabilities import catalog_capability_override
from deeptutor.services.llm.exceptions import (
    LLMProviderError,
    LLMProviderTransportError,
)
from deeptutor.services.llm.openai_http_client import (
    openai_sdk_client_kwargs,
    sanitize_invalid_ssl_env,
)
from deeptutor.services.llm.reasoning_params import (
    build_openai_compatible_reasoning_kwargs,
)
from deeptutor.services.provider_registry import (
    api_format_for_provider,
    api_format_from_legacy,
    effective_backend,
    find_by_name,
    model_overrides_for,
    normalize_api_format,
    wire_api_for_provider,
    wire_api_from_api_format,
)

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
    api_key: str | list[str] | None
    base_url: str | None
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    reasoning_effort: str | None = None
    wire_api: str = "auto"
    api_format: str = "auto"

    def __post_init__(self) -> None:
        # Same rule as LLMConfig: an explicit ``api_format`` decides
        # ``wire_api``; a caller that only knows ``wire_api`` gets the format
        # derived from it. The two fields never disagree.
        spec = find_by_name(self.binding)
        if normalize_api_format(self.api_format) == "auto":
            object.__setattr__(self, "api_format", api_format_from_legacy(spec, self.wire_api))
            object.__setattr__(self, "wire_api", wire_api_for_provider(self.wire_api, spec))
        else:
            api_format = api_format_for_provider(self.api_format, spec)
            object.__setattr__(self, "api_format", api_format)
            object.__setattr__(
                self,
                "wire_api",
                wire_api_for_provider(wire_api_from_api_format(api_format), spec),
            )


def _client_cache_key(
    config: LLMClientConfig,
    loop: asyncio.AbstractEventLoop,
    disable_ssl_verify: bool,
) -> tuple[Any, ...]:
    serialized_key = json.dumps(config.api_key or "", ensure_ascii=False, separators=(",", ":"))
    secret = hashlib.sha256(serialized_key.encode("utf-8")).hexdigest()[:16]
    headers = json.dumps(config.extra_headers or {}, sort_keys=True, separators=(",", ":"))
    return (
        loop,
        config.binding,
        config.model or "",
        secret,
        config.base_url or "",
        config.api_version or "",
        headers,
        config.wire_api,
        config.api_format,
        disable_ssl_verify,
    )


def _build_openai_client(
    config: LLMClientConfig,
    *,
    disable_ssl_verify: bool,
    sdk_max_retries: int | None = None,
) -> Any:
    # A stale SSL_CERT_FILE (common with cloned conda envs) makes httpx's
    # create_ssl_context raise FileNotFoundError mid-__init__, aborting client
    # construction. Drop broken CA paths first so TLS uses its default CA config.
    sanitize_invalid_ssl_env()
    if isinstance(config.api_key, list):
        keys = [str(key).strip() for key in config.api_key if str(key or "").strip()]
        clients = {
            key: _build_openai_client(
                replace(config, api_key=key),
                disable_ssl_verify=disable_ssl_verify,
                sdk_max_retries=0,
            )
            for key in keys
        }
        return _KeyRotatingClient(KeyPool(keys), clients)
    spec = find_by_name(config.binding)
    backend = effective_backend(spec, config.api_format)
    wire_api = wire_api_for_provider(config.wire_api, spec)
    if wire_api == "responses":
        from deeptutor.services.llm.provider_core import OpenAICompatProvider

        responses_provider = OpenAICompatProvider(
            api_key=config.api_key,
            api_base=config.base_url or (spec.default_api_base if spec else None),
            default_model=config.model or "gpt-4o-mini",
            extra_headers=config.extra_headers,
            spec=spec,
            provider_name=config.binding,
            wire_api="responses",
        )
        return _ProviderOpenAIAdapter(responses_provider)
    if spec and wire_api != "chat_completions":
        native_adapter = _build_native_provider_adapter(config, spec, backend)
        if native_adapter is not None:
            return native_adapter

    # Same constructor recipe as the services-layer provider, so headers, the
    # SDK retry budget and the TLS bypass cannot drift between the two paths.
    sdk_kwargs = openai_sdk_client_kwargs(
        api_key=config.api_key or "sk-no-key-required",
        base_url=config.base_url or None,
        extra_headers=config.extra_headers,
        spec=spec,
        disable_ssl_verify=disable_ssl_verify,
        sdk_max_retries=sdk_max_retries,
    )
    if config.binding == "azure_openai" or (config.binding == "openai" and config.api_version):
        sdk_kwargs.pop("base_url", None)
        return AsyncAzureOpenAI(
            azure_endpoint=config.base_url,
            api_version=config.api_version,
            **sdk_kwargs,
        )
    return AsyncOpenAI(**sdk_kwargs)


class _KeyRotatingCompletions:
    def __init__(self, key_pool: KeyPool, clients: dict[str, Any]) -> None:
        self._key_pool = key_pool
        self._clients = clients

    async def create(self, **kwargs: Any) -> Any:
        for attempt in range(2):
            api_key = self._key_pool.next()
            try:
                return await self._clients[api_key].chat.completions.create(**kwargs)
            except Exception as exc:
                status = getattr(exc, "status_code", None) or getattr(
                    getattr(exc, "response", None), "status_code", None
                )
                if status != 429:
                    raise
                self._key_pool.mark_429(api_key)
                if attempt:
                    raise
        raise RuntimeError("LLM key rotation exhausted")


class _KeyRotatingClient:
    def __init__(self, key_pool: KeyPool, clients: dict[str, Any]) -> None:
        self._clients = clients
        self.chat = SimpleNamespace(completions=_KeyRotatingCompletions(key_pool, clients))

    async def close(self) -> None:
        await asyncio.gather(*(_close_client(client) for client in self._clients.values()))


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
        api_key=primary_api_key(config.api_key),
        api_base=config.base_url or spec.default_api_base_for(config.api_format) or None,
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
        api_key=primary_api_key(config.api_key),
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
        wire_api=config.wire_api,
    )
    return _ProviderOpenAIAdapter(provider)


_NATIVE_ADAPTER_BUILDERS: dict[str, Callable[[LLMClientConfig, Any], Any]] = {
    "anthropic": _build_anthropic_adapter,
    "openai_codex": _build_codex_adapter,
    "github_copilot": _build_copilot_adapter,
    "codebuddy": _build_codebuddy_adapter,
}


def _build_native_provider_adapter(
    config: LLMClientConfig, spec: Any, backend: str | None = None
) -> Any | None:
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
    native_web_search_models = {
        str(name).strip().lower()
        for name in getattr(spec, "native_web_search_models", ())
        if str(name).strip()
    }
    if model.split("/")[-1] in native_web_search_models and not config.api_version:
        # DeepSeek's native web search is a Responses-only capability. Route
        # the supported model through the provider adapter; sibling models
        # stay on the ordinary Chat Completions client.
        return _build_direct_openai_adapter(config, spec)
    builder = _NATIVE_ADAPTER_BUILDERS.get(backend or spec.backend)
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
                        provider_specific_fields=response.provider_specific_fields,
                    ),
                    finish_reason=(
                        "tool_calls" if response.tool_calls else response.finish_reason or "stop"
                    ),
                )
            ],
            usage=response.usage or None,
        )


def _provider_streams_tool_args(provider: Any) -> bool:
    """Whether *provider* declares the live tool-argument callback.

    Probed rather than passed unconditionally: every provider in this family
    forwards its unknown keyword arguments into the request body, so handing
    the callback to one that does not name it would serialise a function into
    an API call. A provider that has not opted in simply keeps the old
    behaviour — its tool calls arrive whole.
    """
    chat_stream = getattr(provider, "chat_stream", None)
    if not callable(chat_stream):
        return False
    try:
        parameters = inspect.signature(chat_stream).parameters
    except (TypeError, ValueError):
        return False
    return "on_tool_args_delta" in parameters


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
        self._emitted_reasoning = False

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

    def _raise_for_error_response(self, response: Any) -> None:
        """Turn an error-shaped response back into the exception it describes.

        Providers in this family do not raise; they *return* ``finish_reason ==
        "error"`` with an operator-facing string in ``content`` (see
        ``LLMProvider._handle_error`` and the stream-stall branch of
        ``AnthropicProvider.chat_stream``). Forwarded as an ordinary chunk,
        that string streams into the reply as if the model had written it —
        "Error calling LLM: stream stalled for more than 90 seconds" arriving
        as the tutor's answer — and because nothing was raised, neither the
        provider's own retry nor the loop's transport retry ever ran.

        Retrying is left to the caller rather than done here: the loop already
        knows whether this round put text on the wire, and replaying a stream
        that half-succeeded would splice a second attempt onto the visible
        first one.
        """
        if str(getattr(response, "finish_reason", "") or "") != "error":
            return
        message = str(getattr(response, "content", "") or "").strip()
        detail = message or "The model provider returned an error."
        # A provider may narrow the marker list; fall back to the shared one
        # rather than treating an unclassifiable failure as permanent, which
        # would skip a retry that the base policy would have granted.
        is_transient = getattr(self._provider, "_is_transient_error", None)
        if not callable(is_transient):
            from deeptutor.services.llm.provider_core.base import LLMProvider

            is_transient = LLMProvider._is_transient_error
        if is_transient(message):
            raise LLMProviderTransportError(detail, partial_response=self._emitted_content)
        raise LLMProviderError(detail)

    async def _run(self) -> None:
        assert self._queue is not None

        async def _on_content_delta(text: str) -> None:
            if text:
                self._emitted_content = True
                await self._queue.put(_openai_stream_chunk(content=text))

        async def _on_reasoning_delta(text: str) -> None:
            if text:
                self._emitted_reasoning = True
                await self._queue.put(_openai_stream_chunk(reasoning_content=text))

        async def _on_tool_args_delta(call_id: str, name: str, arguments: str) -> None:
            # A side channel, not the call itself: the finished tool call is
            # still queued whole below. Consumers that do not know the field
            # see an ordinary chunk with an empty delta and skip it, so this
            # cannot double-count arguments in a tool-call accumulator.
            await self._queue.put(
                _openai_stream_chunk(
                    provider_specific_fields={
                        "tool_args_preview": {
                            "id": call_id,
                            "name": name,
                            "arguments": arguments,
                        }
                    }
                )
            )

        extra_call_kwargs: dict[str, Any] = {}
        if _provider_streams_tool_args(self._provider):
            extra_call_kwargs["on_tool_args_delta"] = _on_tool_args_delta

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
                on_reasoning_delta=_on_reasoning_delta,
                **extra_call_kwargs,
                **self._extra_kwargs,
            )
            self._raise_for_error_response(response)
            # A provider that reports reasoning only on the finished message
            # still gets it onto the thinking channel, once.
            if response.reasoning_content and not self._emitted_reasoning:
                await self._queue.put(
                    _openai_stream_chunk(reasoning_content=response.reasoning_content)
                )
            if response.content and not self._emitted_content:
                await self._queue.put(_openai_stream_chunk(content=response.content))
            for index, tool_call in enumerate(response.tool_calls or []):
                await self._queue.put(_openai_stream_chunk(tool_call=tool_call, index=index))
            provider_fields = dict(response.provider_specific_fields or {})
            if response.reasoning_content:
                provider_fields["reasoning_content"] = response.reasoning_content
            if response.thinking_blocks:
                # Anthropic requires the *signed* thinking blocks of a turn to
                # be replayed verbatim on the next request. The provider parsed
                # them out, but nothing carried them back, so the loop had no
                # way to return them and every round dropped its signature.
                provider_fields["thinking_blocks"] = response.thinking_blocks
            await self._queue.put(
                _openai_stream_chunk(
                    finish_reason=(
                        "tool_calls" if response.tool_calls else response.finish_reason or "stop"
                    ),
                    usage=response.usage or None,
                    provider_specific_fields=provider_fields,
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
    reasoning_content: str | None = None,
    tool_call: Any | None = None,
    index: int = 0,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    provider_specific_fields: dict[str, Any] | None = None,
) -> Any:
    tool_calls = None
    if tool_call is not None:
        tool_calls = [_openai_tool_call(tool_call, index=index)]
    # ``reasoning_content`` is read off the delta by the agent loop, the same
    # way an OpenAI-compatible reasoning model reports it. Only set the
    # attribute when there is one, so a plain chunk stays plain.
    delta_fields: dict[str, Any] = {"content": content, "tool_calls": tool_calls}
    if reasoning_content is not None:
        delta_fields["reasoning_content"] = reasoning_content
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(**delta_fields),
                finish_reason=finish_reason,
                provider_specific_fields=provider_specific_fields,
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
    # Apply model-intrinsic overrides last, matching OpenAICompatProvider. A
    # None value drops the parameter instead of serialising JSON null.
    spec = find_by_name(binding)
    for key, value in model_overrides_for(model, spec).items():
        if value is None:
            kwargs.pop(key, None)
        else:
            kwargs[key] = value
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


def can_use_native_tool_calling(
    *, binding: str, model: str | None, api_format: str = "auto"
) -> bool:
    """Whether the current provider supports OpenAI-style function calling.

    Resolution order:

    0. A capability the user declared on the model in Settings wins outright —
       that is the whole point of letting them declare it.
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
    declared = catalog_capability_override(binding, model, "supports_tools")
    if declared is not None:
        return declared
    spec = find_by_name(binding)
    backend = effective_backend(spec, api_format)
    if spec and backend in _NATIVE_TOOL_BACKENDS:
        return True
    if binding in _NATIVE_TOOL_BLOCKED_BINDINGS or (spec and spec.is_local):
        return False
    if supports_tools(binding, model):
        return True
    return bool(spec and backend == "openai_compat")
