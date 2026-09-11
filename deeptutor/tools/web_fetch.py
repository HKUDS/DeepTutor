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
* IP literals and hostnames resolving to **any private / loopback / link-local**
  address are rejected up front. The strict-host check happens both
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
from urllib.parse import urljoin, urlparse, urlsplit

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 50_000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MB — safety cap on raw download
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_USER_AGENT = "DeepTutor/1.0 (+https://hkuds.dev/deeptutor)"
ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5

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

    factory = client_factory or _default_client_factory
    current_url = url_clean
    try:
        async with factory(timeout=timeout_s, user_agent=user_agent) as client:
            # Redirects are followed by hand so that every hop is validated
            # *before* it is contacted. `follow_redirects=True` only lets us
            # inspect the final URL, by which point the client has already
            # connected to each intermediate host.
            for hop in range(MAX_REDIRECTS + 1):
                current = urlsplit(current_url)
                current_host = (current.hostname or "").strip()
                if current.scheme.lower() not in ALLOWED_SCHEMES or not current_host:
                    return FetchOutcome(ok=False, error="Redirect target is not a valid HTTP URL.")
                if validator(current_host):
                    return FetchOutcome(
                        ok=False,
                        error=(
                            f"Redirect to private/loopback host blocked: {current_host}."
                            if hop
                            else f"Refusing to fetch private/loopback host: {current_host}."
                        ),
                    )
                async with client.stream(
                    "GET",
                    current_url,
                    headers={
                        "User-Agent": user_agent,
                        "Accept": "text/html,*/*;q=0.5",
                    },
                    follow_redirects=False,
                ) as response:
                    location = response.headers.get("location", "")
                    if response.status_code in {301, 302, 303, 307, 308} and location:
                        if hop >= MAX_REDIRECTS:
                            return FetchOutcome(ok=False, error="Too many HTTP redirects.")
                        current_url = urljoin(current_url, location)
                        continue
                    final_url = str(response.url) or current_url
                    if response.status_code >= 400:
                        return FetchOutcome(
                            ok=False,
                            url=final_url,
                            error=f"HTTP {response.status_code} from {final_url}.",
                        )
                    raw = await _bounded_read(response, MAX_RESPONSE_BYTES)
                    break
            else:  # pragma: no cover — the loop returns at its redirect limit
                return FetchOutcome(ok=False, error="Too many HTTP redirects.")
    except httpx.HTTPError as exc:
        return FetchOutcome(ok=False, error=f"Network error: {exc}")
    except Exception as exc:  # pragma: no cover — defensive
        return FetchOutcome(ok=False, error=f"Unexpected fetch failure: {exc}")

    title, body = _extract_readable(raw, base_url=final_url)
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
    names. Every resolved address must be public because the HTTP client later
    connects by hostname and may select any answer. DNS failures and malformed
    answer rows are treated as disallowed so validation fails closed.
    """

    candidate = host.strip("[]")
    try:
        return _is_disallowed_ip(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    lower = candidate.lower()
    if lower in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return True
    if lower.endswith(".local"):
        return True
    try:
        infos = socket.getaddrinfo(candidate, None)
    except OSError:
        return True
    if not infos:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (IndexError, TypeError, ValueError):
            return True
        if _is_disallowed_ip(ip):
            return True
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


def _extract_readable(html_or_text: str, base_url: str = "") -> tuple[str, str]:
    """Return ``(title, body_text)`` extracted from an HTML string.

    For non-HTML payloads (plain text, JSON dumps) just normalises
    whitespace and returns the input as-is — the model still gets
    something usable.
    """
    title = ""
    if "<" in html_or_text and ">" in html_or_text:
        # Immersive Reading needs article structure rather than a page-wide
        # text dump. Reuse the product's mature documentation/article extractor
        # when lxml is available; the regex path below remains a lean-install
        # fallback for malformed pages or environments without that dependency.
        try:
            from deeptutor.services.web_source.html_extractor import (
                extract_article_markdown,
            )

            return extract_article_markdown(html_or_text, base_url=base_url)
        except Exception:
            logger.debug("structured HTML extraction failed; using text fallback", exc_info=True)
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
