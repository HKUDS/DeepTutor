"""Portable filename normalization for stored user attachments."""

import re

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_filename(name: str) -> str:
    """Replace unsafe path / control characters; ``.`` / ``..`` become empty."""
    cleaned = _CONTROL_CHARS.sub("", _UNSAFE_CHARS.sub("_", name or "")).strip().strip(".")
    return cleaned
