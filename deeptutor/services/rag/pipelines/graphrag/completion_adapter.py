"""GraphRAG completion adapter with a strict JSON-object compatibility fallback."""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from deeptutor.services.rag.pipelines.oauth_completion import (
    OAUTH_PROVIDER,
    OAuthCompletion,
    oauth_binding,
)

from .errors import (
    MODEL_INCOMPATIBLE_MESSAGE,
    MODEL_OUTPUT_TRUNCATED_MESSAGE,
    GraphRagStructuredOutputError,
    GraphRagStructuredOutputTruncatedError,
    is_unsupported_schema_error,
)
from .provider import COMPLETION_TYPE

_CAPABILITY_LOCK = threading.RLock()
_JSON_OBJECT_CAPABILITIES: set[tuple[str, str, str]] = set()
_ADAPTER_CLASSES: tuple[type, type] | None = None


def _capability_key(model_config: Any) -> tuple[str, str, str]:
    return (
        str(getattr(model_config, "model_provider", "") or "").lower(),
        str(getattr(model_config, "model", "") or "").lower(),
        str(getattr(model_config, "api_base", "") or "").rstrip("/").lower(),
    )


def _uses_json_object(model_config: Any) -> bool:
    with _CAPABILITY_LOCK:
        return _capability_key(model_config) in _JSON_OBJECT_CAPABILITIES


def _remember_json_object(model_config: Any) -> None:
    with _CAPABILITY_LOCK:
        _JSON_OBJECT_CAPABILITIES.add(_capability_key(model_config))


def _uses_prompt_only_structured_output(model_config: Any) -> bool:
    """Use the common messages contract for third-party Anthropic-compatible APIs.

    LiteLLM implements Pydantic response formats on the Anthropic transport with
    a forced synthetic tool. Third-party endpoints may implement Anthropic's
    messages API without matching those tool semantics. A schema instruction
    plus local Pydantic validation keeps the GraphRAG contract strict while
    avoiding assumptions beyond the configured endpoint's base protocol.
    """
    provider = str(getattr(model_config, "model_provider", "") or "").lower()
    if provider == OAUTH_PROVIDER:
        return True
    if provider != "anthropic":
        return False

    api_base = str(getattr(model_config, "api_base", "") or "").strip()
    if not api_base:
        return False
    parsed = urlparse(api_base if "://" in api_base else f"https://{api_base}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname != "api.anthropic.com" and not hostname.endswith(".anthropic.com")


def clear_capability_cache() -> None:
    """Clear process-local compatibility discoveries; intended for deterministic tests."""
    with _CAPABILITY_LOCK:
        _JSON_OBJECT_CAPABILITIES.clear()


def _is_schema_model(response_format: Any) -> bool:
    return isinstance(response_format, type) and issubclass(response_format, BaseModel)


def _schema_instruction(response_format: type[BaseModel]) -> str:
    schema = json.dumps(
        response_format.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "Return only one valid JSON object. Do not use Markdown fences or explanatory text. "
        f"The JSON object must match this JSON schema exactly: {schema}"
    )


def _messages_with_schema(messages: Any, response_format: type[BaseModel]) -> Any:
    instruction = _schema_instruction(response_format)
    if isinstance(messages, str):
        return f"{messages}\n\n{instruction}"
    if not isinstance(messages, list):
        return messages

    copied = list(messages)
    for index in range(len(copied) - 1, -1, -1):
        message = copied[index]
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            copied[index] = {**message, "content": f"{content}\n\n{instruction}"}
            return copied
    copied.append({"role": "user", "content": instruction})
    return copied


def _format_fallback_kwargs(kwargs: dict[str, Any], response_format: type[BaseModel]) -> dict:
    fallback = dict(kwargs)
    fallback["messages"] = _messages_with_schema(fallback["messages"], response_format)
    fallback.pop("response_format", None)
    return fallback


def _format_response(response: Any, response_format: type[BaseModel]) -> Any:
    from graphrag_llm.utils import structure_completion_response

    try:
        response.formatted_response = structure_completion_response(
            response.content,
            response_format,
        )
    except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as error:
        choices = getattr(response, "choices", None)
        finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
        if finish_reason in {"length", "max_tokens"}:
            raise GraphRagStructuredOutputTruncatedError(MODEL_OUTPUT_TRUNCATED_MESSAGE) from error
        raise GraphRagStructuredOutputError(MODEL_INCOMPATIBLE_MESSAGE) from error
    return response


def _native_validation_error(error: BaseException) -> bool:
    return isinstance(error, (json.JSONDecodeError, ValidationError))


def _fallback_sync(instance: Any, kwargs: dict[str, Any], response_format: type[BaseModel]) -> Any:
    fallback = _format_fallback_kwargs(kwargs, response_format)
    if fallback.get("stream"):
        raise ValueError("response_format is not supported for streaming completions.")
    messages = fallback.pop("messages")
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    request_metrics = fallback.pop("metrics", None) or {}
    if not instance._track_metrics:
        request_metrics = None
    try:
        response = instance._completion(
            messages=messages,
            metrics=request_metrics,
            response_format_json_object=not _uses_prompt_only_structured_output(
                instance._model_config
            ),
            **fallback,
        )
        return _format_response(response, response_format)
    finally:
        if request_metrics is not None:
            instance._metrics_store.update_metrics(metrics=request_metrics)


async def _fallback_async(
    instance: Any,
    kwargs: dict[str, Any],
    response_format: type[BaseModel],
) -> Any:
    fallback = _format_fallback_kwargs(kwargs, response_format)
    if fallback.get("stream"):
        raise ValueError("response_format is not supported for streaming completions.")
    messages = fallback.pop("messages")
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    request_metrics = fallback.pop("metrics", None) or {}
    if not instance._track_metrics:
        request_metrics = None
    try:
        response = await instance._completion_async(
            messages=messages,
            metrics=request_metrics,
            response_format_json_object=not _uses_prompt_only_structured_output(
                instance._model_config
            ),
            **fallback,
        )
        return _format_response(response, response_format)
    finally:
        if request_metrics is not None:
            instance._metrics_store.update_metrics(metrics=request_metrics)


def _get_adapter_classes() -> tuple[type, type]:
    global _ADAPTER_CLASSES
    with _CAPABILITY_LOCK:
        if _ADAPTER_CLASSES is not None:
            return _ADAPTER_CLASSES

        from graphrag_llm.completion.lite_llm_completion import LiteLLMCompletion

        class DeepTutorLiteLLMCompletion(LiteLLMCompletion):
            """LiteLLM completion with a narrow GraphRAG structured-output fallback."""

            def completion(self, /, **kwargs: Any) -> Any:
                response_format = kwargs.get("response_format")
                if not _is_schema_model(response_format):
                    return super().completion(**kwargs)
                if _uses_prompt_only_structured_output(self._model_config):
                    return _fallback_sync(self, kwargs, response_format)
                if _uses_json_object(self._model_config):
                    return _fallback_sync(self, kwargs, response_format)
                try:
                    return super().completion(**kwargs)
                except Exception as error:
                    explicit_unsupported = is_unsupported_schema_error(error)
                    if not explicit_unsupported and not _native_validation_error(error):
                        raise
                    formatted = _fallback_sync(self, kwargs, response_format)
                    if explicit_unsupported:
                        _remember_json_object(self._model_config)
                    return formatted

            async def completion_async(self, /, **kwargs: Any) -> Any:
                response_format = kwargs.get("response_format")
                if not _is_schema_model(response_format):
                    return await super().completion_async(**kwargs)
                if _uses_prompt_only_structured_output(self._model_config):
                    return await _fallback_async(self, kwargs, response_format)
                if _uses_json_object(self._model_config):
                    return await _fallback_async(self, kwargs, response_format)
                try:
                    return await super().completion_async(**kwargs)
                except Exception as error:
                    explicit_unsupported = is_unsupported_schema_error(error)
                    if not explicit_unsupported and not _native_validation_error(error):
                        raise
                    formatted = await _fallback_async(self, kwargs, response_format)
                    if explicit_unsupported:
                        _remember_json_object(self._model_config)
                    return formatted

        class DeepTutorOAuthCompletion(DeepTutorLiteLLMCompletion):
            """Bind an indexing or query operation to its DeepTutor credential owner."""

            def __init__(self, *, model_config: Any, **kwargs: Any) -> None:
                from deeptutor.services.llm.config import LLMConfig

                binding = str(getattr(model_config, "oauth_binding", ""))
                config = LLMConfig(
                    model=model_config.model,
                    api_key="",
                    binding=binding,
                    provider_name=binding,
                    provider_mode="oauth",
                    reasoning_effort=getattr(model_config, "oauth_reasoning_effort", None),
                )
                if model_config.model_provider != OAUTH_PROVIDER or not oauth_binding(config):
                    raise ValueError("GraphRAG OAuth settings require a DeepTutor OAuth binding.")
                self._oauth_completion = OAuthCompletion.for_current_user(config)
                super().__init__(model_config=model_config, **kwargs)

            def completion(self, /, **kwargs: Any) -> Any:
                with self._oauth_completion.activate():
                    return super().completion(**kwargs)

            async def completion_async(self, /, **kwargs: Any) -> Any:
                with self._oauth_completion.activate():
                    return await super().completion_async(**kwargs)

        _ADAPTER_CLASSES = DeepTutorLiteLLMCompletion, DeepTutorOAuthCompletion
        return _ADAPTER_CLASSES


def register_completion_adapter() -> None:
    """Register DeepTutor's completion type through GraphRAG's public factory API."""
    from graphrag_llm.completion import register_completion

    initializer, oauth_initializer = _get_adapter_classes()
    register_completion(COMPLETION_TYPE, initializer, scope="singleton")
    # GraphRAG's singleton cache is process-wide. Never share an OAuth
    # completion instance across account contexts.
    register_completion(OAUTH_PROVIDER, oauth_initializer, scope="transient")


__all__ = ["clear_capability_cache", "register_completion_adapter"]
