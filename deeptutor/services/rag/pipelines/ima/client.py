"""Thin async HTTP client for Tencent IMA's knowledge-base OpenAPI.

Every IMA call is ``POST https://ima.qq.com/openapi/wiki/v1/<method>`` with a
JSON body, authenticated by two headers, and answers with a
``{"code", "msg", "data"}`` envelope where ``code == 0`` means success. Only the
read-only calls DeepTutor needs are wrapped:

* ``search_knowledge`` — retrieval inside one knowledge base. Returns matching
  items with a ``highlight_content`` snippet, cursor-paginated.
* ``search_knowledge_base`` — lists knowledge bases available to the supplied
  credentials so users do not need to copy an internal id by hand.
* ``get_knowledge_base`` — a KB's name/description, used to confirm at connect
  time that the credentials work and the id resolves.
* ``get_media_info`` / ``get_doc_content`` — bounded fallback content for
  title-only search matches.

Writing to IMA is deliberately out of scope: a connected KB is a read-only
pointer, and documents are added in IMA itself.

Mirrors :class:`LightRagServerClient`: a fresh :class:`httpx.AsyncClient` per
call so the object is safe to construct once and reuse, and an injectable
``transport`` so tests can stub the wire without a live server.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import httpx

from .config import ImaConfig

logger = logging.getLogger(__name__)

API_BASE_URL = "https://ima.qq.com"
_API_PREFIX = "/openapi/wiki/v1"
_NOTE_API_PREFIX = "/openapi/note/v1"

# Official IMA media links are short-lived Tencent COS URLs. Restricting the
# downloader to that boundary prevents a compromised API response from turning
# retrieval into an SSRF primitive. IMA's own credentials are never attached to
# this separate client.
_COS_ROOT_DOMAIN = "myqcloud.com"
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

# Envelope codes worth naming. IMA returns hundreds of business codes; these are
# the two classes a caller reacts to differently from a generic failure.
_CREDENTIAL_CODES = frozenset({20004, 200002})
_RATE_LIMIT_CODES = frozenset({20002, 110021})

# ``search_knowledge`` is cursor-paginated. Retrieval feeds an LLM prompt, so a
# couple of pages is plenty — this bounds the calls a single search can make.
_MAX_SEARCH_PAGES = 3


class ImaAPIError(RuntimeError):
    """Raised when IMA returns an error envelope or an unexpected payload."""


class ImaAuthError(ImaAPIError):
    """Raised when IMA rejects the client id / API key pair."""


class ImaRateLimitError(ImaAPIError):
    """Raised when IMA rate-limits the request."""


@dataclass(frozen=True)
class ImaMediaContent:
    """One IMA item's content, as either note text or downloaded file bytes."""

    text: str = ""
    data: bytes = b""
    filename: str = ""


class ImaClient:
    """Stateless wrapper over the IMA knowledge-base OpenAPI."""

    def __init__(
        self,
        config: ImaConfig,
        *,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._config = config
        self._timeout = timeout
        self._transport = transport

    def _open(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers={
                "Content-Type": "application/json",
                "ima-openapi-clientid": self._config.client_id,
                "ima-openapi-apikey": self._config.api_key,
            },
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _post(
        self,
        method: str,
        body: dict[str, Any],
        *,
        prefix: str = _API_PREFIX,
    ) -> dict[str, Any]:
        """POST one IMA method and return its unwrapped ``data`` object."""
        async with self._open() as client:
            resp = await client.post(f"{prefix}/{method}", json=body)
        if resp.status_code == 429:
            raise ImaRateLimitError("IMA rate limit reached. Try again shortly.")
        try:
            payload = resp.json()
        except Exception as exc:
            raise ImaAPIError(
                f"IMA returned a non-JSON response with status {resp.status_code}"
            ) from exc
        if not isinstance(payload, dict):
            raise ImaAPIError(f"IMA returned an unexpected payload: {payload!r}")

        code = payload.get("code")
        message = str(payload.get("msg") or "").strip()
        if code == 0:
            data = payload.get("data")
            return data if isinstance(data, dict) else {}
        if code in _CREDENTIAL_CODES:
            raise ImaAuthError(message or "IMA rejected the client ID / API key.")
        if code in _RATE_LIMIT_CODES:
            raise ImaRateLimitError(message or "IMA rate limit reached.")
        raise ImaAPIError(message or f"IMA request failed with code {code}.")

    # ----- retrieval ------------------------------------------------------

    async def search_knowledge(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """Return up to *limit* matching items from the bound knowledge base.

        Each item is ``{"media_id", "title", "parent_folder_id",
        "highlight_content"}``. Pages are followed until the result is full,
        IMA reports the end of the list, or the page budget runs out.
        """
        items: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(_MAX_SEARCH_PAGES):
            data = await self._post(
                "search_knowledge",
                {
                    "query": query,
                    "cursor": cursor,
                    "knowledge_base_id": self._config.knowledge_base_id,
                },
            )
            page = data.get("info_list")
            if isinstance(page, list):
                items.extend(entry for entry in page if isinstance(entry, dict))
            cursor = str(data.get("next_cursor") or "")
            if len(items) >= limit or data.get("is_end") or not cursor:
                break
        return items[:limit]

    async def get_media_content(self, media_id: str) -> ImaMediaContent | None:
        """Fetch full content for one search result when IMA omitted a snippet.

        IMA notes are returned as plain text by the notes API. File media is
        streamed from the short-lived COS URL with a hard byte limit. Missing
        or inaccessible media returns ``None`` so retrieval can degrade to the
        result title without failing the whole search.
        """
        normalized_id = str(media_id or "").strip()
        if not normalized_id:
            return None

        info = await self._post("get_media_info", {"media_id": normalized_id})
        note_info = info.get("notebook_ext_info")
        if info.get("media_type") == 11 and isinstance(note_info, dict):
            note_id = str(note_info.get("notebook_id") or "").strip()
            if note_id:
                data = await self._post(
                    "get_doc_content",
                    {"note_id": note_id, "target_content_format": 0},
                    prefix=_NOTE_API_PREFIX,
                )
                content = str(data.get("content") or "").strip()
                return ImaMediaContent(text=content) if content else None

        url_info = info.get("url_info")
        if not isinstance(url_info, dict):
            return None
        url = str(url_info.get("url") or "").strip()
        if not url:
            return None
        headers = _media_headers(url_info.get("headers"))
        return await self._download_media(url, headers=headers)

    async def _download_media(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> ImaMediaContent:
        _validate_media_url(url)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
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

                filename = _media_filename(url, response.headers.get("content-type"))
                return ImaMediaContent(data=bytes(body), filename=filename)

    # ----- probing --------------------------------------------------------

    async def search_knowledge_bases(
        self,
        query: str = "",
        *,
        cursor: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return one page of knowledge bases available to these credentials.

        Official docs name the wire fields ``id`` / ``name`` while current live
        responses also use ``kb_id`` / ``kb_name``. Both are normalized here.
        A single batch details request enriches descriptions when possible; that
        optional request never prevents a usable name list from being returned.
        """
        if not 1 <= limit <= 20:
            raise ValueError("IMA knowledge base list limit must be between 1 and 20.")

        data = await self._post(
            "search_knowledge_base",
            {
                "query": str(query or "").strip(),
                "cursor": str(cursor or "").strip(),
                "limit": limit,
            },
        )
        entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        page = data.get("info_list")
        if isinstance(page, list):
            for raw in page:
                if not isinstance(raw, dict):
                    continue
                kb_id = str(raw.get("id") or raw.get("kb_id") or "").strip()
                name = str(raw.get("name") or raw.get("kb_name") or "").strip()
                if not kb_id or not name or kb_id in seen:
                    continue
                seen.add(kb_id)
                entries.append((kb_id, name))

        details: dict[str, dict[str, Any]] = {}
        if entries:
            try:
                details = await self.get_knowledge_bases([kb_id for kb_id, _ in entries])
            except Exception:
                # Names from search_knowledge_base are sufficient for selection;
                # description lookup is intentionally best-effort.
                details = {}

        knowledge_bases = []
        for kb_id, name in entries:
            raw_description = details.get(kb_id, {}).get("description")
            description = str(raw_description).strip() if raw_description is not None else ""
            knowledge_bases.append(
                {
                    "id": kb_id,
                    "name": name,
                    "description": description or None,
                }
            )

        return {
            "knowledge_bases": knowledge_bases,
            "next_cursor": str(data.get("next_cursor") or ""),
            "is_end": bool(data.get("is_end")),
        }

    async def get_knowledge_bases(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return details for at most 20 knowledge base ids."""
        normalized: list[str] = []
        for item in ids:
            kb_id = str(item or "").strip()
            if kb_id and kb_id not in normalized:
                normalized.append(kb_id)
        if not normalized:
            return {}
        if len(normalized) > 20:
            raise ValueError("IMA accepts at most 20 knowledge base IDs per request.")

        data = await self._post("get_knowledge_base", {"ids": normalized})
        infos = data.get("infos")
        if not isinstance(infos, dict):
            return {}
        return {str(kb_id): info for kb_id, info in infos.items() if isinstance(info, dict)}

    async def get_knowledge_base(self) -> dict[str, Any]:
        """Return the bound knowledge base's info, or ``{}`` when unknown.

        Doubles as the credential check: bad credentials raise
        :class:`ImaAuthError`, while a well-formed but unknown id simply yields
        no entry for it.
        """
        kb_id = self._config.knowledge_base_id
        return (await self.get_knowledge_bases([kb_id])).get(kb_id, {})


def _validate_media_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not hostname:
        raise ImaAPIError("IMA media URL must use HTTPS.")
    if hostname != _COS_ROOT_DOMAIN and not hostname.endswith(f".{_COS_ROOT_DOMAIN}"):
        raise ImaAPIError("IMA media URL is outside Tencent COS.")


def _media_headers(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if str(key).lower() not in _FORBIDDEN_MEDIA_HEADERS and isinstance(value, (str, int, float))
    }


def _media_filename(url: str, content_type: str | None) -> str:
    name = unquote(PurePosixPath(urlparse(url).path).name).strip()
    if "." in name:
        return name
    extensions = {
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
    media_type = str(content_type or "").partition(";")[0].strip().lower()
    return f"{name or 'ima-document'}{extensions.get(media_type, '')}"


__all__ = [
    "API_BASE_URL",
    "ImaAPIError",
    "ImaAuthError",
    "ImaClient",
    "ImaMediaContent",
    "ImaRateLimitError",
    "MAX_MEDIA_BYTES",
]
