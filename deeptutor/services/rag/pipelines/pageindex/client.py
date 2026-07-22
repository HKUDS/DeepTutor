"""Thin async HTTP client for the hosted PageIndex REST API.

Upload and lifecycle only — retrieval happens agent-side through the PageIndex
MCP server:

* ``POST /doc/``                — submit a document for processing → ``doc_id``
* ``GET  /doc/{doc_id}/``       — poll processing status
* ``DELETE /doc/{doc_id}/``     — best-effort cloud cleanup

The client keeps the dependency surface to ``httpx`` (already a dependency)
and is trivially mockable: inject an ``httpx`` transport or swap the whole
client out via ``PageIndexPipeline(client=...)`` in tests.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import PageIndexConfig

logger = logging.getLogger(__name__)

_TERMINAL_OK = {"completed", "complete", "done", "ready", "success", "finished"}
_TERMINAL_FAIL = {"failed", "error", "cancelled", "canceled"}


class PageIndexAPIError(RuntimeError):
    """Raised when the PageIndex API returns an error or unexpected payload."""


class PageIndexClient:
    """Stateless wrapper over the PageIndex REST API.

    A fresh :class:`httpx.AsyncClient` is opened per call so the object is safe
    to construct once and reuse across requests without managing a connection
    lifecycle.
    """

    def __init__(
        self,
        config: PageIndexConfig,
        *,
        timeout: float = 120.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._config = config
        self._timeout = timeout
        self._transport = transport

    def _open(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.api_base_url,
            headers={"Authorization": f"Bearer {self._config.api_key}"},
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _json(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise PageIndexAPIError(f"PageIndex API {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except Exception as exc:  # pragma: no cover - defensive
            raise PageIndexAPIError(f"PageIndex returned non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise PageIndexAPIError(f"PageIndex returned unexpected payload: {data!r}")
        return data

    # ----- document processing (indexing) ---------------------------------

    async def submit_document(self, file_path: str | Path) -> str:
        path = Path(file_path)
        async with self._open() as client:
            with open(path, "rb") as handle:
                resp = await client.post(
                    "/doc/",
                    files={"file": (path.name, handle, "application/octet-stream")},
                )
        data = self._json(resp)
        doc_id = data.get("doc_id") or data.get("id")
        if not doc_id:
            raise PageIndexAPIError(f"submit_document returned no doc_id: {data!r}")
        return str(doc_id)

    async def get_document(self, doc_id: str, *, summary: bool = False) -> dict[str, Any]:
        """GET /doc/{id}/ — status plus the document tree in ``result``.

        ``summary=True`` asks the API to include per-node summaries.
        """
        params = {"summary": "true"} if summary else None
        async with self._open() as client:
            resp = await client.get(f"/doc/{doc_id}/", params=params)
        return self._json(resp)

    async def wait_until_ready(
        self,
        doc_id: str,
        *,
        poll_interval: float = 3.0,
        max_attempts: int = 200,
    ) -> dict[str, Any]:
        """Poll ``get_document`` until processing reaches a terminal state."""
        for _ in range(max_attempts):
            data = await self.get_document(doc_id)
            status = str(data.get("status") or "").strip().lower()
            ready = bool(data.get("retrieval_ready"))
            if status in _TERMINAL_FAIL:
                raise PageIndexAPIError(f"PageIndex processing failed for {doc_id}: {data!r}")
            if ready or status in _TERMINAL_OK:
                return data
            await asyncio.sleep(poll_interval)
        raise PageIndexAPIError(
            f"PageIndex processing timed out for {doc_id} after {max_attempts} polls"
        )

    async def delete_document(self, doc_id: str) -> bool:
        try:
            async with self._open() as client:
                resp = await client.delete(f"/doc/{doc_id}/")
            return resp.status_code < 400
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("PageIndex delete_document(%s) failed: %s", doc_id, exc)
            return False


__all__ = ["PageIndexClient", "PageIndexAPIError"]
