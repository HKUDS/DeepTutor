"""Deterministic Anthropic Messages API adapter.

Converts the provider-neutral unified types to/from the Anthropic Messages
wire format (``POST /v1/messages``), including SSE streaming, thinking
blocks, tool_use/tool_result, usage, and stop reasons.
"""

from __future__ import annotations

from typing import Any

from .common import map_finish_status, parse_usage, strict_json_loads_optional
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

ANTHROPIC_MESSAGES_PATH = "/v1/messages"

_THINKING_OFF_EFFORTS = frozenset({"none", "minimal", "minimum"})
_BUDGET_MAP = {"low": 1024, "medium": 4096, "high": 8192}


def _convert_thinking(reasoning_effort: str | None) -> dict[str, Any] | None:
    """Map a unified reasoning effort onto Anthropic ``thinking``.

    ``adaptive`` maps directly; off-sentinels omit the parameter entirely;
    any other real effort maps to ``enabled`` with a deterministic budget.
    """
    if not reasoning_effort:
        return None
    effort = reasoning_effort.strip().lower()
    if effort in _THINKING_OFF_EFFORTS:
        return None
    if effort == "adaptive":
        return {"type": "adaptive"}
    budget = _BUDGET_MAP.get(effort, 4096)
    return {"type": "enabled", "budget_tokens": budget}


def _convert_tool_choice(
    tool_choice: str | dict[str, Any] | None,
    thinking_enabled: bool,
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
        name = (tool_choice.get("function") or {}).get("name")
        if name:
            return {"type": "tool", "name": name}
    return {"type": "auto"}


def _user_blocks(msg: UnifiedMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in msg.content:
        if isinstance(block, UnifiedTextBlock):
            if block.text:
                blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, UnifiedImageBlock):
            if block.base64:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block.media_type or "image/png",
                            "data": block.base64,
                        },
                    }
                )
            elif block.image_url:
                blocks.append({"type": "image", "source": {"type": "url", "url": block.image_url}})
    return blocks or [{"type": "text", "text": "(empty)"}]


def _assistant_blocks(msg: UnifiedMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in msg.content:
        if isinstance(block, UnifiedTextBlock) and block.text:
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, UnifiedReasoningBlock):
            entry: dict[str, Any] = {"type": "thinking", "thinking": block.text}
            if block.signature:
                entry["signature"] = block.signature
            blocks.append(entry)
        elif isinstance(block, UnifiedToolCallBlock):
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.arguments,
                }
            )
    return blocks or [{"type": "text", "text": ""}]


def _tool_result_block(block: UnifiedToolResultBlock) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": block.tool_call_id,
        "content": block.output,
    }
    if block.is_error:
        entry["is_error"] = True
    return entry


def _convert_messages(messages: list[UnifiedMessage]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    raw: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            text = "".join(
                block.text for block in msg.content if isinstance(block, UnifiedTextBlock)
            )
            if text:
                system_parts.append(text)
            continue
        if msg.role == "tool":
            block = next(
                (b for b in msg.content if isinstance(b, UnifiedToolResultBlock)),
                None,
            )
            if block is None:
                continue
            entry = {"role": "user", "content": [_tool_result_block(block)]}
            if raw and raw[-1]["role"] == "user":
                _append_content(raw[-1], entry["content"])
            else:
                raw.append(entry)
            continue
        if msg.role == "assistant":
            raw.append({"role": "assistant", "content": _assistant_blocks(msg)})
            continue
        if msg.role == "user":
            raw.append({"role": "user", "content": _user_blocks(msg)})
            continue

    return "\n\n".join(system_parts), _merge_consecutive(raw)


def _append_content(target: dict[str, Any], content: list[dict[str, Any]]) -> None:
    existing = target["content"]
    if not isinstance(existing, list):
        existing = [{"type": "text", "text": existing}]
    existing.extend(content)
    target["content"] = existing


def _merge_consecutive(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic requires alternating user/assistant roles."""
    merged: list[dict[str, Any]] = []
    for msg in msgs:
        if merged and merged[-1]["role"] == msg["role"]:
            _append_content(merged[-1], msg["content"])
        else:
            merged.append(msg)
    return merged


def _convert_tool(tool: UnifiedToolDefinition) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": tool.name,
        "input_schema": tool.parameters or {"type": "object", "properties": {}},
    }
    if tool.description:
        entry["description"] = tool.description
    return entry


def build_anthropic_request(request: UnifiedRequest) -> dict[str, Any]:
    """Build the Anthropic Messages request body from a unified request."""
    system, messages = _convert_messages(request.messages)
    thinking = _convert_thinking(request.reasoning_effort)
    thinking_enabled = thinking is not None

    body: dict[str, Any] = {
        "model": (request.model or "").split("/")[-1],
        "messages": messages,
        "max_tokens": max(1, request.max_tokens),
    }
    if system:
        body["system"] = system
    if thinking is not None:
        body["thinking"] = thinking
        if thinking.get("type") == "enabled":
            budget = int(thinking.get("budget_tokens") or 4096)
            body["max_tokens"] = max(body["max_tokens"], budget + 4096)
            body["temperature"] = 1.0
    elif request.temperature is not None:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [_convert_tool(tool) for tool in request.tools]
        tool_choice = _convert_tool_choice(request.tool_choice, thinking_enabled)
        if tool_choice:
            body["tool_choice"] = tool_choice
    body.update({key: value for key, value in request.extra.items() if value is not None})
    return body


def _stop_map() -> dict[str, str]:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
    }


def parse_anthropic_response(raw: dict[str, Any]) -> UnifiedResponse:
    """Parse a non-streaming Anthropic Messages response into unified."""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    signature: str | None = None
    tool_calls: list[UnifiedToolCall] = []

    for block in raw.get("content") or []:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                content_parts.append(text)
        elif block_type == "thinking":
            text = block.get("thinking")
            if isinstance(text, str) and text:
                reasoning_parts.append(text)
                signature = block.get("signature") or signature
        elif block_type == "tool_use":
            name = block.get("name") or ""
            tool_calls.append(
                UnifiedToolCall(
                    id=str(block.get("id") or ""),
                    name=name,
                    arguments=strict_json_loads_optional(
                        block.get("input"),
                        context=f"tool call input for {name!r}",
                    ),
                )
            )

    stop_reason = _stop_map().get(raw.get("stop_reason") or "", raw.get("stop_reason") or "stop")
    reasoning_text = "".join(reasoning_parts) or None
    return UnifiedResponse(
        id=raw.get("id"),
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        reasoning=(
            UnifiedReasoning(text=reasoning_text, signature=signature) if reasoning_text else None
        ),
        usage=parse_usage(raw.get("usage")),
        finish_status=stop_reason,
        model=raw.get("model"),
        status=raw.get("stop_reason") or stop_reason,
    )


class AnthropicStreamParser:
    """Accumulate Anthropic Messages SSE events into normalized events."""

    def __init__(self) -> None:
        self.id: str | None = None
        self.model: str | None = None
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.signature: str | None = None
        self.tool_buffers: dict[str, dict[str, Any]] = {}
        self._index_to_tool_id: dict[int, str] = {}
        self._active_tool_id: str | None = None
        self.tool_completed: list[UnifiedToolCall] = []
        self.stop_reason: str | None = None
        self.usage_input: int = 0
        self.usage_output: int = 0

    def feed(self, event: dict[str, Any]) -> list[UnifiedResponseEvent]:
        event_type = event.get("type")
        events: list[UnifiedResponseEvent] = []

        if event_type == "message_start":
            message = event.get("message") or {}
            self.id = self.id or message.get("id")
            self.model = self.model or message.get("model")
            usage = message.get("usage") or {}
            self.usage_input = int(usage.get("input_tokens") or 0)
        elif event_type == "content_block_start":
            block = event.get("content_block") or {}
            block_type = block.get("type")
            index = event.get("index")
            if block_type == "tool_use":
                tool_id = str(block.get("id") or f"toolu_{index}")
                self.tool_buffers[tool_id] = {
                    "name": str(block.get("name") or ""),
                    "arguments": "",
                }
                if index is not None:
                    self._index_to_tool_id[index] = tool_id
                self._active_tool_id = tool_id
                events.append(
                    UnifiedResponseEvent(
                        type="tool_call_started",
                        tool_call_id=tool_id,
                        tool_call_name=str(block.get("name") or ""),
                    )
                )
        elif event_type == "content_block_delta":
            delta = event.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text")
                if isinstance(text, str) and text:
                    self.content_parts.append(text)
                    events.append(UnifiedResponseEvent(type="content_delta", delta=text))
            elif delta_type == "thinking_delta":
                text = delta.get("thinking")
                if isinstance(text, str) and text:
                    self.reasoning_parts.append(text)
                    events.append(UnifiedResponseEvent(type="reasoning_delta", delta=text))
            elif delta_type == "signature_delta":
                signature = delta.get("signature")
                if isinstance(signature, str) and signature:
                    self.signature = signature
            elif delta_type == "input_json_delta":
                partial = delta.get("partial_json")
                if isinstance(partial, str) and partial:
                    buffer = self._active_tool_buffer()
                    if buffer is not None:
                        buffer["arguments"] += partial
                        events.append(
                            UnifiedResponseEvent(
                                type="tool_call_arguments_delta",
                                tool_call_id=self._active_tool_id,
                                tool_call_name=buffer["name"],
                                arguments_delta=partial,
                            )
                        )
        elif event_type == "content_block_stop":
            index = event.get("index")
            tool_id = None
            if index is not None:
                tool_id = self._index_to_tool_id.get(index)
            if tool_id is not None and tool_id in self.tool_buffers:
                buffer = self.tool_buffers.pop(tool_id)
                if index is not None:
                    self._index_to_tool_id.pop(index, None)
                if self._active_tool_id == tool_id:
                    self._active_tool_id = None
                name = buffer["name"]
                args = strict_json_loads_optional(
                    buffer["arguments"],
                    context=f"tool call input for {name!r}",
                )
                tool_call = UnifiedToolCall(id=tool_id, name=name, arguments=args)
                self.tool_completed.append(tool_call)
                events.append(UnifiedResponseEvent(type="tool_call_completed", tool_call=tool_call))
        elif event_type == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason"):
                self.stop_reason = delta["stop_reason"]
            usage = event.get("usage") or {}
            self.usage_output = int(usage.get("output_tokens") or 0)
        elif event_type == "error":
            detail = event.get("error") or event
            raise UnifiedProtocolError(
                f"Anthropic stream failed: {str(detail)[:500]}",
                code="provider_stream_error",
                protocol="anthropic_messages",
            )
        return events

    def _active_tool_buffer(self) -> dict[str, Any] | None:
        if self._active_tool_id is None:
            return None
        return self.tool_buffers.get(self._active_tool_id)

    def final_response(self) -> UnifiedResponse:
        if self.tool_buffers:
            unfinished = ", ".join(sorted(self.tool_buffers))
            raise UnifiedProtocolError(
                f"Anthropic stream ended with incomplete tool_use block(s): {unfinished}",
                code="tool_call_incomplete",
                protocol="anthropic_messages",
            )
        reasoning_text = "".join(self.reasoning_parts) or None
        stop_reason = self.stop_reason or "end_turn"
        finish_status = map_finish_status(stop_reason)
        return UnifiedResponse(
            id=self.id,
            content="".join(self.content_parts) or None,
            tool_calls=self.tool_completed,
            reasoning=(
                UnifiedReasoning(text=reasoning_text, signature=self.signature)
                if reasoning_text
                else None
            ),
            usage=parse_usage(
                {
                    "input_tokens": self.usage_input,
                    "output_tokens": self.usage_output,
                }
            ),
            finish_status=finish_status,
            model=self.model,
            status=stop_reason,
        )


__all__ = [
    "ANTHROPIC_MESSAGES_PATH",
    "AnthropicStreamParser",
    "build_anthropic_request",
    "parse_anthropic_response",
]
