"""Official version discovery stays bounded and independent of OAuth."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from deeptutor.services.codex_auth.client_version import latest_client_version
from deeptutor.services.codex_auth.constants import CODEX_MAX_VERSION_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"name": "@openai/codex", "version": "0.0.0"},
        {"name": "@openai/codex", "version": "1.23.456"},
    ],
)
async def test_stable_versions_are_accepted(payload: dict[str, str]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        assert await latest_client_version(http) == payload["version"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"name": "codex", "version": "1.2.3"},
        {"version": "1.2.3"},
        *[
            {"name": "@openai/codex", "version": version}
            for version in [
                None,
                123,
                True,
                "",
                "v1.2.3",
                "1.2",
                "01.2.3",
                "1.2.3\n",
                "1.2.3-alpha.1",
                "1.2.3+build",
                " 1.2.3",
                "1.2.3/path",
            ]
        ],
    ],
)
async def test_invalid_metadata_is_unavailable(payload: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        assert await latest_client_version(http) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(302, headers={"location": "https://example.test/"}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, content=b"[" * 2_000 + b"]" * 2_000),
        httpx.Response(200, headers={"content-length": str(CODEX_MAX_VERSION_BYTES + 1)}),
        httpx.Response(200, content=b" " * (CODEX_MAX_VERSION_BYTES + 1)),
        httpx.ConnectError("offline"),
        httpx.ReadTimeout("timeout"),
        TimeoutError(),
    ],
)
async def test_source_failure_is_unavailable(response: httpx.Response | Exception) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if isinstance(response, Exception):
            raise response
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await latest_client_version(http) is None
    assert calls == 1


@pytest.mark.asyncio
async def test_json_recursion_failure_is_unavailable_and_closes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise decoder recursion failure independently of Python's nesting limit."""

    class MetadataStream(httpx.AsyncByteStream):
        """Keep the response open until discovery explicitly closes it."""

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"{}"

    response = httpx.Response(200, stream=MetadataStream())
    assert not response.is_closed

    def reject_nested_json(content: object) -> object:
        raise RecursionError("JSON nesting exceeded the decoder limit")

    monkeypatch.setattr(
        "deeptutor.services.codex_auth.client_version.json.loads", reject_nested_json
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as http:
        assert await latest_client_version(http) is None
    assert response.is_closed


@pytest.mark.asyncio
async def test_client_defaults_cannot_leak_auth_or_cookies_to_npm() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert "chatgpt-account-id" not in request.headers
        return httpx.Response(200, json={"name": "@openai/codex", "version": "1.2.3"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        auth=("private", "private"),
        headers={"Authorization": "Bearer private", "chatgpt-account-id": "private"},
        cookies={"session": "private"},
    ) as http:
        assert await latest_client_version(http) == "1.2.3"


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(asyncio.CancelledError):
            await latest_client_version(http)


@pytest.mark.asyncio
@pytest.mark.parametrize("stall", [False, True])
async def test_stream_is_closed_at_size_limit_or_total_deadline(stall: bool) -> None:
    class MetadataStream(httpx.AsyncByteStream):
        """Serve slow or oversized chunks without a Content-Length header."""

        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            if stall:
                await asyncio.sleep(60)
            yield b" " * CODEX_MAX_VERSION_BYTES
            yield b"x"
            pytest.fail("Metadata discovery must stop consuming the oversized body")

        async def aclose(self) -> None:
            self.closed = True

    stream = MetadataStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    ) as http:
        assert await latest_client_version(http) is None
    assert stream.closed
