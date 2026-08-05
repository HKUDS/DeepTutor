"""Value-level redaction shared by the media worker and adapters (MED-02).

§10.5/§14 require that provider/MCP error text and durable job/artifact
metadata never carry credentials, auth headers, cookies, full private URLs,
percent-encoded credential values, or base64 payloads.  This module owns the
single sanitizer used by the worker (persisted errors, request snapshots) and
by the adapters (structured MCP error text) so every persistence/log surface
uses the identical rules.
"""

from __future__ import annotations

import re
from typing import Any

#: Value-level secret patterns.  Order matters: the Authorization-header and
#: cookie patterns run before the generic labeled-value pattern so the whole
#: ``Authorization: <scheme> <credential>`` header (any scheme) and the entire
#: cookie value (which may contain ``;`` separators) collapse to ``***``.
_SECRET_VALUE_PATTERNS = (
    # OpenAI-style secret keys.
    re.compile(r"(sk-[A-Za-z0-9_\-]{6,})"),
    # Complete Authorization header for any scheme (Bearer, Basic, ...).
    re.compile(
        r"(authorization\s*[:=]\s*)(?:[A-Za-z0-9._~+/=\-]+\s+)?[A-Za-z0-9._~+/=\-]+",
        re.IGNORECASE,
    ),
    # Complete cookie value (spans ';'-separated fields).
    re.compile(r"(cookie\s*[:=]\s*)[^\r\n]+", re.IGNORECASE),
    # Labeled token/secret/password values (including percent-encoded values).
    re.compile(
        r"\b(api[_-]?key|token|secret|password|passwd|"
        r"session[_-]?id|auth[_-]?token|access[_-]?token|refresh[_-]?token)"
        r"\s*[:=]\s*[^\s,;]+",
        re.IGNORECASE,
    ),
)

#: Credential-bearing dict keys that are redacted wherever they appear inside a
#: request snapshot (top level or nested, e.g. ``headers.Authorization``).
_CREDENTIAL_KEY_RE = re.compile(
    r"(^|[._\-])(api[_-]?key|apikey|token|secret|password|passwd|cookie|"
    r"authorization|credential|auth[_-]?token|access[_-]?token|refresh[_-]?token)"
    r"([._\-]|$)",
    re.IGNORECASE,
)

#: A base64 data URI, e.g. ``data:image/png;base64,`` (metadata parameters such
#: as ``;charset=utf-8`` are allowed).  Precise so prose that merely mentions
#: "base64" is not mistaken for a payload.
_BASE64_DATA_URI_RE = re.compile(r"data:[^,]*;base64,", re.IGNORECASE)

#: Longest contiguous base64-alphabet token that can still be ordinary prose.
#: 64 base64 characters decode to >= 48 bytes of data — far beyond any
#: natural-language word (the longest common English words are < 45
#: characters) — so even a 128+ character prompt made of plain words separated
#: by spaces contains no such token and passes through byte-for-byte intact.
_BASE64_TOKEN_MIN_LENGTH = 64

_BASE64_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=]+")

#: Full http(s) URLs including scheme, userinfo, host, port, path, query and
#: fragment.  Collapsed entirely: a private endpoint, its host/path, and any
#: query that carries a credential must never survive into a durable record or
#: a log line (§14).
_URL_RE = re.compile(r"(?i)https?://[^\s<>\"']+")


def _normalize_key(key: str) -> str:
    """Collapse a dict key to a canonical form for forbidden-key matching.

    Lowercases and strips separators so snake, camel and mixed-case aliases of
    the same identity key are all recognized (``Previous_Response_ID``,
    ``previousResponseId`` and ``previous_response_id`` all become
    ``previousresponseid``).  A caller cannot bypass the server-owned
    continuation rule by changing only the casing or separator style.
    """
    return re.sub(r"[^a-z0-9]", "", (key or "").lower())


def looks_like_base64_payload(text: str) -> bool:
    """True when *text* embeds a base64 image payload that must not be
    persisted into metadata JSON (§10.5).

    Detection is precise: a ``data:...;base64,`` URI, or a sufficiently long
    *contiguous* base64 token (``+``/``/``/``=`` padding optional), is a payload
    and is redacted.  Ordinary natural-language prompts — even 128+ character
    runs of plain words separated by spaces with no punctuation — contain no
    such contiguous token and are preserved byte-for-byte.
    """
    if _BASE64_DATA_URI_RE.search(text):
        return True
    return any(len(token) >= _BASE64_TOKEN_MIN_LENGTH for token in _BASE64_TOKEN_RE.findall(text))


def _collapse_url(match: re.Match[str]) -> str:
    return "[url]"


def redact_text(text: str) -> str:
    """Redact secret values and full URLs from a string without truncating it."""
    text = str(text or "")
    # Collapse full URLs first so host, path, query and any embedded credentials
    # never reach the later value-level patterns or the persisted result.
    text = _URL_RE.sub(_collapse_url, text)
    for index, pattern in enumerate(_SECRET_VALUE_PATTERNS):
        if index == 0:
            text = pattern.sub("sk-***", text)
        else:
            text = pattern.sub(r"\1***", text)
    if looks_like_base64_payload(text):
        return "[REDACTED base64 payload]"
    return text


def sanitize_snapshot(value: Any, *, strip_keys: frozenset[str] = frozenset()) -> Any:
    """Recursively sanitize a request snapshot.

    Credential-bearing keys are redacted in place; keys listed in *strip_keys*
    are dropped entirely (caller-injected remote/continuation references),
    matched case-insensitively and across common snake/camel separators so a
    caller cannot smuggle a forbidden identity key through casing alone.
    String values are passed through :func:`redact_text` so a leaked
    Authorization header, a private URL, or a base64 payload inside any value
    is also scrubbed.
    """
    strip_set = frozenset(_normalize_key(key) for key in strip_keys) if strip_keys else frozenset()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if strip_set and _normalize_key(key_text) in strip_set:
                continue
            if _CREDENTIAL_KEY_RE.search(key_text):
                out[key_text] = "[REDACTED]"
            else:
                out[key_text] = sanitize_snapshot(item, strip_keys=strip_keys)
        return out
    if isinstance(value, list):
        return [sanitize_snapshot(item, strip_keys=strip_keys) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


__all__ = [
    "looks_like_base64_payload",
    "redact_text",
    "sanitize_snapshot",
]
