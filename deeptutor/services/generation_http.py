"""Shared HTTP plumbing for media-generation providers (imagegen / videogen).

Image- and video-generation endpoints across OpenAI, Volcengine Ark (Seedream /
Seedance) and compatible gateways share the same auth + base-URL conventions as
the rest of the OpenAI-compatible cluster. This module factors out the few
helpers both generation services need so each adapter stays thin.

Voice keeps its own copy in ``services/voice/base.py`` — this module is
deliberately scoped to image/video generation rather than refactoring voice.
"""

from __future__ import annotations

import base64
import binascii

import httpx

# Auth header styles understood by the generation adapters.
AUTH_BEARER = "bearer"  # Authorization: Bearer <key>  (OpenAI, Volcengine, gateways)
AUTH_API_KEY_HEADER = "api_key_header"  # api-key: <key>  (Azure OpenAI)


class GenerationProviderError(RuntimeError):
    """Raised when an image/video provider request fails or is misconfigured."""


def decode_base64_media(payload: str, action: str) -> bytes:
    """Decode an inline provider result and reject malformed/empty media.

    Provider protocol failures should reach the model as an actionable tool
    failure, not bubble out as an unrelated ``binascii.Error`` or get published
    as a zero-byte image.
    """
    try:
        data = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GenerationProviderError(f"{action} returned invalid base64 data.") from exc
    if not data:
        raise GenerationProviderError(f"{action} returned empty base64 data.")
    return data


def build_auth_headers(auth_style: str, api_key: str) -> dict[str, str]:
    """Map an ``auth_style`` + key onto request headers.

    ``bearer`` (default) → ``Authorization: Bearer``; ``api_key_header`` →
    ``api-key`` (Azure OpenAI).
    """
    if not api_key:
        return {}
    if auth_style == AUTH_API_KEY_HEADER:
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def join_api_path(base_url: str, suffix: str) -> str:
    """Append an OpenAI-style path to a configured API base.

    ``base_url`` is the API base (e.g. ``https://api.openai.com/v1`` or
    ``https://ark.cn-beijing.volces.com/api/v3``); ``suffix`` is the relative
    path (e.g. ``images/generations``). If the admin already pasted a full
    endpoint ending in ``suffix`` it is returned verbatim, query string kept.
    """
    base = (base_url or "").strip()
    if not base:
        raise GenerationProviderError("No endpoint URL configured for this provider.")
    head, sep, query = base.partition("?")
    norm_suffix = suffix.strip("/")
    if head.rstrip("/").endswith(norm_suffix):
        return base
    joined = f"{head.rstrip('/')}/{norm_suffix}"
    return f"{joined}?{query}" if sep else joined


def raise_for_provider(resp: httpx.Response, action: str) -> None:
    """Surface a provider error with a trimmed body for diagnostics."""
    if resp.status_code < 400:
        return
    detail = (resp.text or "").strip()[:400]
    raise GenerationProviderError(
        f"{action} failed with HTTP {resp.status_code}" + (f": {detail}" if detail else ".")
    )


__all__ = [
    "AUTH_BEARER",
    "AUTH_API_KEY_HEADER",
    "GenerationProviderError",
    "build_auth_headers",
    "decode_base64_media",
    "join_api_path",
    "raise_for_provider",
]
