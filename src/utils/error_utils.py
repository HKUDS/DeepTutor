#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Error Utilities - Error formatting and handling utilities
"""

import json
from typing import Optional


def _find_json_block(message: str) -> Optional[str]:
    """Extract potential JSON block from message by matching braces."""
    start_idx = message.find("{")
    if start_idx == -1:
        return None

    brace_count = 0
    in_string = False
    escape_next = False

    for char_idx in range(start_idx, len(message)):
        char = message[char_idx]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return message[start_idx : char_idx + 1]

    return None


def format_exception_message(exc: Exception) -> str:
    """
    Format exception message for better readability

    Args:
        exc: The exception to format

    Returns:
        Formatted error message
    """
    message = str(exc)

    # Try to parse JSON error messages (common in API errors)
    potential_json = _find_json_block(message)
    if potential_json:
        try:
            error_data = json.loads(potential_json)

            # Standard extraction logic
            if isinstance(error_data, dict) and "error" in error_data:
                error_info = error_data["error"]
                if isinstance(error_info, dict):
                    parts = []
                    if "message" in error_info:
                        parts.append(f"Message: {error_info['message']}")
                    if "type" in error_info:
                        parts.append(f"Type: {error_info['type']}")
                    if "code" in error_info:
                        parts.append(f"Code: {error_info['code']}")
                    if parts:
                        return " | ".join(parts)
        except (json.JSONDecodeError, AttributeError):
            pass

    # Return original message if parsing fails
    return message
