"""Shared text shaping for the notebook agents."""

from __future__ import annotations


def clip_text(value: str, limit: int) -> str:
    """Trim prose to *limit* characters, saying so when anything was cut."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


__all__ = ["clip_text"]
