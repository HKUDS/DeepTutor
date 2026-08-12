"""Convert Chat Completions messages/tools to Responses API format."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

_CHAT_TOKEN_LIMIT_ALIASES = ("max_completion_tokens", "max_tokens")


def convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Convert Chat Completions messages to Responses API input items."""
    system_prompt = ""
    input_items: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            system_prompt = content if isinstance(content, str) else ""
            continue

        if role == "user":
            input_items.append(convert_user_message(content))
            continue

        if role == "assistant":
            if isinstance(content, str) and content:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                        "status": "completed",
                        "id": f"msg_{idx}",
                    }
                )
            for tool_call in msg.get("tool_calls", []) or []:
                fn = tool_call.get("function") or {}
                call_id, item_id = split_tool_call_id(tool_call.get("id"))
                input_items.append(
                    {
                        "type": "function_call",
                        "id": item_id or f"fc_{idx}",
                        "call_id": call_id or f"call_{idx}",
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments") or "{}",
                    }
                )
            continue

        if role == "tool":
            call_id, _ = split_tool_call_id(msg.get("tool_call_id"))
            output = _convert_tool_output(content)
            input_items.append(
                {"type": "function_call_output", "call_id": call_id, "output": output}
            )

    return system_prompt, input_items


def _convert_tool_output(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)

    converted: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            converted.append({"type": "input_text", "text": str(item.get("text") or "")})
        elif item.get("type") == "image_url":
            url = (item.get("image_url") or {}).get("url")
            if url:
                converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
    return converted or json.dumps(content, ensure_ascii=False)


def convert_user_message(content: Any) -> dict[str, Any]:
    """Convert user message content to Responses API blocks."""
    if isinstance(content, str):
        return {"role": "user", "content": [{"type": "input_text", "text": content}]}
    if isinstance(content, list):
        converted: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                converted.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url")
                if url:
                    converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
        if converted:
            return {"role": "user", "content": converted}
    return {"role": "user", "content": [{"type": "input_text", "text": ""}]}


def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI function calling schemas to Responses API tools."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or {}
        converted.append(
            {
                "type": "function",
                "name": name,
                "description": fn.get("description") or "",
                "parameters": params if isinstance(params, dict) else {},
            }
        )
    return converted


def split_tool_call_id(tool_call_id: Any) -> tuple[str, str | None]:
    """Split a compound call_id|item_id tool id."""
    if isinstance(tool_call_id, str) and tool_call_id:
        if "|" in tool_call_id:
            call_id, item_id = tool_call_id.split("|", 1)
            return call_id, item_id or None
        return tool_call_id, None
    return "call_0", None


def adapt_chat_kwargs_to_responses(extra_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Translate Chat Completions kwargs to Responses API equivalents.

    Callers building requests for the Chat Completions endpoint may pass
    ``max_completion_tokens`` for newer OpenAI models (o1/o3/gpt-4o/gpt-5.x)
    or ``max_tokens`` for older chat models. The Responses API does not accept
    either name and uses ``max_output_tokens`` instead, so the OpenAI SDK raises
    ``TypeError`` from ``responses.create`` before any HTTP request leaves the
    client. See DeepTutor#437.

    Drops keys with ``None`` values to match the existing merge filter, and
    only applies the alias when the caller did not already set the Responses
    name explicitly.
    """
    result = {
        key: value
        for key, value in extra_kwargs.items()
        if value is not None and key not in _CHAT_TOKEN_LIMIT_ALIASES
    }
    if "max_output_tokens" in result:
        return result

    for key in _CHAT_TOKEN_LIMIT_ALIASES:
        value = extra_kwargs.get(key)
        if value is not None:
            result["max_output_tokens"] = value
            break
    return result
