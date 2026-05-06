"""Anthropic provider — direct SDK integration for Claude models.

Handles message format conversion (OpenAI -> Anthropic Messages API),
prompt caching, extended thinking, tool calls, and streaming.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import re
import secrets
import string
from typing import Any

import json_repair

from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse, ToolCallRequest

_ALNUM = string.ascii_letters + string.digits


def _gen_tool_id() -> str:
    return "toolu_" + "".join(secrets.choice(_ALNUM) for _ in range(22))


class AnthropicProvider(LLMProvider):
    """LLM provider using the native Anthropic SDK for Claude models."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "claude-sonnet-4-20250514",
        extra_headers: dict[str, str] | None = None,
        supports_prompt_caching: bool = True,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._supports_prompt_caching = supports_prompt_caching

        from anthropic import AsyncAnthropic

        from deeptutor.services.llm.utils import sanitize_url

        client_kw: dict[str, Any] = {"max_retries": 0}
        if api_key:
            client_kw["api_key"] = api_key
        if api_base:
            client_kw["base_url"] = sanitize_url(api_base)
        if extra_headers:
            client_kw["default_headers"] = extra_headers
        self._client = AsyncAnthropic(**client_kw)

    @classmethod
    def _handle_error(cls, e: Exception) -> LLMResponse:
        payload = (
            getattr(e, "body", None)
            or getattr(e, "doc", None)
            or getattr(getattr(e, "response", None), "text", None)
        )
        payload_text = (
            payload if isinstance(payload, str) else str(payload) if payload is not None else ""
        )
        msg = (
            f"Error: {payload_text.strip()[:500]}"
            if payload_text.strip()
            else f"Error calling LLM: {e}"
        )
        return LLMResponse(content=msg, finish_reason="error")

    @staticmethod
    def _strip_prefix(model: str) -> str:
        if model.startswith("anthropic/"):
            return model[len("anthropic/") :]
        return model

    # ------------------------------------------------------------------
    # Message conversion: OpenAI chat format -> Anthropic Messages API
    # ------------------------------------------------------------------

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]]]:
        """Return ``(system, anthropic_messages)``."""
        system: str | list[dict[str, Any]] = ""
        raw: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content")

            if role == "system":
                system = content if isinstance(content, (str, list)) else str(content or "")
                continue

            if role == "tool":
                block = self._tool_result_block(msg)
                if raw and raw[-1]["role"] == "user":
                    prev_c = raw[-1]["content"]
                    if isinstance(prev_c, list):
                        prev_c.append(block)
                    else:
                        raw[-1]["content"] = [
                            {"type": "text", "text": prev_c or ""},
                            block,
                        ]
                else:
                    raw.append({"role": "user", "content": [block]})
                continue

            if role == "assistant":
                raw.append({"role": "assistant", "content": self._assistant_blocks(msg)})
                continue

            if role == "user":
                raw.append(
                    {
                        "role": "user",
                        "content": self._convert_user_content(content),
                    }
                )
                continue

        return system, self._merge_consecutive(raw)

    @staticmethod
    def _tool_result_block(msg: dict[str, Any]) -> dict[str, Any]:
        content = msg.get("content")
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": msg.get("tool_call_id", ""),
        }
        if isinstance(content, (str, list)):
            block["content"] = content
        else:
            block["content"] = str(content) if content else ""
        return block

    @staticmethod
    def _assistant_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        content = msg.get("content")

        for tb in msg.get("thinking_blocks") or []:
            if isinstance(tb, dict) and tb.get("type") == "thinking":
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": tb.get("thinking", ""),
                        "signature": tb.get("signature", ""),
                    }
                )

        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for item in content:
                blocks.append(
                    item if isinstance(item, dict) else {"type": "text", "text": str(item)}
                )

        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                args = json_repair.loads(args)
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id") or _gen_tool_id(),
                    "name": func.get("name", ""),
                    "input": args,
                }
            )

        return blocks or [{"type": "text", "text": ""}]

    def _convert_user_content(self, content: Any) -> Any:
        if isinstance(content, str) or content is None:
            return content or "(empty)"
        if not isinstance(content, list):
            return str(content)

        result: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                result.append({"type": "text", "text": str(item)})
                continue
            if item.get("type") == "image_url":
                converted = self._convert_image_block(item)
                if converted:
                    result.append(converted)
                continue
            result.append(item)
        return result or "(empty)"

    @staticmethod
    def _convert_image_block(block: dict[str, Any]) -> dict[str, Any] | None:
        url = (block.get("image_url") or {}).get("url", "")
        if not url:
            return None
        m = re.match(r"data:(image/\w+);base64,(.+)", url, re.DOTALL)
        if m:
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)},
            }
        return {
            "type": "image",
            "source": {"type": "url", "url": url},
        }

    @staticmethod
    def _merge_consecutive(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Anthropic requires alternating user/assistant roles."""
        merged: list[dict[str, Any]] = []
        for msg in msgs:
            if merged and merged[-1]["role"] == msg["role"]:
                prev_c = merged[-1]["content"]
                cur_c = msg["content"]
                if isinstance(prev_c, str):
                    prev_c = [{"type": "text", "text": prev_c}]
                if isinstance(cur_c, str):
                    cur_c = [{"type": "text", "text": cur_c}]
                if isinstance(cur_c, list):
                    prev_c.extend(cur_c)
                merged[-1]["content"] = prev_c
            else:
                merged.append(msg)
        return merged

    # ------------------------------------------------------------------
    # Tool definition conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        result = []
        for tool in tools:
            func = tool.get("function", tool)
            entry: dict[str, Any] = {
                "name": func.get("name", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            }
            desc = func.get("description")
            if desc:
                entry["description"] = desc
            if "cache_control" in tool:
                entry["cache_control"] = tool["cache_control"]
            result.append(entry)
        return result

    @staticmethod
    def _convert_tool_choice(
        tool_choice: str | dict[str, Any] | None,
        thinking_enabled: bool = False,
    ) -> dict[str, Any] | None:
        if thinking_enabled:
            return {"type": "auto"}
        if tool_choice is None or tool_choice == "auto":
            return {"type": "auto"}
        if tool_choice == "required":
            return {"type": "any"}
        if tool_choice == "none":
            return None
        if isinstance(tool_choice, dict):
            name = tool_choice.get("function", {}).get("name")
            if name:
                return {"type": "tool", "name": name}
        return {"type": "auto"}

    # ------------------------------------------------------------------
    # Prompt caching
    # ------------------------------------------------------------------

    @classmethod
    def _apply_cache_control(
        cls,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]] | None]:
        marker = {"type": "ephemeral"}

        if isinstance(system, str) and system:
            system = [{"type": "text", "text": system, "cache_control": marker}]
        elif isinstance(system, list) and system:
            system = list(system)
            system[-1] = {**system[-1], "cache_control": marker}

        new_msgs = list(messages)
        if len(new_msgs) >= 3:
            m = new_msgs[-2]
            c = m.get("content")
            if isinstance(c, str):
                new_msgs[-2] = {
                    **m,
                    "content": [{"type": "text", "text": c, "cache_control": marker}],
                }
            elif isinstance(c, list) and c:
                nc = list(c)
                nc[-1] = {**nc[-1], "cache_control": marker}
                new_msgs[-2] = {**m, "content": nc}

        new_tools = tools
        if tools:
            new_tools = list(tools)
            for idx in cls._tool_cache_marker_indices(new_tools):
                new_tools[idx] = {**new_tools[idx], "cache_control": marker}

        return system, new_msgs, new_tools

    # ------------------------------------------------------------------
    # Build API kwargs
    # ------------------------------------------------------------------

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        model_name = self._strip_prefix(model or self.default_model)
        system, anthropic_msgs = self._convert_messages(self._sanitize_empty_content(messages))
        anthropic_tools = self._convert_tools(tools)

        if self._supports_prompt_caching:
            system, anthropic_msgs, anthropic_tools = self._apply_cache_control(
                system,
                anthropic_msgs,
                anthropic_tools,
            )

        max_tokens = max(1, max_tokens)
        thinking_enabled = bool(reasoning_effort)
        omit_temperature = "opus-4-7" in model_name

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
        }

        if system:
            kwargs["system"] = system

        if reasoning_effort == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}
            if not omit_temperature:
                kwargs["temperature"] = 1.0
        elif thinking_enabled:
            budget_map = {"low": 1024, "medium": 4096, "high": max(8192, max_tokens)}
            budget = budget_map.get(reasoning_effort.lower(), 4096)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["max_tokens"] = max(max_tokens, budget + 4096)
            if not omit_temperature:
                kwargs["temperature"] = 1.0
        elif not omit_temperature:
            kwargs["temperature"] = temperature

        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            tc = self._convert_tool_choice(tool_choice, thinking_enabled)
            if tc:
                kwargs["tool_choice"] = tc

        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        return kwargs

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        thinking_blocks: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )
            elif block.type == "thinking":
                thinking_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": getattr(block, "signature", ""),
                    }
                )

        stop_map = {"tool_use": "tool_calls", "end_turn": "stop", "max_tokens": "length"}
        finish_reason = stop_map.get(response.stop_reason or "", response.stop_reason or "stop")

        usage: dict[str, int] = {}
        if response.usage:
            input_tokens = response.usage.input_tokens
            cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            total_prompt = input_tokens + cache_creation + cache_read
            usage = {
                "prompt_tokens": total_prompt,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": total_prompt + response.usage.output_tokens,
            }

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            thinking_blocks=thinking_blocks or None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        kwargs = self._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        for key in ("response_format", "seed", "logit_bias", "stream", "stream_options"):
            extra_kwargs.pop(key, None)
        kwargs.update({k: v for k, v in extra_kwargs.items() if v is not None})
        try:
            response = await self._client.messages.create(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            return self._handle_error(e)

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
        kwargs = self._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        for key in ("response_format", "seed", "logit_bias", "stream", "stream_options"):
            extra_kwargs.pop(key, None)
        kwargs.update({k: v for k, v in extra_kwargs.items() if v is not None})
        idle_timeout_s = 90
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                if on_content_delta:
                    stream_iter = stream.text_stream.__aiter__()
                    while True:
                        try:
                            text = await asyncio.wait_for(
                                stream_iter.__anext__(),
                                timeout=idle_timeout_s,
                            )
                        except StopAsyncIteration:
                            break
                        await on_content_delta(text)
                response = await asyncio.wait_for(
                    stream.get_final_message(),
                    timeout=idle_timeout_s,
                )
            return self._parse_response(response)
        except asyncio.TimeoutError:
            return LLMResponse(
                content=f"Error calling LLM: stream stalled for more than {idle_timeout_s} seconds",
                finish_reason="error",
            )
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model
