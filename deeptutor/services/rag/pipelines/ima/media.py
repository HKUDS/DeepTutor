"""Fetching and reading one IMA item's actual content.

An IMA knowledge item is either a *note* (whose text the notes API returns
directly) or a *file* (which IMA hands over as a short-lived Tencent COS
download URL). This module owns the file half — the download and the text
extraction — so both retrieval (``pipeline``) and the capability's ``ima_read``
tool read documents through exactly one implementation.

Security boundary
-----------------
The download URL arrives inside an API response, so it is treated as untrusted
input: it must be HTTPS and served from a trusted Tencent domain (Tencent COS
or IMA's own resource host, :data:`_ALLOWED_MEDIA_ROOT_DOMAINS`), which
prevents a tampered or buggy response from turning retrieval into an SSRF
primitive. Redirects are not followed, IMA's own credentials are never attached
to this separate client, and hop-by-hop / identity headers are stripped from
whatever header set the response asked us to send. Size is capped
(:data:`MAX_MEDIA_BYTES`) both by the advertised ``content-length`` and while
streaming, so a mis-sized response cannot exhaust memory.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx

from deeptutor.utils.document_extractor import (
    SUPPORTED_DOC_EXTENSIONS,
    extract_text_from_bytes,
)

from .envelope import ImaAPIError

# Official IMA media links are short-lived Tencent COS download URLs, and
# note/file content is served from IMA's exact resource host
# (res-pkb.ima.qq.com). Do not trust every sibling under ima.qq.com: a broad
# suffix allowlist would let an unrelated or later-compromised service become
# an SSRF relay.
_ALLOWED_MEDIA_ROOT_DOMAINS = ("myqcloud.com",)
_ALLOWED_MEDIA_HOSTS = frozenset({"res-pkb.ima.qq.com"})

# Headers we never forward, whatever the API response asks for: hop-by-hop
# fields and anything that would carry identity to COS.
_FORBIDDEN_MEDIA_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "cookie",
        "host",
        "proxy-authorization",
        "transfer-encoding",
    }
)

MAX_MEDIA_BYTES = 20 * 1024 * 1024

_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/json": ".json",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


@dataclass(frozen=True)
class ImaMediaContent:
    """One IMA item's content, as either note text or downloaded file bytes."""

    text: str = ""
    data: bytes = b""
    filename: str = ""


async def download_media(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> ImaMediaContent:
    """Stream a COS media URL into memory, bounded by :data:`MAX_MEDIA_BYTES`."""
    validate_media_url(url)
    async with httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        follow_redirects=False,
    ) as client:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_MEDIA_BYTES:
                raise ImaAPIError("IMA media exceeds the 20 MB retrieval limit.")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_MEDIA_BYTES:
                    raise ImaAPIError("IMA media exceeds the 20 MB retrieval limit.")
            filename = media_filename(url, response.headers.get("content-type"))
            return ImaMediaContent(data=bytes(body), filename=filename)


async def extract_text(
    media: ImaMediaContent | None,
    *title_candidates: str,
    max_chars: int,
) -> str:
    """Plain text for *media*, truncated to *max_chars* (``""`` when unreadable).

    Note text is already plain. File bytes are decoded by
    :func:`~deeptutor.utils.document_extractor.extract_text_from_bytes`, which
    needs a filename to pick a decoder — the download's own filename or the
    item title, whichever carries a supported extension. Extraction is CPU-bound
    (PDF / Office parsing), so it runs in a worker thread.
    """
    if media is None:
        return ""
    if media.text:
        return media.text[:max_chars].strip()
    if not media.data:
        return ""
    filename = _extractable_filename(media.filename, *title_candidates)
    if not filename:
        return ""
    return await asyncio.to_thread(
        extract_text_from_bytes,
        filename,
        media.data,
        max_bytes=MAX_MEDIA_BYTES,
        max_chars=max_chars,
    )


def validate_media_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not hostname:
        raise ImaAPIError("IMA media URL must use HTTPS.")
    trusted_root = any(
        hostname == root or hostname.endswith(f".{root}") for root in _ALLOWED_MEDIA_ROOT_DOMAINS
    )
    if hostname not in _ALLOWED_MEDIA_HOSTS and not trusted_root:
        raise ImaAPIError("IMA media URL is outside the trusted Tencent media hosts.")


def media_headers(raw: object) -> dict[str, str]:
    """The subset of a response's suggested download headers we will forward."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if str(key).lower() not in _FORBIDDEN_MEDIA_HEADERS and isinstance(value, (str, int, float))
    }


def media_filename(url: str, content_type: str | None) -> str:
    """A filename for the download, inferring an extension when the path lacks one."""
    name = unquote(PurePosixPath(urlparse(url).path).name).strip()
    if "." in name:
        return name
    media_type = str(content_type or "").partition(";")[0].strip().lower()
    return f"{name or 'ima-document'}{_CONTENT_TYPE_EXTENSIONS.get(media_type, '')}"


def _extractable_filename(*candidates: str) -> str:
    for candidate in candidates:
        if candidate and PurePath(candidate).suffix.lower() in SUPPORTED_DOC_EXTENSIONS:
            return candidate
    return ""


__all__ = [
    "MAX_MEDIA_BYTES",
    "ImaMediaContent",
    "download_media",
    "extract_text",
    "media_filename",
    "media_headers",
    "validate_media_url",
]
