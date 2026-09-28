from __future__ import annotations

import asyncio

import httpx
import pytest

from deeptutor.services.web_source import crawler, robots


@pytest.fixture
def crawl_clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(robots.time, "monotonic", lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr(robots.asyncio, "sleep", sleep)
    monkeypatch.setattr(robots, "_is_disallowed_host", lambda _: False)
    monkeypatch.setattr(crawler, "_is_disallowed_host", lambda _: False)
    return now


def test_specific_agent_groups_merge_and_support_wildcards_queries_and_escaped_paths():
    policy = robots.parse_robots_txt("""
User-agent: *
Disallow: /
User-agent: DeepTutor
Disallow: /docs/*?private=*
Disallow: /caf%C3%A9
Allow: /docs/open$
Crawl-delay: nan
User-agent: OtherBot
Disallow: /
User-agent: deeptutor
Disallow: /docs/open
Allow: /docs/open
Disallow: /%7Eprivate
Crawl-delay: 2
""")
    assert policy.crawl_delay_s == 2
    assert policy.permits("https://example.com/docs/open")
    assert policy.permits("https://example.com/docs/public")
    assert not policy.permits("https://example.com/docs/x?private=yes")
    assert not policy.permits("https://example.com/café")
    assert not policy.permits("https://example.com/~private")


@pytest.mark.asyncio
async def test_crawl_skips_disallowed_links_and_paces_concurrent_siblings(crawl_clock):
    requested = []

    def handler(request):
        requested.append((request.url.path, crawl_clock[0]))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nDisallow: /docs/private\nCrawl-delay: 2"
            )
        return httpx.Response(
            200,
            text='<html><h1>Guide</h1><a href="/docs/private">private</a><a href="/docs/a">a</a><a href="/docs/b">b</a></html>',
        )

    result = await crawler.crawl_docs_site(
        "https://example.com/docs/",
        max_depth=1,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert len(result.pages) == 3
    assert [path for path, _ in requested] == ["/robots.txt", "/docs/", "/docs/a", "/docs/b"]
    assert all(b[1] - a[1] >= 2 for a, b in zip(requested, requested[1:]))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(404, True), (503, False), (429, False)])
async def test_missing_robots_allows_pages_but_unreachable_policy_blocks(
    crawl_clock, status, expected
):
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return httpx.Response(
            status if request.url.path == "/robots.txt" else 200, text="<h1>Docs</h1>"
        )

    result = await crawler.crawl_docs_site(
        "https://example.com/docs/",
        max_depth=0,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert bool(result.pages) is expected
    assert ("/docs/" in requested) is expected
    if not expected:
        assert result.errors == ["robots.txt unavailable; crawl blocked"]


@pytest.mark.asyncio
async def test_redirect_target_uses_its_own_origin_policy(crawl_clock):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            rule = "Disallow: /private" if request.url.host == "other.example.com" else ""
            return httpx.Response(200, text="User-agent: *\n" + rule)
        return httpx.Response(302, headers={"Location": "https://other.example.com/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (
            await crawler._fetch_page(
                "https://example.com/docs", client=client, access=robots.CrawlAccess(client)
            )
            is None
        )
    assert requested == [
        "https://example.com/robots.txt",
        "https://example.com/docs",
        "https://other.example.com/robots.txt",
    ]


@pytest.mark.asyncio
async def test_robots_redirect_cannot_contact_private_network(crawl_clock, monkeypatch):
    requested = []
    monkeypatch.setattr(robots, "_is_disallowed_host", lambda host: host == "127.0.0.1")

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/robots.txt"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        policy = await robots.CrawlAccess(client).policy_for("https://example.com/docs")
    assert not policy.available
    assert requested == ["https://example.com/robots.txt"]


@pytest.mark.asyncio
async def test_concurrent_requests_fetch_robots_once_and_keep_minimum_pacing(crawl_clock):
    requested = []

    async def handler(request):
        requested.append((request.url.path, crawl_clock[0]))
        return httpx.Response(
            404 if request.url.path == "/robots.txt" else 200, text="<h1>Docs</h1>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        access = robots.CrawlAccess(client)
        await asyncio.gather(
            *(
                crawler._fetch_page(f"https://example.com/docs/{i}", client=client, access=access)
                for i in range(4)
            )
        )
    assert [path for path, _ in requested].count("/robots.txt") == 1
    assert all(
        b[1] - a[1] >= robots.DEFAULT_REQUEST_INTERVAL_S for a, b in zip(requested, requested[1:])
    )
