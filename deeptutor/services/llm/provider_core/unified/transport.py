"""Transport abstraction for the unified LLM protocol layer.

All tests use fakes/fixtures; no real provider endpoint is ever probed.  The
real :class:`HttpTransport` is a thin httpx wrapper used only by production
selection of an explicit protocol adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from deeptutor.services.llm.provider_core.openai_responses.parsing import iter_sse


class TransportError(RuntimeError):
    """Raised when a transport request cannot be satisfied (e.g. no fixture)."""


class LLMTransport(ABC):
    """Minimal HTTP transport interface used by the unified adapters."""

    @abstractmethod
    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a JSON request and return the parsed JSON response body."""

    @abstractmethod
    def request_json_lines(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a request and yield parsed JSON SSE events (or JSON lines)."""

    async def aclose(self) -> None:
        """Release transport-owned resources.

        The adapter awaits this exactly once per :meth:`UnifiedLLMAdapter.aclose`
        call.  Transports with an underlying HTTP pool override it and make
        repeated closes idempotent; doubles that own nothing keep the no-op.
        """
        return None


class HttpTransport(LLMTransport):
    """Real httpx-backed transport.

    ``base_url`` may or may not end in ``/v1``; the transport normalizes the
    join so protocol paths like ``/v1/chat/completions`` resolve correctly for
    both ``https://api.openai.com/v1`` and ``https://api.anthropic.com``.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        verify: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.verify = verify
        self._client: httpx.AsyncClient | None = None

    def _url(self, path: str) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}{path}"

    async def _client_for(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                verify=self.verify,
                follow_redirects=False,
            )
        return self._client

    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        client = await self._client_for()
        response = await client.request(
            method,
            self._url(path),
            json=body,
            headers=dict(headers or {}),
        )
        if response.status_code >= 400:
            raise TransportError(
                f"{method} {path} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise TransportError(f"{method} {path} returned a non-object JSON payload")
        return payload

    async def request_json_lines(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        client = await self._client_for()
        async with client.stream(
            method,
            self._url(path),
            json=body,
            headers=dict(headers or {}),
        ) as response:
            if response.status_code >= 400:
                raw = await response.aread()
                raise TransportError(
                    f"{method} {path} returned HTTP {response.status_code}: "
                    f"{raw.decode('utf-8', 'ignore')[:300]}"
                )
            async for event in iter_sse(response):
                yield event

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class FakeTransport(LLMTransport):
    """In-memory transport double for fixture-driven contract tests.

    Register canned JSON responses / SSE event streams by ``(method, path)``.
    Every request is recorded on :attr:`requests` so tests can assert exact
    method/path/body and that retrieve/cancel never re-submit.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], dict[str, Any]] = {}
        self._streams: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._errors: dict[tuple[str, str], Exception] = {}

    def add_response(
        self,
        method: str,
        path: str,
        response: dict[str, Any],
    ) -> None:
        self._responses[(method, path)] = response

    def add_stream(
        self,
        method: str,
        path: str,
        events: list[dict[str, Any]],
    ) -> None:
        self._streams[(method, path)] = list(events)

    def add_error(self, method: str, path: str, error: Exception) -> None:
        self._errors[(method, path)] = error

    def calls_for(self, method: str, path: str) -> list[dict[str, Any]]:
        return [
            request
            for request in self.requests
            if request["method"] == method and request["path"] == path
        ]

    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": dict(headers or {}),
            }
        )
        key = (method, path)
        if key in self._errors:
            raise self._errors[key]
        if key in self._responses:
            return self._responses[key]
        raise TransportError(f"no fixture registered for {method} {path}")

    async def request_json_lines(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": dict(headers or {}),
            }
        )
        key = (method, path)
        if key in self._errors:
            raise self._errors[key]
        if key in self._streams:
            for event in self._streams[key]:
                yield event
            return
        if key in self._responses:
            yield self._responses[key]
            return
        raise TransportError(f"no fixture registered for {method} {path}")

    async def aclose(self) -> None:  # noqa: D401 - test double lifecycle hook
        return None


__all__ = [
    "FakeTransport",
    "HttpTransport",
    "LLMTransport",
    "TransportError",
]
