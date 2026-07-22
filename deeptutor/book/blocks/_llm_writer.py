"""
Shared LLM helper for text-flavoured block generators.

Avoids subclassing BaseAgent for these tiny calls; instead uses
``deeptutor.services.llm.complete`` directly with a sane default config.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.services.llm import (
    clean_thinking_tags,
    get_llm_config,
    get_token_limit_kwargs,
)
from deeptutor.services.llm import (
    complete as llm_complete,
)
from deeptutor.services.prompt.language import append_language_directive
from deeptutor.utils.json_parser import parse_json_response


async def llm_text(
    *,
    user_prompt: str,
    system_prompt: str,
    max_tokens: int = 1200,
    temperature: float = 0.4,
    response_format: dict[str, Any] | None = None,
    language: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Run an LLM completion for a Book block / agent.

    Pass ``language`` (the book's chosen language code, e.g. ``"zh"`` or
    ``"en"``) and the helper appends a strict language directive to the
    system prompt. This is the single chokepoint that prevents the LLM from
    drifting between languages when prompts contain English token names,
    JSON keys, or non-matching source material.
    """
    if language:
        system_prompt = append_language_directive(system_prompt, language)

    config = get_llm_config()
    model = config.model
    binding = getattr(config, "binding", None) or "openai"
    kwargs: dict[str, Any] = {"temperature": temperature}
    kwargs.update(get_token_limit_kwargs(model, max_tokens))
    if response_format:
        kwargs["response_format"] = response_format
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    response = await llm_complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=model,
        api_key=config.api_key,
        base_url=config.base_url,
        api_version=getattr(config, "api_version", None),
        binding=binding,
        **kwargs,
    )
    return clean_thinking_tags(response, binding, model).strip()


def _normalize_json_payload(data: Any, expected_key: str | None = None) -> dict[str, Any]:
    """Normalize common LLM JSON shapes into an object for block generators."""
    if isinstance(data, dict):
        return data

    if isinstance(data, list):
        if expected_key:
            if len(data) == 1 and isinstance(data[0], dict) and expected_key in data[0]:
                return data[0]
            return {expected_key: data}
        if len(data) == 1 and isinstance(data[0], dict):
            return data[0]

    return {}


def _json_has_expected(data: dict[str, Any], expected_key: str | None) -> bool:
    if not data:
        return False
    if expected_key is None:
        return True
    value = data.get(expected_key)
    return bool(value)


def _strip_thinking_preamble(text: str) -> str:
    """Strip model thinking/reasoning preamble before JSON output.

    Some local/Qwen models output reasoning text (e.g. "Here's a thinking
    process:...") even when ``response_format`` is ``json_object``.  The
    reasoning text often contains backtick-quoted JSON templates with `{`
    characters, so finding the *first* ``{`` is wrong.  Instead we find the
    **last** ``{`` in the response — the actual JSON output comes after the
    thinking text, and a top-level JSON object starts with its opening brace.
    """
    if not text:
        return text
    if "{" not in text:
        # No JSON object present (refusal / plain prose) — return as-is so the
        # caller's json-repair fallback can decide, instead of raising here.
        return text
    # Find the last '{' — that's where the actual JSON object starts
    brace = text.rindex("{")
    if brace > 0:
        candidate = text[brace:]
        # Quick check: can json.loads parse it?
        try:
            json.loads(candidate)
            return candidate  # Valid JSON -> use it
        except (json.JSONDecodeError, ValueError):
            pass  # Not valid JSON, fall through to original approach
    # Fallback: try the first '{' with the thinking-heuristic check
    brace = text.index("{")
    if brace > 0:
        before = text[:brace].strip()
        if (
            not before
            or before.lower().startswith(
                ("here", "think", "let me", "ok", "okay", "i will", "first", "note", "so")
            )
            or before.rstrip(".").isdigit()
        ):
            return text[brace:]
    return text


async def llm_json(
    *,
    user_prompt: str,
    system_prompt: str,
    max_tokens: int = 2600,
    temperature: float = 0.4,
    language: str | None = None,
    expected_key: str | None = None,
) -> dict[str, Any]:
    """Run a structured JSON LLM call with robust parsing and one safe retry.

    Reasoning models can spend the whole response budget on hidden/scratchpad
    tokens and leave the visible JSON object empty. For structured book blocks
    we first honor the configured reasoning mode, then retry once with low
    reasoning effort if parsing fails or the expected top-level key is missing.
    ("low" rather than "minimal": local/Qwen models served via vLLM reject
    "minimal", and "minimal" disables thinking entirely.)

    Also strips thinking/reasoning preamble text (common with local models)
    before JSON parsing.
    """

    async def _once(reasoning_effort: str | None) -> dict[str, Any]:
        raw = await llm_text(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            # Floor of 2600: room for thinking + JSON, but let callers raise it.
            max_tokens=max(max_tokens, 2600),
            temperature=temperature,
            language=language,
            reasoning_effort=reasoning_effort,
        )
        # First pass: strip thinking preamble (Qwen outputs thinking text
        # even with json_object format), then let parse_json_response handle
        # what remains via its json-repair fallback.
        cleaned = _strip_thinking_preamble(raw)
        parsed = parse_json_response(cleaned, fallback={})
        if parsed:
            return _normalize_json_payload(parsed, expected_key=expected_key)
        # Second pass: if stripping failed, feed the raw response to
        # parse_json_response — json-repair may extract JSON from mixed text.
        recovered = parse_json_response(raw, fallback={})
        return _normalize_json_payload(recovered, expected_key=expected_key)

    data = await _once(None)
    if _json_has_expected(data, expected_key):
        return data

    retry_data = await _once("low")
    if _json_has_expected(retry_data, expected_key):
        retry_data.setdefault("_metadata", {})["reasoning_retry"] = "low"
        return retry_data
    return data or retry_data


__all__ = ["llm_json", "llm_text"]
