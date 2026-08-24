"""Responses API bridge for raw OpenAI-compatible agent clients.

Every agentic pipeline (chat loop, labeled steps, research, question,
explore) streams through a raw ``AsyncOpenAI`` client built by
:func:`deeptutor.core.agentic.client.build_openai_client`, which targets
``{base}/chat/completions``. Many gateways — OpenAI itself and relays that
pass the Responses API through — only grant prompt caching on
``{base}/responses``. That matters for agent loops, which replay one growing
conversation many times per turn: without prefix-cache hits every round pays
full input price again.

This module wraps such a client so ``chat.completions.create(...)`` is served
by the Responses API instead:

* request side — chat messages/tools/kwargs are converted with the shared
  converters from ``services.llm.provider_core.openai_responses.converters``
  (system messages are merged into ``instructions`` because the converter
  keeps only the last one);
* response side — Responses SDK events and objects are re-shaped into
  chat-completions chunks (``delta.content`` / ``delta.reasoning_content`` /
  ``delta.tool_calls`` / ``finish_reason`` / ``usage``, including cached-token
  details) so every existing consumer keeps working unchanged;
* failure side — any bridge error immediately retries the original call via
  Chat Completions and feeds a per-(base, model) circuit breaker, so gateways
  without ``/responses`` degrade after at most two probes and stay degraded
  for five minutes.

Activation policy (env ``DEEPTUTOR_USE_RESPONSES_API``):

* ``"on"/"1"/"true"/"yes"``  — always bridge;
* ``"off"/"0"/"false"/"no"`` — never bridge (kill switch);
* unset / anything else      — auto: bridge cloud OpenAI-compatible clients;
  local inference servers (Ollama, vLLM, LM Studio, …) keep plain Chat
  Completions.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any
from types import SimpleNamespace

from deeptutor.services.llm.provider_core.openai_responses.converters import (
    convert_messages,
    convert_tools,
)
from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    map_finish_reason,
)
from deeptutor.services.provider_registry import find_by_name

logger = logging.getLogger(__name__)

ENV_USE_RESPONSES_API = "DEEPTUTOR_USE_RESPONSES_API"

_TRUTHY_MODES = frozenset({"1", "true", "yes", "on"})
_FALSY_MODES = frozenset({"0", "false", "no", "off"})

#: Models that reject ``temperature`` on the reasoning endpoints — mirror of
#: OpenAICompatProvider._supports_temperature.
_TEMP_UNSUPPORTED_TOKENS = ("gpt-5", "o1", "o3", "o4")

_BRIDGE_FAILURE_THRESHOLD = 2
_BRIDGE_COOLDOWN_S = 300.0

_breaker_lock = threading.Lock()
_bridge_failures: dict[str, int] = {}
_bridge_tripped_at: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def _breaker_key(base_url: str | None, model: str | None) -> str:
    return f"{(base_url or '').strip().lower()}|{(model or '').strip().lower()}"


def _breaker_tripped(key: str) -> bool:
    now = time.monotonic()
    with _breaker_lock:
        tripped_at = _bridge_tripped_at.get(key)
        if tripped_at is None:
            return False
        if now - tripped_at >= _BRIDGE_COOLDOWN_S:
            # Cooldown elapsed: expire the entry so the next call probes again.
            _bridge_tripped_at.pop(key, None)
            _bridge_failures.pop(key, None)
            return False
        return True


def _record_bridge_failure(key: str) -> None:
    with _breaker_lock:
        failures = _bridge_failures.get(key, 0) + 1
        _bridge_failures[key] = failures
        if failures >= _BRIDGE_FAILURE_THRESHOLD:
            _bridge_tripped_at[key] = time.monotonic()
            logger.info(
                "Responses bridge tripped for %s after %d failures; "
                "chat completions only for %ds",
                key,
                failures,
                _BRIDGE_COOLDOWN_S,
            )


def _record_bridge_success(key: str) -> None:
    with _breaker_lock:
        _bridge_failures.pop(key, None)
        _bridge_tripped_at.pop(key, None)


def reset_bridge_breaker() -> None:
    """Clear breaker state (test helper)."""
    with _breaker_lock:
        _bridge_failures.clear()
        _bridge_tripped_at.clear()


# ---------------------------------------------------------------------------
# Activation policy
# ---------------------------------------------------------------------------


def responses_bridge_enabled(config: Any) -> bool:
    """Whether *config*'s client should be wrapped with the bridge."""
    raw = os.environ.get(ENV_USE_RESPONSES_API, "").strip().lower()
    if raw in _TRUTHY_MODES:
        return True
    if raw in _FALSY_MODES:
        return False
    # Auto: local servers rarely expose /responses; cloud gateways get probed
    # and fall back through the breaker when they do not.
    spec = find_by_name(config.binding)
    if spec is not None and getattr(spec, "is_local", False):
        return False
    return True


# ---------------------------------------------------------------------------
# Request conversion
# ---------------------------------------------------------------------------


def _split_system_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Merge every system message into one instructions string.

    ``convert_messages`` keeps only the *last* system message, but agent
    pipelines legitimately ship several (base prompt + capability
    injections), so they are merged here before delegating.
    """
    parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "system":
            rest.append(message)
            continue
        content = message.get("content")
        if isinstance(content, str):
            if content.strip():
                parts.append(content)
        elif isinstance(content, list):
            text = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
            if text.strip():
                parts.append(text)
    return "\n\n".join(parts), rest


def _supports_temperature(model_name: str, reasoning_effort: str | None) -> bool:
    if reasoning_effort and str(reasoning_effort).lower() != "none":
        return False
    lowered = model_name.lower()
    return not any(token in lowered for token in _TEMP_UNSUPPORTED_TOKENS)


def build_responses_body(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Translate one chat.completions.create kwargs dict to Responses body."""
    model = str(kwargs.get("model") or "")
    messages = list(kwargs.get("messages") or [])
    reasoning_effort = kwargs.get("reasoning_effort")

    instructions, rest = _split_system_messages(messages)
    converted_instructions, input_items = convert_messages(rest)
    merged_instructions = "\n\n".join(
        part for part in (converted_instructions.strip(), instructions.strip()) if part
    )

    body: dict[str, Any] = {
        "model": model,
        "instructions": merged_instructions or None,
        "input": input_items,
        "store": False,
        "stream": bool(kwargs.get("stream")),
    }

    max_output_tokens = kwargs.get("max_completion_tokens")
    if max_output_tokens is None:
        max_output_tokens = kwargs.get("max_tokens")
    if max_output_tokens is not None:
        body["max_output_tokens"] = max(1, int(max_output_tokens))

    temperature = kwargs.get("temperature")
    if temperature is not None and _supports_temperature(model, reasoning_effort):
        body["temperature"] = temperature

    if reasoning_effort and str(reasoning_effort).lower() != "none":
        body["reasoning"] = {"effort": str(reasoning_effort)}

    tools = kwargs.get("tools")
    if tools:
        body["tools"] = convert_tools(list(tools))
        body["tool_choice"] = kwargs.get("tool_choice") or "auto"

    extra_body = kwargs.get("extra_body")
    if isinstance(extra_body, dict):
        body.update(extra_body)

    # Unknown Chat Completions kwargs (stream_options, gateway session ids,
    # …) are deliberately dropped rather than forwarded.
    return body


# ---------------------------------------------------------------------------
# Response conversion
# ---------------------------------------------------------------------------


def _map_usage(usage_obj: Any) -> SimpleNamespace | None:
    if usage_obj is None:
        return None
    input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
    total = int(getattr(usage_obj, "total_tokens", 0) or (input_tokens + output_tokens))
    usage = SimpleNamespace(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=total,
    )
    details = getattr(usage_obj, "input_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
    if cached:
        usage.prompt_tokens_details = SimpleNamespace(cached_tokens=cached)
    return usage


def _tool_call_chunk(
    *, index: int, id_: str, name: str, arguments: str
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=id_,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _delta_chunk(
    *,
    content: str | None = None,
    reasoning: str | None = None,
    tool_call: SimpleNamespace | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    tool_calls = [tool_call] if tool_call is not None else None
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=tool_calls,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=None,
    )


async def responses_events_to_chat_chunks(events: Any) -> Any:
    """Re-shape a Responses SDK event stream into chat-completions chunks.

    Tool-call arguments are buffered and emitted exactly once per call (on
    ``output_item.done``) because chat consumers accumulate deltas by
    concatenation — forwarding partial deltas AND a final full copy would
    duplicate them. Text and reasoning still stream token by token.
    """
    pending: dict[str, dict[str, Any]] = {}
    emitted_calls = 0
    if not hasattr(events, "__aiter__"):
        sync_items = list(events)

        async def _sync_events() -> Any:
            for item in sync_items:
                yield item

        events = _sync_events()

    async for event in events:
        event_type = getattr(event, "type", None)

        if event_type == "response.output_text.delta":
            delta = getattr(event, "delta", None)
            if delta:
                yield _delta_chunk(content=delta)

        elif event_type == "response.reasoning_summary_text.delta":
            delta = getattr(event, "delta", None)
            if delta:
                yield _delta_chunk(reasoning=delta)

        elif event_type == "response.output_item.added":
            item = getattr(event, "item", None)
            if item is not None and getattr(item, "type", None) == "function_call":
                call_id = getattr(item, "call_id", None) or ""
                pending[call_id] = {
                    "item_id": getattr(item, "id", None),
                    "name": getattr(item, "name", None) or "",
                    "arguments": getattr(item, "arguments", None) or "",
                }

        elif event_type == "response.function_call_arguments.delta":
            call_id = getattr(event, "call_id", None) or ""
            state = pending.setdefault(call_id, {"name": "", "arguments": ""})
            state["arguments"] += getattr(event, "delta", None) or ""

        elif event_type == "response.function_call_arguments.done":
            call_id = getattr(event, "call_id", None) or ""
            state = pending.setdefault(call_id, {"name": "", "arguments": ""})
            done_args = getattr(event, "arguments", None)
            if done_args:
                state["arguments"] = done_args

        elif event_type == "response.output_item.done":
            item = getattr(event, "item", None)
            if item is None or getattr(item, "type", None) != "function_call":
                continue
            call_id = getattr(item, "call_id", None) or ""
            state = pending.pop(call_id, {})
            name = getattr(item, "name", None) or state.get("name") or ""
            arguments = (
                state.get("arguments")
                or getattr(item, "arguments", None)
                or "{}"
            )
            index = emitted_calls
            emitted_calls += 1
            yield _delta_chunk(
                tool_call=_tool_call_chunk(
                    index=index,
                    id_=call_id or f"call_{index}",
                    name=name,
                    arguments=arguments,
                )
            )

        elif event_type == "response.completed":
            response = getattr(event, "response", None)
            finish_reason = (
                "tool_calls"
                if emitted_calls
                else map_finish_reason(getattr(response, "status", None))
            )
            yield _delta_chunk(finish_reason=finish_reason)
            usage = _map_usage(getattr(response, "usage", None))
            if usage is not None:
                yield SimpleNamespace(choices=[], usage=usage)

        elif event_type in ("error", "response.failed"):
            detail = (
                getattr(event, "error", None)
                or getattr(event, "message", None)
                or event
            )
            raise RuntimeError(f"Responses stream failed: {str(detail)[:300]}")




def response_to_chat_shape(response: Any) -> SimpleNamespace:
    """Convert a non-streaming Responses object into a chat completion."""
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[SimpleNamespace] = []

    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            for part in getattr(item, "content", None) or []:
                part_type = getattr(part, "type", None)
                if part_type in ("output_text", "text"):
                    text_parts.append(getattr(part, "text", "") or "")
        elif item_type == "reasoning":
            summary = (
                getattr(item, "summary", None) or getattr(item, "content", None) or []
            )
            for part in summary:
                text = getattr(part, "text", "")
                if text:
                    reasoning_parts.append(text)
        elif item_type == "function_call":
            index = len(tool_calls)
            call_id = getattr(item, "call_id", None) or f"call_{index}"
            tool_calls.append(
                _tool_call_chunk(
                    index=index,
                    id_=call_id,
                    name=getattr(item, "name", "") or "",
                    arguments=getattr(item, "arguments", "") or "{}",
                )
            )

    finish_reason = (
        "tool_calls"
        if tool_calls
        else map_finish_reason(getattr(response, "status", None))
    )
    message = SimpleNamespace(
        content="".join(text_parts) or None,
        tool_calls=tool_calls or None,
        reasoning_content="".join(reasoning_parts) or None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=_map_usage(getattr(response, "usage", None)),
    )


# ---------------------------------------------------------------------------
# Bridged client
# ---------------------------------------------------------------------------


class _StreamProxy:
    """Chat-chunks async iterator with the ``close()`` contract callers use."""

    def __init__(self, agen: Any, events_stream: Any, breaker_key: str) -> None:
        self._agen = agen
        self._events_stream = events_stream
        self._key = breaker_key

    def __aiter__(self) -> Any:
        return self

    async def __anext__(self) -> Any:
        try:
            return await self._agen.__anext__()
        except Exception:
            _record_bridge_failure(self._key)
            raise

    async def close(self) -> None:
        close = getattr(self._events_stream, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result


class _BridgedCompletions:
    def __init__(self, inner: Any, base_url: str | None) -> None:
        self._inner = inner
        self._base_url = base_url or ""

    async def create(self, **kwargs: Any) -> Any:
        key = _breaker_key(self._base_url, kwargs.get("model"))
        if _breaker_tripped(key):
            return await self._inner.chat.completions.create(**kwargs)
        try:
            body = build_responses_body(kwargs)
        except Exception as exc:
            _record_bridge_failure(key)
            logger.warning(
                "Responses bridge request conversion failed (%s); "
                "using chat completions",
                exc,
            )
            return await self._inner.chat.completions.create(**kwargs)
        try:
            if body.get("stream"):
                events_stream = await self._inner.responses.create(**body)
                agen = responses_events_to_chat_chunks(events_stream)
                return _StreamProxy(agen, events_stream, key)
            response = await self._inner.responses.create(**body)
            _record_bridge_success(key)
            return response_to_chat_shape(response)
        except Exception as exc:
            _record_bridge_failure(key)
            logger.warning(
                "Responses bridge failed (%s); retrying via chat completions", exc
            )
            return await self._inner.chat.completions.create(**kwargs)


class _BridgeClient:
    """Delegating facade: ``chat.completions.create`` bridged, rest passthrough."""

    def __init__(self, inner: Any, base_url: str | None) -> None:
        self._inner = inner
        self.chat = SimpleNamespace(
            completions=_BridgedCompletions(inner, base_url)
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def wrap_responses_bridge(client: Any, config: Any) -> Any:
    """Wrap *client* when the bridge is enabled for *config*'s binding."""
    if not responses_bridge_enabled(config):
        return client
    logger.debug(
        "Responses bridge active for binding=%s base=%s",
        getattr(config, "binding", ""),
        getattr(config, "base_url", ""),
    )
    return _BridgeClient(client, getattr(config, "base_url", None))
