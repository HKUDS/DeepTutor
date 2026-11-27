"""Shared HTTP header builders.

Small, boring, and easy to get wrong in ways that only show up for non-English
users — so they live in one place rather than once per router.
"""

from __future__ import annotations

import re
from urllib.parse import quote

# C0 control characters (incl. CR/LF) have no place in a header value.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def content_disposition(filename: str, *, disposition: str = "inline") -> str:
    """Build a Content-Disposition header that survives non-ASCII filenames.

    HTTP/1.1 headers are latin-1, so dropping a Chinese / accented filename
    straight into ``filename="..."`` blows up with UnicodeEncodeError. RFC
    6266 / RFC 5987 cover this: emit ``filename*=UTF-8''<percent-encoded>``
    plus an ASCII fallback on ``filename=`` for legacy clients.
    """
    ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
    # Quotes / backslashes break the simple-quoted-string form; collapse them.
    ascii_fallback = ascii_fallback.replace('"', "_").replace("\\", "_")
    # Strip CR/LF and other control chars so the header value stays single-line
    # (a raw newline is a malformed header / response-splitting shape).
    ascii_fallback = _CONTROL_CHARS.sub("_", ascii_fallback)
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


__all__ = ["content_disposition"]
