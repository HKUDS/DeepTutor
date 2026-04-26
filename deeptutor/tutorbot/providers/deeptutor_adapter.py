"""LLM provider adapter that reuses DeepTutor's LLM configuration.

When TutorBot runs in-process inside the DeepTutor server, this provider
reads api_key / model / base_url from DeepTutor's unified config and
delegates to the appropriate provider (OpenAICompat or Anthropic).
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.llm.provider_core.base import (
    LLMProvider as CoreLLMProvider,
)
from deeptutor.services.llm.provider_core.base import (
    LLMResponse as CoreLLMResponse,
)
from deeptutor.tutorbot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)


class DeepTutorProviderAdapter(LLMProvider):
    """Adapt DeepTutor's unified provider to TutorBot's provider protocol."""

    def __init__(self, provider: CoreLLMProvider):
        super().__init__(api_key=provider.api_key, api_base=provider.api_base)
        self._provider = provider
        self.generation = GenerationSettings(
            temperature=provider.generation.temperature,
            max_tokens=provider.generation.max_tokens,
            reasoning_effort=provider.generation.reasoning_effort,
        )

    @staticmethod
    def _convert_response(response: CoreLLMResponse) -> LLMResponse:
        return LLMResponse(
            content=response.content,
            tool_calls=[
                ToolCallRequest(
                    id=tool_call.id,
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                    provider_specific_fields=tool_call.provider_specific_fields,
                    function_provider_specific_fields=(tool_call.function_provider_specific_fields),
                )
                for tool_call in response.tool_calls
            ],
            finish_reason=response.finish_reason,
            usage=response.usage,
            reasoning_content=response.reasoning_content,
            thinking_blocks=response.thinking_blocks,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        response = await self._provider.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )
        return self._convert_response(response)

    def get_default_model(self) -> str:
        return self._provider.get_default_model()


def create_deeptutor_provider() -> DeepTutorProviderAdapter:
    """Build a provider pre-configured from DeepTutor's LLMConfig."""
    from deeptutor.services.llm.provider_factory import get_runtime_provider

    return DeepTutorProviderAdapter(get_runtime_provider())
