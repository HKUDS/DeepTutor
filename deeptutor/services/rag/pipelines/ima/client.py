"""Thin async HTTP client for Tencent IMA's knowledge-base OpenAPI.

Every IMA call is ``POST https://ima.qq.com/openapi/wiki/v1/<method>`` with a
JSON body, authenticated by two headers, and answers with a
``{"code", "msg", "data"}`` envelope where ``code == 0`` means success. Only the
two read-only calls DeepTutor needs are wrapped:

* ``search_knowledge`` — retrieval inside one knowledge base. Returns matching
  items with a ``highlight_content`` snippet, cursor-paginated.
* ``get_knowledge_base`` — a KB's name/description, used to confirm at connect
  time that the credentials work and the id resolves.

Writing to IMA is deliberately out of scope: a connected KB is a read-only
pointer, and documents are added in IMA itself.

Mirrors :class:`LightRagServerClient`: a fresh :class:`httpx.AsyncClient` per
call so the object is safe to construct once and reuse, and an injectable
``transport`` so tests can stub the wire without a live server.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import ImaConfig

logger = logging.getLogger(__name__)

API_BASE_URL = "https://ima.qq.com"
_API_PREFIX = "/openapi/wiki/v1"

# Envelope codes worth naming. IMA returns hundreds of business codes; these are
# the two classes a caller reacts to differently from a generic failure.
_CREDENTIAL_CODES = frozenset({20004})
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

    async def _post(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST one IMA method and return its unwrapped ``data`` object."""
        async with self._open() as client:
            resp = await client.post(f"{_API_PREFIX}/{method}", json=body)
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

    # ----- probing --------------------------------------------------------

    async def get_knowledge_base(self) -> dict[str, Any]:
        """Return the bound knowledge base's info, or ``{}`` when unknown.

        Doubles as the credential check: bad credentials raise
        :class:`ImaAuthError`, while a well-formed but unknown id simply yields
        no entry for it.
        """
        kb_id = self._config.knowledge_base_id
        data = await self._post("get_knowledge_base", {"ids": [kb_id]})
        infos = data.get("infos")
        if not isinstance(infos, dict):
            return {}
        info = infos.get(kb_id)
        return info if isinstance(info, dict) else {}


__all__ = [
    "API_BASE_URL",
    "ImaClient",
    "ImaAPIError",
    "ImaAuthError",
    "ImaRateLimitError",
]
