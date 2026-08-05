"""Deterministic OpenAI Chat Completions adapter.

Converts the provider-neutral unified types to/from the Chat Completions wire
format (``POST /v1/chat/completions``), including streaming deltas, tool
calls, reasoning content, usage, and finish reasons.
"""

from __future__ import annotations

import json
from typing import Any

from .common import (
    map_finish_status,
    parse_usage,
    strict_json_loads,
    strict_json_loads_optional,
)
from .types import (
    UnifiedImageBlock,
    UnifiedMessage,
    UnifiedProtocolError,
    UnifiedReasoning,
    UnifiedReasoningBlock,
    UnifiedRequest,
    UnifiedResponse,
    UnifiedResponseEvent,
    UnifiedTextBlock,
    UnifiedToolCall,
    UnifiedToolCallBlock,
    UnifiedToolDefinition,
    UnifiedToolResultBlock,
)

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


def _user_content(messages: list[UnifiedMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            text = "".join(
                block.text for block in msg.content if isinstance(block, UnifiedTextBlock)
            )
            result.append({"role": "system", "content": text})
        elif msg.role == "user":
            result.append({"role": "user", "content": _convert_user_content(msg)})
        elif msg.role == "tool":
            block = next(
                (b for b in msg.content if isinstance(b, UnifiedToolResultBlock)),
                None,
            )
            if block is not None:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.tool_call_id,
                        "content": block.output,
                    }
                )
        elif msg.role == "assistant":
            result.append(_convert_assistant(msg))
    return result


def _convert_assistant(msg: UnifiedMessage) -> dict[str, Any]:
    text_parts = [b.text for b in msg.content if isinstance(b, UnifiedTextBlock)]
    reasoning_parts = [b.text for b in msg.content if isinstance(b, UnifiedReasoningBlock)]
    tool_call_blocks = [b for b in msg.content if isinstance(b, UnifiedToolCallBlock)]

    converted: dict[str, Any] = {"role": "assistant"}
    converted["content"] = "".join(text_parts) if text_parts else None
    if reasoning_parts:
        converted["reasoning_content"] = "".join(reasoning_parts)
    if tool_call_blocks:
        converted["tool_calls"] = [
            {
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.arguments, ensure_ascii=False),
                },
            }
            for block in tool_call_blocks
        ]
    return converted


def _convert_user_content(msg: UnifiedMessage) -> Any:
    text_parts = [b.text for b in msg.content if isinstance(b, UnifiedTextBlock)]
    image_parts = [b for b in msg.content if isinstance(b, UnifiedImageBlock)]
    if not image_parts:
        return "".join(text_parts) if text_parts else "(empty)"

    blocks: list[dict[str, Any]] = []
    if text_parts:
        blocks.append({"type": "text", "text": "".join(text_parts)})
    for image in image_parts:
        url = image.image_url
        if not url and image.base64:
            media = image.media_type or "image/png"
            url = f"data:{media};base64,{image.base64}"
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def _convert_tool(tool: UnifiedToolDefinition) -> dict[str, Any]:
    function: dict[str, Any] = {
        "name": tool.name,
        "parameters": tool.parameters or {"type": "object", "properties": {}},
    }
    if tool.description:
        function["description"] = tool.description
    if tool.strict:
        function["strict"] = True
    return {"type": "function", "function": function}


def build_chat_completions_request(request: UnifiedRequest) -> dict[str, Any]:
    """Build the Chat Completions request body from a unified request."""
    body: dict[str, Any] = {
        "model": request.model or "",
        "messages": _user_content(request.messages),
    }
    extra = {key: value for key, value in request.extra.items() if value is not None}
    # A caller-supplied token limit wins (newer models require
    # max_completion_tokens); otherwise fall back to the request default.
    if "max_completion_tokens" not in extra and "max_tokens" not in extra:
        body["max_tokens"] = max(1, request.max_tokens)
    if request.temperature is not None and "temperature" not in extra:
        body["temperature"] = request.temperature
    if request.reasoning_effort and request.reasoning_effort.lower() != "none":
        body["reasoning_effort"] = request.reasoning_effort
    if request.tools:
        body["tools"] = [_convert_tool(tool) for tool in request.tools]
        body["tool_choice"] = request.tool_choice or "auto"
    body.update(extra)
    return body


def _extract_content(value: Any) -> str | None:
    """Extract text from a string or a typed content-array message."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") in ("text", "output_text", "input_text"):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "".join(parts) if parts else None
    return str(value) if value else None


def _extract_reasoning(message: dict[str, Any]) -> str | None:
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def parse_chat_completions_response(raw: dict[str, Any]) -> UnifiedResponse:
    """Parse a non-streaming Chat Completions response into a unified response."""
    choices = raw.get("choices") or []
    if not choices:
        raise UnifiedProtocolError(
            "Chat Completions response contained no choices",
            code="empty_provider_response",
            protocol="openai_chat_completions",
        )
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    finish_reason = map_finish_status(choice.get("finish_reason"))

    tool_calls: list[UnifiedToolCall] = []
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = strict_json_loads_optional(
            fn.get("arguments"),
            context=f"tool call arguments for {name!r}",
        )
        tool_calls.append(
            UnifiedToolCall(
                id=str(tc.get("id") or ""),
                name=name,
                arguments=args,
            )
        )

    reasoning_text = _extract_reasoning(message)
    return UnifiedResponse(
        id=raw.get("id"),
        content=_extract_content(message.get("content")),
        tool_calls=tool_calls,
        reasoning=UnifiedReasoning(text=reasoning_text) if reasoning_text else None,
        usage=parse_usage(raw.get("usage")),
        finish_status=finish_reason,
        model=raw.get("model"),
        status=finish_reason,
    )


class ChatCompletionsStreamParser:
    """Accumulate Chat Completions SSE chunks into normalized events.

    Feed each parsed chunk via :meth:`feed`; call :meth:`final_response` when
    the stream ends.  Malformed or incomplete tool-call arguments raise a
    stable :class:`UnifiedProtocolError` instead of inventing output.
    """

    def __init__(self) -> None:
        self.id: str | None = None
        self.model: str | None = None
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.tool_buffers: dict[int, dict[str, Any]] = {}
        self.tool_started: set[int] = set()
        self.finish_status: str = "stop"
        self.usage: Any = None

    def feed(self, chunk: dict[str, Any]) -> list[UnifiedResponseEvent]:
        events: list[UnifiedResponseEvent] = []
        if chunk.get("id"):
            self.id = self.id or str(chunk["id"])
        if chunk.get("model"):
            self.model = str(chunk["model"])
        usage = parse_usage(chunk.get("usage"))
        if usage is not None:
            self.usage = usage
            events.append(UnifiedResponseEvent(type="usage", usage=usage))

        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                self.finish_status = map_finish_status(choice["finish_reason"])
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str) and text:
                self.content_parts.append(text)
                events.append(UnifiedResponseEvent(type="content_delta", delta=text))
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                self.reasoning_parts.append(reasoning)
                events.append(UnifiedResponseEvent(type="reasoning_delta", delta=reasoning))
            for tc in delta.get("tool_calls") or []:
                if isinstance(tc, dict):
                    events.extend(self._feed_tool_call(tc))
        return events

    def _feed_tool_call(self, tc: dict[str, Any]) -> list[UnifiedResponseEvent]:
        index = tc.get("index")
        index = int(index) if index is not None else len(self.tool_buffers)
        buffer = self.tool_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
        events: list[UnifiedResponseEvent] = []
        if index not in self.tool_started:
            self.tool_started.add(index)
            events.append(
                UnifiedResponseEvent(
                    type="tool_call_started",
                    tool_call_id=str(tc.get("id") or ""),
                    tool_call_name="",
                )
            )
        if tc.get("id"):
            buffer["id"] = str(tc["id"])
        function = tc.get("function") or {}
        if function.get("name"):
            buffer["name"] = str(function["name"])
        args = function.get("arguments")
        if isinstance(args, str) and args:
            buffer["arguments"] += args
            events.append(
                UnifiedResponseEvent(
                    type="tool_call_arguments_delta",
                    tool_call_id=buffer["id"],
                    tool_call_name=buffer["name"],
                    arguments_delta=args,
                )
            )
        return events

    def final_response(self) -> UnifiedResponse:
        tool_calls: list[UnifiedToolCall] = []
        for index in sorted(self.tool_buffers):
            buffer = self.tool_buffers[index]
            if not buffer["id"]:
                raise UnifiedProtocolError(
                    "Chat Completions stream ended with an incomplete tool call (missing id)",
                    code="tool_call_incomplete",
                    protocol="openai_chat_completions",
                )
            if buffer["arguments"]:
                args = strict_json_loads(
                    buffer["arguments"],
                    context=f"tool call arguments for {buffer['name']!r}",
                )
            else:
                args = {}
            tool_calls.append(UnifiedToolCall(id=buffer["id"], name=buffer["name"], arguments=args))

        content = "".join(self.content_parts) or None
        reasoning_text = "".join(self.reasoning_parts) or None
        return UnifiedResponse(
            id=self.id,
            content=content,
            tool_calls=tool_calls,
            reasoning=UnifiedReasoning(text=reasoning_text) if reasoning_text else None,
            usage=self.usage,
            finish_status=self.finish_status,
            model=self.model,
            status=self.finish_status,
        )


__all__ = [
    "CHAT_COMPLETIONS_PATH",
    "ChatCompletionsStreamParser",
    "build_chat_completions_request",
    "parse_chat_completions_response",
]
