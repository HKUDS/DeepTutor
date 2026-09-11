"""Thin HTTP client for Tencent WeKnora's documented REST API."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from .config import WeKnoraConfig

logger = logging.getLogger(__name__)

# An external service is not allowed to make the DeepTutor process buffer an
# unbounded body. Four MiB is ample for a page of KB summaries or retrieval
# chunks while keeping a compromised/misconfigured server cheap to reject.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class WeKnoraAPIError(RuntimeError):
    """Raised when WeKnora returns an error or unexpected payload."""


class WeKnoraClient:
    def __init__(
        self,
        config: WeKnoraConfig,
        *,
        timeout: float = 60.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._config = config
        self._timeout = timeout
        self._transport = transport

    def _open(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.base_url,
            headers={
                "Accept": "application/json",
                "X-API-Key": self._config.api_key,
            },
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        # Re-resolve on every request. Checking only when the connection is
        # saved would leave retrieval vulnerable to DNS rebinding later.
        from deeptutor.services.mcp.network import validate_mcp_url_async

        ok, error = await validate_mcp_url_async(self._config.base_url)
        if not ok:
            raise WeKnoraAPIError(f"Unsafe WeKnora server URL: {error}")

        async with self._open() as client:
            async with client.stream(method, path, **kwargs) as resp:
                declared = resp.headers.get("content-length")
                if declared:
                    try:
                        if int(declared) > MAX_RESPONSE_BYTES:
                            raise WeKnoraAPIError("WeKnora response exceeds the 4 MiB limit.")
                    except ValueError:
                        pass
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise WeKnoraAPIError("WeKnora response exceeds the 4 MiB limit.")

        if resp.status_code >= 400:
            preview = bytes(body[:300]).decode("utf-8", errors="replace")
            raise WeKnoraAPIError(f"WeKnora returned {resp.status_code}: {preview}")
        try:
            data = json.loads(body)
        except Exception as exc:
            raise WeKnoraAPIError(f"WeKnora returned a non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise WeKnoraAPIError(f"WeKnora returned unexpected payload: {data!r}")
        return data

    async def list_knowledge_bases(self) -> list[dict[str, Any]]:
        data = (await self._request_json("GET", "/api/v1/knowledge-bases")).get("data")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise WeKnoraAPIError("WeKnora returned an unexpected knowledge-base list.")
        return data

    async def search(self, query: str) -> list[dict[str, Any]]:
        data = (
            await self._request_json(
                "POST",
                "/api/v1/knowledge-search",
                params={"resource_urls": "handle"},
                json={
                    "query": query,
                    "knowledge_base_id": self._config.knowledge_base_id,
                },
            )
        ).get("data")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise WeKnoraAPIError("WeKnora returned unexpected search results.")
        return data


__all__ = ["MAX_RESPONSE_BYTES", "WeKnoraAPIError", "WeKnoraClient"]
