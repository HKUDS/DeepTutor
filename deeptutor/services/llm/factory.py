"""Unified services-layer LLM factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
import contextlib
import logging
from types import SimpleNamespace
from typing import Any, TypedDict

from deeptutor.config.settings import settings
from deeptutor.services.provider_registry import (
    PROVIDERS,
    canonical_provider_name,
    find_by_model,
    find_by_name,
    find_gateway,
)

from .capabilities import supports_response_format, supports_vision
from .config import LLMConfig, get_llm_config
from .error_mapping import map_error
from .multimodal import prepare_multimodal_messages
from .provider_factory import get_runtime_provider
from .utils import is_local_llm_server

DEFAULT_MAX_RETRIES = settings.retry.max_retries
DEFAULT_RETRY_DELAY = settings.retry.base_delay
DEFAULT_EXPONENTIAL_BACKOFF = settings.retry.exponential_backoff
DEFAULT_STREAM_COALESCE_CHARS = 64
DEFAULT_STREAM_COALESCE_SECONDS = 0.04
STREAM_CONTROL_TOKENS = {"<think>", "</think>"}

CallKwargs = dict[str, Any]

logger = logging.getLogger(__name__)

#: Kwarg key callers use to pass an explicit audit context to the shared LLM
#: boundary. Absent for legacy calls → provider behaviour is unchanged.
MODEL_INVOCATION_AUDIT_KWARG = "model_invocation_audit"


class ApiProviderPreset(TypedDict, total=False):
    """Typed representation of API provider presets."""

    name: str
    base_url: str
    requires_key: bool
    models: list[str]
    binding: str


class LocalProviderPreset(TypedDict, total=False):
    """Typed representation of local provider presets."""

    name: str
    base_url: str
    requires_key: bool
    default_key: str
    binding: str


ProviderPreset = ApiProviderPreset | LocalProviderPreset
ProviderPresetMap = Mapping[str, ProviderPreset]
ProviderPresetBundle = Mapping[str, ProviderPresetMap]


def _build_retry_delays(
    max_retries: int,
    retry_delay: float,
    exponential_backoff: bool,
) -> tuple[float, ...]:
    if max_retries <= 0:
        return ()
    delays: list[float] = []
    base = max(float(retry_delay), 0.0)
    for attempt in range(max_retries):
        delay = base * (2**attempt) if exponential_backoff else base
        delays.append(min(delay, 120.0))
    return tuple(delays)


def _resolve_provider_spec(
    *,
    binding: str | None,
    model: str,
    api_key: str,
    base_url: str | None,
    fallback: str | None,
):
    explicit = find_by_name(binding)
    gateway = find_gateway(
        provider_name=explicit.name if explicit else None,
        api_key=api_key or None,
        api_base=base_url or None,
    )
    if explicit and gateway and explicit.name == "openai":
        return gateway
    if explicit:
        return explicit
    if gateway:
        return gateway

    model_spec = find_by_model(model)
    if model_spec:
        return model_spec

    if is_local_llm_server(base_url):
        if base_url and "11434" in base_url:
            return find_by_name("ollama") or find_by_name("vllm")
        return find_by_name("vllm") or find_by_name("ollama")

    return find_by_name(fallback) or find_by_name("openai")


def _url_matches_current(explicit_url: str | None, current: LLMConfig) -> bool:
    if explicit_url is None:
        return True
    return explicit_url in {
        url for url in (current.base_url, current.effective_url) if url is not None
    }


def _binding_matches_current(binding: str | None, current: LLMConfig) -> bool:
    if not binding:
        return True
    canonical = canonical_provider_name(binding) or binding
    return canonical in {current.binding, current.provider_name}


def _matching_current_config(
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    api_version: str | None,
    binding: str | None,
) -> LLMConfig | None:
    """Return the active config when explicit call fields came from it.

    Several agent call sites pass model/api_key/base_url/binding explicitly
    after reading ``get_llm_config()``. Treat those fields as a partial
    override, not as a request to drop profile-only settings such as
    extra_headers or reasoning_effort.
    """
    with contextlib.suppress(Exception):
        current = get_llm_config()
        if (
            model == current.model
            and api_key == current.api_key
            and _url_matches_current(base_url, current)
            and (api_version is None or api_version == current.api_version)
            and _binding_matches_current(binding, current)
        ):
            return current
    return None


def _resolve_call_config(
    *,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    api_version: str | None,
    binding: str | None,
    extra_headers: dict[str, str] | None,
    reasoning_effort: str | None,
) -> tuple[LLMConfig, Any]:
    if model and api_key is not None and (base_url is not None or binding is not None):
        current = _matching_current_config(
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            binding=binding,
        )
        merged_headers = dict(current.extra_headers or {}) if current is not None else {}
        if extra_headers:
            merged_headers.update(extra_headers)
        resolved_reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else current.reasoning_effort
            if current is not None
            else None
        )
        provider_spec = _resolve_provider_spec(
            binding=binding,
            model=model,
            api_key=api_key,
            base_url=base_url,
            fallback=binding or "openai",
        )
        provider_name = (
            provider_spec.name
            if provider_spec is not None
            else canonical_provider_name(binding) or binding or "openai"
        )
        provider_mode = provider_spec.mode if provider_spec is not None else "standard"
        config = LLMConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            effective_url=base_url,
            binding=provider_name,
            provider_name=provider_name,
            provider_mode=provider_mode,
            api_version=api_version,
            extra_headers=merged_headers,
            reasoning_effort=resolved_reasoning_effort,
        )
        return config, provider_spec

    current = get_llm_config()
    merged_headers = dict(getattr(current, "extra_headers", None) or {})
    if extra_headers:
        merged_headers.update(extra_headers)

    resolved_model = model or current.model
    resolved_api_key = current.api_key if api_key is None else api_key
    resolved_base_url = base_url if base_url is not None else current.base_url
    resolved_effective_url = base_url if base_url is not None else current.effective_url
    resolved_api_version = api_version if api_version is not None else current.api_version
    binding_hint = binding or current.provider_name or current.binding
    provider_spec = _resolve_provider_spec(
        binding=binding_hint,
        model=resolved_model,
        api_key=resolved_api_key,
        base_url=resolved_effective_url,
        fallback=current.provider_name or current.binding,
    )
    provider_name = provider_spec.name if provider_spec is not None else current.provider_name
    provider_mode = provider_spec.mode if provider_spec is not None else current.provider_mode
    resolved_binding = provider_name or binding_hint or current.binding or "openai"

    config = current.model_copy(
        update={
            "model": resolved_model,
            "api_key": resolved_api_key,
            "base_url": resolved_base_url,
            "effective_url": resolved_effective_url,
            "binding": resolved_binding,
            "provider_name": provider_name or resolved_binding,
            "provider_mode": provider_mode,
            "api_version": resolved_api_version,
            "extra_headers": merged_headers,
            "reasoning_effort": (
                reasoning_effort if reasoning_effort is not None else current.reasoning_effort
            ),
        }
    )
    return config, provider_spec


def _capability_binding(config: LLMConfig, provider_spec: Any) -> str:
    backend = (
        getattr(provider_spec, "backend", "openai_compat") if provider_spec else "openai_compat"
    )
    if backend == "anthropic":
        return "anthropic"
    if backend == "azure_openai":
        return "azure_openai"
    return (
        getattr(provider_spec, "name", None) or config.provider_name or config.binding or "openai"
    )


def _build_messages(
    prompt: str,
    system_prompt: str,
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if messages is not None:
        return messages
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def _coerce_stream_coalesce_chars(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_STREAM_COALESCE_CHARS


def _coerce_stream_coalesce_seconds(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_STREAM_COALESCE_SECONDS


def _apply_inline_image_data(
    messages: list[dict[str, Any]],
    *,
    binding: str,
    model: str,
    image_data: str | None,
    image_mime_type: str = "image/png",
    image_filename: str = "image.png",
) -> list[dict[str, Any]]:
    if not image_data:
        return messages

    attachment = SimpleNamespace(
        type="image",
        base64=image_data,
        filename=image_filename,
        mime_type=image_mime_type,
    )
    result = prepare_multimodal_messages(messages, [attachment], binding=binding, model=model)
    return result.messages


def _sanitize_call_kwargs(
    *,
    binding: str,
    model: str,
    kwargs: dict[str, Any],
) -> CallKwargs:
    extra_kwargs = dict(kwargs)
    for key in (
        "messages",
        "image_data",
        "image_mime_type",
        "image_filename",
        "api_key",
        "base_url",
        "api_version",
        "binding",
        "extra_headers",
        "reasoning_effort",
    ):
        extra_kwargs.pop(key, None)

    if not supports_response_format(binding, model):
        extra_kwargs.pop("response_format", None)
    return extra_kwargs


def _audit_start(audit: Any) -> str | None:
    """Start an audited invocation (persist ``pending`` before the provider call).

    Best-effort: an audit failure is logged and the caller continues with
    legacy provider behaviour — audit must never break an LLM request.
    """
    if audit is None:
        return None
    try:
        from deeptutor.services.model_selection import start_audited_invocation

        return start_audited_invocation(audit)
    except Exception:
        logger.warning(
            "model invocation audit start failed; continuing without audit", exc_info=True
        )
        return None


def _audit_finish_completed(audit: Any, record_id: str | None, response: Any = None) -> None:
    if audit is None or record_id is None:
        return
    reported_model: str | None = None
    usage: dict[str, int] | None = None
    if response is not None:
        reported_model = str(getattr(response, "model", "") or "") or None
        raw_usage = getattr(response, "usage", None)
        if isinstance(raw_usage, dict):
            usage = {
                str(k): int(v or 0)
                for k, v in raw_usage.items()
                if str(k) in {"prompt_tokens", "completion_tokens", "total_tokens"}
            }
    try:
        from deeptutor.learning.models import ModelInvocationStatus
        from deeptutor.services.model_selection import finish_audited_invocation

        finish_audited_invocation(
            audit,
            record_id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model=reported_model,
            usage=usage,
        )
    except Exception:
        logger.warning("model invocation audit finish (completed) failed", exc_info=True)


def _audit_finish_failed(audit: Any, record_id: str | None, exc: BaseException) -> None:
    if audit is None or record_id is None:
        return
    try:
        from deeptutor.learning.models import ModelInvocationStatus
        from deeptutor.services.model_selection import finish_audited_invocation

        finish_audited_invocation(
            audit,
            record_id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error=str(exc),
            error_code=_audit_error_code(exc),
        )
    except Exception:
        logger.warning("model invocation audit finish (failed) failed", exc_info=True)


def _audit_error_code(exc: BaseException) -> str:
    name = type(exc).__name__
    if name.endswith("Error"):
        name = name[: -len("Error")]
    return (name or "unknown").lower()


async def complete(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_version: str | None = None,
    binding: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    exponential_backoff: bool = DEFAULT_EXPONENTIAL_BACKOFF,
    **kwargs: Any,
) -> str:
    audit = kwargs.pop(MODEL_INVOCATION_AUDIT_KWARG, None)
    caller_extra_headers = kwargs.pop("extra_headers", None)
    reasoning_effort = kwargs.pop("reasoning_effort", None)
    image_data = kwargs.pop("image_data", None)
    image_mime_type = kwargs.pop("image_mime_type", "image/png")
    image_filename = kwargs.pop("image_filename", "image.png")

    config, provider_spec = _resolve_call_config(
        model=model,
        api_key=api_key,
        base_url=base_url,
        api_version=api_version,
        binding=binding,
        extra_headers=caller_extra_headers,
        reasoning_effort=reasoning_effort,
    )
    provider = get_runtime_provider(config)
    capability_binding = _capability_binding(config, provider_spec)
    request_messages = _build_messages(prompt, system_prompt, messages)
    request_messages = _apply_inline_image_data(
        request_messages,
        binding=capability_binding,
        model=config.model,
        image_data=image_data,
        image_mime_type=str(image_mime_type or "image/png"),
        image_filename=str(image_filename or "image.png"),
    )
    retry_delays = _build_retry_delays(max_retries, retry_delay, exponential_backoff)
    extra_kwargs = _sanitize_call_kwargs(
        binding=capability_binding, model=config.model, kwargs=kwargs
    )

    record_id = _audit_start(audit)
    try:
        response = await provider.chat_with_retry(
            messages=request_messages,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            retry_delays=retry_delays,
            allow_image_fallback=not supports_vision(capability_binding, config.model),
            **extra_kwargs,
        )
    except Exception as exc:
        _audit_finish_failed(audit, record_id, exc)
        raise map_error(exc, provider=config.provider_name) from exc

    if response.finish_reason == "error":
        _audit_finish_failed(
            audit, record_id, RuntimeError(response.content or "LLM request failed")
        )
        raise map_error(
            RuntimeError(response.content or "LLM request failed"), provider=config.provider_name
        )
    _audit_finish_completed(audit, record_id, response)
    return response.content or ""


async def stream(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_version: str | None = None,
    binding: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    exponential_backoff: bool = DEFAULT_EXPONENTIAL_BACKOFF,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    audit = kwargs.pop(MODEL_INVOCATION_AUDIT_KWARG, None)
    caller_extra_headers = kwargs.pop("extra_headers", None)
    reasoning_effort = kwargs.pop("reasoning_effort", None)
    image_data = kwargs.pop("image_data", None)
    image_mime_type = kwargs.pop("image_mime_type", "image/png")
    image_filename = kwargs.pop("image_filename", "image.png")
    stream_coalesce_chars = _coerce_stream_coalesce_chars(
        kwargs.pop("stream_coalesce_chars", DEFAULT_STREAM_COALESCE_CHARS)
    )
    stream_coalesce_seconds = _coerce_stream_coalesce_seconds(
        kwargs.pop("stream_coalesce_seconds", DEFAULT_STREAM_COALESCE_SECONDS)
    )

    config, provider_spec = _resolve_call_config(
        model=model,
        api_key=api_key,
        base_url=base_url,
        api_version=api_version,
        binding=binding,
        extra_headers=caller_extra_headers,
        reasoning_effort=reasoning_effort,
    )
    provider = get_runtime_provider(config)
    capability_binding = _capability_binding(config, provider_spec)
    request_messages = _build_messages(prompt, system_prompt, messages)
    request_messages = _apply_inline_image_data(
        request_messages,
        binding=capability_binding,
        model=config.model,
        image_data=image_data,
        image_mime_type=str(image_mime_type or "image/png"),
        image_filename=str(image_filename or "image.png"),
    )
    retry_delays = _build_retry_delays(max_retries, retry_delay, exponential_backoff)
    extra_kwargs = _sanitize_call_kwargs(
        binding=capability_binding, model=config.model, kwargs=kwargs
    )

    # Persist-before-call: the ``pending`` audit record is saved here, before
    # the runner task starts the provider request.
    record_id = _audit_start(audit)

    queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()
    saw_output = False
    saw_content = False
    in_think_block = False

    async def _on_reasoning_delta(chunk: str) -> None:
        nonlocal saw_output, in_think_block
        if not chunk:
            return
        saw_output = True
        if not in_think_block:
            in_think_block = True
            await queue.put("<think>")
        await queue.put(chunk)

    async def _on_content_delta(chunk: str) -> None:
        nonlocal saw_output, saw_content, in_think_block
        if not chunk:
            return
        saw_output = True
        saw_content = True
        if in_think_block:
            in_think_block = False
            await queue.put("</think>")
        await queue.put(chunk)

    async def _runner() -> None:
        nonlocal in_think_block
        try:
            response = await provider.chat_stream_with_retry(
                messages=request_messages,
                model=config.model,
                reasoning_effort=config.reasoning_effort,
                on_content_delta=_on_content_delta,
                on_reasoning_delta=_on_reasoning_delta,
                retry_delays=retry_delays,
                allow_image_fallback=not supports_vision(capability_binding, config.model),
                **extra_kwargs,
            )
            if in_think_block:
                in_think_block = False
                await queue.put("</think>")
            # Some providers synthesize a final response only after the stream.
            # Do not replay reasoning_content as user-visible answer text.
            if (
                not saw_content
                and response.content
                and response.content != response.reasoning_content
            ):
                saw_output = True
                await queue.put(response.content)
            if response.finish_reason == "error" and not saw_output:
                await queue.put(
                    map_error(
                        RuntimeError(response.content or "LLM request failed"),
                        provider=config.provider_name,
                    )
                )
        except Exception as exc:
            await queue.put(map_error(exc, provider=config.provider_name))
        finally:
            await queue.put(None)

    task = asyncio.create_task(_runner())
    finalized = record_id is None
    try:
        sent_first_text_chunk = False
        buffered_chunks: list[str] = []
        buffered_chars = 0

        def _flush_buffer() -> str:
            nonlocal buffered_chars
            text = "".join(buffered_chunks)
            buffered_chunks.clear()
            buffered_chars = 0
            return text

        async def _queue_get(timeout: float | None = None) -> str | BaseException | None:
            if timeout is None:
                return await queue.get()
            return await asyncio.wait_for(queue.get(), timeout=timeout)

        stream_finished = False
        while True:
            item = await queue.get()
            if item is None:
                if buffered_chunks:
                    yield _flush_buffer()
                break
            if isinstance(item, BaseException):
                if buffered_chunks:
                    yield _flush_buffer()
                raise item
            if item in STREAM_CONTROL_TOKENS or stream_coalesce_seconds <= 0:
                if buffered_chunks:
                    yield _flush_buffer()
                yield item
                continue
            if not sent_first_text_chunk:
                sent_first_text_chunk = True
                yield item
                continue
            buffered_chunks.append(item)
            buffered_chars += len(item)
            deadline = asyncio.get_running_loop().time() + stream_coalesce_seconds
            while buffered_chunks and buffered_chars < stream_coalesce_chars:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    next_item = await _queue_get(timeout)
                except asyncio.TimeoutError:
                    break
                if next_item is None:
                    if buffered_chunks:
                        yield _flush_buffer()
                    await task
                    stream_finished = True
                    break
                if isinstance(next_item, BaseException):
                    if buffered_chunks:
                        yield _flush_buffer()
                    raise next_item
                if next_item in STREAM_CONTROL_TOKENS:
                    if buffered_chunks:
                        yield _flush_buffer()
                    yield next_item
                    break
                buffered_chunks.append(next_item)
                buffered_chars += len(next_item)
            if stream_finished:
                break
            if buffered_chunks:
                yield _flush_buffer()
        await task
        if not finalized:
            _audit_finish_completed(audit, record_id)
            finalized = True
    except BaseException as exc:
        if not finalized:
            _audit_finish_failed(audit, record_id, exc)
            finalized = True
        raise
    finally:
        if not finalized:
            _audit_finish_failed(
                audit,
                record_id,
                RuntimeError("stream closed before completion"),
            )
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def fetch_models(
    binding: str,
    base_url: str,
    api_key: str | None = None,
) -> list[str]:
    if is_local_llm_server(base_url):
        from . import local_provider

        return await local_provider.fetch_models(base_url, api_key)

    from . import cloud_provider

    return await cloud_provider.fetch_models(base_url, api_key, binding)


def _build_api_provider_presets() -> dict[str, ApiProviderPreset]:
    presets: dict[str, ApiProviderPreset] = {}
    for spec in PROVIDERS:
        if spec.is_local:
            continue
        presets[spec.name] = {
            "name": spec.label,
            "base_url": spec.default_api_base,
            "requires_key": not spec.is_oauth,
            "models": [],
            "binding": spec.name,
        }
    return presets


def _build_local_provider_presets() -> dict[str, LocalProviderPreset]:
    presets: dict[str, LocalProviderPreset] = {}
    for spec in PROVIDERS:
        if not spec.is_local:
            continue
        presets[spec.name] = {
            "name": spec.label,
            "base_url": spec.default_api_base,
            "requires_key": False,
            "default_key": "sk-no-key-required",
            "binding": spec.name,
        }
    return presets


API_PROVIDER_PRESETS: dict[str, ApiProviderPreset] = _build_api_provider_presets()
LOCAL_PROVIDER_PRESETS: dict[str, LocalProviderPreset] = _build_local_provider_presets()


def get_provider_presets() -> ProviderPresetBundle:
    return {
        "api": API_PROVIDER_PRESETS,
        "local": LOCAL_PROVIDER_PRESETS,
    }


__all__ = [
    "complete",
    "stream",
    "fetch_models",
    "get_provider_presets",
    "API_PROVIDER_PRESETS",
    "LOCAL_PROVIDER_PRESETS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_EXPONENTIAL_BACKOFF",
    "LLMFactory",
]


class LLMFactory:
    """Compatibility factory for legacy integrations."""

    @staticmethod
    def get_provider(config: LLMConfig):
        return get_runtime_provider(config)
