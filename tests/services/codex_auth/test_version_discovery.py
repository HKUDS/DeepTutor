from __future__ import annotations

import json

import httpx
import pytest

from deeptutor.services.codex_auth.constants import CODEX_NPM_METADATA_URL
from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.codex_auth.version import (
    CodexClientVersionDiscovery,
    validate_stable_version,
)

pytestmark = pytest.mark.asyncio


def _client_factory(
    responder,
) -> tuple[list[httpx.Request], httpx.AsyncClient]:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responder(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
        follow_redirects=False,
    )
    return requests, client


async def test_discovery_reads_only_stable_version_metadata() -> None:
    requests, client = _client_factory(
        lambda _request: httpx.Response(200, json={"version": "1.2.3"})
    )
    discovery = CodexClientVersionDiscovery(lambda: client)

    assert await discovery.discover() == "1.2.3"
    assert requests[0].url == httpx.URL(CODEX_NPM_METADATA_URL)
    assert requests[0].headers["accept"] == "application/vnd.npm.install-v1+json"
    assert not requests[0].headers.keys() & {"authorization", "cookie", "chatgpt-account-id"}


async def test_discovery_refuses_redirects() -> None:
    _requests, client = _client_factory(lambda _request: httpx.Response(302))
    discovery = CodexClientVersionDiscovery(lambda: client)

    with pytest.raises(CodexAuthError) as exc_info:
        await discovery.discover()

    assert exc_info.value.code == "client_version_redirect"


async def test_discovery_enforces_response_limit() -> None:
    _requests, client = _client_factory(lambda _request: httpx.Response(200, content=b"x" * 65_537))
    discovery = CodexClientVersionDiscovery(lambda: client)

    with pytest.raises(CodexAuthError) as exc_info:
        await discovery.discover()

    assert exc_info.value.code == "client_version_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (httpx.Response(429), "client_version_rate_limited"),
        (httpx.Response(403), "client_version_forbidden"),
        (httpx.Response(500), "client_version_unavailable"),
        (httpx.Response(200, content=b"{broken"), "client_version_invalid"),
        (httpx.Response(200, json={"version": "1.2.3-beta"}), "client_version_invalid"),
    ],
)
async def test_discovery_classifies_failures(
    response: httpx.Response,
    error_code: str,
) -> None:
    _requests, client = _client_factory(lambda _request: response)
    discovery = CodexClientVersionDiscovery(lambda: client)

    with pytest.raises(CodexAuthError) as exc_info:
        await discovery.discover()

    assert exc_info.value.code == error_code


async def test_discovery_classifies_timeout() -> None:
    def responder(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    _requests, client = _client_factory(responder)
    discovery = CodexClientVersionDiscovery(lambda: client)

    with pytest.raises(CodexAuthError) as exc_info:
        await discovery.discover()

    assert exc_info.value.code == "client_version_timeout"


def test_stable_version_validation_rejects_metadata_noise() -> None:
    assert validate_stable_version("0.153.4") == "0.153.4"
    for value in ("latest", "1.2", "1.2.3+build", "1.2.3-rc.1", 1.2, None):
        with pytest.raises(CodexAuthError):
            validate_stable_version(value)


def test_npm_metadata_document_is_small_and_json() -> None:
    payload = {"name": "@openai/codex", "version": "1.2.3"}
    encoded = json.dumps(payload).encode("utf-8")

    assert len(encoded) < 64 * 1024
