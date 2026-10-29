"""Wire adaptation shared by local agent SDK model providers.

SDK lifecycle and authentication stay with each provider. This module only
translates prompts, streamed messages and DeepTutor-owned MCP tool calls.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from .base import LLMResponse, ToolCallRequest

logger = logging.getLogger(__name__)
_MCP_SERVER_NAME = "deeptutor"
_MCP_TOOL_PREFIX = f"mcp__{_MCP_SERVER_NAME}__"


async def _consume_messages(
    messages: Any,
    *,
    on_content_delta: Callable[[str], Awaitable[None]] | None,
    interrupt: Callable[[], Awaitable[None]] | None = None,
    label: str = "CodeBuddy",
) -> LLMResponse:
    chunks: list[str] = []
    pending_result_text = ""
    async for message in messages:
        if _is_error_result(message):
            return LLMResponse(
                content=f"Error calling {label}: {_result_text(message)}",
                finish_reason="error",
            )
        if _is_result_message(message):
            pending_result_text = _result_text(message)
            continue

        tool_calls = _assistant_tool_calls(message)
        text = _assistant_text(message)
        if text:
            chunks.append(text)
            if on_content_delta:
                await on_content_delta(text)
        if tool_calls:
            if interrupt is not None:
                try:
                    await interrupt()
                except Exception as exc:
                    logger.warning(
                        "%s interrupt after tool calls failed (%s); "
                        "background generation may keep running",
                        label,
                        type(exc).__name__,
                    )
                else:
                    await _drain_interrupted_response(messages, label=label)
            return LLMResponse(
                content="".join(chunks),
                tool_calls=tool_calls,
                finish_reason="tool_calls",
            )

    if not chunks and pending_result_text:
        chunks.append(pending_result_text)
        if on_content_delta:
            await on_content_delta(pending_result_text)
    return LLMResponse(content="".join(chunks), finish_reason="stop")


async def _drain_interrupted_response(messages: Any, *, label: str = "CodeBuddy") -> None:
    """Consume the SDK's interrupt result so it cannot leak into the next turn."""
    try:
        async for message in messages:
            if _is_result_message(message) or type(message).__name__ == "ErrorMessage":
                return
    except Exception as exc:
        logger.warning(
            "%s interrupted response drain failed (%s); "
            "stale SDK messages may surface in the next turn",
            label,
            type(exc).__name__,
        )


def _assistant_tool_calls(message: Any) -> list[ToolCallRequest]:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if not isinstance(content, list):
        return []

    calls: list[ToolCallRequest] = []
    for block in content:
        if isinstance(block, dict):
            block_type = str(block.get("type") or "").lower()
            name = str(block.get("name") or "")
            call_id = str(block.get("id") or "")
            arguments = block.get("input")
        else:
            block_type = type(block).__name__.lower()
            name = str(getattr(block, "name", "") or "")
            call_id = str(getattr(block, "id", "") or "")
            arguments = getattr(block, "input", None)
        if block_type not in {"tool_use", "tooluse"} and not block_type.endswith("tooluseblock"):
            continue
        if not name.startswith(_MCP_TOOL_PREFIX):
            continue
        tool_name = name[len(_MCP_TOOL_PREFIX) :]
        if not tool_name:
            continue
        calls.append(
            ToolCallRequest(
                id=call_id or f"codebuddy_tool_{len(calls)}",
                name=tool_name,
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    return calls


def _reasoning_options(reasoning_effort: str | None) -> dict[str, Any]:
    """Map DeepTutor reasoning levels to CodeBuddy SDK thinking controls.

    The SDK enables adaptive thinking when the field is omitted, unlike the
    local CodeBuddy CLI configuration. Defaulting to disabled keeps ordinary
    chat latency aligned with the CLI; an explicit effort turns it back on.
    """
    effort = (reasoning_effort or "").strip().lower()
    if effort in {"low", "medium", "high", "xhigh"}:
        return {"thinking": {"type": "adaptive"}, "effort": effort}
    if effort == "adaptive":
        return {"thinking": {"type": "adaptive"}}
    return {"thinking": {"type": "disabled"}}


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").strip() or "user"
        content = _content_text(message.get("content"))
        if not content:
            continue
        if role == "system":
            heading = "System instructions"
        elif role == "assistant":
            heading = "Assistant"
        elif role == "tool":
            name = message.get("name") or message.get("tool_call_id") or "tool"
            heading = f"Tool result ({name})"
        else:
            heading = "User"
        sections.append(f"{heading}:\n{content}")

    return "\n\n".join(sections) if sections else ""


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_part_text(content)
    if isinstance(content, list):
        parts = [_content_part_text(part) for part in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def _content_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(part)
    part_type = part.get("type")
    if part_type in {"text", "input_text", "output_text"}:
        return str(part.get("text") or "")
    if "text" in part and isinstance(part.get("text"), str):
        return str(part["text"])
    if part_type in {"image_url", "input_image"}:
        return "[image input omitted]"
    return ""


def _assistant_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        content = [content]

    chunks: list[str] = []
    for block in content:
        text = _block_text(block)
        if text:
            chunks.append(text)
    return "".join(chunks)


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        block_type = block.get("type")
        if block_type in {"text", "assistant_text"} or "text" in block:
            return str(block.get("text") or "")
        return ""
    block_type = type(block).__name__
    if block_type == "TextBlock" or hasattr(block, "text"):
        return str(getattr(block, "text") or "")
    return ""


def _is_result_message(message: Any) -> bool:
    message_type = type(message).__name__
    if message_type == "ResultMessage" or message_type.endswith("ResultMessage"):
        return True
    if hasattr(message, "result") and hasattr(message, "is_error"):
        return True
    return isinstance(message, dict) and str(message.get("type") or "").lower() == "result"


def _is_error_result(message: Any) -> bool:
    if not _is_result_message(message):
        return False
    if isinstance(message, dict):
        return bool(message.get("is_error") or message.get("error"))
    return bool(getattr(message, "is_error", False) or getattr(message, "error", None))


def _result_text(message: Any) -> str:
    if isinstance(message, dict):
        value = message.get("result") or message.get("error") or message.get("content")
    else:
        value = getattr(message, "result", None) or getattr(message, "error", None)
    return "" if value is None else str(value)
