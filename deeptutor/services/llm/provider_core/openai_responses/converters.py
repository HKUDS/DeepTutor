"""Convert Chat Completions messages/tools to Responses API format."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

from deeptutor.services.session.provider_response_state import (
    normalize_provider_response_state,
)

_CHAT_TOKEN_LIMIT_ALIASES = ("max_completion_tokens", "max_tokens")


def _replay_output_item(item: dict[str, Any]) -> dict[str, Any]:
    """Copy a persisted output item for replay as an input item.

    The SDK's ``model_dump()`` writes ``"status": None`` for an item that came
    back without one, as a ``reasoning`` item usually does. The Responses API
    rejects that null on input (``unknown_parameter`` on ``input[N].status``),
    so an unset status is left out. A status the provider did send is kept.
    """
    replayed = dict(item)
    if replayed.get("status") is None:
        replayed.pop("status", None)
    return replayed


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
            state = normalize_provider_response_state(msg.get("_provider_response_state"))
            state_items = state.get("responses_output_items") if state is not None else None
            if not isinstance(state_items, list):
                legacy_state = normalize_provider_response_state(
                    {"responses_output_items": msg.get("_responses_output_items")}
                )
                state_items = (
                    legacy_state.get("responses_output_items") if legacy_state is not None else None
                )
            if isinstance(state_items, list) and state_items:
                input_items.extend(
                    _replay_output_item(item) for item in state_items if isinstance(item, dict)
                )
                continue
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
            output_text = (
                content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            )
            input_items.append(
                {"type": "function_call_output", "call_id": call_id, "output": output_text}
            )

    return system_prompt, input_items


# GPT-5.6 introduced explicit cache breakpoints in the Responses API.
_EXPLICIT_CACHE_MODEL = re.compile(r"^gpt-(\d+)(?:\.(\d+))?")


def supports_explicit_prompt_cache(model: str | None) -> bool:
    """Whether *model* accepts ``prompt_cache_options``/breakpoints."""
    name = str(model or "").strip().lower().rsplit("/", 1)[-1]
    match = _EXPLICIT_CACHE_MODEL.match(name)
    if match is None:
        return False
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return (major, minor) >= (5, 6)


# Responses allows four cache writes per request. A sliding window of the
# last four durable user messages keeps the previous turn's newest breakpoint
# present in the next request, so the lookup can match the cache entry it just
# wrote instead of only the newest (still uncached) boundary.
_EXPLICIT_CACHE_BREAKPOINTS = 4


def mark_stable_history_breakpoint(input_items: list[dict[str, Any]]) -> bool:
    """Place explicit cache breakpoints before the trailing user block.

    The answer loop appends the current runtime snapshot and the learner's
    message as consecutive ``user`` items. Everything before them is durable,
    but the last durable item is usually the assistant reply, whose
    ``output_text`` block cannot carry ``prompt_cache_breakpoint``. Step back
    to durable user messages: their ``input_text`` blocks are supported
    breakpoints and the next turn's prefix still matches.

    Marking a sliding window (not just the newest message) is what makes the
    previous turn's cache entry discoverable: the new request must still
    contain the breakpoint boundary that the old request wrote.
    """

    last_user = None
    for index, item in enumerate(input_items):
        if item.get("role") == "user":
            last_user = index
    if last_user is None:
        return False

    start = last_user
    while start > 0 and input_items[start - 1].get("role") == "user":
        start -= 1

    marked = 0
    for index in range(start - 1, -1, -1):
        if marked >= _EXPLICIT_CACHE_BREAKPOINTS:
            break
        item = input_items[index]
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if block.get("type") == "input_text" and block.get("text"):
                block["prompt_cache_breakpoint"] = {"mode": "explicit"}
                marked += 1
                break
    return marked > 0


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


def convert_tools(
    tools: list[dict[str, Any]],
    *,
    native_web_search: bool = False,
) -> list[dict[str, Any]]:
    """Convert OpenAI function calling schemas to Responses API tools.

    Unset strict flags use the non-strict Chat Completions default. Explicit
    boolean settings are preserved, including an opt-in to strict validation.

    With ``native_web_search=True`` (providers whose Responses API performs
    web searches server-side, e.g. DeepSeek), DeepTutor's ``web_search``
    function tool is declared as the provider's native ``{"type":
    "web_search"}`` tool instead of a function schema: the server runs the
    search mid-generation and the response carries ``web_search_call`` items
    with ``url_citation`` annotations rather than a function call.
    """
    converted: list[dict[str, Any]] = []
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        if native_web_search and name == "web_search":
            converted.append({"type": "web_search"})
            continue
        params = fn.get("parameters") or {}
        item: dict[str, Any] = {
            "type": "function",
            "name": name,
            "description": fn.get("description") or "",
            "parameters": params if isinstance(params, dict) else {},
        }
        # Preserve Chat Completions' optional-parameter semantics. Responses
        # may normalize an omitted strict flag and require every field, conflicting
        # with tools whose optional arguments must genuinely be absent.
        strict = fn.get("strict")
        item["strict"] = strict if isinstance(strict, bool) else False
        converted.append(item)
    return converted


def convert_tool_choice(tool_choice: Any) -> Any:
    """Convert an OpenAI function-calling ``tool_choice`` for the Responses API.

    The two endpoints name a forced tool differently. Chat Completions nests
    it — ``{"type": "function", "function": {"name": "ask_user"}}`` — while the
    Responses API puts the name at the top level. Sending the nested shape to a
    Responses endpoint is rejected outright ("tool_choice: missing field
    `name`"), which killed every Ask Questions turn on a Responses-wire
    provider: that mode forces ``ask_user`` on its first round, so the whole
    capability failed before the model was ever called.

    Mode strings (``"auto"``, ``"none"``, ``"required"``) and shapes that
    already name the tool at the top level pass through unchanged, as does
    anything else — a hosted-tool choice is the provider's to validate, not
    ours to guess at.
    """
    if not isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice.get("type") != "function":
        return tool_choice
    if tool_choice.get("name"):
        return tool_choice
    name = (tool_choice.get("function") or {}).get("name")
    return {"type": "function", "name": name} if name else tool_choice


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

    Output formats use ``text.format`` instead of ``response_format``;
    JSON Schema options live directly in that format, without the chat
    endpoint's ``json_schema`` wrapper. Preserve other ``text`` options.

    Drops keys with ``None`` values to match the existing merge filter, and
    preserves explicitly supplied Responses format and token-limit values.
    """
    result = {
        key: value
        for key, value in extra_kwargs.items()
        if value is not None and key not in _CHAT_TOKEN_LIMIT_ALIASES
    }
    response_format = result.pop("response_format", None)
    if response_format is not None:
        text = dict(result.get("text") or {})
        if "format" not in text:
            if response_format.get("type") == "json_schema":
                text["format"] = {"type": "json_schema", **response_format["json_schema"]}
            else:
                text["format"] = response_format
        result["text"] = text

    if "max_output_tokens" in result:
        return result

    for key in _CHAT_TOKEN_LIMIT_ALIASES:
        value = extra_kwargs.get(key)
        if value is not None:
            result["max_output_tokens"] = value
            break
    return result
