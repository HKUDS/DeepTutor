"""Helpers for learner-facing text that models sometimes double-encode."""

from __future__ import annotations

import codecs
import re

# Match dense JSON-style ``\\uXXXX`` runs (3+ escapes), mirroring the web
# markdown decoder so mastery / ask_user cards do not leak literal escapes (#973).
_ESCAPED_UNICODE_RUN = re.compile(r"(?:\\u[0-9a-fA-F]{4}){3,}")


def decode_escaped_unicode_for_display(text: str) -> str:
    """Decode dense ``\\uXXXX`` runs when they clearly represent non-ASCII text."""
    if not text or "\\u" not in text:
        return text

    def _replace(match: re.Match[str]) -> str:
        run = match.group(0)
        try:
            decoded = codecs.decode(run, "unicode_escape")
        except (UnicodeDecodeError, ValueError):
            return run
        if any(ord(ch) > 0x7F for ch in decoded):
            return decoded
        return run

    return _ESCAPED_UNICODE_RUN.sub(_replace, text)


__all__ = ["decode_escaped_unicode_for_display"]
