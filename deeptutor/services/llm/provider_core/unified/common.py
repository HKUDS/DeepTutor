"""Shared normalization helpers for the unified LLM protocol layer.

Converts the legacy chat-format message/tool dictionaries used by existing
callers into the provider-neutral :mod:`types` and back, so the unified
adapters can be dropped into the existing ``LLMProvider`` interface without
breaking legacy ``LLMResponse`` consumers.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.services.llm.provider_core.base import LLMResponse, ToolCallRequest

from .types import (
    UnifiedImageBlock,
    UnifiedMessage,
    UnifiedProtocolError,
    UnifiedReasoningBlock,
    UnifiedResponse,
    UnifiedTextBlock,
    UnifiedToolCallBlock,
    UnifiedToolDefinition,
    UnifiedToolResultBlock,
    UnifiedUsage,
)

_IMAGE_URL_KEYS = ("image_url", "url")


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _content_block_from_dict(item: dict[str, Any]) -> Any:
    """Convert a legacy chat-format content dict into a unified block."""
    block_type = item.get("type")
    if block_type in ("text", "input_text", "output_text"):
        return UnifiedTextBlock(text=_coerce_text(item.get("text")))
    if block_type in ("image_url", "image"):
        image_url = ""
        if block_type == "image_url":
            image_url = _coerce_text((item.get("image_url") or {}).get("url"))
        else:
            for key in _IMAGE_URL_KEYS:
                value = item.get(key)
                if isinstance(value, str) and value:
                    image_url = value
                    break
            if not image_url:
                source = item.get("source") or {}
                if source.get("type") == "base64":
                    return UnifiedImageBlock(
                        image_url="",
                        media_type=source.get("media_type"),
                        base64=_coerce_text(source.get("data")),
                    )
                image_url = _coerce_text(source.get("url"))
        return UnifiedImageBlock(image_url=image_url)
    if block_type in ("reasoning", "thinking"):
        return UnifiedReasoningBlock(
            text=_coerce_text(item.get("text") or item.get("thinking")),
            signature=item.get("signature"),
        )
    if block_type == "tool_call":
        return UnifiedToolCallBlock(
            id=_coerce_text(item.get("id")),
            name=_coerce_text(item.get("name")),
            arguments=item.get("arguments") or {},
        )
    if block_type == "tool_result":
        return UnifiedToolResultBlock(
            tool_call_id=_coerce_text(item.get("tool_call_id")),
            output=_coerce_text(item.get("output") or item.get("content")),
            is_error=bool(item.get("is_error")),
        )
    return UnifiedTextBlock(text=_coerce_text(item))


def _normalize_content(content: Any) -> list[Any]:
    """Normalize a message content field (str | list[dict]) into blocks."""
    if content is None:
        return []
    if isinstance(content, str):
        return [UnifiedTextBlock(text=content)] if content else []
    if isinstance(content, list):
        blocks: list[Any] = []
        for item in content:
            if isinstance(item, str):
                blocks.append(UnifiedTextBlock(text=item))
            elif isinstance(item, dict):
                blocks.append(_content_block_from_dict(item))
        return blocks
    return [UnifiedTextBlock(text=_coerce_text(content))]


def normalize_messages(messages: list[dict[str, Any]]) -> list[UnifiedMessage]:
    """Convert legacy chat-format messages into provider-neutral messages.

    ``messages`` may contain ``system`` / ``user`` / ``assistant`` / ``tool``
    roles, typed image blocks, assistant ``tool_calls``, and optional
    ``reasoning_content`` / ``thinking_blocks``.
    """
    normalized: list[UnifiedMessage] = []

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue

        blocks = _normalize_content(msg.get("content"))

        if role == "assistant":
            # Attach reasoning/thinking carried in dedicated fields.
            reasoning = msg.get("reasoning_content")
            if not reasoning:
                reasoning = msg.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                blocks.append(UnifiedReasoningBlock(text=reasoning))
            for tb in msg.get("thinking_blocks") or []:
                if isinstance(tb, dict) and tb.get("type") == "thinking":
                    blocks.append(
                        UnifiedReasoningBlock(
                            text=_coerce_text(tb.get("thinking")),
                            signature=tb.get("signature"),
                        )
                    )
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = strict_json_loads(
                        args,
                        context=f"assistant tool call {tc.get('id')!r}",
                        code="tool_call_invalid_arguments",
                    )
                blocks.append(
                    UnifiedToolCallBlock(
                        id=_coerce_text(tc.get("id")),
                        name=_coerce_text(fn.get("name")),
                        arguments=args if isinstance(args, dict) else {},
                    )
                )

        if role == "tool":
            normalized.append(
                UnifiedMessage(
                    role="tool",
                    content=[
                        UnifiedToolResultBlock(
                            tool_call_id=_coerce_text(msg.get("tool_call_id")),
                            output=_coerce_text(msg.get("content")),
                        )
                    ],
                )
            )
            continue

        normalized.append(UnifiedMessage(
            role=role,
            content=blocks,
            responses_continuation_items=(
                list(msg.get("responses_continuation_items") or [])
                if role == "assistant" else []
            ),
        ))

    return normalized


def normalize_tools(
    tools: list[dict[str, Any]] | None,
) -> list[UnifiedToolDefinition] | None:
    """Convert legacy OpenAI-style tool definitions into unified definitions."""
    if not tools:
        return None
    result: list[UnifiedToolDefinition] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function":
            fn = tool.get("function") or {}
        else:
            fn = tool
        name = fn.get("name")
        if not name:
            continue
        result.append(
            UnifiedToolDefinition(
                name=_coerce_text(name),
                description=_coerce_text(fn.get("description")),
                parameters=fn.get("parameters") or {},
                strict=bool(fn.get("strict") or tool.get("strict")),
            )
        )
    return result or None


def strict_json_loads(
    raw: str,
    *,
    context: str = "tool arguments",
    code: str = "tool_call_invalid_arguments",
) -> dict[str, Any]:
    """Parse tool-call JSON strictly.

    Malformed or truncated arguments raise a stable
    :class:`UnifiedProtocolError` instead of silently repairing/inventing a
    result.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise UnifiedProtocolError(
            f"Empty {context} payload; refusing to invent a result",
            code=code,
        )
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - normalize all parse failures
        raise UnifiedProtocolError(
            f"Malformed {context}: {str(exc)}",
            code=code,
        ) from exc
    if not isinstance(parsed, dict):
        raise UnifiedProtocolError(
            f"{context} must be a JSON object, got {type(parsed).__name__}",
            code=code,
        )
    return parsed


def strict_json_loads_optional(raw: Any, *, context: str) -> dict[str, Any]:
    """Parse tool-call JSON that may already be a dict."""
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    return strict_json_loads(raw, context=context)


def parse_usage(usage: Any) -> UnifiedUsage | None:
    """Normalize a provider usage dict (or SDK-like object) into UnifiedUsage."""
    if usage is None:
        return None
    if not isinstance(usage, dict):
        model_dump = getattr(usage, "model_dump", None)
        usage = model_dump() if callable(model_dump) else {}
    if not isinstance(usage, dict) or not usage:
        return None

    def _as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    prompt = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _as_int(usage.get("completion_tokens") or usage.get("output_tokens"))
    details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    reasoning = _as_int(
        usage.get("reasoning_tokens")
        or (details.get("reasoning_tokens") if isinstance(details, dict) else 0)
    )
    total = usage.get("total_tokens")
    if total is None:
        total = prompt + completion
    return UnifiedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=_as_int(total),
        reasoning_tokens=reasoning,
    )


def map_finish_status(finish_reason: Any) -> str:
    """Normalize a provider finish/stop reason to a unified status."""
    value = (finish_reason or "stop").strip().lower()
    aliases = {
        "stop": "stop",
        "end_turn": "stop",
        "eos": "stop",
        "completed": "stop",
        "length": "length",
        "max_tokens": "length",
        "incomplete": "length",
        "tool_calls": "tool_calls",
        "tool_use": "tool_calls",
        "function_call": "tool_calls",
        "content_filter": "content_filter",
        "error": "error",
        "failed": "error",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    return aliases.get(value, value or "stop")


def to_legacy_llm_response(unified: UnifiedResponse) -> LLMResponse:
    """Project a unified response onto the legacy ``LLMResponse`` dataclass.

    This is the only place a unified response is converted for legacy callers;
    no raw SDK object is ever returned.
    """
    tool_calls = [
        ToolCallRequest(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in unified.tool_calls
    ]
    reasoning_content: str | None = None
    thinking_blocks: list[dict[str, Any]] | None = None
    if unified.reasoning is not None and unified.reasoning.text:
        reasoning_content = unified.reasoning.text
        if unified.reasoning.signature:
            thinking_blocks = [
                {
                    "type": "thinking",
                    "thinking": unified.reasoning.text,
                    "signature": unified.reasoning.signature,
                }
            ]

    usage: dict[str, int] = {}
    if unified.usage is not None:
        usage = {
            "prompt_tokens": unified.usage.prompt_tokens,
            "completion_tokens": unified.usage.completion_tokens,
            "total_tokens": unified.usage.total_tokens,
        }
        if unified.usage.reasoning_tokens:
            usage["reasoning_tokens"] = unified.usage.reasoning_tokens

    return LLMResponse(
        content=unified.content,
        tool_calls=tool_calls,
        finish_reason=unified.finish_status,
        usage=usage,
        reasoning_content=reasoning_content,
        thinking_blocks=thinking_blocks,
        termination={
            "protocol": unified.metadata.get("api_protocol", ""),
            "provider_status": unified.status,
            "finish_reason": unified.finish_status,
            "response_id": unified.id,
            "incomplete_details": unified.metadata.get("incomplete_details"),
        },
        continuation_items=list(unified.metadata.get("continuation_items") or []),
    )


__all__ = [
    "map_finish_status",
    "normalize_messages",
    "normalize_tools",
    "parse_usage",
    "strict_json_loads",
    "strict_json_loads_optional",
    "to_legacy_llm_response",
]
