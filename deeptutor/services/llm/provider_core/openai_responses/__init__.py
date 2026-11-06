"""Shared helpers for Responses API providers."""

from .converters import (
    adapt_chat_kwargs_to_responses,
    convert_messages,
    convert_tool_choice,
    convert_tools,
    convert_user_message,
    mark_stable_history_breakpoint,
    split_tool_call_id,
    supports_explicit_prompt_cache,
)
from .parsing import (
    FINISH_REASON_MAP,
    ToolArgsDeltaHook,
    consume_sdk_stream,
    consume_sse,
    iter_sse,
    map_finish_reason,
    parse_response_output,
)

__all__ = [
    "adapt_chat_kwargs_to_responses",
    "convert_messages",
    "convert_tool_choice",
    "convert_tools",
    "convert_user_message",
    "mark_stable_history_breakpoint",
    "supports_explicit_prompt_cache",
    "split_tool_call_id",
    "iter_sse",
    "consume_sse",
    "consume_sdk_stream",
    "map_finish_reason",
    "parse_response_output",
    "FINISH_REASON_MAP",
    "ToolArgsDeltaHook",
]
