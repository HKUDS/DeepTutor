"""Parse Responses API SSE streams and SDK response objects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    finish_reason = "stop"

    async for event in iter_sse(response):
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buffer = {
                    "id": item.get("id") or "fc_0",
                    "name": item.get("name"),
                    "arguments": item.get("arguments") or "",
                }
                tool_call_buffers[call_id] = buffer
                item_id = item.get("id")
                if item_id:
                    tool_call_buffers[item_id] = buffer
        elif event_type == "response.output_text.delta":
            delta_text = event.get("delta") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.function_call_arguments.delta":
            buffer_id = event.get("call_id") or event.get("item_id")
            if buffer_id and buffer_id in tool_call_buffers:
                tool_call_buffers[buffer_id]["arguments"] += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.done":
            buffer_id = event.get("call_id") or event.get("item_id")
            if buffer_id and buffer_id in tool_call_buffers:
                tool_call_buffers[buffer_id]["arguments"] = event.get("arguments") or ""
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buf = tool_call_buffers.get(call_id) or tool_call_buffers.get(item.get("id")) or {}
                args_raw = buf.get("arguments") or item.get("arguments") or "{}"
                try:
                    args = json.loads(args_raw)
                except Exception:
                    logger.warning(
                        "Failed to parse tool call arguments for '{}': {}",
                        buf.get("name") or item.get("name"),
                        args_raw[:200],
                    )
                    args = json_repair.loads(args_raw)
                    if not isinstance(args, dict):
                        args = {"raw": args_raw}
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or item.get('id') or 'fc_0'}",
                        name=buf.get("name") or item.get("name") or "",
                        arguments=args if isinstance(args, dict) else {},
                    )
                )
        elif event_type == "response.completed":
            status = (event.get("response") or {}).get("status")
            finish_reason = map_finish_reason(status)
        elif event_type in {"error", "response.failed"}:
            detail = event.get("error") or event.get("message") or event
            raise RuntimeError(f"Response failed: {str(detail)[:500]}")

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
            item_id = item.get("id") or "fc_0"
            args_raw = item.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except Exception:
                logger.warning(
                    "Failed to parse tool call arguments for '{}': {}",
                    item.get("name"),
                    str(args_raw)[:200],
                )
                args = json_repair.loads(args_raw) if isinstance(args_raw, str) else args_raw
                if not isinstance(args, dict):
                    args = {"raw": args_raw}
            tool_calls.append(
                ToolCallRequest(
                    id=f"{call_id}|{item_id}",
                    name=item.get("name") or "",
                    arguments=args if isinstance(args, dict) else {},
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
    tool_call_buffers: dict[str, dict[str, Any]] = {}
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
                buffer = {
                    "id": getattr(item, "id", None) or "fc_0",
                    "name": getattr(item, "name", None),
                    "arguments": getattr(item, "arguments", None) or "",
                }
                tool_call_buffers[call_id] = buffer
                item_id = getattr(item, "id", None)
                if item_id:
                    tool_call_buffers[item_id] = buffer
        elif event_type == "response.output_text.delta":
            delta_text = getattr(event, "delta", "") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.function_call_arguments.delta":
            buffer_id = getattr(event, "call_id", None) or getattr(event, "item_id", None)
            if buffer_id and buffer_id in tool_call_buffers:
                tool_call_buffers[buffer_id]["arguments"] += getattr(event, "delta", "") or ""
        elif event_type == "response.function_call_arguments.done":
            buffer_id = getattr(event, "call_id", None) or getattr(event, "item_id", None)
            if buffer_id and buffer_id in tool_call_buffers:
                tool_call_buffers[buffer_id]["arguments"] = getattr(event, "arguments", "") or ""
        elif event_type == "response.output_item.done":
            item = getattr(event, "item", None)
            if item and getattr(item, "type", None) == "function_call":
                call_id = getattr(item, "call_id", None)
                if not call_id:
                    continue
                buf = (
                    tool_call_buffers.get(call_id)
                    or tool_call_buffers.get(getattr(item, "id", None))
                    or {}
                )
                args_raw = buf.get("arguments") or getattr(item, "arguments", None) or "{}"
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except Exception:
                    args = json_repair.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    if not isinstance(args, dict):
                        args = {"raw": args_raw}
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or getattr(item, 'id', None) or 'fc_0'}",
                        name=buf.get("name") or getattr(item, "name", None) or "",
                        arguments=args if isinstance(args, dict) else {},
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

    return content, tool_calls, finish_reason, usage, reasoning_content
