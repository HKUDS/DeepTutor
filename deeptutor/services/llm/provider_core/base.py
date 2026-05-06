"""Base LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
import json
from typing import Any

from loguru import logger


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]
    provider_specific_fields: dict[str, Any] | None = None
    function_provider_specific_fields: dict[str, Any] | None = None

    def to_openai_tool_call(self) -> dict[str, Any]:
        """Serialize to an OpenAI-style tool_call payload."""
        tool_call: dict[str, Any] = {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }
        if self.provider_specific_fields:
            tool_call["provider_specific_fields"] = self.provider_specific_fields
        if self.function_provider_specific_fields:
            tool_call["function"]["provider_specific_fields"] = (
                self.function_provider_specific_fields
            )
        return tool_call


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None
    thinking_blocks: list[dict[str, Any]] | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


@dataclass(frozen=True)
class GenerationSettings:
    """Default generation parameters for LLM calls."""

    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    _CHAT_RETRY_DELAYS = (1, 2, 4)
    _TRANSIENT_ERROR_MARKERS = (
        "429",
        "rate limit",
        "500",
        "502",
        "503",
        "504",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "server error",
        "temporarily unavailable",
    )
    _IMAGE_BLOCK_TYPES = frozenset({"image_url", "image"})
    _SENTINEL = object()

    @staticmethod
    def _coerce_int(value: object, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, (str, bytes, bytearray)):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _coerce_float(value: object, default: float) -> float:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, (str, bytes, bytearray)):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
        self.generation: GenerationSettings = GenerationSettings()

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace empty text content that causes provider 400 errors."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = (
                    None
                    if (msg.get("role") == "assistant" and msg.get("tool_calls"))
                    else "(empty)"
                )
                result.append(clean)
                continue

            if isinstance(content, list):
                filtered = [
                    item
                    for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            if isinstance(content, dict):
                clean = dict(msg)
                clean["content"] = [content]
                result.append(clean)
                continue

            result.append(msg)
        return result

    @staticmethod
    def _tool_cache_marker_indices(tools: list[dict[str, Any]]) -> list[int]:
        """Return indices of tool definitions that should get cache_control markers."""
        n = len(tools)
        if n == 0:
            return []
        if n <= 5:
            return [n - 1]
        return [i for i in range(n - 1, -1, -5)]

    @staticmethod
    def _sanitize_request_messages(
        messages: list[dict[str, Any]],
        allowed_keys: frozenset[str],
    ) -> list[dict[str, Any]]:
        """Keep only provider-safe message keys and normalize assistant content."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in allowed_keys}
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    @staticmethod
    def _image_placeholder(block: dict[str, Any]) -> str:
        meta = block.get("_meta") or {}
        label = ""
        if isinstance(meta, dict):
            label = str(meta.get("path") or meta.get("filename") or "").strip()
        if not label and block.get("type") == "image_url":
            image_url = block.get("image_url") or {}
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "").strip()
                if url and not url.startswith("data:"):
                    label = url
        return f"[image: {label}]" if label else "[image omitted]"

    @classmethod
    def _strip_image_content(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """Replace image blocks with text placeholders."""
        found = False
        stripped: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                stripped.append(dict(msg))
                continue
            new_content: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") in cls._IMAGE_BLOCK_TYPES:
                    new_content.append({"type": "text", "text": cls._image_placeholder(block)})
                    found = True
                else:
                    new_content.append(block)
            stripped.append({**msg, "content": new_content})
        return stripped if found else None

    @classmethod
    def _strip_image_content_inplace(cls, messages: list[dict[str, Any]]) -> bool:
        """Replace image blocks with text placeholders in-place."""
        found = False
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for idx, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") in cls._IMAGE_BLOCK_TYPES:
                    content[idx] = {"type": "text", "text": cls._image_placeholder(block)}
                    found = True
        return found

    @staticmethod
    def _normalize_retry_delays(retry_delays: Sequence[float] | None) -> tuple[float, ...]:
        if retry_delays is None:
            return tuple(float(delay) for delay in LLMProvider._CHAT_RETRY_DELAYS)
        normalized: list[float] = []
        for delay in retry_delays:
            try:
                value = float(delay)
            except (TypeError, ValueError):
                continue
            if value > 0:
                normalized.append(value)
        return tuple(normalized)

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request."""

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
        **kwargs: Any,
    ) -> LLMResponse:
        """Fallback streaming implementation that emits the full response once."""
        response = await self.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            **kwargs,
        )
        if on_reasoning_delta and response.reasoning_content:
            await on_reasoning_delta(response.reasoning_content)
        if on_content_delta and response.content:
            await on_content_delta(response.content)
        return response

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        err = (content or "").lower()
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def _call_with_retry(
        self,
        call: Callable[..., Awaitable[LLMResponse]],
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        retry_delays: Sequence[float] | None,
        **kwargs: Any,
    ) -> LLMResponse:
        delays = self._normalize_retry_delays(retry_delays)
        attempt = 0

        while True:
            attempt += 1
            try:
                response = await call(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                    **kwargs,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                response = LLMResponse(
                    content=f"Error calling LLM: {exc}",
                    finish_reason="error",
                )

            if response.finish_reason != "error":
                return response

            if not self._is_transient_error(response.content):
                stripped = self._strip_image_content(messages)
                if stripped is not None:
                    logger.warning(
                        "Non-transient LLM error with image content, retrying once without images"
                    )
                    retry_response = await call(
                        messages=stripped,
                        tools=tools,
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        reasoning_effort=reasoning_effort,
                        tool_choice=tool_choice,
                        **kwargs,
                    )
                    if retry_response.finish_reason != "error":
                        self._strip_image_content_inplace(messages)
                    return retry_response
                return response

            if attempt > len(delays):
                return response

            delay = delays[attempt - 1]
            logger.warning(
                "LLM transient error (attempt {}/{}), retrying in {}s: {}",
                attempt,
                len(delays) + 1,
                delay,
                (response.content or "")[:120].lower(),
            )
            await asyncio.sleep(delay)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = _SENTINEL,
        temperature: object = _SENTINEL,
        reasoning_effort: object = _SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
        retry_delays: Sequence[float] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call chat() with retry on transient provider failures."""
        if max_tokens is self._SENTINEL:
            max_tokens = self.generation.max_tokens
        if temperature is self._SENTINEL:
            temperature = self.generation.temperature
        if reasoning_effort is self._SENTINEL:
            reasoning_effort = self.generation.reasoning_effort

        resolved_max_tokens = self._coerce_int(max_tokens, self.generation.max_tokens)
        resolved_temperature = self._coerce_float(temperature, self.generation.temperature)
        resolved_reasoning_effort = (
            reasoning_effort
            if reasoning_effort is None or isinstance(reasoning_effort, str)
            else None
        )

        return await self._call_with_retry(
            self.chat,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
            reasoning_effort=resolved_reasoning_effort,
            tool_choice=tool_choice,
            retry_delays=retry_delays,
            **kwargs,
        )

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = _SENTINEL,
        temperature: object = _SENTINEL,
        reasoning_effort: object = _SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        retry_delays: Sequence[float] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call chat_stream() with the same transient retry policy as chat()."""
        if max_tokens is self._SENTINEL:
            max_tokens = self.generation.max_tokens
        if temperature is self._SENTINEL:
            temperature = self.generation.temperature
        if reasoning_effort is self._SENTINEL:
            reasoning_effort = self.generation.reasoning_effort

        resolved_max_tokens = self._coerce_int(max_tokens, self.generation.max_tokens)
        resolved_temperature = self._coerce_float(temperature, self.generation.temperature)
        resolved_reasoning_effort = (
            reasoning_effort
            if reasoning_effort is None or isinstance(reasoning_effort, str)
            else None
        )

        return await self._call_with_retry(
            self.chat_stream,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
            reasoning_effort=resolved_reasoning_effort,
            tool_choice=tool_choice,
            retry_delays=retry_delays,
            on_content_delta=on_content_delta,
            on_reasoning_delta=on_reasoning_delta,
            **kwargs,
        )

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
