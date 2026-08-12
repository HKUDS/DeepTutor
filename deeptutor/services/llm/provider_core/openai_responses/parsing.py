"""Parse Responses API SSE streams and SDK response objects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
from typing import Any, AsyncGenerator

import httpx
import json_repair
from loguru import logger

from deeptutor.services.llm.provider_core.base import LLMResponse, ToolCallRequest

FINISH_REASON_MAP = {
    "completed": "stop",
    "incomplete": "length",
    "failed": "error",
    "cancelled": "error",
}


def map_finish_reason(status: str | None) -> str:
    return FINISH_REASON_MAP.get(status or "completed", "stop")


@dataclass(slots=True)
class _ToolCallBuffer:
    """Arguments accumulated for one streamed Responses API function call."""

    call_id: str
    item_id: str
    name: str
    arguments: str


class _ToolCallBuffers:
    """Resolve stream events by either call ID or output-item ID.

    OpenAI-compatible providers are not consistent about which identity they
    put on argument delta events. Keeping the aliases here lets both the raw
    SSE and SDK consumers share the same correlation rules.
    """

    #: Stands in for the output-item id when a provider omits one. It is not an
    #: identity — several calls in one response can carry it — so it is never
    #: registered as a lookup key (see :meth:`add`).
    PLACEHOLDER_ITEM_ID = "fc_0"

    def __init__(self) -> None:
        self._by_identity: dict[str, _ToolCallBuffer] = {}

    def add(
        self,
        *,
        call_id: str,
        item_id: str | None,
        name: str,
        arguments: str,
    ) -> None:
        buffer = _ToolCallBuffer(call_id, item_id or self.PLACEHOLDER_ITEM_ID, name, arguments)
        self._by_identity[call_id] = buffer
        # Only a real id becomes an alias. Aliasing the placeholder would let
        # the *next* call that omits its item id resolve to this buffer and be
        # dispatched under this call's tool name, with this call's arguments.
        if item_id and item_id != self.PLACEHOLDER_ITEM_ID:
            self._by_identity[item_id] = buffer

    def get(
        self,
        *,
        call_id: str | None = None,
        item_id: str | None = None,
    ) -> _ToolCallBuffer | None:
        for identity in (call_id, item_id):
            if identity and identity in self._by_identity:
                return self._by_identity[identity]
        return None

    def append(
        self,
        value: str,
        *,
        call_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        if buffer := self.get(call_id=call_id, item_id=item_id):
            buffer.arguments += value

    def replace(
        self,
        value: str,
        *,
        call_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        if buffer := self.get(call_id=call_id, item_id=item_id):
            buffer.arguments = value


def _parse_tool_arguments(arguments: Any, tool_name: str) -> dict[str, Any]:
    """Parse function arguments consistently across all response modes."""
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except Exception:
        logger.warning(
            "Failed to parse tool call arguments for '{}': {}",
            tool_name,
            str(arguments)[:200],
        )
        parsed = json_repair.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(parsed, dict):
            return {"raw": arguments}
    return parsed if isinstance(parsed, dict) else {}


def _build_tool_call(
    *,
    call_id: str,
    item_id: str,
    name: str,
    arguments: Any,
) -> ToolCallRequest:
    return ToolCallRequest(
        id=f"{call_id}|{item_id}",
        name=name,
        arguments=_parse_tool_arguments(arguments, name),
    )


def _response_error_detail(event: Any) -> str:
    """Extract a useful message from raw or SDK Responses error events."""

    def _field(value: Any, name: str) -> Any:
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    response = _field(event, "response")
    error = _field(response, "error") if response is not None else _field(event, "error")
    if error is not None:
        code = _field(error, "code")
        message = _field(error, "message")
        if code and message:
            return f"{code}: {message}"
        return str(message or error)
    return str(_field(event, "message") or event)


async def iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    """Yield parsed JSON events from a Responses API SSE stream."""
    buffer: list[str] = []

    def _flush() -> dict[str, Any] | None:
        data_lines = [line[5:].strip() for line in buffer if line.startswith("data:")]
        buffer.clear()
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return None
        try:
            return json.loads(data)
        except Exception:
            logger.warning("Failed to parse SSE event JSON: {}", data[:200])
            return None

    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                event = _flush()
                if event is not None:
                    yield event
            continue
        buffer.append(line)

    if buffer:
        event = _flush()
        if event is not None:
            yield event


async def consume_sse(
    response: httpx.Response,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str]:
    """Consume a Responses API SSE stream."""
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers = _ToolCallBuffers()
    finish_reason = "stop"

    async for event in iter_sse(response):
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                tool_call_buffers.add(
                    call_id=call_id,
                    item_id=item.get("id"),
                    name=item.get("name") or "",
                    arguments=item.get("arguments") or "",
                )
        elif event_type == "response.output_text.delta":
            delta_text = event.get("delta") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.function_call_arguments.delta":
            tool_call_buffers.append(
                event.get("delta") or "",
                call_id=event.get("call_id"),
                item_id=event.get("item_id"),
            )
        elif event_type == "response.function_call_arguments.done":
            tool_call_buffers.replace(
                event.get("arguments") or "",
                call_id=event.get("call_id"),
                item_id=event.get("item_id"),
            )
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                # Look up by the ids this item actually carries; the
                # placeholder is only a fallback for the id we report back.
                raw_item_id = item.get("id")
                buf = tool_call_buffers.get(call_id=call_id, item_id=raw_item_id)
                tool_calls.append(
                    _build_tool_call(
                        call_id=call_id,
                        item_id=(buf.item_id if buf else raw_item_id)
                        or _ToolCallBuffers.PLACEHOLDER_ITEM_ID,
                        name=(buf.name if buf else "") or item.get("name") or "",
                        arguments=(buf.arguments if buf else "") or item.get("arguments") or "{}",
                    )
                )
        elif event_type == "response.completed":
            status = (event.get("response") or {}).get("status")
            finish_reason = map_finish_reason(status)
        elif event_type in {"error", "response.failed"}:
            raise RuntimeError(f"Response failed: {_response_error_detail(event)[:500]}")

    return content, tool_calls, finish_reason


def parse_response_output(response: Any) -> LLMResponse:
    """Parse an SDK Response object into LLMResponse."""
    if not isinstance(response, dict):
        dump = getattr(response, "model_dump", None)
        response = dump() if callable(dump) else vars(response)

    output = response.get("output") or []
    content_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    reasoning_content: str | None = None

    for item in output:
        if not isinstance(item, dict):
            dump = getattr(item, "model_dump", None)
            item = dump() if callable(dump) else vars(item)

        item_type = item.get("type")
        if item_type == "message":
            for block in item.get("content") or []:
                if not isinstance(block, dict):
                    dump = getattr(block, "model_dump", None)
                    block = dump() if callable(dump) else vars(block)
                if block.get("type") == "output_text":
                    content_parts.append(block.get("text") or "")
        elif item_type == "reasoning":
            for summary in item.get("summary") or []:
                if not isinstance(summary, dict):
                    dump = getattr(summary, "model_dump", None)
                    summary = dump() if callable(dump) else vars(summary)
                if summary.get("type") == "summary_text" and summary.get("text"):
                    reasoning_content = (reasoning_content or "") + summary["text"]
        elif item_type == "function_call":
            call_id = item.get("call_id") or ""
            item_id = item.get("id") or _ToolCallBuffers.PLACEHOLDER_ITEM_ID
            args_raw = item.get("arguments") or "{}"
            tool_calls.append(
                _build_tool_call(
                    call_id=call_id,
                    item_id=item_id,
                    name=item.get("name") or "",
                    arguments=args_raw,
                )
            )

    usage_raw = response.get("usage") or {}
    if not isinstance(usage_raw, dict):
        dump = getattr(usage_raw, "model_dump", None)
        usage_raw = dump() if callable(dump) else vars(usage_raw)
    usage = {}
    if usage_raw:
        usage = {
            "prompt_tokens": int(usage_raw.get("input_tokens") or 0),
            "completion_tokens": int(usage_raw.get("output_tokens") or 0),
            "total_tokens": int(usage_raw.get("total_tokens") or 0),
        }

    finish_reason = map_finish_reason(response.get("status"))
    return LLMResponse(
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
    )


async def consume_sdk_stream(
    stream: Any,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str, dict[str, int], str | None]:
    """Consume an SDK async stream from client.responses.create(stream=True)."""
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers = _ToolCallBuffers()
    finish_reason = "stop"
    usage: dict[str, int] = {}
    reasoning_content: str | None = None

    async for event in stream:
        event_type = getattr(event, "type", None)
        if event_type == "response.output_item.added":
            item = getattr(event, "item", None)
            if item and getattr(item, "type", None) == "function_call":
                call_id = getattr(item, "call_id", None)
                if not call_id:
                    continue
                tool_call_buffers.add(
                    call_id=call_id,
                    item_id=getattr(item, "id", None),
                    name=getattr(item, "name", None) or "",
                    arguments=getattr(item, "arguments", None) or "",
                )
        elif event_type == "response.output_text.delta":
            delta_text = getattr(event, "delta", "") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.function_call_arguments.delta":
            tool_call_buffers.append(
                getattr(event, "delta", "") or "",
                call_id=getattr(event, "call_id", None),
                item_id=getattr(event, "item_id", None),
            )
        elif event_type == "response.function_call_arguments.done":
            tool_call_buffers.replace(
                getattr(event, "arguments", "") or "",
                call_id=getattr(event, "call_id", None),
                item_id=getattr(event, "item_id", None),
            )
        elif event_type == "response.output_item.done":
            item = getattr(event, "item", None)
            if item and getattr(item, "type", None) == "function_call":
                call_id = getattr(item, "call_id", None)
                if not call_id:
                    continue
                raw_item_id = getattr(item, "id", None)
                buf = tool_call_buffers.get(call_id=call_id, item_id=raw_item_id)
                tool_calls.append(
                    _build_tool_call(
                        call_id=call_id,
                        item_id=(buf.item_id if buf else raw_item_id)
                        or _ToolCallBuffers.PLACEHOLDER_ITEM_ID,
                        name=(buf.name if buf else "") or getattr(item, "name", None) or "",
                        arguments=(buf.arguments if buf else "")
                        or getattr(item, "arguments", None)
                        or "{}",
                    )
                )
        elif event_type == "response.reasoning_summary_text.delta":
            delta_text = getattr(event, "delta", "") or ""
            reasoning_content = (reasoning_content or "") + delta_text
            if on_reasoning_delta and delta_text:
                await on_reasoning_delta(delta_text)
        elif event_type == "response.completed":
            response = getattr(event, "response", None)
            status = getattr(response, "status", None) if response is not None else None
            usage_obj = getattr(response, "usage", None) if response is not None else None
            finish_reason = map_finish_reason(status)
            if usage_obj is not None:
                usage = {
                    "prompt_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
                }
        elif event_type in {"error", "response.failed"}:
            raise RuntimeError(f"Response failed: {_response_error_detail(event)[:500]}")

    return content, tool_calls, finish_reason, usage, reasoning_content
