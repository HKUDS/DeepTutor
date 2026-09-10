"""Reading one string out of a loaded prompt pack.

Prompt packs are nested YAML mappings, and every caller wants the same thing
from them: the string at a path, or a fallback when that path is missing,
holds a mapping, or holds an empty string. Seven modules used to carry their
own copy of this walk — six of them the ``default=""`` special case of the
seventh.
"""

from __future__ import annotations

from typing import Any


def prompt_text(prompts: dict[str, Any], path: tuple[str, ...], default: str = "") -> str:
    """The string at *path* inside *prompts*, or *default*."""
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return value if isinstance(value, str) and value else default


__all__ = ["prompt_text"]
