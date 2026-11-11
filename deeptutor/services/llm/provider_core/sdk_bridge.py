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
    rejected_tool_errors: list[str] = []
    async for message in messages:
        if _is_error_result(message):
            return LLMResponse(
                content=f"Error calling {label}: {_error_detail(message, rejected_tool_errors)}",
                finish_reason="error",
            )
        if _is_result_message(message):
            pending_result_text = _result_text(message)
            continue

        rejected_tool_errors.extend(_tool_result_errors(message))
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


def _result_errors(message: Any) -> list[str]:
    """The CLI's own prose for a failed turn (``errors: [...]``).

    ``ResultMessage.errors`` is where the CLI puts the sentence a human should
    read — ``"Reached maximum number of turns (1)"``, the unavailable-tool
    rejection, an API failure. It is normally the *only* place: a turn that
    ends on ``error_max_turns`` carries ``result=None``. The SDK's own
    ``_error_result_text`` prefers this field for the same reason.
    """
    if isinstance(message, dict):
        raw = message.get("errors")
    else:
        raw = getattr(message, "errors", None)
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, list):
        return []
    # Older or buggy emitters may put non-strings in the list.
    return [str(item).strip() for item in raw if isinstance(item, str) and item.strip()]


def _result_subtype(message: Any) -> str:
    """The CLI's own one-word verdict for the turn (``error_max_turns`` …)."""
    if isinstance(message, dict):
        value = message.get("subtype")
    else:
        value = getattr(message, "subtype", None)
    return str(value or "").strip()


def _result_api_status(message: Any) -> int | None:
    """HTTP status of the failing API call, when the CLI reports one."""
    if isinstance(message, dict):
        value = message.get("api_error_status")
    else:
        value = getattr(message, "api_error_status", None)
    return value if isinstance(value, int) else None


# Why a failed turn ended. The CLI reports these in ``subtype``; ``errors[]``
# is preferred when present, so this table is the fallback for frames that
# carry the subtype only.
_RESULT_FAILURES: dict[str, str] = {
    "error_max_turns": "the turn hit its maximum number of turns",
    "error_during_execution": "the CLI reported an error while running the turn",
    "error_max_budget_usd": "the turn hit its budget limit",
}


def _result_detail(message: Any) -> str:
    """An operator-facing reason for a failed SDK turn that is never blank.

    Sources, in the order the SDK itself prefers them (see
    ``claude_agent_sdk._internal.query._error_result_text``): ``errors[]``,
    then ``result``, then a non-``success`` ``subtype``, then the HTTP status.

    A turn that dies on the turn limit or on a rejected tool call ends with
    ``result=None`` and the prose in ``errors[]``; the old code read only
    ``result``, so a reported ``write_note`` failure reached the UI as
    ``"Error calling Claude Code: "`` with the cause nowhere on screen
    (#2539). Note that such a frame arrives as ``subtype: "success"`` when the
    run ended on an API failure, which is why the subtype is not the primary
    source.
    """
    errors = _result_errors(message)
    if errors:
        return "; ".join(errors)
    text = _result_text(message).strip()
    subtype = _result_subtype(message)
    if text:
        # Keep the CLI's wording first; the subtype is a machine-readable hint.
        return f"{text} ({subtype})" if subtype and subtype != "success" else text
    if subtype in _RESULT_FAILURES:
        return f"{_RESULT_FAILURES[subtype]} ({subtype})"
    if subtype and subtype != "success":
        return f"the CLI ended the turn without a result ({subtype})"
    status = _result_api_status(message)
    if status is not None:
        return f"the provider API call failed (HTTP {status})"
    return "the CLI ended the turn without a result and reported no reason"


def _error_detail(message: Any, rejected_tool_errors: list[str] | None = None) -> str:
    """The CLI's reason for the failed turn, plus rejected-tool evidence.

    Wraps ``_result_detail``, keeping the CLI's own fields (``errors[]``,
    ``result``, ``subtype``, HTTP status) in their priority order, and appends
    the text of tool calls the CLI rejected during the turn. A turn killed by
    ``max_turns`` right after a ``No such tool available`` rejection often
    carries the rejection only in a ``tool_result`` block, so without this the
    named cause would be lost (#2539). A rejection the CLI already reported in
    ``errors[]`` or ``result`` is not repeated.
    """
    detail = _result_detail(message)
    for error in rejected_tool_errors or []:
        if not error:
            continue
        # A ``tool_result`` block often wraps the sentence the CLI already
        # reported (an ``Error: `` prefix around it); containment either way
        # marks it as the same fact, not new evidence.
        if error in detail or detail in error:
            continue
        detail = f"{detail}; rejected tool call: {error}"
    return detail


def _tool_result_errors(message: Any) -> list[str]:
    """Error text carried by ``tool_result`` blocks — e.g. a rejected tool call.

    When the CLI rejects a tool call the model made (``No such tool
    available: <name>``), the rejection only surfaces as an error
    ``tool_result`` on a user message. Collect it so a turn that dies right
    afterwards can still report an actionable cause (#2539).
    """
    blocks: list[Any] = []
    containers = [message]
    if isinstance(message, dict):
        inner = message.get("message")
    else:
        inner = getattr(message, "message", None)
    if inner is not None:
        containers.append(inner)
    for container in containers:
        content = (
            container.get("content")
            if isinstance(container, dict)
            else getattr(container, "content", None)
        )
        if isinstance(content, list):
            blocks.extend(content)

    errors: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            block_type = str(block.get("type") or "")
            is_error = bool(block.get("is_error"))
            raw = block.get("content")
            if raw is None:
                raw = block.get("text")
        else:
            block_type = str(getattr(block, "type", "") or "")
            is_error = bool(getattr(block, "is_error", False))
            raw = getattr(block, "content", None)
            if raw is None:
                raw = getattr(block, "text", None)
        if "tool_result" not in block_type:
            continue
        text = _content_text(raw).strip()
        if not is_error and "<tool_use_error>" not in text:
            continue
        cleaned = text.replace("<tool_use_error>", "").replace("</tool_use_error>", "").strip()
        if cleaned:
            errors.append(cleaned)
    return errors
