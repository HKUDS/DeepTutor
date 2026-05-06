"""Azure OpenAI provider backed by the OpenAI SDK Responses API."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
import uuid

from openai import AsyncOpenAI

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse
from deeptutor.services.llm.provider_core.openai_responses import (
    adapt_chat_kwargs_to_responses,
    consume_sdk_stream,
    convert_messages,
    convert_tools,
    parse_response_output,
)


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI provider using the Responses API."""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

        if not api_key:
            raise ValueError("Azure OpenAI api_key is required")
        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")

        base_url = api_base.rstrip("/")
        if not base_url.endswith("/openai/v1"):
            base_url = f"{base_url}/openai/v1"
        base_url = f"{base_url.rstrip('/')}/"

        headers = {"x-session-affinity": uuid.uuid4().hex}
        if extra_headers:
            headers.update(extra_headers)

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=headers,
            max_retries=0,
        )

    @staticmethod
    def _supports_temperature(
        deployment_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        if reasoning_effort and reasoning_effort.lower() != "none":
            return False
        name = deployment_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        deployment = model or self.default_model
        instructions, input_items = convert_messages(self._sanitize_empty_content(messages))

        body: dict[str, Any] = {
            "model": deployment,
            "instructions": instructions or None,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
            "store": False,
            "stream": False,
        }
        if self._supports_temperature(deployment, reasoning_effort):
            body["temperature"] = temperature
        if reasoning_effort and reasoning_effort.lower() != "none":
            body["reasoning"] = {"effort": reasoning_effort}
            body["include"] = ["reasoning.encrypted_content"]
        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"
        return body

    @staticmethod
    def _handle_error(exc: Exception) -> LLMResponse:
        response = getattr(exc, "response", None)
        body = getattr(exc, "body", None) or getattr(response, "text", None)
        body_text = str(body).strip() if body is not None else ""
        message = f"Error: {body_text[:500]}" if body_text else f"Error calling Azure OpenAI: {exc}"
        return LLMResponse(content=message, finish_reason="error")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **extra_kwargs: Any,
    ) -> LLMResponse:
        body = self._build_body(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        body.update(adapt_chat_kwargs_to_responses(extra_kwargs))
        try:
            return parse_response_output(await self._client.responses.create(**body))
        except Exception as exc:
            return self._handle_error(exc)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **extra_kwargs: Any,
    ) -> LLMResponse:
        body = self._build_body(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        body.update(adapt_chat_kwargs_to_responses(extra_kwargs))
        body["stream"] = True
        idle_timeout_s = 90

        try:
            stream = await self._client.responses.create(**body)

            async def _timed_stream():
                stream_iter = stream.__aiter__()
                while True:
                    try:
                        yield await asyncio.wait_for(
                            stream_iter.__anext__(), timeout=idle_timeout_s
                        )
                    except StopAsyncIteration:
                        break

            content, tool_calls, finish_reason, usage, reasoning_content = await consume_sdk_stream(
                _timed_stream(),
                on_content_delta,
                on_reasoning_delta=on_reasoning_delta,
            )
            return LLMResponse(
                content=content or None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )
        except asyncio.TimeoutError:
            return LLMResponse(
                content=f"Error calling Azure OpenAI: stream stalled for more than {idle_timeout_s} seconds",
                finish_reason="error",
            )
        except Exception as exc:
            return self._handle_error(exc)

    def get_default_model(self) -> str:
        return self.default_model
