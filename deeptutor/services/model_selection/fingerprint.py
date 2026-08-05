"""Deterministic, secret-safe fingerprints for model audit records (§7.8, §9.4).

Every value here is computed so that no API key, auth header, full private URL,
query value, or raw provider response ever appears in a serialized
``ModelInvocationRecord``, an ``EvaluatorSnapshot``, an error string, a log line
or an API-ready audit view. All fingerprints are stable SHA-256 truncations of
the *safe* identity only.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from deeptutor.services.config.model_catalog import sanitize_probe_message


def _stable_hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def base_url_fingerprint(base_url: str | None) -> str:
    """Fingerprint of the *authority* of a base URL.

    Only ``scheme://host:port`` is hashed. Userinfo, path, query and fragment
    are deliberately excluded so a private URL or a secret query value (e.g.
    ``?token=...``) never appears in persisted audit records (§14). An empty or
    missing URL yields ``""``.
    """
    if not base_url:
        return ""
    text = str(base_url)
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
    except ValueError:
        return _stable_hash(text)
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return _stable_hash(text)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None:
        port = 443 if scheme == "https" else 80
    return _stable_hash(f"{scheme}://{host}:{port}")


#: Keys that never participate in a profile revision (credentials/auth material).
_PROFILE_SECRET_KEYS = frozenset({"api_key", "extra_headers", "auth", "authorization"})
#: Volatile probe state that must not bump a revision (status/timestamps/messages).
_PROFILE_VOLATILE_PREFIX = "capability_probe_"


def _profile_key_included(key: str) -> bool:
    return (
        key not in _PROFILE_SECRET_KEYS
        and not key.startswith(_PROFILE_VOLATILE_PREFIX)
        and key != "base_url"
    )


def _profile_revision_model(model: dict[str, Any]) -> dict[str, Any]:
    """Project one model entry onto its revision-relevant fields.

    Every non-secret runtime-affecting field — including ``reasoning_effort``
    and context-window/runtime knobs — participates, so any such change bumps
    the profile revision. Secrets and volatile probe state never do.
    """
    out: dict[str, Any] = {}
    for key, value in model.items():
        if key in _PROFILE_SECRET_KEYS or key.startswith(_PROFILE_VOLATILE_PREFIX):
            continue
        out[str(key)] = "" if value is None else value
    return out


def profile_revision(profile: dict[str, Any] | None) -> str:
    """Deterministic revision of a profile's non-secret configuration.

    Only identity/config and runtime-affecting fields participate; ``api_key``
    and ``extra_headers`` never do, and volatile probe status/timestamps/
    messages are excluded. ``base_url`` is reduced to its fingerprint (not
    stored raw), and every non-secret model field — including
    ``reasoning_effort`` and context-window/runtime knobs — participates, so a
    request-affecting change always bumps the revision and historical
    invocations stay pinned to the revision they actually ran against (§9.4).
    """
    if not isinstance(profile, dict) or not profile:
        return ""
    payload: dict[str, Any] = {
        str(key): ("" if value is None else value)
        for key, value in profile.items()
        if _profile_key_included(str(key))
    }
    if "base_url" in profile:
        payload["base_url_fingerprint"] = base_url_fingerprint(str(profile.get("base_url") or ""))
    payload["models"] = [
        _profile_revision_model(model)
        for model in profile.get("models") or []
        if isinstance(model, dict)
    ]
    return _stable_hash(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def invocation_request_fingerprint(
    *,
    purpose: Any,
    profile_id: str = "",
    profile_revision: str = "",
    protocol: str = "",
    model: str = "",
    prompt_version: str = "",
    tool_schema_version: str = "",
) -> str:
    """Stable fingerprint of what an invocation *asked for* (config only)."""
    payload = {
        "purpose": str(getattr(purpose, "value", purpose) or ""),
        "profile_id": str(profile_id or ""),
        "profile_revision": str(profile_revision or ""),
        "protocol": str(protocol or ""),
        "model": str(model or ""),
        "prompt_version": str(prompt_version or ""),
        "tool_schema_version": str(tool_schema_version or ""),
    }
    return _stable_hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def invocation_response_fingerprint(
    *,
    status: Any,
    reported_model: str | None = None,
    error_code: str = "",
) -> str:
    """Stable fingerprint of the terminal outcome of an invocation."""
    payload = {
        "status": str(getattr(status, "value", status) or ""),
        "reported_model": str(reported_model or ""),
        "error_code": str(error_code or ""),
    }
    return _stable_hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))


#: Full URLs in an error string are scrubbed down to ``scheme://[REDACTED]`` so
#: a private host, path, query value (including percent-encoded secrets) or
#: userinfo can never be persisted or exposed.
_URL_RE = re.compile(r"(?i)\b((?:https?|ftp)://)[^\s'\"<>)\]},;]+")

#: Query-string parameter names whose values are treated as secrets. ``key`` is
#: deliberately broad because provider errors echo it both as ``?key=`` and as
#: an api-key form; the scrubber only applies this to query strings and
#: ``name=value`` pairs, never to prose.
_QUERY_SECRET_PARAMS = (
    "token",
    "key",
    "api_key",
    "apikey",
    "api-key",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "access_token",
    "refresh_token",
    "signature",
    "sig",
    "auth",
    "authorization",
    "session",
    "credential",
)
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:"
    + "|".join(re.escape(param) for param in _QUERY_SECRET_PARAMS)
    + r")=)[^&\s'\"<>)\]},;]+"
)
#: Header / JSON-style ``name: value`` secret forms (colon separator). Query
#: ``name=value`` pairs are handled separately by ``_QUERY_SECRET_RE`` so the
#: colon form never greedily consumes an ``&``-separated query string.
_FIELD_SECRET_NAMES = (
    "authorization",
    "proxy-authorization",
    "api-key",
    "apikey",
    "x-api-key",
    "x-goog-api-key",
    "token",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "access_token",
    "refresh_token",
    "api_key",
)
_FIELD_SECRET_RE = re.compile(
    r"(?i)([\"']?(?:"
    + "|".join(re.escape(name) for name in _FIELD_SECRET_NAMES)
    + r")\s*[\"']?\s*:\s*[\"']?\s*)[^\"',}\n]+"
)
#: Bare ``name=value`` secret assignments (e.g. ``token=%74opsecret``) that are
#: not inside a ``?query`` string. Values stop at whitespace / ``&`` / quotes.
_BARE_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:"
    + "|".join(re.escape(name) for name in _FIELD_SECRET_NAMES)
    + r")\s*=\s*)[^\s&'\"]+"
)


def sanitize_error(message: str | None) -> str:
    """Fail-closed redaction of a provider error string (§14).

    Credential material never survives to a serialized record or audit view:

    * URLs (userinfo / authority / path / query, including percent-encoded
      secret values) collapse to ``scheme://[REDACTED]``;
    * common token/password/secret query values and Authorization/api-key
      header forms are redacted;
    * the underlying model-catalog scrubber still covers ``sk-`` keys, Bearer
      tokens and Authorization header values.

    A stable, useful error class/code is retained — the message text and the
    URL scheme survive; only the private material is removed.
    """
    safe = _URL_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", str(message or ""))
    safe = sanitize_probe_message(safe)
    safe = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", safe)
    safe = _FIELD_SECRET_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", safe)
    safe = _BARE_SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", safe)
    return safe


__all__ = [
    "_stable_hash",
    "base_url_fingerprint",
    "invocation_request_fingerprint",
    "invocation_response_fingerprint",
    "profile_revision",
    "sanitize_error",
]
