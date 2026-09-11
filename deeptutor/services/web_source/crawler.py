"""Async documentation-site crawler.

Fetches pages from a base URL, extracts readable text + internal links,
and follows links BFS up to a configurable depth / page count.  Designed
for documentation sites (Docusaurus, MkDocs, GitBook, readthedocs, …)
where the content is in the server-rendered HTML.

Security: reuses the SSRF host-validation logic from ``web_fetch.py`` so
a malicious base URL can't be used to scan an internal network.

Output is a list of :class:`CrawledPage` objects — one per discovered
page with ``url``, ``title``, ``markdown``, and ``content_hash``.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, unquote, urldefrag, urljoin, urlparse

import httpx

from deeptutor.services.web_source.markdown import strip_leading_snapshot_provenance

# Reuse the SSRF guard and HTML extraction from web_fetch
from deeptutor.tools.web_fetch import (
    DEFAULT_MAX_CHARS,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    MAX_RESPONSE_BYTES,
    _bounded_read,
    _extract_readable,
    _is_disallowed_host,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_PAGES = 200
MAX_CRAWL_DEPTH = 5
MAX_CRAWL_PAGES = DEFAULT_MAX_PAGES
DEFAULT_CONCURRENCY = 8
MAX_REDIRECTS = 5


@dataclass(frozen=True)
class CrawledPage:
    """One crawled documentation page."""

    url: str
    title: str
    markdown: str
    content_hash: str
    headings: list[dict] = field(default_factory=list)


@dataclass
class CrawlResult:
    """Outcome of a single :func:`crawl_docs_site` invocation."""

    pages: list[CrawledPage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Site-wide navigation extracted from sidebar elements.
    navigation_links: list[dict] = field(default_factory=list)
    # How navigation was obtained: "original", "inferred", or "" (none).
    navigation_kind: str = ""

    @property
    def ok(self) -> bool:
        return len(self.pages) > 0


# ── link extraction ──────────────────────────────────────────────────

_HREF_RE = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _extract_links(html: str) -> list[str]:
    """Extract all href values from ``<a>`` tags in *html*."""
    return _HREF_RE.findall(html)


def _normalise_link(base: str, href: str) -> str | None:
    """Resolve *href* against *base*, return absolute URL or ``None``.

    Returns ``None`` for non-http schemes, ``javascript:``, ``mailto:``,
    and other non-page links.
    """
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    lower = href.lower()
    if lower.startswith(("javascript:", "mailto:", "tel:", "data:", "blob:")):
        return None
    # Defragment
    href, _frag = urldefrag(href)
    if not href:
        return None
    absolute = urljoin(base, href)
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    return absolute


def _is_internal(url: str, base_host: str, base_path_prefix: str) -> bool:
    """Return True if *url* belongs to the same site under the prefix."""
    parsed = urlparse(url)
    if parsed.hostname != base_host:
        return False
    path = parsed.path.rstrip("/") or "/"
    prefix = base_path_prefix.rstrip("/") or "/"
    # Root prefix: every path on the host is internal.
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


def _to_filename(url: str, base_path_prefix: str) -> str:
    """Derive a stable ``.md`` filename from a page URL.

    Uses the full URL path (preserving directory structure) so pages from
    different sources sharing the same ``raw/`` directory never collide:

    ``/docs/getting-started/`` → ``docs/getting-started.md``
    ``/zh-cn/docs/intro``      → ``zh-cn/docs/intro.md``
    ``/``                      → ``index.md``

    ``base_path_prefix`` is accepted for signature compatibility but no
    longer stripped — the full path is what makes filenames unique.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        filename = "index"
    else:
        # Decode one URL component at a time, then quote it back into one
        # filesystem-safe component. Encoded slashes and dot segments must
        # never turn into traversal below the KB's ``raw/`` directory.
        segments: list[str] = []
        for raw_segment in path.split("/"):
            if not raw_segment:
                continue
            decoded = unquote(raw_segment)
            safe = quote(decoded, safe="-_.~")
            if decoded in {".", ".."} or safe in {".", ".."}:
                safe = f"segment-{hashlib.sha256(raw_segment.encode()).hexdigest()[:10]}"
            segments.append(safe or "segment")
        filename = "/".join(segments) or "index"

    # Query-backed documentation routes may share a path while rendering
    # different pages. Keep them distinct without exposing raw query data.
    if parsed.query:
        filename += f"-q-{hashlib.sha256(parsed.query.encode()).hexdigest()[:10]}"
    return filename + ".md"


def _source_filename(source: dict, page_url: str, base_path_prefix: str) -> str:
    """Namespace a page so independent web sources cannot overwrite it."""
    identity = str(source.get("url") or source.get("id") or "")
    namespace = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"_web/{namespace}/{_to_filename(page_url, base_path_prefix)}"


def _contained_path(root: Path, relative: str) -> Path | None:
    """Resolve *relative* below *root*, rejecting legacy traversal metadata."""
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


# Status codes worth retrying (transient server/infrastructure issues).
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2


async def _fetch_page(
    url: str,
    *,
    client: httpx.AsyncClient,
) -> tuple[str, str] | None:
    """Fetch *url*, return ``(html, final_url)`` or ``None`` on failure.

    Retries up to ``_MAX_RETRIES`` times on transient status codes (429,
    5xx) and network errors, with exponential backoff.
    """
    current_url = url
    redirects = 0
    attempt = 0
    while True:
        parsed = urlparse(current_url)
        host = (parsed.hostname or "").strip()
        if parsed.scheme.lower() not in ("http", "https") or not host:
            logger.warning("Crawl: redirect to invalid URL %s blocked", current_url)
            return None
        # Validate every redirect hop before sending its request. Automatic
        # redirects followed by a final-host check have already contacted a
        # private target by the time they can be rejected.
        if _is_disallowed_host(host):
            logger.warning("Crawl: request to disallowed host %s blocked", host)
            return None
        try:
            async with client.stream(
                "GET",
                current_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
                },
                follow_redirects=False,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "").strip()
                    if not location or redirects >= MAX_REDIRECTS:
                        logger.warning("Crawl: invalid or excessive redirects for %s", url)
                        return None
                    current_url = urljoin(current_url, location)
                    redirects += 1
                    attempt = 0
                    continue

                final_url = str(response.url)
                final_host = (urlparse(final_url).hostname or "").strip()
                if not final_host or _is_disallowed_host(final_host):
                    logger.warning("Crawl: response from disallowed host %s blocked", final_host)
                    return None

                if response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                    backoff = 0.5 * (2**attempt)
                    logger.debug(
                        "Crawl: HTTP %d for %s, retrying in %.1fs",
                        response.status_code,
                        current_url,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue

                if response.status_code >= 400:
                    logger.debug("Crawl: HTTP %d for %s", response.status_code, current_url)
                    return None

                html = await _bounded_read(response, MAX_RESPONSE_BYTES)
                return html, final_url

        except httpx.HTTPError as exc:
            if attempt < _MAX_RETRIES:
                backoff = 0.5 * (2**attempt)
                logger.debug(
                    "Crawl: network error for %s: %s, retrying in %.1fs",
                    current_url,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                attempt += 1
                continue
            logger.debug("Crawl: network error for %s: %s (giving up)", current_url, exc)
            return None


async def _process_page(
    url: str,
    depth: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    base_host: str,
    base_path_prefix: str,
    max_depth: int,
) -> dict | None:
    """Fetch and process a single page for concurrent crawling.

    Returns a dict with ``page``, ``links``, ``nav``, ``depth``, ``final_url``
    or ``None`` on fetch failure.
    """
    async with sem:
        fetched = await _fetch_page(url, client=client)
    if fetched is None:
        return None
    html, final_url = fetched

    from deeptutor.services.web_source.html_extractor import (
        extract_article_markdown,
        extract_headings,
        extract_navigation,
    )

    try:
        title, body = extract_article_markdown(html, base_url=final_url or url)
    except Exception:
        title, body = _extract_readable(html)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    # Extract sidebar navigation from shallow pages (cheap, most complete there).
    nav = extract_navigation(html, final_url) if depth <= 1 else []

    page_headings = extract_headings(body)

    if len(body) > DEFAULT_MAX_CHARS:
        body = body[:DEFAULT_MAX_CHARS].rstrip() + "\n…[truncated]"

    page = CrawledPage(
        url=final_url,
        title=title,
        markdown=body,
        content_hash=content_hash,
        headings=page_headings,
    )

    links: list[str] = []
    if depth < max_depth:
        for href in _extract_links(html):
            link = _normalise_link(url, href)
            if link and _is_internal(link, base_host, base_path_prefix):
                links.append(link)

    return {"page": page, "links": links, "nav": nav, "depth": depth, "final_url": final_url}


async def crawl_docs_site(
    base_url: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client_factory: Any = None,
) -> CrawlResult:
    """Crawl a documentation site starting from *base_url*.

    BFS traversal: fetch *base_url*, extract internal links under the same
    path prefix, follow them up to *max_depth* levels deep and *max_pages*
    total pages.

    Returns a :class:`CrawlResult` with all successfully fetched pages.
    """
    result = CrawlResult()

    # Validate base URL
    try:
        max_depth = int(max_depth)
        max_pages = int(max_pages)
    except (TypeError, ValueError):
        result.errors.append("Crawl depth and page count must be integers")
        return result
    if not 0 <= max_depth <= MAX_CRAWL_DEPTH:
        result.errors.append(f"Crawl depth must be between 0 and {MAX_CRAWL_DEPTH}")
        return result
    if not 1 <= max_pages <= MAX_CRAWL_PAGES:
        result.errors.append(f"Crawl page count must be between 1 and {MAX_CRAWL_PAGES}")
        return result
    parsed = urlparse(base_url)
    if parsed.scheme.lower() not in ("http", "https"):
        result.errors.append(f"Invalid scheme: {parsed.scheme}")
        return result
    base_host = parsed.hostname or ""
    if not base_host:
        result.errors.append("Missing host in base URL")
        return result
    if _is_disallowed_host(base_host):
        result.errors.append(f"Disallowed host: {base_host}")
        return result

    base_path_prefix = parsed.path or "/"

    factory = client_factory or (
        lambda: httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            max_redirects=5,
        )
    )

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(base_url, 0)])
    concurrency = min(DEFAULT_CONCURRENCY, max_pages)
    sem = asyncio.Semaphore(concurrency)

    async with factory() as client:
        while queue and len(visited) < max_pages:
            # Dequeue a batch of URLs to process concurrently.
            batch: list[tuple[str, int]] = []
            while queue and len(batch) < concurrency and len(visited) < max_pages:
                url, depth = queue.popleft()
                if url not in visited:
                    visited.add(url)
                    batch.append((url, depth))

            if not batch:
                continue

            # Fetch and process all pages in the batch concurrently.
            tasks = [
                _process_page(
                    url,
                    depth,
                    client,
                    sem,
                    base_host=base_host,
                    base_path_prefix=base_path_prefix,
                    max_depth=max_depth,
                )
                for url, depth in batch
            ]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)

            for outcome in outcomes:
                if isinstance(outcome, BaseException) or outcome is None:
                    continue

                # Track redirect target in visited set.
                final_url = outcome["final_url"]
                if final_url:
                    visited.add(final_url)

                result.pages.append(outcome["page"])

                # Update navigation (keep the result with the most links).
                nav = outcome.get("nav", [])
                if nav and len(nav) > len(result.navigation_links):
                    result.navigation_links = nav
                    result.navigation_kind = "original"

                # Enqueue discovered links.
                for link in outcome["links"]:
                    if link not in visited:
                        queue.append((link, outcome["depth"] + 1))

    # If no sidebar navigation was found, infer a simple hierarchy from
    # the URL paths of all crawled pages.
    if not result.navigation_links and result.pages:
        result.navigation_links = _infer_navigation(result.pages, base_url)
        result.navigation_kind = "inferred" if result.navigation_links else ""

    logger.info(
        "Crawled %s: %d pages (%d errors), nav=%s (%d links)",
        base_url,
        len(result.pages),
        len(result.errors),
        result.navigation_kind,
        len(result.navigation_links),
    )
    return result


def _infer_navigation(pages: list[CrawledPage], base_url: str) -> list[dict]:
    """Build a flat navigation list from crawled page URLs.

    Pages are sorted by URL path, and depth is inferred from the number
    of path segments.  This produces a usable (if not perfect) tree when
    the site has no detectable sidebar.
    """
    from urllib.parse import urlparse

    result: list[dict] = []
    seen: set[str] = set()

    for page in sorted(pages, key=lambda p: p.url):
        parsed = urlparse(page.url)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"
        if path in seen:
            continue
        seen.add(path)

        segments = [s for s in path.split("/") if s]
        # Depth: index page = 0, /docs/ = 1, /docs/intro = 2, etc.
        depth = len(segments)

        title = page.title or segments[-1] if segments else "Home"
        result.append(
            {
                "title": title,
                "url": page.url,
                "path": parsed.path,
                "depth": depth if depth > 0 else 0,
            }
        )

    return result


# ── shared crawl-diff-write pipeline ─────────────────────────────────


@dataclass
class CrawlDiff:
    """Result of crawling a source, diffing against stored hashes, and writing.

    :func:`sync_source` uses this to keep crawl, hash, diff, write, removal,
    and navigation behavior in one bounded implementation.
    """

    ok: bool = True
    error: str = ""
    url: str = ""
    page_hashes: dict[str, str] = field(default_factory=dict)
    page_files: list[str] = field(default_factory=list)
    page_urls: dict[str, str] = field(default_factory=dict)
    pages_added: list[str] = field(default_factory=list)
    pages_updated: list[str] = field(default_factory=list)
    pages_unchanged: list[str] = field(default_factory=list)
    pages_removed: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    navigation: dict = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.page_hashes)

    @property
    def changed_names(self) -> list[str]:
        return self.pages_added + self.pages_updated


async def crawl_and_diff(
    source: dict,
    raw_dir: Path,
    *,
    max_depth: int | None = None,
    max_pages: int | None = None,
) -> CrawlDiff:
    """Crawl one source, diff against stored hashes, write changed pages.

    This shared pipeline is used by ``sync_source``.  It handles:

    1. Crawl the site.
    2. Build ``{filename: content_hash}`` for every page.
    3. Compare with ``source["page_hashes"]`` to compute added/updated/removed.
    4. Write new/changed pages to ``raw_dir``.
    5. Report deleted pages for the caller to remove from raw storage and index.
    6. Build a navigation manifest.

    The caller is responsible for indexing and metadata persistence.
    """
    from deeptutor.services.web_source.navigation import build_navigation_manifest

    url = source["url"]
    depth = max_depth if max_depth is not None else source.get("max_depth", DEFAULT_MAX_DEPTH)
    pages = max_pages if max_pages is not None else source.get("max_pages", DEFAULT_MAX_PAGES)
    old_hashes: dict[str, str] = source.get("page_hashes", {})
    base_path_prefix = urlparse(url).path or "/"

    # 1. Crawl
    try:
        result = await crawl_docs_site(url, max_depth=depth, max_pages=pages)
    except Exception as exc:
        logger.exception("Crawl failed for %s", url)
        return CrawlDiff(ok=False, error=str(exc), url=url)

    if not result.ok:
        msg = f"Crawl returned no pages from {url}"
        if result.errors:
            msg += ": " + "; ".join(result.errors)
        return CrawlDiff(ok=False, error=msg, url=url)

    # 2. Build current page set
    current: dict[str, str] = {}
    page_contents: dict[str, str] = {}
    page_urls: dict[str, str] = {}
    page_files: list[str] = []

    for page in result.pages:
        fname = _source_filename(source, page.url, base_path_prefix)
        current[fname] = page.content_hash
        page_contents[fname] = page.markdown
        page_urls[fname] = page.url
        page_files.append(fname)

    # 3. Compute changes
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    removed: list[str] = []

    for fname, chash in current.items():
        old = old_hashes.get(fname)
        if old is None:
            added.append(fname)
        elif old != chash:
            updated.append(fname)
        else:
            target = _contained_path(raw_dir, fname)
            if target is not None and target.is_file():
                unchanged.append(fname)
            else:
                # Metadata can outlive a manually removed/corrupt raw file.
                # Re-stage it even though the remote content hash is stable.
                updated.append(fname)

    for fname in old_hashes:
        if fname not in current:
            removed.append(fname)

    # 4. Write new/changed pages
    changed_paths: list[str] = []
    for fname in added + updated:
        content = page_contents.get(fname, "")
        full_content = strip_leading_snapshot_provenance(content)
        dest = _contained_path(raw_dir, fname)
        if dest is None:
            return CrawlDiff(ok=False, error=f"Unsafe page filename: {fname}", url=url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(full_content, encoding="utf-8")
        changed_paths.append(str(dest))

    # 5. Build navigation manifest. Deletions are deliberately left to the
    # caller, which must purge both the raw file and the retrieval index.
    nav_manifest = build_navigation_manifest(
        result.navigation_links,
        result.navigation_kind,
        page_urls,
    )

    return CrawlDiff(
        ok=True,
        url=url,
        page_hashes=current,
        page_files=page_files,
        page_urls=page_urls,
        pages_added=added,
        pages_updated=updated,
        pages_unchanged=unchanged,
        pages_removed=removed,
        changed_paths=changed_paths,
        navigation=nav_manifest,
    )
