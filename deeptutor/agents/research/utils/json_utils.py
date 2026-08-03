#!/usr/bin/env python
"""
JSON Utils - JSON parsing and validation utilities
- Robustly extract JSON from LLM text output
- Provide strict structure validation and error messages
"""

import json
import re
from typing import Any, Dict, Iterable, List, Union


def extract_json_from_text(text: str) -> Union[Dict[str, Any], List[Any], None]:
    """
    Extract JSON object or array from text.
    Allows the following formats:
    1) Pure JSON text
    2) Code blocks wrapped in ```json ...``` or ``` ...```
    3) First JSON fragment {...} or [...] contained in text
    """
    if not text:
        return None

    # 1) Code block
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_block:
        snippet = code_block.group(1).strip()
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            pass

    # 2) Parse entire text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3) First JSON value in surrounding prose / adjacent values
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed

    return None


# --------- Strict Validation Utilities ---------


def ensure_json_dict(data: Any, err: str = "Expected JSON object") -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(err)
    return data


def ensure_json_list(data: Any, err: str = "Expected JSON array") -> List[Any]:
    if not isinstance(data, list):
        raise ValueError(err)
    return data


def ensure_keys(data: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    missing = [k for k in keys if k not in data]
    if missing:
        raise KeyError(f"Missing required keys: {', '.join(missing)}")
    return data


def safe_json_loads(text: str, default: Any = None) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def json_to_text(data: Any, indent: int = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


__all__ = [
    "extract_json_from_text",
    "ensure_json_dict",
    "ensure_json_list",
    "ensure_keys",
    "safe_json_loads",
    "json_to_text",
]
