"""MED-02 safe-downloader security tests (offline).

Covers the SSRF address policy (private/loopback/link-local/metadata/reserved/
multicast, IPv4-mapped IPv6), URL shape (scheme, credentials), redirect
re-validation, DNS-rebinding defense, and the media policy (Content-Type/magic
agreement, byte cap, pixel cap before decompression, decode completeness).
No real network call is made anywhere.
"""

from __future__ import annotations

import base64
import ipaddress

import httpx
import pytest

from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import MediaValidationError
from deeptutor.services.media.safe_download import (
    SafeDownloader,
    SafeDownloadError,
    SSRFBlockedError,
    _ValidatedNetworkBackend,
    is_blocked_ip,
    validate_media_bytes,
)
from tests.services.media._media_helpers import make_png, make_png_header_only


def _downloader(
    handler,
    *,
    resolver=None,
    limits: MediaLimits | None = None,
) -> SafeDownloader:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    default_resolver = lambda host: ["93.184.216.34"]  # noqa: E731 - test double
    return SafeDownloader(
        limits=limits or MediaLimits(),
        client=client,
        resolver=resolver or default_resolver,
    )


# ── address policy ──────────────────────────────────────────────────────────


def test_is_blocked_ip_covers_private_loopback_linklocal_metadata_and_v6() -> None:
    blocked = [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.5",
        "100.64.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
    ]
    for text in blocked:
        assert is_blocked_ip(ipaddress.ip_address(text)), text

    allowed = ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1"]
    for text in allowed:
        assert not is_blocked_ip(ipaddress.ip_address(text)), text


def test_is_blocked_ip_normalizes_ipv4_mapped_ipv6() -> None:
    """``::ffff:169.254.169.254`` must be treated as the metadata address."""
    assert is_blocked_ip(ipaddress.ip_address("::ffff:169.254.169.254"))
    assert is_blocked_ip(ipaddress.ip_address("::ffff:127.0.0.1"))
    assert not is_blocked_ip(ipaddress.ip_address("::ffff:93.184.216.34"))


# ── URL shape ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_scheme_rejected() -> None:
    dl = _downloader(lambda req: httpx.Response(404))
    with pytest.raises(SSRFBlockedError, match="Only http/https"):
        await dl.download("file:///etc/passwd")


@pytest.mark.asyncio
async def test_credentials_in_url_rejected() -> None:
    dl = _downloader(lambda req: httpx.Response(404))
    with pytest.raises(SSRFBlockedError, match="credentials"):
        await dl.download("https://user:secret@cdn.example/img.png")


@pytest.mark.asyncio
async def test_missing_hostname_rejected() -> None:
    dl = _downloader(lambda req: httpx.Response(404))
    with pytest.raises(SSRFBlockedError, match="hostname"):
        await dl.download("https:///img.png")


# ── DNS / IP rejection at the hop level ─────────────────────────────────────


@pytest.mark.asyncio
async def test_host_resolving_to_private_ip_rejected() -> None:
    dl = _downloader(
        lambda req: httpx.Response(200, content=make_png(), headers={"content-type": "image/png"}),
        resolver=lambda host: ["10.0.0.5"],
    )
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        await dl.download("https://internal.example/img.png")


@pytest.mark.asyncio
async def test_host_resolving_to_metadata_ip_rejected() -> None:
    dl = _downloader(
        lambda req: httpx.Response(404),
        resolver=lambda host: ["169.254.169.254"],
    )
    with pytest.raises(SSRFBlockedError, match="169.254.169.254"):
        await dl.download("http://metadata.example/latest/meta-data")


# ── redirect re-validation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redirect_to_public_url_is_followed_and_validated() -> None:
    png = make_png()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://cdn.example/img.png"})
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    dl = _downloader(handler)
    result = await dl.download("https://cdn.example/start")
    assert result.data == png
    assert result.mime_type == "image/png"
    assert "cdn.example/img.png" in result.final_url


@pytest.mark.asyncio
async def test_redirect_to_metadata_ip_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
        )

    def resolver(host: str):
        if host == "169.254.169.254":
            return ["169.254.169.254"]
        return ["93.184.216.34"]

    dl = _downloader(handler, resolver=resolver)
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        await dl.download("https://cdn.example/start")


@pytest.mark.asyncio
async def test_redirect_to_private_ip_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://192.168.0.10/secret"})

    dl = _downloader(
        handler,
        resolver=lambda host: ["192.168.0.10"] if host == "192.168.0.10" else ["93.184.216.34"],
    )
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        await dl.download("https://cdn.example/start")


@pytest.mark.asyncio
async def test_too_many_redirects_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    dl = _downloader(handler, limits=MediaLimits(max_file_bytes=1000))
    with pytest.raises(SafeDownloadError, match="Too many redirects"):
        await dl.download("https://cdn.example/start")


# ── DNS-rebinding defense (connect-time pinning) ────────────────────────────


class _FakeInnerBackend:
    def __init__(self) -> None:
        self.connected: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append((host, port))
        return f"stream-to-{host}"

    async def sleep(self, seconds: float) -> None:
        return None


@pytest.mark.asyncio
async def test_connect_pins_the_validated_public_ip() -> None:
    inner = _FakeInnerBackend()
    backend = _ValidatedNetworkBackend(inner=inner, resolver=lambda host: ["93.184.216.34"])
    await backend.connect_tcp("example.com", 443)
    # The socket is opened to the *validated IP*, never a re-resolvable hostname.
    assert inner.connected == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_connect_rejects_private_resolution() -> None:
    inner = _FakeInnerBackend()
    backend = _ValidatedNetworkBackend(inner=inner, resolver=lambda host: ["10.0.0.5"])
    with pytest.raises(SSRFBlockedError):
        await backend.connect_tcp("evil.example", 443)
    assert inner.connected == []


@pytest.mark.asyncio
async def test_connect_rejects_metadata_resolution() -> None:
    inner = _FakeInnerBackend()
    backend = _ValidatedNetworkBackend(inner=inner, resolver=lambda host: ["169.254.169.254"])
    with pytest.raises(SSRFBlockedError):
        await backend.connect_tcp("metadata.example", 443)


@pytest.mark.asyncio
async def test_dns_rebinding_after_validation_cannot_redirect() -> None:
    """A record that flips to a private address on a later connection must be
    re-validated at connect time; the socket is never opened inward."""
    inner = _FakeInnerBackend()
    state = {"flipped": False}

    def resolver(host: str):
        # First connection resolves public; after that the attacker flips DNS.
        return ["169.254.169.254"] if state["flipped"] else ["93.184.216.34"]

    backend = _ValidatedNetworkBackend(inner=inner, resolver=resolver)
    await backend.connect_tcp("flip.example", 443)
    assert inner.connected == [("93.184.216.34", 443)]

    state["flipped"] = True
    with pytest.raises(SSRFBlockedError):
        await backend.connect_tcp("flip.example", 443)
    # The inner backend was never asked to connect to the metadata address.
    assert inner.connected == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_unix_socket_connect_is_refused() -> None:
    inner = _FakeInnerBackend()
    backend = _ValidatedNetworkBackend(inner=inner, resolver=lambda host: ["93.184.216.34"])
    with pytest.raises(SSRFBlockedError, match="Unix-socket"):
        await backend.connect_unix_socket("/tmp/whatever")


# ── media policy on the downloaded bytes ────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_png_downloads_ok() -> None:
    png = make_png()
    dl = _downloader(
        lambda req: httpx.Response(200, content=png, headers={"content-type": "image/png"})
    )
    result = await dl.download("https://cdn.example/img.png")
    assert result.data == png
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_content_type_mismatch_rejected() -> None:
    dl = _downloader(
        lambda req: httpx.Response(200, content=make_png(), headers={"content-type": "text/html"})
    )
    with pytest.raises(MediaValidationError, match="MIME mismatch"):
        await dl.download("https://cdn.example/img.png")


@pytest.mark.asyncio
async def test_svg_script_payload_rejected() -> None:
    payload = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    dl = _downloader(
        lambda req: httpx.Response(200, content=payload, headers={"content-type": "image/svg+xml"})
    )
    with pytest.raises(MediaValidationError, match="magic"):
        await dl.download("https://cdn.example/img.svg")


@pytest.mark.asyncio
async def test_mime_spoof_png_bytes_but_gif_header_rejected() -> None:
    png = make_png()
    # Declares image/gif but carries PNG magic.
    dl = _downloader(
        lambda req: httpx.Response(200, content=png, headers={"content-type": "image/gif"})
    )
    with pytest.raises(MediaValidationError, match="MIME mismatch"):
        await dl.download("https://cdn.example/img.png")


@pytest.mark.asyncio
async def test_byte_cap_exceeded_while_streaming() -> None:
    limits = MediaLimits(max_file_bytes=50)
    dl = _downloader(
        lambda req: httpx.Response(200, content=make_png(), headers={"content-type": "image/png"}),
        limits=limits,
    )
    with pytest.raises(MediaValidationError, match="per-file limit"):
        await dl.download("https://cdn.example/img.png")


@pytest.mark.asyncio
async def test_pixel_cap_rejected_before_decompression() -> None:
    limits = MediaLimits(max_pixels=64 * 64)
    # Header declares 8192x8192 = 67M pixels; no IDAT needed for the header
    # check to fire before any decompression.
    dl = _downloader(
        lambda req: httpx.Response(
            200,
            content=make_png_header_only(8192, 8192),
            headers={"content-type": "image/png"},
        ),
        limits=limits,
    )
    with pytest.raises(MediaValidationError, match="pixel limit"):
        await dl.download("https://cdn.example/big.png")


@pytest.mark.asyncio
async def test_truncated_png_rejected_on_decode() -> None:
    png = make_png()
    truncated = png[: len(png) - 12]  # drop IEND + crc
    dl = _downloader(
        lambda req: httpx.Response(200, content=truncated, headers={"content-type": "image/png"})
    )
    with pytest.raises(MediaValidationError, match="decode/verification"):
        await dl.download("https://cdn.example/broken.png")


@pytest.mark.asyncio
async def test_http_error_surfaces_without_body() -> None:
    dl = _downloader(
        lambda req: httpx.Response(
            500,
            content="sk-super-secret-key-value leaked",
            headers={"content-type": "text/plain"},
        )
    )
    with pytest.raises(SafeDownloadError) as excinfo:
        await dl.download("https://cdn.example/err.png")
    assert "sk-super-secret" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_error_text_never_includes_query_string_or_credentials() -> None:
    dl = _downloader(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(SafeDownloadError) as excinfo:
        await dl.download("https://cdn.example/img.png?token=supersecretquery")
    text = str(excinfo.value)
    assert "supersecretquery" not in text
    assert "?token=" not in text


# ── validate_media_bytes unit coverage ──────────────────────────────────────


def test_validate_media_bytes_accepts_valid_png() -> None:
    sniffed, width, height = validate_media_bytes(make_png(4, 4), limits=MediaLimits())
    assert sniffed == "image/png"
    assert (width, height) == (4, 4)


def test_validate_media_bytes_rejects_empty() -> None:
    with pytest.raises(MediaValidationError, match="empty"):
        validate_media_bytes(b"", limits=MediaLimits())


def test_validate_media_bytes_rejects_oversized() -> None:
    with pytest.raises(MediaValidationError, match="per-file limit"):
        validate_media_bytes(make_png(), limits=MediaLimits(max_file_bytes=10))
