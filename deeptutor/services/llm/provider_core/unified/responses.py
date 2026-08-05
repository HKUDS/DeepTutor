"""Deterministic OpenAI Responses API adapter.

Converts the provider-neutral unified types to/from the Responses wire format
(``POST /v1/responses``, ``GET /v1/responses/{id}``,
``POST /v1/responses/{id}/cancel``), including SSE streaming, reasoning,
tool calls, usage, background submit/retrieve/cancel, and the
``call_id|item_id`` tool identity convention preserved by the rest of the
codebase.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.services.llm.provider_core.openai_responses.converters import (
    adapt_chat_kwargs_to_responses,
    split_tool_call_id,
)

from .common import map_finish_status, parse_usage, strict_json_loads_optional
from .types import (
    UnifiedImageBlock,
    UnifiedMessage,
    UnifiedProtocolError,
    UnifiedReasoning,
    UnifiedRequest,
    UnifiedResponse,
    UnifiedResponseEvent,
    UnifiedTextBlock,
    UnifiedToolCall,
    UnifiedToolCallBlock,
    UnifiedToolDefinition,
    UnifiedToolResultBlock,
)

RESPONSES_PATH = "/v1/responses"


def responses_retrieve_path(response_id: str) -> str:
    return f"/v1/responses/{response_id}"


def responses_cancel_path(response_id: str) -> str:
    return f"/v1/responses/{response_id}/cancel"


def _combine_tool_call_id(call_id: str, item_id: str | None) -> str:
    if call_id and item_id:
        return f"{call_id}|{item_id}"
    return call_id or item_id or ""


def _user_content(messages: list[UnifiedMessage]) -> tuple[str, list[dict[str, Any]]]:
    instructions_parts: list[str] = []
    input_items: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        if msg.role == "system":
            text = "".join(
                block.text for block in msg.content if isinstance(block, UnifiedTextBlock)
            )
            if text:
                instructions_parts.append(text)
            continue

        if msg.role == "user":
            input_items.append(
                {"type": "message", "role": "user", "content": _convert_user_blocks(msg)}
            )
            continue

        if msg.role == "assistant":
            for block in msg.content:
                if isinstance(block, UnifiedTextBlock) and block.text:
                    input_items.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": block.text}],
                            "status": "completed",
                            "id": f"msg_{idx}",
                        }
                    )
                elif isinstance(block, UnifiedToolCallBlock):
                    call_id, item_id = split_tool_call_id(block.id)
                    input_items.append(
                        {
                            "type": "function_call",
                            "id": item_id or f"fc_{idx}",
                            "call_id": call_id or f"call_{idx}",
                            "name": block.name,
                            "arguments": json.dumps(block.arguments, ensure_ascii=False),
                        }
                    )
            continue

        if msg.role == "tool":
            block = next(
                (b for b in msg.content if isinstance(b, UnifiedToolResultBlock)),
                None,
            )
            if block is not None:
                call_id, _ = split_tool_call_id(block.tool_call_id)
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": block.output,
                    }
                )

    return "\n\n".join(instructions_parts), input_items


def _convert_user_blocks(msg: UnifiedMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in msg.content:
        if isinstance(block, UnifiedTextBlock):
            if block.text:
                blocks.append({"type": "input_text", "text": block.text})
        elif isinstance(block, UnifiedImageBlock):
            url = block.image_url
            if not url and block.base64:
                media = block.media_type or "image/png"
                url = f"data:{media};base64,{block.base64}"
            blocks.append({"type": "input_image", "image_url": url, "detail": "auto"})
    if not blocks:
        blocks.append({"type": "input_text", "text": ""})
    return blocks


def _convert_tool(tool: UnifiedToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description or "",
        "parameters": tool.parameters or {"type": "object", "properties": {}},
        **({"strict": True} if tool.strict else {}),
    }


def build_responses_request(request: UnifiedRequest) -> dict[str, Any]:
    """Build the Responses API request body from a unified request."""
    instructions, input_items = _user_content(request.messages)
    body: dict[str, Any] = {
        "model": request.model or "",
        "instructions": instructions or None,
        "input": input_items,
        "max_output_tokens": max(1, request.max_tokens),
        "store": False,
        "stream": False,
    }
    if request.background:
        body["background"] = True
    if request.reasoning_effort and request.reasoning_effort.lower() != "none":
        body["reasoning"] = {"effort": request.reasoning_effort}
        body["include"] = ["reasoning.encrypted_content"]
    if request.temperature is not None and "temperature" not in request.extra:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [_convert_tool(tool) for tool in request.tools]
        body["tool_choice"] = request.tool_choice or "auto"
    body.update(adapt_chat_kwargs_to_responses(request.extra))
    return body


def _parse_output_item(item: dict[str, Any]) -> tuple[str | None, UnifiedToolCall | None]:
    """Return ``(text_piece, tool_call)`` for one Responses output item."""
    item_type = item.get("type")
    if item_type == "message":
        text_parts: list[str] = []
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        return ("".join(text_parts) or None, None)
    if item_type == "reasoning":
        text_parts = []
        for summary in item.get("summary") or []:
            if isinstance(summary, dict) and summary.get("type") == "summary_text":
                text = summary.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        return (None, None)
    if item_type == "function_call":
        call_id = item.get("call_id") or ""
        item_id = item.get("id") or "fc_0"
        name = item.get("name") or ""
        args = strict_json_loads_optional(
            item.get("arguments"),
            context=f"tool call arguments for {name!r}",
        )
        tool_call = UnifiedToolCall(
            id=_combine_tool_call_id(str(call_id), str(item_id)),
            name=name,
            arguments=args,
        )
        return (None, tool_call)
    return (None, None)


def parse_responses_response(raw: dict[str, Any]) -> UnifiedResponse:
    """Parse a Responses API response (background or completed) into unified."""
    content_parts: list[str] = []
    tool_calls: list[UnifiedToolCall] = []
    reasoning_parts: list[str] = []

    for item in raw.get("output") or []:
        if not isinstance(item, dict):
            continue
        text, tool_call = _parse_output_item(item)
        if text:
            content_parts.append(text)
        if tool_call is not None:
            tool_calls.append(tool_call)
        if item.get("type") == "reasoning":
            for summary in item.get("summary") or []:
                if isinstance(summary, dict) and summary.get("type") == "summary_text":
                    text = summary.get("text")
                    if isinstance(text, str) and text:
                        reasoning_parts.append(text)

    status = raw.get("status")
    finish_status = map_finish_status(status)
    # The Responses API reports ``completed`` even when the model produced
    # function calls; expose that as the tool_calls finish status so callers
    # know the turn ended awaiting tool execution.
    if tool_calls and finish_status == "stop":
        finish_status = "tool_calls"
    reasoning_text = "".join(reasoning_parts) or None
    return UnifiedResponse(
        id=raw.get("id"),
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        reasoning=UnifiedReasoning(text=reasoning_text) if reasoning_text else None,
        usage=parse_usage(raw.get("usage")),
        finish_status=finish_status,
        model=raw.get("model"),
        status=status or finish_status,
    )


class ResponsesStreamParser:
    """Accumulate Responses API SSE events into normalized events.

    Feed parsed JSON events via :meth:`feed`; call :meth:`final_response` at
    the end of the stream.  Incomplete tool calls (started but never
    finalized with ``response.function_call_arguments.done`` /
    ``response.output_item.done``) raise a stable error.
    """

    def __init__(self) -> None:
        self.id: str | None = None
        self.model: str | None = None
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.tool_buffers: dict[str, dict[str, Any]] = {}
        self.tool_started: dict[str, str] = {}
        self.tool_completed: list[UnifiedToolCall] = []
        self.finish_status: str = "stop"
        self.status: str | None = None
        self.usage: Any = None

    def feed(self, event: dict[str, Any]) -> list[UnifiedResponseEvent]:
        event_type = event.get("type")
        events: list[UnifiedResponseEvent] = []

        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if call_id:
                    self.tool_buffers[str(call_id)] = {
                        "id": str(item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or ""),
                    }
                    self.tool_started[str(call_id)] = ""
                    events.append(
                        UnifiedResponseEvent(
                            type="tool_call_started",
                            tool_call_id=str(call_id),
                            tool_call_name=str(item.get("name") or ""),
                        )
                    )
        elif event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                self.content_parts.append(delta)
                events.append(UnifiedResponseEvent(type="content_delta", delta=delta))
        elif event_type == "response.reasoning_summary_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                self.reasoning_parts.append(delta)
                events.append(UnifiedResponseEvent(type="reasoning_delta", delta=delta))
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            delta = event.get("delta")
            if call_id and isinstance(delta, str) and delta:
                buffer = self.tool_buffers.setdefault(
                    str(call_id),
                    {"id": "", "name": "", "arguments": ""},
                )
                buffer["arguments"] += delta
                events.append(
                    UnifiedResponseEvent(
                        type="tool_call_arguments_delta",
                        tool_call_id=str(call_id),
                        tool_call_name=buffer["name"],
                        arguments_delta=delta,
                    )
                )
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and str(call_id) in self.tool_buffers:
                self.tool_buffers[str(call_id)]["arguments"] = str(event.get("arguments") or "")
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    call_id = "call_0"
                buffer = self.tool_buffers.get(str(call_id)) or {}
                name = buffer.get("name") or item.get("name") or ""
                args_raw = buffer.get("arguments")
                if not args_raw:
                    args_raw = item.get("arguments") or ""
                tool_call = UnifiedToolCall(
                    id=_combine_tool_call_id(str(call_id), buffer.get("id") or item.get("id")),
                    name=str(name),
                    arguments=strict_json_loads_optional(
                        args_raw,
                        context=f"tool call arguments for {name!r}",
                    ),
                )
                self.tool_completed.append(tool_call)
                self.tool_started.pop(str(call_id), None)
                events.append(UnifiedResponseEvent(type="tool_call_completed", tool_call=tool_call))
        elif event_type == "response.completed":
            response = event.get("response") or {}
            self.status = response.get("status") or self.status
            self.finish_status = map_finish_status(self.status)
            self.id = self.id or response.get("id")
            self.model = self.model or response.get("model")
            usage = parse_usage(response.get("usage"))
            if usage is not None:
                self.usage = usage
                events.append(UnifiedResponseEvent(type="usage", usage=usage))
            events.append(
                UnifiedResponseEvent(
                    type="finished",
                    finish_status=self.finish_status,
                    status=self.status,
                    model=self.model,
                )
            )
        elif event_type in {"error", "response.failed"}:
            detail = event.get("error") or event.get("message") or event
            error_text = str(detail)[:500]
            raise UnifiedProtocolError(
                f"Responses stream failed: {error_text}",
                code="provider_stream_error",
                protocol="openai_responses",
            )
        return events

    def final_response(self) -> UnifiedResponse:
        if self.tool_started:
            unfinished = ", ".join(sorted(self.tool_started))
            raise UnifiedProtocolError(
                f"Responses stream ended with incomplete tool call(s): {unfinished}",
                code="tool_call_incomplete",
                protocol="openai_responses",
            )
        if self.tool_completed and self.finish_status == "stop":
            self.finish_status = "tool_calls"
        reasoning_text = "".join(self.reasoning_parts) or None
        return UnifiedResponse(
            id=self.id,
            content="".join(self.content_parts) or None,
            tool_calls=self.tool_completed,
            reasoning=UnifiedReasoning(text=reasoning_text) if reasoning_text else None,
            usage=self.usage,
            finish_status=self.finish_status,
            model=self.model,
            status=self.status or self.finish_status,
        )


__all__ = [
    "RESPONSES_PATH",
    "ResponsesStreamParser",
    "build_responses_request",
    "parse_responses_response",
    "responses_cancel_path",
    "responses_retrieve_path",
]
