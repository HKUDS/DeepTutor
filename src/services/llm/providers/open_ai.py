"""OpenAI provider implementation using shared HTTP client."""

from __future__ import annotations

from collections.abc import AsyncIterator
import os
from typing import Callable, Protocol, TypeVar, cast

import httpx
import openai

from src.logging import get_logger

from ..config import LLMConfig, get_token_limit_kwargs
from ..exceptions import LLMConfigError
from ..registry import register_provider
from ..telemetry import track_llm_call
from ..types import AsyncStreamGenerator, TutorResponse, TutorStreamChunk
from .base_provider import BaseLLMProvider

logger = get_logger(__name__)
F = TypeVar("F", bound=Callable[..., object])


class OpenAIChoiceDelta(Protocol):
    """Protocol for OpenAI delta payloads."""

    content: str | None


class OpenAIChoice(Protocol):
    """Protocol for OpenAI choices in streaming responses."""

    delta: OpenAIChoiceDelta


class OpenAIChunk(Protocol):
    """Protocol for OpenAI streaming chunks."""

    choices: list[OpenAIChoice]


class OpenAIStream(Protocol):
    """Protocol for OpenAI streaming responses."""

    def __aiter__(self) -> AsyncIterator[OpenAIChunk]: ...


def _typed_track_llm_call(provider: str) -> Callable[[F], F]:
    return cast(Callable[[F], F], track_llm_call(provider))


@register_provider("openai")
class OpenAIProvider(BaseLLMProvider):
    """Production-ready OpenAI Provider with shared HTTP client."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        http_client = None
        if os.getenv("DISABLE_SSL_VERIFY", "").lower() in ("true", "1", "yes"):
            if os.getenv("ENVIRONMENT", "").lower() in ("prod", "production"):
                raise LLMConfigError("DISABLE_SSL_VERIFY is not allowed in production")
            logger.warning("SSL verification disabled for OpenAI HTTP client")
            http_client = httpx.AsyncClient(verify=False)  # nosec B501
        self.client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            http_client=http_client,
        )

    @_typed_track_llm_call("openai")
    async def complete(self, prompt: str, **kwargs: object) -> TutorResponse:
        model_raw = kwargs.pop("model", None)
        model = model_raw if isinstance(model_raw, str) and model_raw else self.config.model
        if not model:
            raise LLMConfigError("Model not configured for OpenAI provider")
        kwargs.pop("stream", None)

        requested_max_tokens = (
            kwargs.pop("max_tokens", None)
            or kwargs.pop("max_completion_tokens", None)
            or getattr(self.config, "max_tokens", 4096)
        )
        if isinstance(requested_max_tokens, (int, float, str)):
            max_tokens = int(requested_max_tokens)
        else:
            max_tokens = int(getattr(self.config, "max_tokens", 4096))
        kwargs.update(get_token_limit_kwargs(model, max_tokens))

        async def _call_api() -> TutorResponse:
            request_kwargs: dict[str, object] = dict(kwargs)
            response = await self.client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **request_kwargs,
            )

            if not response.choices:
                raise ValueError("API returned no choices in response")
            choice = response.choices[0]
            message = choice.message
            content = message.content or ""
            finish_reason = choice.finish_reason
            usage = response.usage.model_dump() if response.usage else {}
            raw_response = response.model_dump() if hasattr(response, "model_dump") else {}
            provider_label = (
                "azure" if isinstance(self.client, openai.AsyncAzureOpenAI) else "openai"
            )

            return TutorResponse(
                content=content,
                raw_response=raw_response,
                usage=usage,
                provider=provider_label,
                model=model,
                finish_reason=finish_reason,
                cost_estimate=self.calculate_cost(usage),
            )

        return await self.execute_with_retry(_call_api)

    def stream(self, prompt: str, **kwargs: object) -> AsyncStreamGenerator:
        model_raw = kwargs.pop("model", None)
        model = model_raw if isinstance(model_raw, str) and model_raw else self.config.model
        if not model:
            raise LLMConfigError("Model not configured for OpenAI provider")

        async def _create_stream() -> OpenAIStream:
            request_kwargs: dict[str, object] = dict(kwargs)
            return cast(
                OpenAIStream,
                await self.client.chat.completions.create(  # type: ignore[call-overload]
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                    **request_kwargs,
                ),
            )

        async def _stream() -> AsyncStreamGenerator:
            stream = cast(OpenAIStream, await self.execute_with_retry(_create_stream))
            accumulated_content = ""
            provider_label = (
                "azure" if isinstance(self.client, openai.AsyncAzureOpenAI) else "openai"
            )

            try:
                async for chunk in stream:
                    delta = ""
                    if chunk.choices and chunk.choices[0].delta.content:
                        delta = chunk.choices[0].delta.content
                        accumulated_content += delta
                        yield TutorStreamChunk(
                            content=accumulated_content,
                            delta=delta,
                            provider=provider_label,
                            model=model,
                            is_complete=False,
                        )
            finally:
                yield TutorStreamChunk(
                    content=accumulated_content,
                    delta="",
                    provider=provider_label,
                    model=model,
                    is_complete=True,
                )

        return _stream()
