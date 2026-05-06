"""OpenAI-compatible provider for all non-Anthropic LLM APIs.

Uses the official ``openai.AsyncOpenAI`` SDK to talk to any OpenAI-compatible
endpoint (OpenAI, DeepSeek, Gemini, Moonshot, MiniMax, gateways, local, etc.).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import hashlib
import secrets
import string
import time
from typing import TYPE_CHECKING, Any
import uuid

import json_repair
from openai import AsyncOpenAI

from deeptutor.services.llm.capabilities import disable_response_format_at_runtime
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse, ToolCallRequest
from deeptutor.services.llm.provider_core.openai_responses import (
    adapt_chat_kwargs_to_responses,
    consume_sdk_stream,
    convert_messages,
    convert_tools,
    parse_response_output,
)

if TYPE_CHECKING:
    from deeptutor.services.provider_registry import ProviderSpec

_ALLOWED_MSG_KEYS = frozenset(
    {
        "role",
        "content",
        "tool_calls",
        "tool_call_id",
        "name",
        "reasoning_content",
        "extra_content",
    }
)
_ALNUM = string.ascii_letters + string.digits

_DEFAULT_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/HKUDS/DeepTutor",
    "X-OpenRouter-Title": "DeepTutor",
}
_RESPONSES_FAILURE_THRESHOLD = 2
_RESPONSES_PROBE_INTERVAL_S = 300.0
_THINKING_STYLE_MAP = {
    "thinking_type": lambda enabled: {"thinking": {"type": "enabled" if enabled else "disabled"}},
    "enable_thinking": lambda enabled: {"enable_thinking": enabled},
    "reasoning_split": lambda enabled: {"reasoning_split": enabled},
}


def _short_tool_id() -> str:
    """9-char alphanumeric ID compatible with all providers (incl. Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _coerce_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value if value else None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict) and dumped:
            return dumped
    return None


def _uses_openrouter(spec: "ProviderSpec | None", api_base: str | None) -> bool:
    if spec and spec.name == "openrouter":
        return True
    return bool(api_base and "openrouter" in api_base.lower())


def _is_direct_openai_base(api_base: str | None) -> bool:
    if not api_base:
        return False
    base = api_base.lower()
    return "api.openai.com" in base


def _responses_circuit_key(
    model: str | None,
    default_model: str,
    reasoning_effort: str | None,
) -> str:
    model_name = (model or default_model or "").strip().lower()
    effort = (reasoning_effort or "").strip().lower() or "none"
    return f"{model_name}|{effort}"


class OpenAICompatProvider(LLMProvider):
    """Unified provider for all OpenAI-compatible APIs.

    Receives a resolved ``ProviderSpec`` from the caller — no internal
    registry lookups needed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4o",
        extra_headers: dict[str, str] | None = None,
        spec: Any = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._spec = spec
        self._provider_name = provider_name

        if api_key and spec and spec.env_key:
            self._setup_env(api_key, api_base)

        effective_base = api_base or (spec.default_api_base if spec else None) or None
        self._effective_base = effective_base
        default_headers: dict[str, str] = {"x-session-affinity": uuid.uuid4().hex}
        if _uses_openrouter(spec, effective_base):
            default_headers.update(_DEFAULT_OPENROUTER_HEADERS)
        if extra_headers:
            default_headers.update(extra_headers)

        self._client = AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=effective_base,
            default_headers=default_headers,
            max_retries=0,
        )
        self._responses_failures: dict[str, int] = {}
        self._responses_tripped_at: dict[str, float] = {}

    def _setup_env(self, api_key: str, api_base: str | None) -> None:
        import os

        spec = self._spec
        if not spec or not spec.env_key:
            return
        if spec.is_gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key).replace(
                "{api_base}", effective_base or ""
            )
            os.environ.setdefault(env_name, resolved)

    # ------------------------------------------------------------------
    # Prompt caching
    # ------------------------------------------------------------------

    @classmethod
    def _apply_cache_control(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        cache_marker = {"type": "ephemeral"}
        new_messages = list(messages)

        def _mark(msg: dict[str, Any]) -> dict[str, Any]:
            content = msg.get("content")
            if isinstance(content, str):
                return {
                    **msg,
                    "content": [
                        {"type": "text", "text": content, "cache_control": cache_marker},
                    ],
                }
            if isinstance(content, list) and content:
                nc = list(content)
                nc[-1] = {**nc[-1], "cache_control": cache_marker}
                return {**msg, "content": nc}
            return msg

        if new_messages and new_messages[0].get("role") == "system":
            new_messages[0] = _mark(new_messages[0])
        if len(new_messages) >= 3:
            new_messages[-2] = _mark(new_messages[-2])

        new_tools = tools
        if tools:
            new_tools = list(tools)
            for idx in cls._tool_cache_marker_indices(new_tools):
                new_tools[idx] = {**new_tools[idx], "cache_control": cache_marker}
        return new_messages, new_tools

    # ------------------------------------------------------------------
    # Message sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_tool_call_id(tool_call_id: Any) -> Any:
        if not isinstance(tool_call_id, str):
            return tool_call_id
        if len(tool_call_id) == 9 and tool_call_id.isalnum():
            return tool_call_id
        return hashlib.sha256(tool_call_id.encode()).hexdigest()[:9]

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized = LLMProvider._sanitize_request_messages(messages, _ALLOWED_MSG_KEYS)
        id_map: dict[str, str] = {}

        def map_id(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            return id_map.setdefault(value, self._normalize_tool_call_id(value))

        for clean in sanitized:
            if isinstance(clean.get("tool_calls"), list):
                normalized = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized.append(tc)
                        continue
                    tc_clean = dict(tc)
                    tc_clean["id"] = map_id(tc_clean.get("id"))
                    normalized.append(tc_clean)
                clean["tool_calls"] = normalized
            if "tool_call_id" in clean and clean["tool_call_id"]:
                clean["tool_call_id"] = map_id(clean["tool_call_id"])
        return sanitized

    # ------------------------------------------------------------------
    # Build kwargs
    # ------------------------------------------------------------------

    @staticmethod
    def _supports_temperature(
        model_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        if reasoning_effort and reasoning_effort.lower() != "none":
            return False
        name = model_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

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
        model_name = model or self.default_model
        spec = self._spec

        if spec and spec.supports_prompt_caching:
            if any(model_name.lower().startswith(k) for k in ("anthropic/", "claude")):
                messages, tools = self._apply_cache_control(messages, tools)

        if spec and spec.strip_model_prefix:
            model_name = model_name.split("/")[-1]

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
        }

        if self._supports_temperature(model_name, reasoning_effort):
            kwargs["temperature"] = temperature

        if spec and getattr(spec, "supports_max_completion_tokens", False):
            kwargs["max_completion_tokens"] = max(1, max_tokens)
        else:
            kwargs["max_tokens"] = max(1, max_tokens)

        if spec:
            model_lower = model_name.lower()
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    break

        if reasoning_effort is None and spec and spec.reasoning_model_patterns:
            model_lower = model_name.lower()
            if any(p.lower() in model_lower for p in spec.reasoning_model_patterns):
                reasoning_effort = "high"

        semantic_effort: str | None = None
        if isinstance(reasoning_effort, str):
            semantic_effort = reasoning_effort.lower()
            if semantic_effort == "minimum":
                semantic_effort = "minimal"

        wire_effort = reasoning_effort
        if spec and spec.name == "dashscope" and semantic_effort == "minimal":
            wire_effort = "minimum"

        if wire_effort:
            kwargs["reasoning_effort"] = wire_effort

        if spec and spec.thinking_style and reasoning_effort is not None:
            thinking_enabled = semantic_effort != "minimal"
            extra = _THINKING_STYLE_MAP.get(spec.thinking_style, lambda _enabled: None)(
                thinking_enabled
            )
            if extra:
                kwargs.setdefault("extra_body", {}).update(extra)

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        return kwargs

    def _should_use_responses_api(
        self,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        spec = self._spec
        if spec and spec.name not in {"openai", "github_copilot"}:
            return False
        if spec is None or spec.name != "github_copilot":
            if not _is_direct_openai_base(self._effective_base):
                return False

        model_name = (model or self.default_model).lower()
        wants_reasoning = bool(reasoning_effort and reasoning_effort.lower() != "none")
        wants_responses = wants_reasoning or any(
            token in model_name for token in ("gpt-5", "o1", "o3", "o4")
        )
        if not wants_responses:
            return False

        circuit_key = _responses_circuit_key(model, self.default_model, reasoning_effort)
        failures = self._responses_failures.get(circuit_key, 0)
        if failures >= _RESPONSES_FAILURE_THRESHOLD:
            tripped_at = self._responses_tripped_at.get(circuit_key, 0.0)
            if (time.monotonic() - tripped_at) < _RESPONSES_PROBE_INTERVAL_S:
                return False
        return True

    def _record_responses_failure(self, model: str | None, reasoning_effort: str | None) -> None:
        circuit_key = _responses_circuit_key(model, self.default_model, reasoning_effort)
        failures = self._responses_failures.get(circuit_key, 0) + 1
        self._responses_failures[circuit_key] = failures
        if failures >= _RESPONSES_FAILURE_THRESHOLD:
            self._responses_tripped_at[circuit_key] = time.monotonic()

    def _record_responses_success(self, model: str | None, reasoning_effort: str | None) -> None:
        circuit_key = _responses_circuit_key(model, self.default_model, reasoning_effort)
        self._responses_failures.pop(circuit_key, None)
        self._responses_tripped_at.pop(circuit_key, None)

    @staticmethod
    def _should_fallback_from_responses_error(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        status_code = getattr(exc, "status_code", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)
        if status_code not in {400, 404, 422}:
            return False

        body = (
            getattr(exc, "body", None)
            or getattr(exc, "doc", None)
            or getattr(response, "text", None)
        )
        body_text = str(body).lower() if body is not None else ""
        return any(
            marker in body_text
            for marker in (
                "responses",
                "response api",
                "max_output_tokens",
                "instructions",
                "previous_response",
                "unknown parameter",
                "unrecognized request argument",
                "unsupported",
                "not supported",
            )
        )

    @staticmethod
    def _is_response_format_error(exc: Exception) -> bool:
        text = str(getattr(exc, "body", None) or getattr(exc, "message", None) or exc).lower()
        if "response_format" not in text and "response format" not in text:
            return False
        return any(
            marker in text
            for marker in (
                "not supported",
                "unsupported",
                "json_object",
                "json_schema",
                "must be 'json_schema' or 'text'",
                "specified for 'response_format.type' is not valid",
            )
        )

    def _build_responses_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        model_name = model or self.default_model
        if self._spec and self._spec.strip_model_prefix:
            model_name = model_name.split("/")[-1]

        instructions, input_items = convert_messages(
            self._sanitize_messages(self._sanitize_empty_content(messages))
        )
        body: dict[str, Any] = {
            "model": model_name,
            "instructions": instructions or None,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
            "store": False,
            "stream": False,
        }

        if self._supports_temperature(model_name, reasoning_effort):
            body["temperature"] = temperature
        if reasoning_effort and reasoning_effort.lower() != "none":
            body["reasoning"] = {"effort": reasoning_effort}
            body["include"] = ["reasoning.encrypted_content"]
        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"
        return body

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _maybe_mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        return None

    @classmethod
    def _extract_text_content(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                item_map = cls._maybe_mapping(item)
                if item_map:
                    text = item_map.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                    continue
                if isinstance(item, str):
                    parts.append(item)
            return "".join(parts) or None
        return str(value)

    @classmethod
    def _extract_usage(cls, response: Any) -> dict[str, int]:
        usage_obj = None
        response_map = cls._maybe_mapping(response)
        if response_map is not None:
            usage_obj = response_map.get("usage")
        elif hasattr(response, "usage") and response.usage:
            usage_obj = response.usage

        usage_map = cls._maybe_mapping(usage_obj)
        if usage_map is not None:
            return {
                "prompt_tokens": int(usage_map.get("prompt_tokens") or 0),
                "completion_tokens": int(usage_map.get("completion_tokens") or 0),
                "total_tokens": int(usage_map.get("total_tokens") or 0),
            }
        if usage_obj:
            return {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
            }
        return {}

    def _parse(self, response: Any) -> LLMResponse:
        if isinstance(response, str):
            return LLMResponse(content=response, finish_reason="stop")

        if not response.choices:
            return LLMResponse(content="Error: API returned empty choices.", finish_reason="error")

        choice = response.choices[0]
        msg = choice.message
        content = msg.content
        finish_reason = choice.finish_reason

        raw_tool_calls: list[Any] = []
        for ch in response.choices:
            m = ch.message
            if hasattr(m, "tool_calls") and m.tool_calls:
                raw_tool_calls.extend(m.tool_calls)
                if ch.finish_reason in ("tool_calls", "stop"):
                    finish_reason = ch.finish_reason
            if not content and m.content:
                content = m.content
            if not content and getattr(m, "reasoning", None):
                content = m.reasoning

        tool_calls = []
        for tc in raw_tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)
            tool_calls.append(
                ToolCallRequest(
                    id=_short_tool_id(),
                    name=tc.function.name,
                    arguments=args if isinstance(args, dict) else {},
                    provider_specific_fields=getattr(tc, "provider_specific_fields", None) or None,
                    function_provider_specific_fields=(
                        getattr(tc.function, "provider_specific_fields", None) or None
                    ),
                )
            )

        reasoning_content = getattr(msg, "reasoning_content", None) or None
        if not reasoning_content and getattr(msg, "reasoning", None):
            reasoning_content = msg.reasoning

        usage = self._extract_usage(response)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )

    @classmethod
    def _parse_chunks(cls, chunks: list[Any]) -> LLMResponse:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tc_bufs: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        def _accum_tc(tc: Any, idx_hint: int) -> None:
            tc_index: int = _get(tc, "index") if _get(tc, "index") is not None else idx_hint
            buf = tc_bufs.setdefault(
                tc_index,
                {
                    "id": "",
                    "name": "",
                    "arguments": "",
                },
            )
            tc_id = _get(tc, "id")
            if tc_id:
                buf["id"] = str(tc_id)
            fn = _get(tc, "function")
            if fn is not None:
                fn_name = _get(fn, "name")
                if fn_name:
                    buf["name"] = str(fn_name)
                fn_args = _get(fn, "arguments")
                if fn_args:
                    buf["arguments"] += str(fn_args)

        for chunk in chunks:
            if isinstance(chunk, str):
                content_parts.append(chunk)
                continue

            if not chunk.choices:
                usage = cls._extract_usage(chunk) or usage
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta and delta.content:
                content_parts.append(delta.content)
            if delta:
                reasoning = getattr(delta, "reasoning_content", None)
                if not reasoning:
                    reasoning = getattr(delta, "reasoning", None)
                if reasoning:
                    reasoning_parts.append(reasoning)
            for tc in (delta.tool_calls or []) if delta else []:
                _accum_tc(tc, getattr(tc, "index", 0))

        content = "".join(content_parts) or None
        reasoning_content = "".join(reasoning_parts) or None

        return LLMResponse(
            content=content,
            tool_calls=[
                ToolCallRequest(
                    id=b["id"] or _short_tool_id(),
                    name=b["name"],
                    arguments=json_repair.loads(b["arguments"]) if b["arguments"] else {},
                )
                for b in tc_bufs.values()
            ],
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content=reasoning_content,
        )

    @staticmethod
    def _handle_error(e: Exception) -> LLMResponse:
        body = (
            getattr(e, "doc", None)
            or getattr(e, "body", None)
            or getattr(getattr(e, "response", None), "text", None)
        )
        body_text = body if isinstance(body, str) else str(body) if body is not None else ""
        msg = (
            f"Error: {body_text.strip()[:500]}" if body_text.strip() else f"Error calling LLM: {e}"
        )
        return LLMResponse(content=msg, finish_reason="error")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _is_tool_format_error(e: Exception) -> bool:
        """Detect errors caused by strict tool-argument JSON validation.

        Some endpoints (e.g. DashScope Coding Plan) reject non-streaming
        tool calls with 400 when the model produces malformed arguments.
        Streaming avoids this because the SDK accumulates tokens into a
        well-formed response.
        """
        text = str(getattr(e, "body", None) or getattr(e, "message", None) or e).lower()
        return any(
            kw in text
            for kw in (
                "function.arguments",
                "must be in json format",
                "invalid.*parameter.*function",
            )
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
        **extra_kwargs: Any,
    ) -> LLMResponse:
        try:
            if self._should_use_responses_api(model, reasoning_effort):
                try:
                    body = self._build_responses_body(
                        messages,
                        tools,
                        model,
                        max_tokens,
                        temperature,
                        reasoning_effort,
                        tool_choice,
                    )
                    body.update(adapt_chat_kwargs_to_responses(extra_kwargs))
                    result = parse_response_output(await self._client.responses.create(**body))
                    self._record_responses_success(model, reasoning_effort)
                    return result
                except Exception as responses_error:
                    if self._spec and self._spec.name == "github_copilot":
                        raise
                    if not self._should_fallback_from_responses_error(responses_error):
                        raise
                    self._record_responses_failure(model, reasoning_effort)

            request_kwargs = self._build_kwargs(
                messages,
                tools,
                model,
                max_tokens,
                temperature,
                reasoning_effort,
                tool_choice,
            )
            request_kwargs.update({k: v for k, v in extra_kwargs.items() if v is not None})
            try:
                return self._parse(await self._client.chat.completions.create(**request_kwargs))
            except Exception as exc:
                if request_kwargs.get(
                    "response_format"
                ) is not None and self._is_response_format_error(exc):
                    binding = self._provider_name or (self._spec.name if self._spec else "openai")
                    disable_response_format_at_runtime(binding, request_kwargs.get("model"))
                    retry_kwargs = dict(request_kwargs)
                    retry_kwargs.pop("response_format", None)
                    return self._parse(await self._client.chat.completions.create(**retry_kwargs))
                raise
        except Exception as e:
            if tools and self._is_tool_format_error(e):
                return await self.chat_stream(
                    messages,
                    tools,
                    model,
                    max_tokens,
                    temperature,
                    reasoning_effort,
                    tool_choice,
                    **extra_kwargs,
                )
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
        request_kwargs = self._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        request_kwargs.update({k: v for k, v in extra_kwargs.items() if v is not None})
        idle_timeout_s = 90
        try:
            if self._should_use_responses_api(model, reasoning_effort):
                try:
                    body = self._build_responses_body(
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
                    stream = await self._client.responses.create(**body)

                    async def _timed_stream():
                        stream_iter = stream.__aiter__()
                        while True:
                            try:
                                yield await asyncio.wait_for(
                                    stream_iter.__anext__(),
                                    timeout=idle_timeout_s,
                                )
                            except StopAsyncIteration:
                                break

                    (
                        content,
                        tool_calls,
                        finish_reason,
                        usage,
                        reasoning_content,
                    ) = await consume_sdk_stream(
                        _timed_stream(),
                        on_content_delta,
                        on_reasoning_delta=on_reasoning_delta,
                    )
                    self._record_responses_success(model, reasoning_effort)
                    return LLMResponse(
                        content=content or None,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                        usage=usage,
                        reasoning_content=reasoning_content,
                    )
                except Exception as responses_error:
                    if self._spec and self._spec.name == "github_copilot":
                        raise
                    if not self._should_fallback_from_responses_error(responses_error):
                        raise
                    self._record_responses_failure(model, reasoning_effort)

            request_kwargs["stream"] = True
            if self._spec is None or self._spec.supports_stream_options:
                request_kwargs["stream_options"] = {"include_usage": True}
            try:
                stream = await self._client.chat.completions.create(**request_kwargs)
            except Exception as exc:
                if request_kwargs.get(
                    "response_format"
                ) is not None and self._is_response_format_error(exc):
                    binding = self._provider_name or (self._spec.name if self._spec else "openai")
                    disable_response_format_at_runtime(binding, request_kwargs.get("model"))
                    retry_kwargs = dict(request_kwargs)
                    retry_kwargs.pop("response_format", None)
                    stream = await self._client.chat.completions.create(**retry_kwargs)
                else:
                    raise

            chunks: list[Any] = []
            stream_iter = stream.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream_iter.__anext__(),
                        timeout=idle_timeout_s,
                    )
                except StopAsyncIteration:
                    break
                chunks.append(chunk)
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if on_reasoning_delta and delta is not None:
                        reasoning_text = getattr(delta, "reasoning_content", None) or getattr(
                            delta, "reasoning", None
                        )
                        if reasoning_text:
                            await on_reasoning_delta(reasoning_text)
                    if on_content_delta and delta is not None:
                        text = getattr(delta, "content", None)
                        if text:
                            await on_content_delta(text)
            return self._parse_chunks(chunks)
        except asyncio.TimeoutError:
            return LLMResponse(
                content=f"Error calling LLM: stream stalled for more than {idle_timeout_s} seconds",
                finish_reason="error",
            )
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model
