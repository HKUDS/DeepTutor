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
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import re
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from lxml import etree

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
DEFAULT_CONCURRENCY = 8

# Operators can explicitly name hosts that resolve to loopback/private
# addresses (for example, a local documentation server). This is a narrow
# exception to the SSRF guard: no wildcards, ports, URL paths, or blanket
# private-network bypass.
ALLOWED_HOSTS_ENV = "DEEPTUTOR_WEB_CRAWL_ALLOWED_HOSTS"


def _configured_allowed_hosts() -> frozenset[str]:
    """Return normalized hosts explicitly opted in by the deployment."""
    value = os.environ.get(ALLOWED_HOSTS_ENV, "")
    return frozenset(
        host.strip("[]").lower()
        for host in value.replace(";", ",").replace(" ", ",").split(",")
        if host.strip("[]")
    )


def _is_crawler_disallowed_host(host: str) -> bool:
    """Apply the crawler-specific explicit host allowlist, then SSRF checks."""
    candidate = host.strip().strip("[]").lower()
    if candidate in _configured_allowed_hosts():
        return False
    return _is_disallowed_host(candidate)


@dataclass(frozen=True)
class CrawledPage:
    """One crawled documentation page."""

    url: str
    title: str
    markdown: str
    content_hash: str
    headings: list[dict] = field(default_factory=list)
    requested_url: str = ""
    canonical_url: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    http_status: int = 200
    status: str = "active"
    redirect_url: str = ""
    document_version: str = ""


@dataclass(frozen=True)
class FetchOutcome:
    html: str
    final_url: str
    status_code: int


@dataclass
class CrawlResult:
    """Outcome of a single :func:`crawl_docs_site` invocation."""

    pages: list[CrawledPage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Site-wide navigation extracted from sidebar elements.
    navigation_links: list[dict] = field(default_factory=list)
    # How navigation was obtained: "original", "inferred", or "" (none).
    navigation_kind: str = ""
    discovery_sources: list[str] = field(default_factory=list)
    deleted_urls: list[str] = field(default_factory=list)
    truncated: bool = False
    fetch_failure_count: int = 0

    @property
    def complete_coverage(self) -> bool:
        return not self.errors and self.fetch_failure_count == 0 and not self.truncated

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
        return "index.md"
    # Preserve full path structure to avoid cross-source filename collisions
    segments = [s for s in path.split("/") if s]
    return "/".join(segments) + ".md"


# Status codes worth retrying (transient server/infrastructure issues).
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2


async def _fetch_page(
    url: str,
    *,
    client: httpx.AsyncClient,
) -> FetchOutcome | None:
    """Fetch *url*, including its final redirect URL and HTTP status.

    Retries up to ``_MAX_RETRIES`` times on transient status codes (429,
    5xx) and network errors, with exponential backoff.
    """
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
                },
                follow_redirects=True,
            ) as response:
                final_url = str(response.url)
                final_host = (urlparse(final_url).hostname or "").strip()
                if final_host and _is_crawler_disallowed_host(final_host):
                    logger.warning("Crawl: redirect to disallowed host %s blocked", final_host)
                    return None

                if response.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                    backoff = 0.5 * (2**attempt)
                    logger.debug(
                        "Crawl: HTTP %d for %s, retrying in %.1fs",
                        response.status_code,
                        url,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if response.status_code >= 400:
                    logger.debug("Crawl: HTTP %d for %s", response.status_code, url)
                    return FetchOutcome(
                        html="", final_url=final_url, status_code=response.status_code
                    )

                html = await _bounded_read(response, MAX_RESPONSE_BYTES)
                return FetchOutcome(
                    html=html, final_url=final_url, status_code=response.status_code
                )

        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                backoff = 0.5 * (2**attempt)
                logger.debug(
                    "Crawl: network error for %s: %s, retrying in %.1fs", url, exc, backoff
                )
                await asyncio.sleep(backoff)
                continue
            logger.debug("Crawl: network error for %s: %s (giving up)", url, exc)
            return None

    return None


def _extract_html_metadata(html: str, final_url: str) -> tuple[str, str]:
    """Return ``(canonical_url, document_version)`` from HTML metadata."""
    canonical = ""
    version = ""
    try:
        tree = etree.fromstring(html.encode("utf-8"), parser=etree.HTMLParser())
        canonical_nodes = tree.xpath("//link[@rel='canonical']/@href")
        if canonical_nodes:
            canonical = urljoin(final_url, str(canonical_nodes[0]).strip())
        version_names = {
            "docsearch:version",
            "docs:version",
            "documentation:version",
            "product:version",
            "version",
        }
        for name in tree.xpath("//meta/@name | //meta/@property"):
            normalized = str(name).lower()
            if normalized not in version_names:
                continue
            values = tree.xpath(
                f"//meta[@name='{name}']/@content | //meta[@property='{name}']/@content"
            )
            if values:
                version = str(values[0]).strip()
                break
    except Exception:
        pass
    return canonical, version


async def _process_page(
    url: str,
    depth: int,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    base_host: str,
    base_path_prefix: str,
    max_depth: int,
) -> dict:
    """Fetch and process a single page for concurrent crawling.

    Returns a dict with ``page``, ``links``, ``nav``, ``depth``, ``final_url``
    or ``None`` on fetch failure.
    """
    async with sem:
        fetched = await _fetch_page(url, client=client)
    if fetched is None:
        return {"requested_url": url, "error": "fetch failed", "status_code": 0}
    if fetched.status_code >= 400:
        return {
            "requested_url": url,
            "error": f"HTTP {fetched.status_code}",
            "status_code": fetched.status_code,
        }
    html, final_url = fetched.html, fetched.final_url

    from deeptutor.services.web_source.html_extractor import (
        extract_article_markdown,
        extract_headings,
        extract_navigation,
    )

    try:
        title, body = extract_article_markdown(html)
    except Exception:
        title, body = _extract_readable(html)
    canonical_url, document_version = _extract_html_metadata(html, final_url)
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
        requested_url=url,
        canonical_url=canonical_url or final_url,
        http_status=fetched.status_code,
        status="redirect" if url != final_url else "active",
        redirect_url=final_url if url != final_url else "",
        document_version=document_version,
    )

    links: list[str] = []
    if depth < max_depth:
        for href in _extract_links(html):
            link = _normalise_link(url, href)
            if link and _is_internal(link, base_host, base_path_prefix):
                links.append(link)

    return {"page": page, "links": links, "nav": nav, "depth": depth, "final_url": final_url}


async def _sitemap_urls(
    base_url: str,
    *,
    client: httpx.AsyncClient,
    base_host: str,
    base_path_prefix: str,
) -> list[str]:
    """Discover internal page URLs from ``sitemap.xml`` and sitemap indexes."""
    parsed = urlparse(base_url)
    candidates = [urljoin(base_url, "/sitemap.xml"), urljoin(base_url, "/sitemap_index.xml")]
    page_urls: list[str] = []
    seen_sitemaps: set[str] = set()

    for candidate in candidates:
        if candidate in seen_sitemaps:
            continue
        seen_sitemaps.add(candidate)
        fetched = await _fetch_page(candidate, client=client)
        if fetched is None or fetched.status_code >= 400 or not fetched.html:
            continue
        try:
            root = etree.fromstring(fetched.html.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        locs = [str(value).strip() for value in root.xpath("//*[local-name()='loc']/text()")]
        for loc in locs:
            loc, _fragment = urldefrag(loc)
            if loc.endswith(".xml") or loc.endswith(".gz"):
                if loc not in seen_sitemaps:
                    candidates.append(loc)
                continue
            if loc.startswith(("http://", "https://")) and _is_internal(
                loc, base_host, base_path_prefix
            ):
                page_urls.append(loc)

    # Preserve the configured entry first, then stable sitemap order.
    return [base_url] + [url for url in dict.fromkeys(page_urls) if url != base_url]


async def crawl_docs_site(
    base_url: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client_factory: any = None,
    seed_urls: list[str] | None = None,
) -> CrawlResult:
    """Crawl a documentation site starting from *base_url*.

    BFS traversal: fetch *base_url*, extract internal links under the same
    path prefix, follow them up to *max_depth* levels deep and *max_pages*
    total pages.

    Returns a :class:`CrawlResult` with all successfully fetched pages.
    """
    result = CrawlResult()

    # Validate base URL
    parsed = urlparse(base_url)
    if parsed.scheme.lower() not in ("http", "https"):
        result.errors.append(f"Invalid scheme: {parsed.scheme}")
        return result
    base_host = parsed.hostname or ""
    if not base_host:
        result.errors.append("Missing host in base URL")
        return result
    if _is_crawler_disallowed_host(base_host):
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
    queue: deque[tuple[str, int]] = deque()
    concurrency = min(DEFAULT_CONCURRENCY, max_pages)
    sem = asyncio.Semaphore(concurrency)

    async with factory() as client:
        discovered_urls = await _sitemap_urls(
            base_url,
            client=client,
            base_host=base_host,
            base_path_prefix=base_path_prefix,
        )
        if len(discovered_urls) > 1:
            result.discovery_sources.append("sitemap")
            for url in discovered_urls:
                queue.append((url, 0))
        else:
            queue.append((base_url, 0))

        for seed in seed_urls or []:
            parsed_seed = urlparse(seed)
            if (
                parsed_seed.scheme.lower() in {"http", "https"}
                and parsed_seed.hostname == base_host
                and seed not in visited
                and all(seed != item for item, _depth in queue)
            ):
                queue.append((seed, 0))

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
                if isinstance(outcome, Exception):
                    result.fetch_failure_count += 1
                    continue
                if outcome.get("error"):
                    status_code = int(outcome.get("status_code") or 0)
                    if status_code in {404, 410}:
                        result.deleted_urls.append(str(outcome.get("requested_url") or ""))
                    else:
                        result.fetch_failure_count += 1
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

        result.truncated = bool(queue)

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


def _section_paths(navigation_links: list[dict]) -> dict[str, list[str]]:
    """Map page URLs to their navigation breadcrumb titles."""
    paths: dict[str, list[str]] = {}
    stack: list[tuple[int, str]] = []
    for link in navigation_links:
        depth = int(link.get("depth") or 0)
        title = str(link.get("title") or "").strip()
        while stack and stack[-1][0] >= depth:
            stack.pop()
        current = [value for _depth, value in stack]
        if title:
            current.append(title)
            stack.append((depth, title))
        url = str(link.get("url") or "")
        if url:
            paths[url] = current
    return paths


def _build_page_manifest(
    pages: list[CrawledPage],
    navigation_links: list[dict],
    *,
    source_version: str,
) -> dict[str, dict]:
    section_paths = _section_paths(navigation_links)
    manifest: dict[str, dict] = {}
    for page in pages:
        file_path = _to_filename(page.url, urlparse(page.url).path or "/")
        manifest[file_path] = {
            "file_path": file_path,
            "canonical_url": page.canonical_url or page.url,
            "requested_url": page.requested_url or page.url,
            "url": page.url,
            "title": page.title,
            "section_path": section_paths.get(page.url, []),
            "content_hash": page.content_hash,
            "fetched_at": page.fetched_at,
            "document_version": page.document_version or source_version,
            "status": page.status,
            "http_status": page.http_status,
            "redirect_url": page.redirect_url,
        }
    return manifest


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

    Both :func:`sync_source` (legacy per-file path) and the orchestrator's
    ``_crawl_and_write`` use this to avoid duplicating ~80 lines of
    crawl-hash-diff-write-remove-navigation logic.
    """

    ok: bool = True
    error: str = ""
    url: str = ""
    page_hashes: dict[str, str] = field(default_factory=dict)
    page_manifest: dict[str, dict] = field(default_factory=dict)
    page_files: list[str] = field(default_factory=list)
    page_urls: dict[str, str] = field(default_factory=dict)
    pages_added: list[str] = field(default_factory=list)
    pages_updated: list[str] = field(default_factory=list)
    pages_unchanged: list[str] = field(default_factory=list)
    pages_removed: list[str] = field(default_factory=list)
    pages_unresolved: list[str] = field(default_factory=list)
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

    This is the shared pipeline used by both the legacy ``sync_source``
    and the bilingual orchestrator.  It handles:

    1. Crawl the site.
    2. Build ``{filename: content_hash}`` for every page.
    3. Compare with ``source["page_hashes"]`` to compute added/updated/removed.
    4. Write new/changed pages to ``raw_dir``.
    5. Remove deleted pages from ``raw_dir``.
    6. Build a navigation manifest.

    The caller is responsible for indexing and metadata persistence.
    """
    from deeptutor.services.web_source.navigation import build_navigation_manifest

    url = source["url"]
    depth = max_depth if max_depth is not None else source.get("max_depth", DEFAULT_MAX_DEPTH)
    pages = max_pages if max_pages is not None else source.get("max_pages", DEFAULT_MAX_PAGES)
    old_hashes: dict[str, str] = source.get("page_hashes", {})
    old_manifest: dict[str, dict] = source.get("page_manifest", {})
    base_path_prefix = urlparse(url).path or "/"

    # 1. Crawl
    try:
        prior_urls = []
        for entry in old_manifest.values():
            for key in ("requested_url", "canonical_url", "url"):
                value = str(entry.get(key) or "")
                if value and value not in prior_urls:
                    prior_urls.append(value)
        result = await crawl_docs_site(
            url,
            max_depth=depth,
            max_pages=pages,
            seed_urls=prior_urls,
        )
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
        fname = _to_filename(page.url, base_path_prefix)
        current[fname] = page.content_hash
        page_contents[fname] = page.markdown
        page_urls[fname] = page.url
        page_files.append(fname)

    page_manifest = _build_page_manifest(
        result.pages,
        result.navigation_links,
        source_version=str(source.get("document_version") or ""),
    )

    # 3. Compute changes
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    removed: list[str] = []
    unresolved: list[str] = []
    explicit_deleted = set(result.deleted_urls)

    for fname, chash in current.items():
        old = old_hashes.get(fname)
        if old is None:
            added.append(fname)
        elif old != chash:
            updated.append(fname)
        else:
            unchanged.append(fname)

    for fname in old_hashes:
        if fname not in current:
            previous = old_manifest.get(fname, {})
            known_urls = {
                str(previous.get(key) or "") for key in ("requested_url", "canonical_url", "url")
            }
            explicitly_deleted = any(url in explicit_deleted for url in known_urls if url)
            if result.complete_coverage or explicitly_deleted:
                removed.append(fname)
                page_manifest[fname] = {
                    **previous,
                    "file_path": fname,
                    "content_hash": previous.get("content_hash") or old_hashes.get(fname, ""),
                    "status": "deleted",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                unresolved.append(fname)
                page_manifest[fname] = {**previous, "file_path": fname, "status": "unknown"}

    # 4. Write new/changed pages
    changed_paths: list[str] = []
    for fname in added + updated:
        content = page_contents.get(fname, "")
        page_url = page_urls.get(fname, "")
        full_content = f"<!-- source: {page_url} -->\n\n{content}"
        dest = raw_dir / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(full_content, encoding="utf-8")
        changed_paths.append(str(dest))

    # 5. Remove deleted pages
    for fname in removed:
        target = raw_dir / fname
        if target.exists():
            target.unlink()

    # 6. Build navigation manifest
    nav_manifest = build_navigation_manifest(
        result.navigation_links,
        result.navigation_kind,
        page_urls,
    )

    return CrawlDiff(
        ok=True,
        url=url,
        page_hashes=current,
        page_manifest=page_manifest,
        page_files=page_files,
        page_urls=page_urls,
        pages_added=added,
        pages_updated=updated,
        pages_unchanged=unchanged,
        pages_removed=removed,
        pages_unresolved=unresolved,
        changed_paths=changed_paths,
        navigation=nav_manifest,
    )
