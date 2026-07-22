#!/usr/bin/env python
"""
Robust JSON parsing utilities with automatic repair and markdown extraction.

Provides safe JSON parsing that handles:
- Markdown code block wrapping (```json...```)
- Malformed JSON (missing commas, trailing commas, etc.)
- Unescaped newlines and control characters
- Empty responses
"""

import json
import logging
import re
from typing import Any

_repair_json_fn: Any = None

try:
    from json_repair import repair_json as _repair_json_import
except ImportError:
    pass
else:
    _repair_json_fn = _repair_json_import

# Keep a public alias so tests and callers can patch the repair hook directly.
repair_json = _repair_json_fn

logger = logging.getLogger(__name__)

_UNSET = object()


def parse_json_response(
    response: str,
    logger_instance: Any = None,
    fallback: Any = _UNSET,
) -> Any:
    """
    Safely parse JSON from LLM responses with automatic repair.

    Implements a three-tier parsing strategy:
    1. Extract JSON from markdown code blocks if present
    2. Direct JSON parsing
    3. Automated repair using json-repair library with fallback

    Args:
        response: Raw string response from LLM
        logger_instance: Logger instance for debugging (optional)
        fallback: Value to return if all parsing fails.
                  Pass ``None`` explicitly to get ``None`` on failure;
                  omit the argument (or leave default) to get ``{}``.

    Returns:
        Parsed JSON object, or fallback value if parsing fails

    Example:
        >>> response = '```json\\n{"key": "value"}\\n```'
        >>> data = parse_json_response(response)
        >>> data
        {'key': 'value'}
    """
    log = logger_instance or logger

    if fallback is _UNSET:
        fallback = {}

    # Handle empty response
    if not response or not response.strip():
        log.warning("LLM returned empty response")
        return fallback

    # Extract from markdown code blocks if present
    extracted_response = response
    if "```" in response:
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)```", response, re.DOTALL)
        if json_match:
            extracted_response = json_match.group(1).strip()
            log.debug("Extracted JSON from markdown code block")

    # Strategy 1: Direct parsing
    try:
        return json.loads(extracted_response)
    except (json.JSONDecodeError, TypeError) as parse_error:
        log.debug(f"Direct JSON parse failed: {parse_error}")

    # Strategy 2: Try json-repair if available
    if repair_json is None:
        log.warning("json-repair library not installed, cannot repair malformed JSON")
        log.debug(f"Response: {extracted_response[:200]}")
        return fallback

    try:
        log.debug("Attempting JSON repair")
        repaired = repair_json(extracted_response)
        result = json.loads(repaired)
        log.info("Successfully repaired malformed JSON")
        return result
    except Exception as repair_error:
        # Most callers use this helper as best-effort parsing with an explicit
        # fallback. Non-JSON prose is common in LLM/tool output and should not
        # look like a backend failure when the caller can safely continue.
        log.debug(f"JSON repair failed: {repair_error}")
        log.debug(f"Response: {extracted_response[:200]}")
        return fallback


def safe_json_loads(data: str, fallback: Any = _UNSET) -> Any:
    """
    Simple wrapper for safe JSON loading.

    Args:
        data: JSON string
        fallback: Value to return on failure (default: {})

    Returns:
        Parsed JSON or fallback value
    """
    if fallback is _UNSET:
        fallback = {}
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"JSON parse error: {e}")
        return fallback
