from __future__ import annotations

import pytest

from deeptutor.services.web_source import crawler


def _xml(body: str) -> crawler.FetchOutcome:
    return crawler.FetchOutcome(html=body, final_url="https://example.test/sitemap", status_code=200)


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
    )

    assert urls[0] == "https://example.com/docs/"
    assert set(urls[1:]) == {
        "https://example.com/docs/getting-started",
        "https://example.com/docs/deep/config",
    }


@pytest.mark.asyncio
async def test_malformed_sitemap_falls_back_to_configured_url(monkeypatch) -> None:
    async def fake_fetch(url, **kwargs):
        return (
            _xml("<urlset><url><loc>broken")
            if url.endswith("/sitemap.xml")
            else None
        )

    monkeypatch.setattr(crawler, "_fetch_page", fake_fetch)

    assert await crawler._sitemap_urls(
        "https://example.test/docs/",
        client=object(),
        base_host="example.test",
        base_path_prefix="/docs",
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

    result = await crawler.crawl_docs_site(
        "https://example.com/docs/",
        seed_urls=["https://external.example/secret"],
    )

    assert [call[0][0] for call in processed] == ["https://example.com/docs/"]
    assert result.pages == []


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

    result = await crawler.crawl_docs_site("https://example.test/docs/")

    assert result.deleted_urls == ["https://example.test/docs/removed"]
    assert result.fetch_failure_count == 0
