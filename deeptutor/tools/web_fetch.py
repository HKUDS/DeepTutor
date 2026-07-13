"""HTTP fetch + readable-content extraction for the chat ``web_fetch`` tool.

Kept deliberately self-contained: a single async entrypoint
:py:func:`fetch_url_as_markdown` that takes a URL and returns either the
extracted text (with a ``url`` field for citation) or a structured error.
The chat pipeline calls it via the thin ``WebFetchTool`` wrapper in
``deeptutor/tools/builtin/__init__.py``; no internal global state, no
hidden side-effects — easy to test by passing a mock httpx client.

Security stance (kept tight on purpose because the model decides
arguments, not a human):

* Only ``http://`` / ``https://`` schemes accepted.
* IP literals and hostnames resolving to **private / loopback / link-local**
  ranges are rejected up front. The strict-host check happens both
  pre-flight (against the parsed URL) and post-redirect (against the
  final resolved URL) so a redirect to ``127.0.0.1`` can't slip past.
* Response size is hard-capped at ``MAX_RESPONSE_BYTES``; we stop reading
  once the body grows past this even before the server finishes.
* Extracted text is truncated to ``max_chars`` (default 50 000 chars,
  caller-overridable) with a ``…[truncated]`` marker.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 50_000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MB — safety cap on raw download
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_USER_AGENT = "DeepTutor/1.0 (+https://hkuds.dev/deeptutor)"
ALLOWED_SCHEMES = {"http", "https"}

# Cheap inline HTML → text. Good enough for blog / docs / arxiv abstract
# pages. For JS-heavy SPAs the tool will return the bare HTML scaffold —
# the docstring tells the model it may fail in that case, so it won't
# fabricate around an empty result.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINE_RE = re.compile(r"\n{3,}")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class FetchOutcome:
    """Result of a single ``web_fetch`` invocation.

    ``ok=True`` paths populate ``markdown`` and ``url`` (the final
    resolved URL after redirects). ``ok=False`` paths populate ``error``
    with a one-line description suitable to surface back to the model.
    """

    ok: bool
    markdown: str = ""
    url: str = ""
    title: str = ""
    truncated: bool = False
    error: str = ""


async def fetch_url_as_markdown(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    user_agent: str = DEFAULT_USER_AGENT,
    client_factory: Any = None,
    host_validator: Any = None,
) -> FetchOutcome:
    """Fetch ``url`` and extract readable text.

    ``client_factory`` accepts a no-arg callable returning an
    ``httpx.AsyncClient``-compatible context manager. ``host_validator``
    is a ``(host: str) -> bool`` that returns ``True`` iff the host
    should be **rejected** as private/loopback — defaults to
    :py:func:`_is_disallowed_host`. Both default to real production
    behaviour; tests inject stubs to bypass DNS or network I/O.
    """
    url_clean = (url or "").strip().strip("`\"'")
    parsed = urlparse(url_clean)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return FetchOutcome(
            ok=False,
            error=f"Unsupported URL scheme: {parsed.scheme or '(empty)'}. Use http:// or https://.",
        )
    host = (parsed.hostname or "").strip()
    if not host:
        return FetchOutcome(ok=False, error="URL is missing a host.")
    validator = host_validator or _is_disallowed_host
    if validator(host):
        return FetchOutcome(
            ok=False,
            error=f"Refusing to fetch private/loopback host: {host}.",
        )

    factory = client_factory or _default_client_factory
    try:
        async with factory(timeout=timeout_s, user_agent=user_agent) as client:
            try:
                async with client.stream(
                    "GET",
                    url_clean,
                    headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"},
                    follow_redirects=True,
                ) as response:
                    final_url = str(response.url)
                    final_host = (urlparse(final_url).hostname or "").strip()
                    if final_host and validator(final_host):
                        return FetchOutcome(
                            ok=False,
                            error=f"Redirect to private/loopback host blocked: {final_host}.",
                        )
                    if response.status_code >= 400:
                        return FetchOutcome(
                            ok=False,
                            url=final_url,
                            error=f"HTTP {response.status_code} from {final_url}.",
                        )
                    raw = await _bounded_read(response, MAX_RESPONSE_BYTES)
            except httpx.HTTPError as exc:
                return FetchOutcome(ok=False, error=f"Network error: {exc}")
    except Exception as exc:  # pragma: no cover — defensive
        return FetchOutcome(ok=False, error=f"Unexpected fetch failure: {exc}")

    title, body = _extract_readable(raw)
    truncated = False
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n…[truncated]"
        truncated = True
    return FetchOutcome(ok=True, markdown=body, url=final_url, title=title, truncated=truncated)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _default_client_factory(*, timeout: float, user_agent: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        max_redirects=5,
    )


def _is_disallowed_host(host: str) -> bool:
    """Block hosts that resolve to private / loopback / link-local IPs.

    Handles both raw IP literals (``127.0.0.1`` / ``[::1]``) and DNS
    names (resolves them once via ``socket.getaddrinfo`` and checks ALL
    returned addresses). DNS failures are treated as disallowed to fail
    closed when in doubt.
    """
    candidate = host.strip("[]")
    # Direct IP literal check
    try:
        ip = ipaddress.ip_address(candidate)
        return _is_disallowed_ip(ip)
    except ValueError:
        pass
    # Common loopback / metadata hostnames before DNS even tries.
    lower = candidate.lower()
    if lower in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return True
    if lower.endswith(".local"):
        return True
    # Resolve once; treat resolution failure as "disallowed" so a typo
    # plus an unlucky stub doesn't accidentally hit a private network.
    try:
        infos = socket.getaddrinfo(candidate, None)
    except OSError:
        return True
    for info in infos:
        addr = info[4][0]
        try:
            if _is_disallowed_ip(ipaddress.ip_address(addr)):
                return True
        except ValueError:
            continue
    return False


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _bounded_read(response: httpx.Response, limit: int) -> str:
    """Stream-read at most ``limit`` bytes from ``response`` then stop.

    Avoids holding hundreds of MB if a server (or an LLM-supplied URL)
    points at a huge resource. Encoding falls back from response.encoding
    → utf-8 with replacement.
    """
    buf = bytearray()
    async for chunk in response.aiter_bytes():
        buf.extend(chunk)
        if len(buf) >= limit:
            break
    encoding = response.encoding or "utf-8"
    try:
        return buf.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        return buf.decode("utf-8", errors="replace")


def _extract_readable(html_or_text: str) -> tuple[str, str]:
    """Return ``(title, body_text)`` extracted from an HTML string.

    For non-HTML payloads (plain text, JSON dumps) just normalises
    whitespace and returns the input as-is — the model still gets
    something usable.
    """
    title = ""
    if "<" in html_or_text and ">" in html_or_text:
        title_match = _TITLE_RE.search(html_or_text)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        stripped = _SCRIPT_STYLE_RE.sub(" ", html_or_text)
        stripped = _TAG_RE.sub(" ", stripped)
        # Decode common entities cheaply (full entity table is overkill).
        stripped = (
            stripped.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        body = stripped
    else:
        body = html_or_text
    body = _WHITESPACE_RE.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    body = _BLANK_LINE_RE.sub("\n\n", body).strip()
    if title:
        body = f"# {title}\n\n{body}"
    return title, body


__all__ = [
    "DEFAULT_MAX_CHARS",
    "FetchOutcome",
    "fetch_url_as_markdown",
]
