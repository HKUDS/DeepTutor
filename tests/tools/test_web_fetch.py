"""Unit tests for the ``web_fetch`` tool's pure helpers."""

from __future__ import annotations

import pytest

from deeptutor.tools.web_fetch import (
    DEFAULT_MAX_CHARS,
    FetchOutcome,
    _extract_readable,
    _is_disallowed_host,
    fetch_url_as_markdown,
)

# ---------------------------------------------------------------------------
# Host validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "localhost",
        "10.0.0.1",
        "192.168.1.1",
        "169.254.1.1",
        "::1",
        "[::1]",
        "metadata.local",
    ],
)
def test_is_disallowed_host_blocks_private_addresses(host: str) -> None:
    assert _is_disallowed_host(host) is True, f"{host!r} should be disallowed"


def test_is_disallowed_host_allows_public_hostname() -> None:
    # The DNS-dependent positive test is environment-fragile (CI sandboxes
    # often block outbound DNS). The negative coverage above plus the
    # injectable ``host_validator`` (used in fetch tests) makes a fully-
    # offline public-host assertion unnecessary.
    pytest.skip("public DNS check skipped; relies on injectable validator in tests")


# ---------------------------------------------------------------------------
# HTML readability extraction
# ---------------------------------------------------------------------------


def test_extract_readable_strips_scripts_and_styles() -> None:
    html = """
    <html><head><title>Hello</title><style>body {color:red;}</style></head>
    <body><p>Visible.</p><script>alert('no');</script></body></html>
    """
    title, body = _extract_readable(html)
    assert title == "Hello"
    assert "Visible." in body
    assert "alert" not in body
    assert "color:red" not in body
    # Title is prepended as h1 markdown
    assert body.startswith("# Hello")


def test_extract_readable_passes_through_plain_text() -> None:
    title, body = _extract_readable("Plain text payload\nwith two lines.")
    assert title == ""
    assert "Plain text payload" in body
    assert "with two lines" in body


# ---------------------------------------------------------------------------
# Top-level fetch — uses injected client_factory so no real network I/O.
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(
        self,
        *,
        body: bytes = b"<html><title>T</title><body><p>x</p></body></html>",
        status: int = 200,
        url: str = "https://example.com/p",
        encoding: str = "utf-8",
    ) -> None:
        self._body = body
        self.status_code = status
        self.url = url
        self.encoding = encoding
        self.headers = {"content-type": "text/html; charset=utf-8"}

    async def aiter_bytes(self):
        yield self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _StubAsyncClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, _method, _url, **_kwargs):
        outer = self

        class _Ctx:
            async def __aenter__(self):
                return outer._response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


def _factory_returning(response: _StubResponse):
    def _factory(*, timeout: float, user_agent: str):
        return _StubAsyncClient(response)

    return _factory


@pytest.mark.asyncio
async def test_fetch_rejects_unsupported_scheme() -> None:
    outcome = await fetch_url_as_markdown("ftp://example.com/x")
    assert outcome.ok is False
    assert "scheme" in outcome.error.lower()


@pytest.mark.asyncio
async def test_fetch_rejects_private_host() -> None:
    outcome = await fetch_url_as_markdown("http://127.0.0.1/x")
    assert outcome.ok is False
    assert "private" in outcome.error.lower() or "loopback" in outcome.error.lower()


# Bypass DNS in every stubbed-network test — the validator is treated as
# trusted here because ``client_factory`` already pins the response.
_ALLOW_ALL = lambda host: False  # noqa: E731 — single-use stub


@pytest.mark.asyncio
async def test_fetch_extracts_html_via_stubbed_client() -> None:
    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        client_factory=_factory_returning(_StubResponse()),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is True
    assert outcome.title == "T"
    assert "x" in outcome.markdown


@pytest.mark.asyncio
async def test_fetch_truncates_at_max_chars() -> None:
    big_body = b"<html><body>" + (b"a" * 5000) + b"</body></html>"
    outcome = await fetch_url_as_markdown(
        "https://example.com/big",
        max_chars=200,
        client_factory=_factory_returning(_StubResponse(body=big_body)),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is True
    assert outcome.truncated is True
    assert outcome.markdown.endswith("…[truncated]")
    assert len(outcome.markdown) <= 220  # cap + marker headroom


@pytest.mark.asyncio
async def test_fetch_propagates_http_error_as_outcome_not_exception() -> None:
    outcome = await fetch_url_as_markdown(
        "https://example.com/missing",
        client_factory=_factory_returning(_StubResponse(status=404, body=b"<p>missing</p>")),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is False
    assert "404" in outcome.error
