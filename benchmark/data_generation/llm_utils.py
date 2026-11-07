#!/usr/bin/env python
"""
LLM Utilities for Benchmark Data Generation

Provides:
- Prompt template loading (from benchmark/prompts/*.yaml)
- Unified LLM calling with JSON parsing (via src.services.llm.factory)
- Template rendering
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("benchmark.llm_utils")

# Project root: benchmark/data_generation/llm_utils.py → project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _normalize_json_like_text(text: str) -> str:
    """Normalize common LLM artifacts before JSON parsing."""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\ufeff", "").replace("\x00", "").strip()
    # Normalize smart quotes that occasionally appear in model outputs.
    text = (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
    )
    return text


def _cleanup_json_candidate(candidate: str) -> str:
    """Best-effort cleanup for a JSON substring candidate."""
    s = _normalize_json_like_text(candidate)
    # If a fence label leaked into content, strip it.
    if s.lower().startswith("json"):
        s = s[4:].lstrip()
    # Remove trailing commas before object/array close.
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _repair_incomplete_json_object(text: str) -> str:
    """Best-effort repair for truncated JSON object text.

    Strategy:
    - Keep content from the first '{' onward (object-only fallback path).
    - Track string/escape states while balancing {} and [].
    - If output ends inside a string, close it.
    - Append missing closing brackets/braces.
    - Remove trailing commas before closers.
    """
    s = _normalize_json_like_text(text)
    start = s.find("{")
    if start == -1:
        return ""
    s = s[start:]

    out: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False

    for ch in s:
        out.append(ch)

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
            continue
        if ch in "}]":
            if stack:
                top = stack[-1]
                if (top == "{" and ch == "}") or (top == "[" and ch == "]"):
                    stack.pop()
            continue

    repaired = "".join(out)
    if in_string:
        repaired += '"'

    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"

    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _yield_json_candidates(text: str):
    """Yield likely JSON substrings from noisy LLM output."""
    t = _normalize_json_like_text(text)
    if not t:
        return

    # Candidate 1: full response
    yield t

    # Candidate 2: fenced code blocks (prefer explicit json fences)
    for m in re.finditer(r"```json\s*(.*?)\s*```", t, re.DOTALL | re.IGNORECASE):
        yield m.group(1)
    for m in re.finditer(r"```(.*?)```", t, re.DOTALL):
        yield m.group(1)

    # Candidate 3: streaming scan with JSONDecoder from each possible start.
    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(t) if ch in "{["]
    for idx in starts:
        try:
            _, end = decoder.raw_decode(t, idx)
            yield t[idx:end]
        except Exception:
            continue


def load_prompt(prompt_name: str) -> dict:
    """
    Load a prompt template from benchmark/prompts/.

    Args:
        prompt_name: Prompt file name without extension (e.g., "generate_profile")

    Returns:
        dict with 'system' and 'user_template' keys
    """
    prompt_path = PROJECT_ROOT / "benchmark" / "prompts" / f"{prompt_name}.yaml"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")

    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyYAML is required for loading benchmark prompt templates. "
            "Install it in the active Python environment with: python3 -m pip install PyYAML"
        ) from exc

    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def call_llm(
    user_prompt: str,
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    **kwargs,
) -> str:
    """
    Call LLM via the project's unified LLM factory.

    Uses src.services.llm.factory.complete() which handles provider routing,
    retry with exponential backoff, etc.

    Args:
        user_prompt: User prompt text
        system_prompt: System prompt text
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        **kwargs: Additional arguments (model, api_key, base_url overrides)

    Returns:
        LLM response text
    """
    from src.services.llm import factory

    return await factory.complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


async def call_llm_json(
    user_prompt: str,
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    **kwargs,
) -> dict:
    """
    Call LLM and parse response as JSON.

    Attempts multiple strategies to extract valid JSON from the response.

    Args:
        user_prompt: User prompt text
        system_prompt: System prompt text
        temperature: Sampling temperature
        max_tokens: Maximum tokens in response
        **kwargs: Additional arguments passed to call_llm

    Returns:
        Parsed JSON dictionary

    Raises:
        json.JSONDecodeError: If response cannot be parsed as JSON
    """
    response = await call_llm(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )

    return extract_json(response)


def extract_json(text: str) -> dict:
    """
    Extract JSON from text that may contain markdown code fences or extra text.

    Args:
        text: Raw text potentially containing JSON

    Returns:
        Parsed JSON dictionary
    """
    normalized = _normalize_json_like_text(text)
    if not normalized:
        raise json.JSONDecodeError("Empty LLM response, no JSON to parse", text, 0)

    last_error: Exception | None = None
    for candidate in _yield_json_candidates(normalized):
        cleaned = _cleanup_json_candidate(candidate)
        if not cleaned:
            continue
        try:
            parsed = json.loads(cleaned)
        except Exception as e:
            last_error = e
            continue

        if isinstance(parsed, dict):
            return parsed
        # Tolerate list-wrapped single object: [{...}]
        if (
            isinstance(parsed, list)
            and len(parsed) == 1
            and isinstance(parsed[0], dict)
        ):
            return parsed[0]

    # Final fallback: repair likely-truncated object and parse once.
    repaired = _repair_incomplete_json_object(normalized)
    if repaired:
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
            if (
                isinstance(parsed, list)
                and len(parsed) == 1
                and isinstance(parsed[0], dict)
            ):
                return parsed[0]
        except Exception as e:
            last_error = e

    preview = normalized[:240].replace("\n", "\\n")
    msg = f"Cannot extract JSON from LLM response (preview='{preview}')"
    if isinstance(last_error, json.JSONDecodeError):
        raise json.JSONDecodeError(msg, normalized, last_error.pos)
    raise json.JSONDecodeError(msg, normalized, 0)


def render_prompt(template: str, **kwargs) -> str:
    """
    Render a prompt template with the given variables.

    Args:
        template: Template string with {variable} placeholders
        **kwargs: Variables to substitute

    Returns:
        Rendered prompt string
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"Missing template variable: {e}")
