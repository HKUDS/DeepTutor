"""Thin async HTTP client for an external LightRAG server's REST API.

We talk to the documented endpoints directly (``httpx`` only) — the calls map
1:1 onto our retrieval-only contract:

* ``POST /query`` with ``only_need_context=True`` — return the grounded context
  the server retrieved, WITHOUT its own generation. DeepTutor's chat loop keeps
  ownership of the answer; the server is used purely as a retriever.
* ``GET /auth-status`` — reachability + whether the server requires an API key
  (whitelisted on the server, so it answers without credentials).
* ``GET /documents/pipeline_status`` — an auth-gated, side-effect-free call used
  only to validate that a configured API key is accepted.

Mirrors :class:`PageIndexClient`: a fresh :class:`httpx.AsyncClient` per call so
the object is safe to construct once and reuse, and an injectable ``transport``
so tests can stub the wire without a live server.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import LightRagServerConfig

logger = logging.getLogger(__name__)


class LightRagServerAPIError(RuntimeError):
    """Raised when the LightRAG server returns an error or unexpected payload."""


class LightRagServerClient:
    """Stateless wrapper over an external LightRAG server's REST API."""

    def __init__(
        self,
        config: LightRagServerConfig,
        *,
        timeout: float = 60.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._config = config
        self._timeout = timeout
        self._transport = transport

    def _open(self) -> httpx.AsyncClient:
        headers = {"Accept": "application/json"}
        if self._config.api_key:
            # LightRAG server authenticates with an ``X-API-Key`` header
            # (its ``LIGHTRAG_API_KEY``); absent when the server runs open.
            headers["X-API-Key"] = self._config.api_key
        return httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _json(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 400:
            raise LightRagServerAPIError(
                f"LightRAG server returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except Exception as exc:  # pragma: no cover - defensive
            raise LightRagServerAPIError(
                f"LightRAG server returned a non-JSON response: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise LightRagServerAPIError(f"LightRAG server returned unexpected payload: {data!r}")
        return data

    # ----- retrieval ------------------------------------------------------

    async def query_context(self, query: str, mode: str) -> dict[str, Any]:
        """Retrieve grounded context for ``query`` without server-side generation.

        Returns ``{"content": <context string>, "sources": [...]}``. ``sources``
        are derived from the server's ``references`` list when present (one entry
        per cited source file); an older server that omits references yields an
        empty list rather than an error.
        """
        async with self._open() as client:
            resp = await client.post(
                "/query",
                json={"query": query, "mode": mode, "only_need_context": True},
            )
        data = self._json(resp)
        content = str(data.get("response") or "")
        sources = _sources_from_references(data.get("references"))
        return {"content": content, "sources": sources}

    # ----- probing --------------------------------------------------------

    async def auth_status(self) -> dict[str, Any]:
        """Fetch ``/auth-status`` (no credentials) to probe reachability.

        The presence of LightRAG-specific keys (``auth_configured`` /
        ``core_version``) doubles as a "this really is a LightRAG server" signal.
        """
        async with self._open() as client:
            resp = await client.get("/auth-status")
        return self._json(resp)

    async def verify_key(self) -> bool:
        """Return whether the configured API key is accepted by the server.

        Hits the auth-gated, read-only ``/documents/pipeline_status``: a 2xx
        means the key (or open access) is valid; 401/403 means it was rejected.
        Any other transport error propagates to the caller.
        """
        async with self._open() as client:
            resp = await client.get("/documents/pipeline_status")
        if resp.status_code in (401, 403):
            return False
        if resp.status_code >= 400:
            raise LightRagServerAPIError(
                f"LightRAG server returned {resp.status_code}: {resp.text[:300]}"
            )
        return True


def _sources_from_references(references: Any) -> list[dict[str, Any]]:
    """Map a LightRAG ``references`` list into DeepTutor's ``sources`` shape."""
    if not isinstance(references, list):
        return []
    sources: list[dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        file_path = str(ref.get("file_path") or "").strip()
        ref_id = str(ref.get("reference_id") or "").strip()
        if not file_path and not ref_id:
            continue
        source: dict[str, Any] = {}
        if ref_id:
            source["id"] = ref_id
        if file_path:
            source["file_path"] = file_path
        sources.append(source)
    return sources


__all__ = ["LightRagServerClient", "LightRagServerAPIError"]
