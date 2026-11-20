"""Unit tests for the ``web_fetch`` tool's pure helpers."""

from __future__ import annotations

from pathlib import Path
import re
import socket

import httpx
import pytest

from deeptutor.tools.web_fetch import (
    DEFAULT_MAX_CHARS,
    FetchOutcome,
    _extract_readable,
    _is_disallowed_host,
    fetch_url_as_markdown,
)

_ARTICLE_FIXTURE = Path(__file__).parents[1] / "fixtures" / "web" / "vector_article.html"


@pytest.fixture(autouse=True)
def _isolated_fetch_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep backend resolution off the machine state: no deployment env
    override and a throwaway settings dir, so ``backend=None`` always
    resolves to local regardless of the real user settings."""
    from deeptutor.services.config import runtime_settings

    monkeypatch.delenv("DEEPTUTOR_FETCH_BACKEND", raising=False)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True)
    monkeypatch.setattr(runtime_settings, "_global_settings_dir", lambda: settings_dir)
    monkeypatch.setattr(runtime_settings.RuntimeSettingsService, "_instances", {}, raising=False)


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


def _dns_rows(*addresses: str) -> list[tuple]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 0, 0, 0) if ":" in address else (address, 0),
        )
        for address in addresses
    ]


def test_is_disallowed_host_allows_public_hostname(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: _dns_rows("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )

    assert _is_disallowed_host("public.example") is False


def test_mixed_public_and_private_dns_answers_are_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: _dns_rows("2001::1", "93.184.216.34"),
    )

    assert _is_disallowed_host("mixed.example") is True


def test_all_unsafe_dns_answers_are_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: _dns_rows("127.0.0.1", "169.254.169.254", "2001::1"),
    )

    assert _is_disallowed_host("unsafe.example") is True


@pytest.mark.parametrize(
    ("host", "disallowed"),
    [
        ("8.8.8.8", False),
        ("127.0.0.1", True),
        ("169.254.169.254", True),
        ("198.18.0.15", True),
        ("[2001:2::8a]", True),
        ("::1", True),
    ],
)
def test_ip_literal_validation_is_unchanged(host: str, disallowed: bool, monkeypatch) -> None:
    doh_called = False

    class _FailIfCalledClient:
        def __init__(self, **_kwargs):
            nonlocal doh_called
            doh_called = True

    monkeypatch.setattr(httpx, "Client", _FailIfCalledClient)
    assert _is_disallowed_host(host) is disallowed
    assert doh_called is False


def _stub_doh_client(responses_by_query):
    class _Response:
        def __init__(self, status_code: int, payload: object):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url: str, **_kwargs):
            result = responses_by_query(url)
            if isinstance(result, Exception):
                raise result
            status_code, payload = result
            return _Response(status_code, payload)

    return _Client


@pytest.mark.parametrize(
    "fake_ips",
    [
        ("198.18.0.15",),
        ("198.18.1.70", "2001:2::8a"),
    ],
)
def test_fake_ip_dns_allows_host_with_verified_public_doh(
    monkeypatch, fake_ips: tuple[str, ...]
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda _host, _port: _dns_rows(*fake_ips))
    monkeypatch.setenv("DEEPTUTOR_DOH_ENDPOINTS", "https://doh1.example/dns-query")

    def _query(url: str):
        if "type=A&" in url or url.endswith("type=A"):
            return (
                200,
                {
                    "Status": 0,
                    "Answer": [
                        {"type": 5, "data": "edge.public.example."},
                        {"type": 1, "data": "93.184.216.34"},
                    ],
                },
            )
        return (
            200,
            {
                "Status": 0,
                "Answer": [{"type": 28, "data": "2606:2800:220:1:248:1893:25c8:1946"}],
            },
        )

    monkeypatch.setattr(httpx, "Client", _stub_doh_client(_query))
    assert _is_disallowed_host("public.example") is False


@pytest.mark.parametrize(
    "doh_payloads",
    [
        # DoH resolves to synthetic Fake-IP itself
        {
            "A": (200, {"Status": 0, "Answer": [{"type": 1, "data": "198.18.0.15"}]}),
            "AAAA": (200, {"Status": 0, "Answer": []}),
        },
        # DoH resolves to loopback
        {
            "A": (200, {"Status": 0, "Answer": [{"type": 1, "data": "127.0.0.1"}]}),
            "AAAA": (200, {"Status": 0, "Answer": []}),
        },
        # DoH mixes public A with private AAAA
        {
            "A": (200, {"Status": 0, "Answer": [{"type": 1, "data": "93.184.216.34"}]}),
            "AAAA": (200, {"Status": 0, "Answer": [{"type": 28, "data": "fc00::1"}]}),
        },
        # DoH reports NXDOMAIN
        {
            "A": (200, {"Status": 3}),
            "AAAA": (200, {"Status": 3}),
        },
        # Transport timeout across endpoints -> fail closed
        {
            "A": httpx.ConnectTimeout("timed out"),
            "AAAA": httpx.ConnectTimeout("timed out"),
        },
    ],
)
def test_fake_ip_dns_fails_closed_when_doh_not_public(monkeypatch, doh_payloads: dict) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda _host, _port: _dns_rows("198.18.1.70"))
    monkeypatch.setenv("DEEPTUTOR_DOH_ENDPOINTS", "https://doh1.example/dns-query")

    def _query(url: str):
        if "type=AAAA" in url:
            return doh_payloads["AAAA"]
        return doh_payloads["A"]

    monkeypatch.setattr(httpx, "Client", _stub_doh_client(_query))
    assert _is_disallowed_host("internal.example") is True


def test_mixed_fake_ip_and_private_dns_blocks_without_doh(monkeypatch) -> None:
    doh_called = False

    class _FailIfCalledClient:
        def __init__(self, **_kwargs):
            nonlocal doh_called
            doh_called = True

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: _dns_rows("198.18.0.15", "127.0.0.1"),
    )
    monkeypatch.setattr(httpx, "Client", _FailIfCalledClient)

    assert _is_disallowed_host("mixed-fake.example") is True
    assert doh_called is False


def test_fake_ip_dns_falls_back_to_second_doh_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda _host, _port: _dns_rows("198.18.1.70"))
    monkeypatch.setenv(
        "DEEPTUTOR_DOH_ENDPOINTS",
        "https://doh1.example/dns-query,https://doh2.example/resolve",
    )

    def _query(url: str):
        if url.startswith("https://doh1.example"):
            return httpx.ConnectError("unreachable")
        if "type=AAAA" in url:
            return (200, {"Status": 0, "Answer": []})
        return (200, {"Status": 0, "Answer": [{"type": 1, "data": "93.184.216.34"}]})

    monkeypatch.setattr(httpx, "Client", _stub_doh_client(_query))
    assert _is_disallowed_host("fallback.example") is False


@pytest.mark.asyncio
async def test_fetch_url_allows_fake_ip_host_through_default_validator(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda _host, _port: _dns_rows("198.18.1.70"))
    monkeypatch.setenv("DEEPTUTOR_DOH_ENDPOINTS", "https://doh1.example/dns-query")

    def _query(url: str):
        if "type=AAAA" in url:
            return (200, {"Status": 0, "Answer": []})
        return (200, {"Status": 0, "Answer": [{"type": 1, "data": "93.184.216.34"}]})

    monkeypatch.setattr(httpx, "Client", _stub_doh_client(_query))
    response = _StubResponse(
        body=b"<html><title>Notice</title><body><p>Public content</p></body></html>",
        url="https://public.example/notice",
    )
    outcome = await fetch_url_as_markdown(
        "https://public.example/notice",
        client_factory=_factory_returning(response),
    )

    assert outcome.ok is True
    assert "Public content" in outcome.markdown


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


def test_extract_readable_prefers_article_over_navigation_chrome() -> None:
    html = """
    <html><head><title>Research note</title></head><body>
      <nav>Home Products Pricing</nav>
      <main><article><h1>Reward models</h1><p>Pairwise comparisons.</p></article></main>
      <footer>Legal sitemap</footer>
    </body></html>
    """
    title, body = _extract_readable(html)
    assert title == "Research note"
    assert "Reward models" in body
    assert "Pairwise comparisons" in body
    assert "Products Pricing" not in body
    assert "Legal sitemap" not in body


def test_extract_readable_keeps_fixture_heading_hierarchy_without_page_chrome() -> None:
    title, body = _extract_readable(_ARTICLE_FIXTURE.read_text(encoding="utf-8"))

    assert title == "Transformer (deep learning)"
    assert re.findall(r"^#{1,6} .+$", body, re.MULTILINE) == [
        "# Transformer (deep learning)",
        "## History",
        "### Predecessors",
        "## Applications",
    ]
    assert "Jump to content" not in body
    assert "Toggle History subsection" not in body
    assert "Privacy policy" not in body
    assert "navigation footer" not in body
    assert "Vector/Parsoid" not in body


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
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.status_code = status
        self.url = url
        self.encoding = encoding
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}

    async def aiter_bytes(self):
        yield self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _StubAsyncClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
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
async def test_default_fetch_connects_by_hostname_not_by_address(
    monkeypatch,
) -> None:
    """The request must keep the hostname, even though DNS was checked.

    Substituting the validated IP into the URL would break TLS certificate
    verification, and behind an HTTP proxy it fails outright — there the proxy
    resolves the name, so an address chosen here is not the one connected to.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: _dns_rows("93.184.216.34"),
    )
    client = _StubAsyncClient(_StubResponse())

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        client_factory=lambda **_kwargs: client,
    )

    assert outcome.ok is True
    _method, request_url, kwargs = client.requests[0]
    assert request_url == "https://example.com/p"
    assert "Host" not in kwargs["headers"]
    # Redirects are followed by hand so each hop is validated before it is
    # contacted; letting the client follow them would skip that check.
    assert kwargs["follow_redirects"] is False


@pytest.mark.asyncio
async def test_default_fetch_revalidates_redirect_before_connecting(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, _port: _dns_rows("93.184.216.34"),
    )
    client = _StubAsyncClient(
        _StubResponse(
            status=302,
            headers={"location": "http://127.0.0.1/private"},
        )
    )

    outcome = await fetch_url_as_markdown(
        "https://example.com/p",
        client_factory=lambda **_kwargs: client,
    )

    assert outcome.ok is False
    assert "Redirect to private/loopback host blocked" in outcome.error
    assert len(client.requests) == 1


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


# "喆" is outside GB2312, so pages labelled gb2312 only render it when the
# label is decoded as its GBK superset, as browsers do.
_GBK_TEXT = "傅里叶变换将信号分解为不同频率的正弦波。——喆"


@pytest.mark.parametrize(
    "meta",
    [
        '<meta charset="gbk">',
        '<meta http-equiv="Content-Type" content="text/html; charset=gb2312">',
    ],
)
@pytest.mark.asyncio
async def test_fetch_honours_meta_charset_when_header_has_none(meta: str) -> None:
    body = f"<html><head>{meta}<title>笔记</title></head><body><p>{_GBK_TEXT}</p></body></html>"
    response = _StubResponse(
        body=body.encode("gbk"),
        headers={"content-type": "text/html"},
    )

    outcome = await fetch_url_as_markdown(
        "https://example.com/gbk",
        client_factory=_factory_returning(response),
        host_validator=_ALLOW_ALL,
    )

    assert outcome.ok is True
    assert outcome.title == "笔记"
    assert _GBK_TEXT in outcome.markdown
    assert "�" not in outcome.markdown


@pytest.mark.asyncio
async def test_fetch_header_charset_wins_over_meta_and_bom_wins_over_both() -> None:
    body = f'<html><head><meta charset="gbk"></head><body><p>{_GBK_TEXT}</p></body></html>'
    header_utf8 = _StubResponse(
        body=body.encode("utf-8"),
        headers={"content-type": 'text/html; charset="UTF-8"'},
    )
    bom_utf8 = _StubResponse(
        body=b"\xef\xbb\xbf" + body.encode("utf-8"),
        headers={"content-type": "text/html; charset=iso-8859-1"},
    )

    for response in (header_utf8, bom_utf8):
        outcome = await fetch_url_as_markdown(
            "https://example.com/utf8",
            client_factory=_factory_returning(response),
            host_validator=_ALLOW_ALL,
        )
        assert outcome.ok is True
        assert _GBK_TEXT in outcome.markdown
        assert "﻿" not in outcome.markdown


@pytest.mark.asyncio
async def test_fetch_propagates_http_error_as_outcome_not_exception() -> None:
    outcome = await fetch_url_as_markdown(
        "https://example.com/missing",
        client_factory=_factory_returning(_StubResponse(status=404, body=b"<p>missing</p>")),
        host_validator=_ALLOW_ALL,
    )
    assert outcome.ok is False
    assert "404" in outcome.error
