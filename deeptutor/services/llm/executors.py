"""Provider-backed LLM executors (LiteLLM + direct OpenAI/Azure)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import os
from typing import Any

from deeptutor.logging import get_logger
from deeptutor.services.llm.provider_registry import find_by_name, normalize_model_for_litellm

from .config import get_token_limit_kwargs
from .utils import extract_response_content

logger = get_logger("LLMExecutors")


def _build_messages(
    *,
    prompt: str,
    system_prompt: str,
    messages: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    if messages:
        return messages
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def _setup_litellm_env(provider_name: str, api_key: str | None, api_base: str | None) -> None:
    spec = find_by_name(provider_name)
    if not spec or not api_key:
        return
    if spec.env_key:
        os.environ.setdefault(spec.env_key, api_key)
    effective_base = api_base or spec.default_api_base
    for env_name, env_val in spec.env_extras:
        resolved = env_val.replace("{api_key}", api_key).replace("{api_base}", effective_base or "")
        os.environ.setdefault(env_name, resolved)


def litellm_available() -> bool:
    try:
        import litellm  # noqa: F401
    except Exception:
        return False
    return True


async def litellm_complete(
    *,
    prompt: str,
    system_prompt: str,
    provider_name: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    messages: list[dict[str, object]] | None = None,
    api_version: str | None = None,
    extra_headers: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
    **kwargs: object,
) -> str:
    from litellm import acompletion

    _setup_litellm_env(provider_name, api_key, base_url)
    spec = find_by_name(provider_name)
    resolved_model = normalize_model_for_litellm(model, spec)
    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": _build_messages(
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
        ),
        "max_tokens": int(kwargs.pop("max_tokens", 4096)),
        "temperature": float(kwargs.pop("temperature", 0.7)),
        "drop_params": True,
    }
    payload.update(get_token_limit_kwargs(model, int(payload["max_tokens"])))
    if api_key:
        payload["api_key"] = api_key
    if base_url:
        payload["api_base"] = base_url
    if api_version:
        payload["api_version"] = api_version
    if extra_headers:
        payload["extra_headers"] = extra_headers
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    payload.update(kwargs)

    response = await acompletion(**payload)
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None and isinstance(choices[0], dict):
        message = choices[0].get("message")
    return extract_response_content(message)


async def litellm_stream(
    *,
    prompt: str,
    system_prompt: str,
    provider_name: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    messages: list[dict[str, object]] | None = None,
    api_version: str | None = None,
    extra_headers: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
    **kwargs: object,
) -> AsyncGenerator[str, None]:
    from litellm import acompletion

    _setup_litellm_env(provider_name, api_key, base_url)
    spec = find_by_name(provider_name)
    resolved_model = normalize_model_for_litellm(model, spec)
    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": _build_messages(
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
        ),
        "max_tokens": int(kwargs.pop("max_tokens", 4096)),
        "temperature": float(kwargs.pop("temperature", 0.7)),
        "drop_params": True,
        "stream": True,
    }
    payload.update(get_token_limit_kwargs(model, int(payload["max_tokens"])))
    if api_key:
        payload["api_key"] = api_key
    if base_url:
        payload["api_base"] = base_url
    if api_version:
        payload["api_version"] = api_version
    if extra_headers:
        payload["extra_headers"] = extra_headers
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    payload.update(kwargs)

    stream_response = await acompletion(**payload)
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
        # Skip stop-chunks where content is explicitly None (avoids
        # extract_response_content converting the delta repr to string).
        raw_content = getattr(delta, "content", None) if not isinstance(delta, dict) else delta.get("content")
        if raw_content is None:
            continue
        content = extract_response_content(delta)
        if content:
            yield content

