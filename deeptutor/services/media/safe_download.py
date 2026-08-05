"""SSRF-safe media downloader for provider URLs, redirects and MCP resources.

Every image that arrives as a URL (OpenAI ``data[].url``, Responses
``image_url``, MCP ``ResourceLink`` / ``BlobResourceContents.uri``) is
materialized here before it reaches the content-addressed store (§12.2).  The
gate is fail-closed and layered:

* **URL shape** — only ``http``/``https``; any credentials in the URL are
  rejected; no other scheme (``file:``, ``data:``, …) is ever accepted.
* **Address policy** — every hop (including every redirect) is resolved and the
  resulting addresses are checked against a comprehensive blocklist: private,
  loopback, link-local / cloud-metadata, reserved, multicast and documentation
  ranges, for both IPv4 and IPv6.  An IPv6-mapped IPv4 address (``::ffff:``) is
  normalized so it cannot slip past as "not IPv4".
* **DNS-rebinding defense** — the production transport pins the *validated*
  address at connect time (``httpcore.AsyncNetworkBackend``): the resolver runs
  once and the socket is opened to the validated IP, with the Host header and
  TLS ``server_hostname`` still bound to the original hostname.  A record that
  flips after validation can never steer the connection inward.
* **Redirect policy** — redirects are followed manually (``follow_redirects``
  is always off) so every ``Location`` is re-validated with the full address
  policy before the next request, and a redirect to a blocked address is
  rejected rather than followed.
* **Body policy** — the body is streamed under a byte cap, the declared
  Content-Type must be an allowed image type and agree with the file magic, the
  pixel dimensions are checked *before* any decompression, and the image must
  decode completely (Pillow ``verify``).

Nothing here logs or persists the raw URL: error text keeps the host but drops
query strings, fragments and any credentials (§10.5).
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
import socket
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import MediaError, MediaValidationError
from deeptutor.services.media.persistence import image_info

logger = logging.getLogger(__name__)

#: Maximum number of redirect hops before a download is rejected.
DEFAULT_MAX_REDIRECTS = 5

#: Networks that are never acceptable download targets, for either posture.
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(item)
    for item in (
        # IPv4 — "this network", private, CGNAT, loopback, link-local/metadata,
        # reserved, benchmarking, TEST-NET, multicast, and the reserved class-E
        # range that also contains the 255.255.255.255 broadcast.
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        # IPv6 — unspecified, loopback, documentation, ORCHID, unique-local,
        # link-local, and multicast.
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "2001:db8::/32",
        "2001:10::/28",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


def _normalize_addr(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Normalize IPv6-mapped IPv4 addresses (``::ffff:169.254.x.x``) to IPv4."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when *addr* is a disallowed download target."""
    normalized = _normalize_addr(addr)
    return any(normalized in net for net in _BLOCKED_NETWORKS)


#: Resolver signature: hostname -> list of dotted/colon address strings.
Resolver = Callable[[str], list[str]]


def _default_resolver(hostname: str) -> list[str]:
    """Resolve *hostname* to every address ``getaddrinfo`` reports."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"Cannot resolve hostname: {hostname!r}") from exc
    addresses: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in addresses:
            addresses.append(addr)
    return addresses


def _addresses(
    hostname: str, resolver: Resolver
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for text in resolver(hostname):
        try:
            addr = ipaddress.ip_address(text)
        except ValueError:
            continue
        if addr not in out:
            out.append(addr)
    return out


def _validate_url_text(url: str) -> httpx.URL:
    """Reject disallowed schemes and URL-embedded credentials."""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SSRFBlockedError(
            f"Only http/https download targets are allowed (got {scheme or 'none'!r})."
        )
    if parsed.username or parsed.password:
        raise SSRFBlockedError("URLs carrying credentials are not allowed.")
    if not parsed.hostname:
        raise SSRFBlockedError("Download URL has no hostname.")
    return httpx.URL(url)


def _sanitize_for_error(url: str) -> str:
    """Trim a URL to ``host/path`` for error text (no query, no credentials)."""
    try:
        parsed = urlsplit(url)
    except Exception:
        return "<invalid url>"
    host = parsed.hostname or "<no-host>"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path or '/'}"


class SafeDownloadError(MediaError):
    """A remote download could not be completed safely."""


class SSRFBlockedError(SafeDownloadError):
    """The URL/host/address was rejected by the SSRF policy."""


@dataclass(frozen=True)
class SafeDownloadResult:
    """Validated media bytes materialized from a remote URL."""

    data: bytes
    mime_type: str
    #: The final URL after redirects, sanitized for provenance (never persisted
    #: with query strings / credentials; kept here so callers can audit hops).
    final_url: str = ""


def validate_media_bytes(data: bytes, *, limits: MediaLimits) -> tuple[str, int, int]:
    """Validate bytes against the media policy without writing anything.

    Returns ``(sniffed_mime, width, height)`` or raises
    :class:`MediaValidationError`.  Used by the downloader and the adapters
    before bytes reach the content-addressed store (§12.1 steps 3-4).
    """
    if not data:
        raise MediaValidationError("Refusing to accept an empty media payload.")
    if len(data) > limits.max_file_bytes:
        raise MediaValidationError(
            f"Media payload of {len(data)} bytes exceeds per-file limit {limits.max_file_bytes}."
        )
    info = image_info(data)
    if info is None:
        raise MediaValidationError("Unrecognized image magic; refusing to accept.")
    sniffed, width, height = info
    if not limits.allows_mime(sniffed):
        raise MediaValidationError(f"MIME {sniffed!r} is not allowed.")
    if width * height > limits.max_pixels:
        raise MediaValidationError(
            f"Image {width}x{height} exceeds pixel limit {limits.max_pixels}."
        )
    # Full decode must succeed (truncated/corrupt data is rejected).
    from io import BytesIO

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - Pillow is a project dependency
        raise MediaValidationError(f"Image decoder unavailable: {exc}") from exc
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise MediaValidationError(f"Image decode/verification failed: {exc}") from exc
    return sniffed, width, height


# ── connect-time DNS-rebinding defense ───────────────────────────────────────


class _ValidatedNetworkBackend:
    """``httpcore.AsyncNetworkBackend`` that pins a validated address per host.

    ``connect_tcp`` resolves the hostname itself, rejects the connection when
    *any* resolved address is disallowed, and opens the socket to the first
    allowed address.  Because the resolution happens here — once — and the
    socket is opened to the resulting IP, a DNS record that changes afterwards
    cannot redirect the connection (the Host header and the TLS
    ``server_hostname`` are still bound to the original hostname by httpcore).
    """

    def __init__(
        self,
        *,
        inner: Any,
        resolver: Resolver | None = None,
    ) -> None:
        self._inner = inner
        self._resolver = resolver or _default_resolver

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        addresses = _addresses(host, self._resolver)
        if not addresses:
            raise SSRFBlockedError(f"Cannot resolve hostname: {host!r}")
        blocked = [addr for addr in addresses if is_blocked_ip(addr)]
        if blocked:
            raise SSRFBlockedError(
                f"Blocked: {host!r} resolves to a disallowed address ({blocked[0]})."
            )
        # Pin the first allowed address; the socket is opened to this IP and
        # never re-resolves the hostname.
        pinned = str(addresses[0])
        return await self._inner.connect_tcp(
            pinned,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> Any:
        raise SSRFBlockedError("Unix-socket download targets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def build_validated_client(
    *,
    resolver: Resolver | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.AsyncClient:
    """Build an :class:`httpx.AsyncClient` whose connections use the validated
    network backend (no proxies, no auto-redirects — redirects are re-validated
    manually by :class:`SafeDownloader`)."""
    import httpcore
    from httpcore._backends.auto import AutoBackend

    ssl_context = httpx._config.create_ssl_context(verify=True, trust_env=False)
    backend = _ValidatedNetworkBackend(
        inner=AutoBackend(),
        resolver=resolver,
    )
    pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl_context,
        network_backend=backend,
        max_connections=10,
    )

    class _ValidatedTransport(httpx.AsyncHTTPTransport):
        def __init__(self) -> None:
            self._pool = pool

    return httpx.AsyncClient(
        transport=_ValidatedTransport(),
        timeout=timeout or httpx.Timeout(60.0, connect=20.0),
        follow_redirects=False,
        trust_env=False,
    )


class SafeDownloader:
    """Materialize a remote image URL into validated bytes (§12.2).

    ``client`` is injectable for offline tests (e.g. ``httpx.MockTransport``);
    production uses :func:`build_validated_client` so the address policy is
    enforced at connect time, not only by the pre-request check.
    """

    def __init__(
        self,
        *,
        limits: MediaLimits,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        read_timeout: float = 1800.0,
        connect_timeout: float = 20.0,
    ) -> None:
        self._limits = limits
        self._resolver = resolver
        self._max_redirects = max_redirects
        self._client = client or build_validated_client(
            resolver=resolver,
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
        )
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _validate_host(self, url: httpx.URL) -> None:
        """Resolve *url*'s host and reject it when any address is disallowed."""
        addresses = _addresses(url.host, self._resolver)
        if not addresses:
            raise SSRFBlockedError(f"Cannot resolve hostname: {url.host!r}")
        blocked = [addr for addr in addresses if is_blocked_ip(addr)]
        if blocked:
            raise SSRFBlockedError(
                f"Blocked: {url.host!r} resolves to a disallowed address ({blocked[0]})."
            )

    async def download(
        self,
        url: str,
        *,
        declared_mime: str = "",
    ) -> SafeDownloadResult:
        """Download *url* to validated bytes.

        Every redirect hop re-enters the full URL + address validation.  The
        body is streamed under the byte cap and then validated (Content-Type,
        magic, pixel cap, decode) before anything is returned.
        """
        current = _validate_url_text(url)
        await self._validate_host(current)
        redirects = 0
        final_url = current

        while True:
            request = self._client.build_request("GET", str(current))
            try:
                response = await self._client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise SafeDownloadError(
                    f"Download of {_sanitize_for_error(str(current))} failed: {type(exc).__name__}"
                ) from exc
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    redirects += 1
                    if redirects > self._max_redirects:
                        raise SafeDownloadError(
                            f"Too many redirects downloading {_sanitize_for_error(str(current))}."
                        )
                    location = response.headers.get("location")
                    if not location:
                        raise SafeDownloadError(
                            f"Redirect with no Location from {_sanitize_for_error(str(current))}."
                        )
                    next_url = str(response.url.join(location))
                    next_parsed = _validate_url_text(next_url)
                    await self._validate_host(next_parsed)
                    current = next_parsed
                    final_url = str(current)
                    continue

                if response.status_code >= 400:
                    raise SafeDownloadError(
                        f"Download of {_sanitize_for_error(str(current))} "
                        f"returned HTTP {response.status_code}."
                    )

                declared = declared_mime or response.headers.get("content-type") or ""
                data = await self._read_body(response)
                sniffed, _width, _height = validate_media_bytes(data, limits=self._limits)
                normalized_declared = (declared or "").split(";")[0].strip().lower()
                if normalized_declared and normalized_declared != sniffed:
                    raise MediaValidationError(
                        f"MIME mismatch: declared {normalized_declared!r}, "
                        f"magic sniffed {sniffed!r}."
                    )
                return SafeDownloadResult(
                    data=data,
                    mime_type=sniffed,
                    final_url=_sanitize_for_error(str(final_url)),
                )
            finally:
                await response.aclose()

    async def _read_body(self, response: httpx.Response) -> bytes:
        """Stream *response* under the byte cap (no unbounded buffering)."""
        chunks: list[bytes] = []
        total = 0
        limit = self._limits.max_file_bytes
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise MediaValidationError(f"Media payload exceeds per-file limit {limit} bytes.")
            chunks.append(chunk)
        return b"".join(chunks)


async def download_media_url(
    url: str,
    *,
    limits: MediaLimits,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
) -> SafeDownloadResult:
    """Convenience one-shot download (owns and closes a temporary client)."""
    downloader = SafeDownloader(limits=limits, client=client, resolver=resolver)
    try:
        return await downloader.download(url)
    finally:
        await downloader.aclose()


__all__ = [
    "DEFAULT_MAX_REDIRECTS",
    "Resolver",
    "SafeDownloadError",
    "SafeDownloadResult",
    "SafeDownloader",
    "SSRFBlockedError",
    "build_validated_client",
    "download_media_url",
    "is_blocked_ip",
    "validate_media_bytes",
]
