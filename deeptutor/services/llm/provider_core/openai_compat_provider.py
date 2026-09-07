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

import json_repair
from loguru import logger
from openai import AsyncOpenAI

from deeptutor.services.keypool import KeyPool
from deeptutor.services.llm.capabilities import (
    disable_forced_tool_choice_at_runtime,
    disable_response_format_at_runtime,
    is_forced_tool_choice_disabled_at_runtime,
)
from deeptutor.services.llm.exceptions import LLMConfigError
from deeptutor.services.llm.openai_http_client import openai_sdk_client_kwargs
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse, ToolCallRequest
from deeptutor.services.llm.provider_core.openai_responses import (
    ToolArgsDeltaHook,
    adapt_chat_kwargs_to_responses,
    consume_sdk_stream,
    convert_messages,
    convert_tool_choice,
    convert_tools,
    parse_response_output,
)
from deeptutor.services.llm.reasoning_params import (
    build_openai_compatible_reasoning_kwargs,
)
from deeptutor.services.llm.request_compat import (
    is_forced_tool_choice_unsupported,
    is_response_format_unsupported,
)
from deeptutor.services.llm.usage_frame import token_counts
from deeptutor.services.provider_registry import model_overrides_for, normalize_wire_api
from deeptutor.services.session.provider_response_state import (
    normalize_provider_response_state,
)

if TYPE_CHECKING:
    pass

_ALLOWED_MSG_KEYS = frozenset(
    {
        "role",
        "content",
        "tool_calls",
        "tool_call_id",
        "name",
        "reasoning_content",
        "extra_content",
        "_provider_response_state",
        "_responses_output_items",
    }
)
_ALNUM = string.ascii_letters + string.digits

_INTERNAL_RESPONSE_STATE_KEYS = frozenset({"_provider_response_state", "_responses_output_items"})

_RESPONSES_FAILURE_THRESHOLD = 2
_RESPONSES_PROBE_INTERVAL_S = 300.0


def _short_tool_id() -> str:
    """9-char alphanumeric ID compatible with all providers (incl. Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _accumulate_streamed_tool_call(
    buffers: dict[int, dict[str, str]],
    tc_delta: Any,
) -> dict[str, str] | None:
    """Fold one live ``delta.tool_calls`` entry into *buffers*, return it.

    ``id`` and ``name`` arrive complete on whichever chunk carries them and
    are assigned; ``arguments`` arrives in fragments and is concatenated
    (appending a repeated ``id`` is issue #937). The id falls back to the
    stream index so a provider that streams arguments before an id still
    yields something a consumer can correlate previews by.
    """
    index = int(_get(tc_delta, "index") or 0)
    buffer = buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
    tc_id = _get(tc_delta, "id")
    if tc_id:
        buffer["id"] = str(tc_id)
    fn = _get(tc_delta, "function")
    if fn is not None:
        fn_name = _get(fn, "name")
        if fn_name:
            buffer["name"] = str(fn_name)
        fn_args = _get(fn, "arguments")
        if fn_args:
            buffer["arguments"] += str(fn_args)
    if not buffer["id"]:
        buffer["id"] = f"call_{index}"
    return buffer


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


def _provider_state_output_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    state = normalize_provider_response_state(message.get("_provider_response_state"))
    items = state.get("responses_output_items") if state is not None else None
    if not isinstance(items, list):
        legacy_state = normalize_provider_response_state(
            {"responses_output_items": message.get("_responses_output_items")}
        )
        items = legacy_state.get("responses_output_items") if legacy_state is not None else None
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


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
        api_key: str | list[str] | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4o",
        extra_headers: dict[str, str] | None = None,
        spec: Any = None,
        provider_name: str | None = None,
        wire_api: str = "auto",
        configure_env: bool = True,
    ):
        keys = api_key if isinstance(api_key, list) else [api_key]
        keys = [str(key).strip() for key in keys if str(key or "").strip()]
        primary_key = keys[0] if keys else None
        super().__init__(primary_key, api_base)
        self._key_pool = KeyPool(keys) if keys else None
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._spec = spec
        self._provider_name = provider_name
        self._wire_api = normalize_wire_api(wire_api)

        if configure_env and primary_key and spec and spec.env_key:
            self._setup_env(primary_key, api_base)

        effective_base = api_base or (spec.default_api_base if spec else None) or None
        self._effective_base = effective_base
        endpoint = (effective_base or "").rstrip("/")
        # api_key may be a list (key pool); only the resolved primary key
        # counts for the configured-key check.
        placeholder_key = primary_key in {None, "", "no-key", "sk-no-key-required"}
        if (
            provider_name == "openai"
            and (not endpoint or endpoint == "https://api.openai.com/v1")
            and placeholder_key
        ):
            raise LLMConfigError(
                "OpenAI API key is not configured. Set it in Settings > Catalog, "
                "or select a local provider such as Ollama."
            )
        self._client = AsyncOpenAI(
            **openai_sdk_client_kwargs(
                api_key=primary_key or "no-key",
                base_url=effective_base,
                extra_headers=extra_headers,
                spec=spec,
                sdk_max_retries=0,
            )
        )
        self._responses_failures: dict[str, int] = {}
        self._responses_tripped_at: dict[str, float] = {}

    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        return getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )

    async def _create_with_key_rotation(self, create, kwargs: dict[str, Any]) -> Any:
        if not self._key_pool:
            return await create(**kwargs)
        api_key = self._key_pool.next()
        for attempt in range(2):
            request = dict(kwargs)
            headers = dict(request.get("extra_headers") or {})
            headers["Authorization"] = f"Bearer {api_key}"
            request["extra_headers"] = headers
            try:
                return await create(**request)
            except Exception as exc:
                if self._status_code(exc) != 429:
                    raise
                self._key_pool.mark_429(api_key)
                if attempt:
                    raise
                api_key = self._key_pool.next()
        raise RuntimeError("LLM key rotation exhausted")

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

    def _sanitize_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        responses_api: bool = False,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                prepared.append(message)
                continue
            clean = {
                key: value
                for key, value in message.items()
                if key not in _INTERNAL_RESPONSE_STATE_KEYS
            }
            if responses_api:
                output_items = _provider_state_output_items(message)
                if output_items:
                    clean["_provider_response_state"] = {"responses_output_items": output_items}
            else:
                state = normalize_provider_response_state(message.get("_provider_response_state"))
                reasoning_content = state.get("reasoning_content") if state is not None else None
                if (
                    isinstance(reasoning_content, str)
                    and reasoning_content
                    and model
                    and "deepseek" in model.lower()
                ):
                    clean["reasoning_content"] = reasoning_content
            prepared.append(clean)

        sanitized = LLMProvider._sanitize_request_messages(prepared, _ALLOWED_MSG_KEYS)
        if responses_api:
            # Responses function calls use the provider-issued ``call_id`` as
            # a protocol identity. The converter splits DeepTutor's compound
            # ``call_id|item_id`` form itself; hashing it here would make the
            # later function_call_output point at a different call than the
            # replayed native function_call item.
            return sanitized
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
            "messages": self._sanitize_messages(
                self._sanitize_empty_content(messages), model=model_name
            ),
        }

        if self._supports_temperature(model_name, reasoning_effort):
            kwargs["temperature"] = temperature

        if spec and getattr(spec, "supports_max_completion_tokens", False):
            kwargs["max_completion_tokens"] = max(1, max_tokens)
        else:
            kwargs["max_tokens"] = max(1, max_tokens)

        for key, value in model_overrides_for(model_name, spec).items():
            # None means "drop this parameter" — e.g. Kimi models reject any
            # explicit temperature and must be sent none.
            if value is None:
                kwargs.pop(key, None)
            else:
                kwargs[key] = value

        kwargs.update(
            build_openai_compatible_reasoning_kwargs(
                spec=spec,
                binding=getattr(spec, "name", None),
                model=model_name,
                reasoning_effort=reasoning_effort,
            )
        )

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = self._effective_tool_choice(tool_choice, model) or "auto"

        return kwargs

    def _should_use_responses_api(
        self,
        model: str | None,
        reasoning_effort: str | None,
        tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        if self._wire_api == "responses":
            return True
        if self._wire_api == "chat_completions":
            return False

        spec = self._spec
        if self._uses_native_web_search(model, tools):
            return self._responses_circuit_allows(model, reasoning_effort)
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

        return self._responses_circuit_allows(model, reasoning_effort)

    def _responses_circuit_allows(
        self,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        circuit_key = _responses_circuit_key(model, self.default_model, reasoning_effort)
        failures = self._responses_failures.get(circuit_key, 0)
        if failures >= _RESPONSES_FAILURE_THRESHOLD:
            tripped_at = self._responses_tripped_at.get(circuit_key, 0.0)
            if (time.monotonic() - tripped_at) < _RESPONSES_PROBE_INTERVAL_S:
                return False
        return True

    def _uses_native_web_search(
        self,
        model: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> bool:
        patterns = {
            str(name).strip().lower()
            for name in getattr(self._spec, "native_web_search_models", ())
            if str(name).strip()
        }
        model_name = (model or self.default_model or "").strip().lower().split("/")[-1]
        if model_name not in patterns:
            return False
        return any(
            ((tool.get("function") or {}).get("name") == "web_search")
            for tool in tools or []
            if isinstance(tool, dict) and tool.get("type") == "function"
        )

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
        endpoint_unsupported = any(
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
        # DeepSeek V4 reports a very specific three-part error when a
        # Responses continuation cannot replay its prior reasoning item.  Keep
        # these markers conjunctive: each phrase on its own is common in
        # unrelated validation errors and must not trip the circuit breaker.
        reasoning_replay_rejected = (
            any(field in body_text for field in ("reasoning_text", "reasoning_content"))
            and "thinking mode" in body_text
            and "passed back" in body_text
        )
        return endpoint_unsupported or reasoning_replay_rejected

    @staticmethod
    def _is_response_format_error(exc: Exception) -> bool:
        return is_response_format_unsupported(exc)

    def _binding_name(self) -> str:
        return self._provider_name or (self._spec.name if self._spec else "openai")

    def _effective_tool_choice(
        self,
        tool_choice: str | dict[str, Any] | None,
        model: str | None,
    ) -> str | dict[str, Any] | None:
        """Soften a forced tool for a provider already known to refuse one.

        Naming the tool is an optimisation, not the contract: ``"required"``
        still says a tool must be called, and the loop wraps the model's own
        question into a card if it answers in prose anyway. Only pairs
        recorded by a previous rejection are softened, so a provider that
        honours a forced tool keeps getting one.
        """
        if not self._names_a_tool(tool_choice):
            return tool_choice
        if is_forced_tool_choice_disabled_at_runtime(
            self._binding_name(), model or self.default_model
        ):
            return "required"
        return tool_choice

    @staticmethod
    def _names_a_tool(tool_choice: Any) -> bool:
        if not isinstance(tool_choice, dict):
            return False
        return bool(tool_choice.get("name") or (tool_choice.get("function") or {}).get("name"))

    def _note_forced_tool_choice_rejected(
        self,
        exc: Exception,
        tool_choice: str | dict[str, Any] | None,
        model: str | None,
    ) -> bool:
        """Record a refusal to force one tool; True when a retry is worth it."""
        if not self._names_a_tool(tool_choice):
            return False
        if not is_forced_tool_choice_unsupported(exc):
            return False
        target = model or self.default_model
        # loguru formats with ``{}``, not printf placeholders.
        logger.warning(
            "provider refused a forced tool_choice for model={}; retrying with "
            "tool_choice=required. error={}",
            target,
            str(exc)[:200],
        )
        disable_forced_tool_choice_at_runtime(self._binding_name(), target)
        return True

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
            self._sanitize_messages(
                self._sanitize_empty_content(messages), responses_api=True, model=model_name
            )
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
            body["tools"] = convert_tools(
                tools,
                native_web_search=self._uses_native_web_search(model, tools),
            )
            body["tool_choice"] = (
                convert_tool_choice(self._effective_tool_choice(tool_choice, model)) or "auto"
            )
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
        response_map = cls._maybe_mapping(response)
        if response_map is not None:
            usage_obj = response_map.get("usage")
        else:
            usage_obj = getattr(response, "usage", None)
        return token_counts(usage_obj)

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
            # Some providers (CodeBuddy) attach usage to the chunk carrying the
            # last delta rather than to a final choice-less one. Only a report
            # with real numbers replaces what we already have: a gateway that
            # echoes a zero-filled usage object on every delta would otherwise
            # wipe the counts on its way past.
            delta_usage = cls._extract_usage(chunk)
            if delta_usage and any(
                delta_usage.get(key)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            ):
                usage = delta_usage
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
            if self._should_use_responses_api(model, reasoning_effort, tools):
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
                    result = parse_response_output(
                        await self._create_with_key_rotation(self._client.responses.create, body)
                    )
                    self._record_responses_success(model, reasoning_effort)
                    return result
                except Exception as responses_error:
                    if self._spec and self._spec.name == "github_copilot":
                        raise
                    if self._wire_api == "responses":
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
                return self._parse(
                    await self._create_with_key_rotation(
                        self._client.chat.completions.create, request_kwargs
                    )
                )
            except Exception as exc:
                if request_kwargs.get(
                    "response_format"
                ) is not None and self._is_response_format_error(exc):
                    binding = self._provider_name or (self._spec.name if self._spec else "openai")
                    disable_response_format_at_runtime(binding, request_kwargs.get("model"))
                    retry_kwargs = dict(request_kwargs)
                    retry_kwargs.pop("response_format", None)
                    return self._parse(
                        await self._create_with_key_rotation(
                            self._client.chat.completions.create, retry_kwargs
                        )
                    )
                raise
        except Exception as e:
            if self._note_forced_tool_choice_rejected(e, tool_choice, model):
                # ``"required"`` cannot be refused for the same reason, so this
                # retries at most once.
                return await self.chat(
                    messages,
                    tools,
                    model,
                    max_tokens,
                    temperature,
                    reasoning_effort,
                    "required",
                    **extra_kwargs,
                )
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
        # Declared, never forwarded to the wire: ``extra_kwargs`` becomes
        # request body below, so a callback passed through it would be
        # serialised into the request.
        on_tool_args_delta: ToolArgsDeltaHook | None = None,
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
            if self._should_use_responses_api(model, reasoning_effort, tools):
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
                    stream = await self._create_with_key_rotation(
                        self._client.responses.create, body
                    )

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

                    native_output_items: list[dict[str, Any]] = []
                    native_citations: list[dict[str, Any]] = []

                    def _collect_provider_event(
                        kind: str,
                        payload: dict[str, Any],
                    ) -> None:
                        if kind == "output_item":
                            native_output_items.append(payload)
                        elif kind == "citation":
                            native_citations.append(payload)

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
                        on_provider_event=_collect_provider_event,
                        on_tool_args_delta=on_tool_args_delta,
                    )
                    if not any(item.get("type") == "reasoning" for item in native_output_items):
                        native_output_items = [
                            item
                            for item in native_output_items
                            if item.get("type") in {"web_search_call", "web_search"}
                        ]
                    self._record_responses_success(model, reasoning_effort)
                    return LLMResponse(
                        content=content or None,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                        usage=usage,
                        reasoning_content=reasoning_content,
                        provider_specific_fields=(
                            {
                                "native_output_items": native_output_items,
                                "citations": native_citations,
                            }
                            if native_output_items or native_citations
                            else {}
                        ),
                    )
                except Exception as responses_error:
                    if self._spec and self._spec.name == "github_copilot":
                        raise
                    if self._wire_api == "responses":
                        raise
                    if not self._should_fallback_from_responses_error(responses_error):
                        raise
                    self._record_responses_failure(model, reasoning_effort)

            request_kwargs["stream"] = True
            if self._spec is None or self._spec.supports_stream_options:
                request_kwargs["stream_options"] = {"include_usage": True}
            try:
                stream = await self._create_with_key_rotation(
                    self._client.chat.completions.create, request_kwargs
                )
            except Exception as exc:
                if request_kwargs.get(
                    "response_format"
                ) is not None and self._is_response_format_error(exc):
                    binding = self._provider_name or (self._spec.name if self._spec else "openai")
                    disable_response_format_at_runtime(binding, request_kwargs.get("model"))
                    retry_kwargs = dict(request_kwargs)
                    retry_kwargs.pop("response_format", None)
                    stream = await self._create_with_key_rotation(
                        self._client.chat.completions.create, retry_kwargs
                    )
                else:
                    raise

            chunks: list[Any] = []
            stream_iter = stream.__aiter__()
            # Mirrors the accumulation ``_parse_chunks`` does after the fact,
            # but live, so ``on_tool_args_delta`` can report a call while it is
            # still being written. The authoritative parse stays below.
            streaming_tool_args: dict[int, dict[str, str]] = {}
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
                    if on_tool_args_delta and delta is not None:
                        for tc in getattr(delta, "tool_calls", None) or []:
                            buffered = _accumulate_streamed_tool_call(streaming_tool_args, tc)
                            if buffered is not None and buffered["name"]:
                                await on_tool_args_delta(
                                    buffered["id"],
                                    buffered["name"],
                                    buffered["arguments"],
                                )
            return self._parse_chunks(chunks)
        except asyncio.TimeoutError:
            return LLMResponse(
                content=f"Error calling LLM: stream stalled for more than {idle_timeout_s} seconds",
                finish_reason="error",
            )
        except Exception as e:
            if self._note_forced_tool_choice_rejected(e, tool_choice, model):
                # Safe to replay: the refusal happens when the request is
                # created, so no part of a response has been streamed yet.
                # ``"required"`` cannot be refused for the same reason, so
                # this retries at most once.
                return await self.chat_stream(
                    messages,
                    tools,
                    model,
                    max_tokens,
                    temperature,
                    reasoning_effort,
                    "required",
                    on_content_delta,
                    on_reasoning_delta,
                    on_tool_args_delta,
                    **extra_kwargs,
                )
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model
