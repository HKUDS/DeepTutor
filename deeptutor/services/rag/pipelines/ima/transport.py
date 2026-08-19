"""HTTP transport shared by every Tencent IMA OpenAPI call.

All IMA methods are ``POST https://ima.qq.com/<prefix>/<method>`` with a JSON
body and two credential headers, so the wire mechanics are identical across the
knowledge-base (``wiki``) and notes modules. Concentrating them here leaves the
client classes as nothing but method tables, and leaves exactly one place that
attaches credentials.

A fresh ``httpx`` client per call (mirroring ``LightRagServerClient``) keeps the
object safe to construct once and reuse from anywhere, and the injectable
``transport`` lets tests stub the wire without a live server.

Both an async and a blocking flavour of the same call are exposed. The async one
serves retrieval and the tool layer; the blocking one exists for the knowledge-base
*inventory*, which is read from the deliberately synchronous manifest layer (see
:mod:`deeptutor.knowledge.manifest`) — giving it a blocking call here is far less
invasive than making that whole path async, and both share this module's URL,
header and envelope handling.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import ImaConfig
from .envelope import ImaRateLimitError, unwrap

API_BASE_URL = "https://ima.qq.com"
WIKI_PREFIX = "/openapi/wiki/v1"
NOTE_PREFIX = "/openapi/note/v1"

DEFAULT_TIMEOUT = 30.0


def build_headers(config: ImaConfig) -> dict[str, str]:
    """The credential headers every IMA request carries."""
    return {
        "Content-Type": "application/json",
        "ima-openapi-clientid": config.client_id,
        "ima-openapi-apikey": config.api_key,
    }


class ImaTransport:
    """POST one IMA method and return its unwrapped ``data`` object."""

    def __init__(
        self,
        config: ImaConfig,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self.transport = transport

    async def post(
        self,
        method: str,
        body: dict[str, Any],
        *,
        prefix: str = WIKI_PREFIX,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers=build_headers(self.config),
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.post(f"{prefix}/{method}", json=body)
        return self._unwrap(response)

    def post_sync(
        self,
        method: str,
        body: dict[str, Any],
        *,
        prefix: str = WIKI_PREFIX,
    ) -> dict[str, Any]:
        with httpx.Client(
            base_url=API_BASE_URL,
            headers=build_headers(self.config),
            timeout=self.timeout,
            transport=_sync_transport(self.transport),
        ) as client:
            response = client.post(f"{prefix}/{method}", json=body)
        return self._unwrap(response)

    @staticmethod
    def _unwrap(response: httpx.Response) -> dict[str, Any]:
        # A transport-level 429 never reaches the envelope, so it is mapped here
        # to the same error the envelope's rate-limit codes raise.
        if response.status_code == 429:
            raise ImaRateLimitError("IMA rate limit reached. Try again shortly.")
        try:
            payload = response.json()
        except Exception:
            payload = None
        return unwrap(payload, status_code=response.status_code)


def _sync_transport(transport: Optional[httpx.AsyncBaseTransport]) -> Optional[httpx.BaseTransport]:
    """Reuse an injected test transport for blocking calls when it supports them.

    ``httpx.MockTransport`` implements both the sync and async protocols, so a
    test's stub works for either flavour; a genuinely async-only transport is
    ignored rather than passed to a blocking client that cannot drive it.
    """
    return transport if isinstance(transport, httpx.BaseTransport) else None


__all__ = [
    "API_BASE_URL",
    "DEFAULT_TIMEOUT",
    "NOTE_PREFIX",
    "WIKI_PREFIX",
    "ImaTransport",
    "build_headers",
]
