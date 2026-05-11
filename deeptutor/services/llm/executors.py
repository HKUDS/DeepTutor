"""Provider-backed LLM executors (openai + anthropic SDKs, no litellm)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import logging
import os
from typing import Any
import uuid

from openai import AsyncOpenAI, BadRequestError

from deeptutor.services.llm.capabilities import disable_response_format_at_runtime
from deeptutor.services.llm.openai_http_client import openai_client_kwargs
from deeptutor.services.llm.provider_registry import find_by_name, strip_provider_prefix

from .config import get_token_limit_kwargs
from .utils import extract_response_content

logger = logging.getLogger(__name__)


def _is_unsupported_response_format_error(exc: BaseException) -> bool:
    """Detect whether a BadRequestError stems from an unsupported ``response_format``.

    Examples seen in the wild:
    - LM Studio + Gemma: ``"'response_format.type' must be 'json_schema' or 'text'"``
    - DashScope + various models: ``"'response_format.type' specified ... not valid: 'json_object' is not supported by this model"``
    """
    text = str(exc).lower()
    if "response_format" not in text and "response format" not in text:
        return False
    return (
        "json_object" in text
        or "json_schema" in text
        or "not supported" in text
        or "not valid" in text
        or "must be" in text
    )


async def _create_with_format_fallback(
    client: AsyncOpenAI,
    payload: dict[str, Any],
    *,
    binding: str,
    model: str,
) -> Any:
    """Run ``client.chat.completions.create`` with auto-fallback on response_format errors.

    Some local servers (LM Studio + Gemma/Qwen) reject ``response_format``
    with HTTP 400. On a matching :class:`BadRequestError`, drop the offending
    field and retry once, then cache the (binding, model) pair so future calls
    skip ``response_format`` upfront.
    """
    try:
        return await client.chat.completions.create(**payload)
    except BadRequestError as exc:
        if "response_format" not in payload or not _is_unsupported_response_format_error(exc):
            raise
        logger.warning(
            f"Provider {binding} rejected response_format for model {model} ({exc}); "
            "retrying without it and disabling response_format for this binding+model."
        )
        disable_response_format_at_runtime(binding, model)
        retry_payload = dict(payload)
        retry_payload.pop("response_format", None)
        return await client.chat.completions.create(**retry_payload)


def _build_messages(
    *,
    prompt: str,
    system_prompt: str,
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if messages:
        return messages
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def _setup_provider_env(provider_name: str, api_key: str | None, api_base: str | None) -> None:
    spec = find_by_name(provider_name)
    if not spec or not api_key:
        return
    if spec.env_key:
        os.environ.setdefault(spec.env_key, api_key)
    effective_base = api_base or spec.default_api_base
    for env_name, env_val in spec.env_extras:
        resolved = env_val.replace("{api_key}", api_key).replace("{api_base}", effective_base or "")
        os.environ.setdefault(env_name, resolved)


def _resolve_model_and_base(
    provider_name: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
) -> tuple[str, str | None, str | None]:
    """Resolve the actual model name, base_url, and api_key for the provider.

    Returns (resolved_model, effective_base_url, effective_api_key).
    """
    spec = find_by_name(provider_name)
    resolved_model = strip_provider_prefix(model, spec) if spec else model
    effective_base = base_url or (spec.default_api_base if spec else None) or None
    effective_key = api_key
    return resolved_model, effective_base, effective_key


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def sdk_complete(
    *,
    prompt: str,
    system_prompt: str,
    provider_name: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    messages: list[dict[str, Any]] | None = None,
    api_version: str | None = None,
    extra_headers: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
    **kwargs: Any,
) -> str:
    """Non-streaming completion using the openai SDK."""
    _setup_provider_env(provider_name, api_key, base_url)
    resolved_model, effective_base, effective_key = _resolve_model_and_base(
        provider_name,
        model,
        api_key,
        base_url,
    )

    default_headers: dict[str, str] = {"x-session-affinity": uuid.uuid4().hex}
    if extra_headers:
        default_headers.update(extra_headers)

    client = AsyncOpenAI(
        api_key=effective_key or "no-key",
        base_url=effective_base,
        default_headers=default_headers,
        max_retries=0,
        **openai_client_kwargs(),
    )

    max_tokens_val = _coerce_int(kwargs.pop("max_tokens", 4096), 4096)
    temperature_val = _coerce_float(kwargs.pop("temperature", 0.7), 0.7)

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": _build_messages(
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
        ),
        "temperature": temperature_val,
    }

    token_kwargs = get_token_limit_kwargs(resolved_model, max_tokens_val)
    payload.update(token_kwargs)

    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    payload.update(kwargs)

    response = await _create_with_format_fallback(
        client, payload, binding=provider_name or "openai", model=resolved_model
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None and isinstance(choices[0], dict):
        message = choices[0].get("message")
    return extract_response_content(message)


async def sdk_stream(
    *,
    prompt: str,
    system_prompt: str,
    provider_name: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    messages: list[dict[str, Any]] | None = None,
    api_version: str | None = None,
    extra_headers: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """Streaming completion using the openai SDK."""
    _setup_provider_env(provider_name, api_key, base_url)
    resolved_model, effective_base, effective_key = _resolve_model_and_base(
        provider_name,
        model,
        api_key,
        base_url,
    )

    default_headers: dict[str, str] = {"x-session-affinity": uuid.uuid4().hex}
    if extra_headers:
        default_headers.update(extra_headers)

    client = AsyncOpenAI(
        api_key=effective_key or "no-key",
        base_url=effective_base,
        default_headers=default_headers,
        max_retries=0,
        **openai_client_kwargs(),
    )

    max_tokens_val = _coerce_int(kwargs.pop("max_tokens", 4096), 4096)
    temperature_val = _coerce_float(kwargs.pop("temperature", 0.7), 0.7)

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": _build_messages(
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
        ),
        "temperature": temperature_val,
        "stream": True,
    }

    token_kwargs = get_token_limit_kwargs(resolved_model, max_tokens_val)
    payload.update(token_kwargs)

    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    payload.update(kwargs)

    stream_response = await _create_with_format_fallback(
        client, payload, binding=provider_name or "openai", model=resolved_model
    )
    async for chunk in stream_response:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta is None and isinstance(choice, dict):
            delta = choice.get("delta")
        if delta is None:
            continue
        raw_content = (
            getattr(delta, "content", None) if not isinstance(delta, dict) else delta.get("content")
        )
        if raw_content is None:
            continue
        content = extract_response_content(delta)
        if content:
            yield content
