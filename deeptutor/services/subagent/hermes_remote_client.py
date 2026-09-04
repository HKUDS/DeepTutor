"""Small authenticated HTTP/SSE client for a Hermes Agent gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from types import TracebackType
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


class HermesRemoteHTTPError(Exception):
    """An HTTP response outside the successful range."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP status {status_code}")


class HermesRemoteProtocolError(Exception):
    """A successful response did not follow the gateway JSON/SSE contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class HermesRemoteClient:
    """Own one authenticated connection pool to a Hermes gateway."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        base_url = self.validate_base_url(base_url)
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_STREAM_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )

    @staticmethod
    def validate_base_url(base_url: str) -> str:
        """Return a canonical HTTP(S) gateway root or reject unsafe input."""
        value = base_url.strip().rstrip("/")
        try:
            parsed = urlsplit(value)
            parsed.port
        except ValueError as exc:
            raise HermesRemoteProtocolError("invalid_base_url") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise HermesRemoteProtocolError("invalid_base_url")
        return value

    async def __aenter__(self) -> HermesRemoteClient:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc_value, traceback)

    async def get_json(self, path: str) -> dict[str, Any]:
        """Fetch and parse a JSON object using the bounded request timeout."""
        response = await self._client.get(path.lstrip("/"), timeout=_REQUEST_TIMEOUT)
        return self._json_object(response)

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST a JSON object without transport retries."""
        response = await self._client.post(
            path.lstrip("/"),
            json=payload,
            headers=headers,
            timeout=_REQUEST_TIMEOUT,
        )
        return self._json_object(response)

    async def get_session_history(self, session_id: str) -> list[dict[str, str]]:
        """Fetch the resumable user/assistant history for one gateway session."""
        path_id = quote(session_id, safe="")
        payload = await self.get_json(f"/api/sessions/{path_id}/messages")
        if payload.get("object") != "list" or not isinstance(payload.get("data"), list):
            raise HermesRemoteProtocolError("invalid_session_history")
        history: list[dict[str, str]] = []
        for row in payload["data"]:
            if not isinstance(row, dict):
                continue
            role = row.get("role")
            content = row.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            if content.strip():
                history.append({"role": role, "content": content})
        return history[-40:]

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield JSON objects from the gateway's data-only SSE frames."""
        async with self._client.stream(
            "GET",
            f"v1/runs/{run_id}/events",
            timeout=_STREAM_TIMEOUT,
        ) as response:
            if not response.is_success:
                raise HermesRemoteHTTPError(response.status_code)
            event_name = ""
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith(":"):
                    # Surface heartbeat comments to the workflow so each one
                    # resets its idle watchdog without producing a UI event.
                    yield {"event": "gateway.keepalive"}
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                    continue
                if line.strip() or not data_lines:
                    continue
                raw = "\n".join(data_lines)
                data_lines.clear()
                if raw == "[DONE]":
                    return
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise HermesRemoteProtocolError("invalid_sse_json") from exc
                if not isinstance(payload, dict):
                    raise HermesRemoteProtocolError("invalid_sse_event")
                if event_name and "event" not in payload:
                    payload["event"] = event_name
                event_name = ""
                yield payload

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        if not response.is_success:
            raise HermesRemoteHTTPError(response.status_code)
        try:
            payload = response.json()
        except (ValueError, UnicodeError) as exc:
            raise HermesRemoteProtocolError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise HermesRemoteProtocolError("invalid_json_object")
        return payload


__all__ = [
    "HermesRemoteClient",
    "HermesRemoteHTTPError",
    "HermesRemoteProtocolError",
]
