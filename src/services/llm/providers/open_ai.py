# -*- coding: utf-8 -*-
import os

import httpx
import openai

from ..registry import register_provider
from ..telemetry import track_llm_call
from ..types import AsyncStreamGenerator, TutorResponse, TutorStreamChunk
from .base_provider import BaseLLMProvider


@register_provider("openai")
class OpenAIProvider(BaseLLMProvider):
    """Production-ready OpenAI Provider."""

    def __init__(self, config):
        super().__init__(config)

        # SSL handling for dev/troubleshooting
        http_client = None
        if os.getenv("DISABLE_SSL_VERIFY", "").lower() in ("true", "1", "yes"):
            http_client = httpx.AsyncClient(verify=False)

        self.client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            http_client=http_client,
        )

    @track_llm_call("openai")
    async def complete(self, prompt: str, **kwargs) -> TutorResponse:
        model = kwargs.pop("model", None) or self.config.model_name or "gpt-4o"
        kwargs.pop("stream", None)

        async def _call_api():
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )

            choice = response.choices[0]
            usage = response.usage.model_dump() if response.usage else {}

            return TutorResponse(
                content=choice.message.content or "",
                raw_response=response.model_dump(),
                usage=usage,
                provider="openai",
                model=model,
                finish_reason=choice.finish_reason,
                cost_estimate=self.calculate_cost(usage),
            )

        return await self.execute_with_retry(_call_api)

    async def stream(self, prompt: str, **kwargs) -> AsyncStreamGenerator:  # type: ignore[override]
        model = kwargs.pop("model", None) or self.config.model_name or "gpt-4o"

        async def _create_stream():
            return await self.client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], stream=True, **kwargs
            )

        stream = await self.execute_with_retry(_create_stream)
        accumulated_content = ""

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                accumulated_content += delta

                yield TutorStreamChunk(
                    content=accumulated_content,
                    delta=delta,
                    provider="openai",
                    model=model,
                    is_complete=False,
                )

        yield TutorStreamChunk(
            content=accumulated_content, delta="", provider="openai", model=model, is_complete=True
        )
