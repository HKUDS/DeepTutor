"""Seed-scope semantics of :func:`crawl_docs_site`'s ``base_path_prefix``.

Contract:

- A page seed scopes its parent directory, so sibling pages are internal:
  ``/intro/home`` seeds ``/intro/*``.
- A root seed still scopes the whole host.
- Anything outside the seed's directory — other directories, other hosts,
  or sibling look-alike prefixes — is rejected.
- A trailing-slash (directory index) seed stays scoped to its own
  directory; it must not widen to the whole host.
"""

from __future__ import annotations

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


async def _crawl(seed_url: str, page_html: str, requested: list[str]) -> crawler.CrawlResult:
    """Crawl a mock site that serves *page_html* for every page request.

    Records every requested URL path (``/robots.txt`` included) into
    *requested*, so tests can assert exactly which pages were fetched.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text=page_html)

    return await crawler.crawl_docs_site(
        seed_url,
        max_depth=1,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_page_seed_scopes_sibling_directory_and_rejects_outside(crawl_clock):
    """``/intro/home`` seeds ``/intro/*``; anything else stays out of scope."""
    requested: list[str] = []
    result = await _crawl(
        "https://example.com/intro/home",
        "<html><body><main>"
        "<a href='/intro/next'>next</a>"
        "<a href='/intro'>parent</a>"
        "<a href='/docs/outside'>outside</a>"
        "<a href='/intro2/lookalike'>lookalike</a>"
        "<a href='https://other.example/x'>external</a>"
        "</main></body></html>",
        requested,
    )

    assert result.ok
    assert not result.errors
    assert requested[0] == "/robots.txt"
    assert requested[1] == "/intro/home"
    # Siblings are internal, including the bare parent directory itself.
    assert sorted(requested[2:]) == ["/intro", "/intro/next"]


@pytest.mark.asyncio
async def test_root_seed_still_scopes_whole_host(crawl_clock):
    """A root URL keeps the historical whole-host scope."""
    requested: list[str] = []
    result = await _crawl(
        "https://example.com/",
        "<html><body><main><a href='/any/deep'>deep</a></main></body></html>",
        requested,
    )

    assert result.ok
    assert sorted(requested[1:]) == ["/", "/any/deep"]


@pytest.mark.asyncio
async def test_directory_seed_stays_scoped_to_its_directory(crawl_clock):
    """A trailing-slash seed is a directory index, not a root override.

    ``Path('/intro/').parent`` is ``/`` — a naive pathlib rewrite would
    widen a section seed to the entire host.
    """
    requested: list[str] = []
    result = await _crawl(
        "https://example.com/intro/",
        "<html><body><main>"
        "<a href='/intro/other'>other</a>"
        "<a href='/docs/elsewhere'>elsewhere</a>"
        "</main></body></html>",
        requested,
    )

    assert result.ok
    assert sorted(requested[1:]) == ["/intro/", "/intro/other"]
