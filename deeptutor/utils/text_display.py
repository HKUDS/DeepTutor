"""Helpers for learner-facing text that models sometimes double-encode."""

from __future__ import annotations

import json
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
        # Decode the run as a JSON string, like the web decoder's JSON.parse:
        # characters outside the BMP (emoji, math letters) arrive as UTF-16
        # surrogate pairs that must be joined into one code point.
        # ``unicode_escape`` keeps the two halves as lone surrogates, which
        # UTF-8 cannot encode.
        try:
            decoded = json.loads(f'"{run}"')
        except ValueError:
            return run
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in decoded):
            # An unpaired surrogate is not text; keep the escapes visible.
            return run
        if any(ord(ch) > 0x7F for ch in decoded):
            return decoded
        return run

    return _ESCAPED_UNICODE_RUN.sub(_replace, text)


__all__ = ["decode_escaped_unicode_for_display"]
