# -*- coding: utf-8 -*-
import anthropic

from ..registry import register_provider
from ..telemetry import track_llm_call
from ..types import AsyncStreamGenerator, TutorResponse, TutorStreamChunk
from .base_provider import BaseLLMProvider


@register_provider("anthropic")
class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude Provider."""

    def __init__(self, config):
        super().__init__(config)

        self.client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
        )

    @track_llm_call("anthropic")
    async def complete(self, prompt: str, **kwargs) -> TutorResponse:
        model = kwargs.pop("model", None) or self.config.model_name or "claude-3-sonnet-20240229"
        kwargs.pop("stream", None)

        async def _call_api():
            response = await self.client.messages.create(
                model=model,
                max_tokens=kwargs.pop("max_tokens", 1024),
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )

            content = response.content[0].text if response.content else ""
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

            return TutorResponse(
                content=content,
                raw_response=response.model_dump(),
                usage=usage,
                provider="anthropic",
                model=model,
                finish_reason=response.stop_reason,
                cost_estimate=self.calculate_cost(usage),
            )

        return await self.execute_with_retry(_call_api)

    @track_llm_call("anthropic")
    async def stream(self, prompt: str, **kwargs) -> AsyncStreamGenerator:
        model = kwargs.pop("model", None) or self.config.model_name or "claude-3-sonnet-20240229"
        max_tokens = kwargs.pop("max_tokens", 1024)

        async def _create_stream():
            return await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **kwargs,
            )

        stream = await self.execute_with_retry(_create_stream)
        accumulated_content = ""
        usage = None

        async for chunk in stream:
            if chunk.type == "content_block_delta" and chunk.delta.text:
                delta = chunk.delta.text
                accumulated_content += delta

                yield TutorStreamChunk(
                    content=accumulated_content,
                    delta=delta,
                    provider="anthropic",
                    model=model,
                    is_complete=False,
                )
            elif chunk.type == "message_delta" and hasattr(chunk, "usage"):
                # Extract usage from the final message delta
                usage = {
                    "input_tokens": chunk.usage.input_tokens,
                    "output_tokens": chunk.usage.output_tokens,
                }

        yield TutorStreamChunk(
            content=accumulated_content,
            delta="",
            provider="anthropic",
            model=model,
            is_complete=True,
            usage=usage,
        )
