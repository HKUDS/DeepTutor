from __future__ import annotations

import httpx
import pytest

from deeptutor.services.web_source import crawler


def _xml(body: str) -> crawler.FetchOutcome:
    return crawler.FetchOutcome(
        html=body, final_url="https://example.test/sitemap", status_code=200
    )


async def _permit_all(*_args: object, **_kwargs: object) -> tuple[crawler.RobotsPolicy, None]:
    return crawler.RobotsPolicy(available=True), None


@pytest.mark.asyncio
async def test_crawl_records_builtin_extraction_quality(monkeypatch) -> None:
    body = "<p>" + ("DeepTutor makes documentation easy to study. " * 20) + "</p>"
    body += "<ul><li>Install</li><li>Read</li></ul><table><tr><th>Feature</th></tr></table>"
    html = f"<html><head><title>Guide</title></head><body><article><h1>Guide</h1>{body}</article></body></html>"
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /", request=request)
        return httpx.Response(200, text=html, request=request)

    class ClientContext:
        async def __aenter__(self):
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return self.client

        async def __aexit__(self, *_args):
            await self.client.aclose()

    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)
    result = await crawler.crawl_docs_site(
        "https://example.test/docs/guide",
        max_depth=0,
        max_pages=1,
        client_factory=ClientContext,
    )

    assert requested == ["https://example.test/robots.txt", "https://example.test/docs/guide"]
    assert len(result.pages) == 1
    assert result.pages[0].extraction_method == "builtin_lxml"
    assert result.pages[0].extraction_quality == 100
    assert result.pages[0].extraction_warnings == ()


@pytest.mark.asyncio
async def test_robots_disallow_blocks_configured_url_before_page_fetch(monkeypatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /docs/", request=request)
        raise AssertionError("the disallowed page must never be requested")

    class ClientContext:
        async def __aenter__(self):
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return self.client

        async def __aexit__(self, *_args):
            await self.client.aclose()

    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)
    result = await crawler.crawl_docs_site(
        "https://example.test/docs/guide",
        max_depth=0,
        max_pages=1,
        client_factory=ClientContext,
    )

    assert requested == ["https://example.test/robots.txt"]
    assert result.pages == []
    assert result.errors == ["robots.txt disallows the configured URL"]


@pytest.mark.asyncio
async def test_unavailable_robots_blocks_crawl_conservatively(monkeypatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(503, request=request)

    class ClientContext:
        async def __aenter__(self):
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return self.client

        async def __aexit__(self, *_args):
            await self.client.aclose()

    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)
    monkeypatch.setattr(crawler, "_MAX_RETRIES", 0)
    result = await crawler.crawl_docs_site(
        "https://example.test/docs/guide",
        max_depth=0,
        max_pages=1,
        client_factory=ClientContext,
    )

    assert requested == ["https://example.test/robots.txt"]
    assert result.pages == []
    assert result.errors == ["robots.txt unavailable; crawl blocked"]


@pytest.mark.asyncio
async def test_allowed_host_redirect_boundary_blocks_cross_host(monkeypatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://other.example/docs"},
            request=request,
        )

    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await crawler._fetch_page(
            "https://example.test/docs",
            client=client,
            allowed_host="example.test",
        )

    assert outcome is None
    assert requested == ["https://example.test/docs"]


@pytest.mark.asyncio
async def test_sitemap_discovery_follows_index_and_filters_prefix(monkeypatch) -> None:
    payloads = {
        "https://example.com/sitemap.xml": _xml(
            "<urlset><url><loc>https://example.com/docs/getting-started</loc></url>"
            "<url><loc>https://example.com/blog/post</loc></url></urlset>"
        ),
        "https://example.com/sitemap_index.xml": _xml(
            "<sitemapindex><sitemap><loc>https://example.com/docs/child.xml</loc></sitemap></sitemapindex>"
        ),
        "https://example.com/docs/child.xml": _xml(
            "<urlset><url><loc>https://example.com/docs/deep/config</loc></url></urlset>"
        ),
    }

    async def fake_fetch(url, **kwargs):
        return payloads.get(url)

    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)

    urls = await crawler._sitemap_urls(
        "https://example.com/docs/",
        client=object(),
        base_host="example.com",
        base_path_prefix="/docs",
        robots_policy=crawler.RobotsPolicy(available=True),
        rate_limiter=crawler._HostRateLimiter(interval_s=0),
    )

    assert urls[0] == "https://example.com/docs/"
    assert set(urls[1:]) == {
        "https://example.com/docs/getting-started",
        "https://example.com/docs/deep/config",
    }


@pytest.mark.asyncio
async def test_malformed_sitemap_falls_back_to_configured_url(monkeypatch) -> None:
    async def fake_fetch(url, **kwargs):
        return _xml("<urlset><url><loc>broken") if url.endswith("/sitemap.xml") else None

    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)

    assert await crawler._sitemap_urls(
        "https://example.test/docs/",
        client=object(),
        base_host="example.test",
        base_path_prefix="/docs",
        robots_policy=crawler.RobotsPolicy(available=True),
        rate_limiter=crawler._HostRateLimiter(interval_s=0),
    ) == ["https://example.test/docs/"]


@pytest.mark.asyncio
async def test_external_seed_url_is_not_crawled(monkeypatch) -> None:
    async def fake_sitemap(*args, **kwargs):
        return ["https://example.com/docs/"]

    processed = []

    async def fake_process(*args, **kwargs):
        processed.append((args, kwargs))
        return {"requested_url": args[0], "error": "must not run", "status_code": 0}

    monkeypatch.setattr(crawler, "_sitemap_urls", fake_sitemap)
    monkeypatch.setattr(crawler, "_process_page", fake_process)
    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda host: False)
    monkeypatch.setattr(
        crawler,
        "_load_robots_policy",
        _permit_all,
    )

    result = await crawler.crawl_docs_site(
        "https://example.com/docs/",
        seed_urls=["https://external.example/secret"],
    )

    assert [call[0][0] for call in processed] == ["https://example.com/docs/"]
    assert result.pages == []


@pytest.mark.asyncio
async def test_single_page_snapshot_skips_sitemap_discovery(monkeypatch) -> None:
    async def fail_sitemap(*_args, **_kwargs):
        raise AssertionError("single-page capture must not probe site-wide sitemaps")

    async def fake_process(url, *_args, **_kwargs):
        return {
            "page": crawler.CrawledPage(
                url=url,
                canonical_url=url,
                title="Article",
                markdown="One page",
                content_hash="one-page",
            ),
            "links": [],
            "nav": [],
            "depth": 0,
            "final_url": url,
        }

    monkeypatch.setattr(crawler, "_sitemap_urls", fail_sitemap)
    monkeypatch.setattr(crawler, "_process_page", fake_process)
    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)
    monkeypatch.setattr(
        crawler,
        "_load_robots_policy",
        _permit_all,
    )

    result = await crawler.crawl_docs_site(
        "https://example.test/article",
        max_depth=0,
        max_pages=1,
    )

    assert [page.url for page in result.pages] == ["https://example.test/article"]


@pytest.mark.asyncio
async def test_sidebar_navigation_follows_sibling_docs_pages(monkeypatch) -> None:
    index_html = """
    <html><head><title>Guide</title></head><body>
      <aside class="theme-doc-sidebar-container"><nav>
        <a href="/docs/index.html">Introduction</a>
        <a href="/docs/install.html">Installation</a>
      </nav></aside>
      <main><article><h1>Guide</h1><p>Welcome.</p></article></main>
    </body></html>
    """
    install_html = """
    <html><head><title>Installation</title></head><body>
      <main><article><h1>Installation</h1><p>Install it.</p></article></main>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/docs/index.html":
            return httpx.Response(200, text=index_html, request=request)
        if request.url.path == "/docs/install.html":
            return httpx.Response(200, text=install_html, request=request)
        return httpx.Response(404, request=request)

    class ClientContext:
        async def __aenter__(self):
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return self.client

        async def __aexit__(self, *_args):
            await self.client.aclose()

    async def base_only(*_args, **_kwargs):
        return ["https://example.test/docs/index.html"]

    monkeypatch.setattr(crawler, "_sitemap_urls", base_only)
    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda _host: False)

    result = await crawler.crawl_docs_site(
        "https://example.test/docs/index.html",
        max_depth=2,
        client_factory=ClientContext,
    )

    assert {page.url for page in result.pages} == {
        "https://example.test/docs/index.html",
        "https://example.test/docs/install.html",
    }
    assert result.navigation_kind == "original"


@pytest.mark.asyncio
async def test_redirect_to_private_host_is_blocked_before_request(monkeypatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/admin"},
                request=request,
            )
        raise AssertionError("the private redirect target must never be requested")

    monkeypatch.setattr(
        crawler,
        "_is_crawler_disallowed_host",
        lambda host: host == "127.0.0.1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await crawler._fetch_page("https://public.example/docs", client=client)

    assert outcome is None
    assert requested == ["https://public.example/docs"]


@pytest.mark.asyncio
async def test_explicit_404_is_a_deletion_signal(monkeypatch) -> None:
    async def fake_sitemap(*args, **kwargs):
        return ["https://example.test/docs/removed"]

    async def fake_process(*args, **kwargs):
        return {
            "requested_url": "https://example.test/docs/removed",
            "error": "HTTP 404",
            "status_code": 404,
        }

    monkeypatch.setattr(crawler, "_sitemap_urls", fake_sitemap)
    monkeypatch.setattr(crawler, "_process_page", fake_process)
    monkeypatch.setattr(crawler, "_is_crawler_disallowed_host", lambda host: False)
    monkeypatch.setattr(crawler, "_load_robots_policy", _permit_all)

    result = await crawler.crawl_docs_site("https://example.test/docs/")

    assert result.deleted_urls == ["https://example.test/docs/removed"]
    assert result.fetch_failure_count == 0
