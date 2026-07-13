"""Thin async HTTP client for the hosted PageIndex REST API.

We talk to the documented REST endpoints directly rather than the ``pageindex``
SDK because the calls we need map 1:1 onto our per-KB pipeline contract:

* ``POST /doc/``                — submit a document for processing → ``doc_id``
* ``GET  /doc/{doc_id}/``       — poll processing status / ``retrieval_ready``
* ``POST /retrieval/``          — submit a doc-scoped, retrieval-only query
* ``GET  /retrieval/{id}/``     — poll for the retrieved nodes
* ``DELETE /doc/{doc_id}/``     — best-effort cloud cleanup

Retrieval-only (not chat-completions) keeps generation on DeepTutor's own LLM
("Option A"). The client keeps the dependency surface to ``httpx`` (already a
dependency) and is trivially mockable: inject an ``httpx`` transport or swap the
whole client out via ``PageIndexPipeline(client=...)`` in tests.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Optional

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

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        async with self._open() as client:
            resp = await client.get(f"/doc/{doc_id}/")
        return self._json(resp)

    async def wait_until_ready(
        self,
        doc_id: str,
        *,
        poll_interval: float = 3.0,
        max_attempts: int = 200,
        on_poll: Optional[Callable[[int, str], None]] = None,
    ) -> dict[str, Any]:
        """Poll ``get_document`` until the document is retrieval-ready."""
        for attempt in range(max_attempts):
            data = await self.get_document(doc_id)
            status = str(data.get("status") or "").strip().lower()
            ready = bool(data.get("retrieval_ready"))
            if on_poll is not None:
                on_poll(attempt, status or ("ready" if ready else "processing"))
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

    # ----- retrieval (query) ----------------------------------------------

    async def submit_retrieval(
        self, doc_id: str, query: str, *, thinking: bool = True
    ) -> dict[str, Any]:
        async with self._open() as client:
            resp = await client.post(
                "/retrieval/",
                json={"doc_id": doc_id, "query": query, "thinking": thinking},
            )
        return self._json(resp)

    async def get_retrieval(self, retrieval_id: str) -> dict[str, Any]:
        async with self._open() as client:
            resp = await client.get(f"/retrieval/{retrieval_id}/")
        return self._json(resp)

    async def retrieve(
        self,
        doc_id: str,
        query: str,
        *,
        thinking: bool = True,
        poll_interval: float = 2.0,
        max_attempts: int = 90,
    ) -> list[dict[str, Any]]:
        """Submit a doc-scoped retrieval query and return its retrieved nodes.

        Tolerant of both the async submit→poll flow (``retrieval_id`` then poll)
        and deployments that return ``retrieved_nodes`` inline on submit.
        """
        submitted = await self.submit_retrieval(doc_id, query, thinking=thinking)
        if isinstance(submitted.get("retrieved_nodes"), list):
            return submitted["retrieved_nodes"]

        retrieval_id = submitted.get("retrieval_id") or submitted.get("id")
        if not retrieval_id:
            raise PageIndexAPIError(
                f"submit_retrieval returned neither nodes nor retrieval_id: {submitted!r}"
            )

        for _ in range(max_attempts):
            data = await self.get_retrieval(str(retrieval_id))
            status = str(data.get("status") or "").strip().lower()
            nodes = data.get("retrieved_nodes")
            if status in _TERMINAL_FAIL:
                raise PageIndexAPIError(f"PageIndex retrieval failed for {doc_id}: {data!r}")
            if status in _TERMINAL_OK or (isinstance(nodes, list) and nodes):
                return nodes if isinstance(nodes, list) else []
            await asyncio.sleep(poll_interval)
        raise PageIndexAPIError(
            f"PageIndex retrieval timed out for {doc_id} after {max_attempts} polls"
        )


__all__ = ["PageIndexClient", "PageIndexAPIError"]
