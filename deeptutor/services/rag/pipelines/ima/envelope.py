"""The response envelope every Tencent IMA OpenAPI call answers with.

Both IMA modules (``/openapi/wiki/v1`` and ``/openapi/note/v1``) wrap their
payload in a status envelope and return HTTP 200 even for business failures, so
unwrapping it is where *all* IMA error handling happens. This module is the one
place that knows its shape, and the exception classes it raises live here too —
the envelope's status code is what decides which one a caller sees.

Field names
-----------
IMA's own reference documents the envelope as ``{"retcode", "errmsg", "data"}``
while live responses have also been observed using ``{"code", "msg", "data"}``.
Both spellings are accepted (:data:`_CODE_KEYS` / :data:`_MESSAGE_KEYS`): a
mismatch here would not degrade gracefully — reading only one spelling turns
every successful call into "request failed with code None", which is exactly the
kind of failure a wire-format assumption should never be able to cause.

Status codes worth naming are the two classes a caller reacts to differently
from a generic failure: rejected credentials and rate limiting. Everything else
surfaces IMA's own message, which the API documents as safe to show the user.
"""

from __future__ import annotations

from typing import Any

# Accepted spellings of the envelope's status fields, in priority order.
_CODE_KEYS: tuple[str, ...] = ("retcode", "code")
_MESSAGE_KEYS: tuple[str, ...] = ("errmsg", "msg")

# Credential rejection: the client id / API key pair was refused.
_CREDENTIAL_CODES = frozenset({20004, 200002})

# Rate limiting: the key exceeded its call frequency. Both modules' codes.
_RATE_LIMIT_CODES = frozenset({20002, 110021})

# Transient upstream failures IMA documents as retryable. Mapped to a plain
# API error, but with a message that says so.
_RETRYABLE_CODES = frozenset({110010, 100003})


class ImaAPIError(RuntimeError):
    """Raised when IMA returns an error envelope or an unexpected payload."""


class ImaAuthError(ImaAPIError):
    """Raised when IMA rejects the client id / API key pair."""


class ImaRateLimitError(ImaAPIError):
    """Raised when IMA rate-limits the request."""


def unwrap(payload: Any, *, status_code: int) -> dict[str, Any]:
    """Return the envelope's ``data`` object, or raise the mapped error.

    ``status_code`` is the HTTP status the payload arrived with; it only matters
    when the body is unusable, so the raised message can name it.
    """
    if not isinstance(payload, dict):
        raise ImaAPIError(f"IMA returned an unexpected payload with status {status_code}.")

    code = _first_present(payload, _CODE_KEYS)
    message = _message_of(payload)
    if _is_success(code):
        data = payload.get("data")
        return data if isinstance(data, dict) else {}
    if code in _CREDENTIAL_CODES:
        raise ImaAuthError(message or "IMA rejected the client ID / API key.")
    if code in _RATE_LIMIT_CODES:
        raise ImaRateLimitError(message or "IMA rate limit reached.")
    if code in _RETRYABLE_CODES:
        raise ImaAPIError(message or f"IMA is temporarily unavailable (code {code}). Try again.")
    if code is None:
        # Neither spelling present: the body is not an IMA envelope at all.
        raise ImaAPIError(f"IMA returned an unrecognized response with status {status_code}.")
    raise ImaAPIError(message or f"IMA request failed with code {code}.")


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    """The first key's value coerced to int, or ``None`` when none is usable."""
    for key in keys:
        if key not in payload:
            continue
        try:
            return int(payload[key])
        except (TypeError, ValueError):
            continue
    return None


def _message_of(payload: dict[str, Any]) -> str:
    for key in _MESSAGE_KEYS:
        value = payload.get(key)
        if value:
            return str(value).strip()
    return ""


def _is_success(code: int | None) -> bool:
    return code == 0


__all__ = [
    "ImaAPIError",
    "ImaAuthError",
    "ImaRateLimitError",
    "unwrap",
]
