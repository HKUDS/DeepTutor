"""Tests for the web source crawler and sync engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.services.web_source.crawler import (
    ALLOWED_HOSTS_ENV,
    CrawledPage,
    CrawlResult,
    _configured_allowed_hosts,
    _is_crawler_disallowed_host,
    _is_internal,
    _normalise_link,
    _to_filename,
    crawl_and_diff,
    crawl_docs_site,
)
from deeptutor.services.web_source.sync import WebSyncResult, sync_source
from deeptutor.services.web_source.sync_service import _is_stale


def test_normalise_link_absolute():
    assert _normalise_link("https://a.com/b/", "/b/c") == "https://a.com/b/c"


def test_normalise_link_javascript():
    assert _normalise_link("https://a.com/b", "javascript:void(0)") is None


def test_normalise_link_fragment():
    assert _normalise_link("https://a.com/b", "#section") is None


def test_is_internal_same_host():
    assert _is_internal("https://a.com/docs/x", "a.com", "/docs") is True


def test_is_internal_different_host():
    assert _is_internal("https://b.com/docs/x", "a.com", "/docs") is False


def test_is_internal_outside_prefix():
    assert _is_internal("https://a.com/blog/x", "a.com", "/docs") is False


def test_to_filename_docs_path():
    assert _to_filename("https://a.com/docs/getting-started/", "/docs") == "docs/getting-started.md"


def test_to_filename_root():
    assert _to_filename("https://a.com/docs/", "/docs") == "docs.md"


def test_to_filename_no_prefix_collision():
    """Full-path filenames must differ across sources with same leaf segment."""
    en = _to_filename("https://docs.deeptutor.info/docs/intro", "/")
    zh = _to_filename("https://docs.deeptutor.info/zh-cn/docs/intro", "/zh-cn/")
    assert en == "docs/intro.md"
    assert zh == "zh-cn/docs/intro.md"
    assert en != zh


def test_crawler_host_allowlist_parses_normalized_hosts(monkeypatch):
    monkeypatch.setenv(ALLOWED_HOSTS_ENV, "Local.Host; 127.0.0.1, [::1]")

    assert _configured_allowed_hosts() == frozenset({"local.host", "127.0.0.1", "::1"})


def test_crawler_host_allowlist_only_bypasses_named_hosts(monkeypatch):
    monkeypatch.setenv(ALLOWED_HOSTS_ENV, "127.0.0.1")
    monkeypatch.setattr(
        "deeptutor.services.web_source.crawler._is_disallowed_host",
        lambda host: host in {"127.0.0.1", "10.0.0.8"},
    )

    assert _is_crawler_disallowed_host("127.0.0.1") is False
    assert _is_crawler_disallowed_host("10.0.0.8") is True
    assert _is_crawler_disallowed_host("example.com") is False


@pytest.mark.asyncio
async def test_crawler_host_allowlist_accepts_local_base_url(monkeypatch):
    monkeypatch.setenv(ALLOWED_HOSTS_ENV, "127.0.0.1")
    monkeypatch.setattr(
        "deeptutor.services.web_source.crawler._fetch_page",
        AsyncMock(return_value=None),
    )

    result = await crawl_docs_site("http://127.0.0.1:18784/en.html")

    assert result.errors == []


def _make_kb(tmp_path: Path, kb_name: str = "kb") -> tuple[str, Path]:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / kb_name
    kb_dir.mkdir()
    (kb_dir / "raw").mkdir()
    manager.register_knowledge_base(kb_name)
    (kb_dir / "metadata.json").write_text("{}", encoding="utf-8")
    return str(manager.base_dir), kb_dir


@pytest.mark.asyncio
async def test_sync_source_first_run(tmp_path: Path):
    base_dir, kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    mgr = KnowledgeBaseManager(base_dir=base_dir)
    source = mgr.add_web_source("kb", "https://example.com/docs/")

    mock_result = CrawlResult(
        pages=[
            CrawledPage(
                url="https://example.com/docs/", title="Home", markdown="# Home", content_hash="aaa"
            ),
            CrawledPage(
                url="https://example.com/docs/intro",
                title="Intro",
                markdown="# Intro",
                content_hash="bbb",
            ),
        ]
    )

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", new_callable=AsyncMock
    ) as mock_crawl:
        mock_crawl.return_value = mock_result
        with patch(
            "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = 2
            result = await sync_source("kb", source, base_dir=base_dir)

    assert result.ok is True
    assert result.pages_added == 2
    assert result.pages_unchanged == 0
    # Verify files written to raw/.  Full-path filenames are preserved
    # (no prefix stripping) so multiple web sources sharing one KB
    # never collide.
    raw = kb_dir / "raw"
    assert (raw / "docs.md").exists()
    assert (raw / "docs" / "intro.md").exists()


@pytest.mark.asyncio
async def test_sync_source_unchanged_pages(tmp_path: Path):
    base_dir, kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    mgr = KnowledgeBaseManager(base_dir=base_dir)
    source = mgr.add_web_source("kb", "https://example.com/docs/")
    # Pre-populate hashes to simulate prior sync
    source["page_hashes"] = {"docs.md": "aaa"}

    mock_result = CrawlResult(
        pages=[
            CrawledPage(
                url="https://example.com/docs/", title="Home", markdown="# Home", content_hash="aaa"
            ),
        ]
    )

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", new_callable=AsyncMock
    ) as mock_crawl:
        mock_crawl.return_value = mock_result
        with patch("deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock):
            result = await sync_source("kb", source, base_dir=base_dir)

    assert result.ok is True
    assert result.pages_added == 0
    assert result.pages_unchanged == 1


def test_is_stale_never_synced():
    assert _is_stale({"last_synced_at": ""}) is True


def test_is_stale_recent():
    recent = datetime.now(timezone.utc).isoformat()
    assert _is_stale({"last_synced_at": recent}) is False


def test_is_stale_old():
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert _is_stale({"last_synced_at": old}) is True


@pytest.mark.asyncio
async def test_crawl_and_diff_persists_page_manifest(tmp_path: Path) -> None:
    page = CrawledPage(
        url="https://example.com/docs/intro/",
        title="Introduction",
        markdown="# Introduction",
        content_hash="hash-1",
        requested_url="https://example.com/docs/intro",
        canonical_url="https://example.com/docs/intro/",
        document_version="v2",
    )
    result = CrawlResult(
        pages=[page],
        navigation_links=[
            {"title": "Docs", "url": "https://example.com/docs/", "depth": 0},
            {"title": "Introduction", "url": "https://example.com/docs/intro/", "depth": 1},
        ],
        navigation_kind="original",
    )

    async def fake_crawl(*_args, **_kwargs):
        return result

    source = {
        "url": "https://example.com/docs/",
        "document_version": "v2",
        "page_hashes": {},
        "page_manifest": {},
    }
    with patch("deeptutor.services.web_source.crawler.crawl_docs_site", new=fake_crawl):
        diff = await crawl_and_diff(source, tmp_path)

    entry = diff.page_manifest["docs/intro.md"]
    assert entry["canonical_url"] == "https://example.com/docs/intro/"
    assert entry["title"] == "Introduction"
    assert entry["section_path"] == ["Docs", "Introduction"]
    assert entry["content_hash"] == "hash-1"
    assert entry["fetched_at"]
    assert entry["document_version"] == "v2"
    assert entry["status"] == "active"


@pytest.mark.asyncio
async def test_incomplete_crawl_does_not_delete_missing_page(tmp_path: Path) -> None:
    old_file = tmp_path / "docs" / "old.md"
    old_file.parent.mkdir(parents=True)
    old_file.write_text("old", encoding="utf-8")
    source = {
        "url": "https://example.com/docs/",
        "page_hashes": {"docs/old.md": "old-hash"},
        "page_manifest": {
            "docs/old.md": {
                "file_path": "docs/old.md",
                "canonical_url": "https://example.com/docs/old",
                "content_hash": "old-hash",
                "status": "active",
            }
        },
    }
    result = CrawlResult(
        pages=[
            CrawledPage(
                url="https://example.com/docs/",
                title="Home",
                markdown="# Home",
                content_hash="home-hash",
            )
        ],
        truncated=True,
    )

    async def fake_crawl(*_args, **_kwargs):
        return result

    with patch("deeptutor.services.web_source.crawler.crawl_docs_site", new=fake_crawl):
        diff = await crawl_and_diff(source, tmp_path)

    assert diff.pages_removed == []
    assert diff.pages_unresolved == ["docs/old.md"]
    assert old_file.exists()
    assert diff.page_manifest["docs/old.md"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_complete_crawl_marks_missing_page_deleted(tmp_path: Path) -> None:
    old_file = tmp_path / "docs" / "old.md"
    old_file.parent.mkdir(parents=True)
    old_file.write_text("old", encoding="utf-8")
    source = {
        "url": "https://example.com/docs/",
        "page_hashes": {"docs/old.md": "old-hash"},
        "page_manifest": {
            "docs/old.md": {
                "file_path": "docs/old.md",
                "canonical_url": "https://example.com/docs/old",
                "content_hash": "old-hash",
                "status": "active",
            }
        },
    }
    result = CrawlResult(
        pages=[
            CrawledPage(
                url="https://example.com/docs/",
                title="Home",
                markdown="# Home",
                content_hash="home-hash",
            )
        ]
    )

    async def fake_crawl(*_args, **_kwargs):
        return result

    with patch("deeptutor.services.web_source.crawler.crawl_docs_site", new=fake_crawl):
        diff = await crawl_and_diff(source, tmp_path)

    assert diff.pages_removed == ["docs/old.md"]
    assert not old_file.exists()
    assert diff.page_manifest["docs/old.md"]["status"] == "deleted"


# ── Navigation extraction tests ──────────────────────────────────────


def test_extract_navigation_docusaurus():
    """Sidebar links should be extracted before they are stripped."""
    from deeptutor.services.web_source.html_extractor import extract_navigation

    html = """<html><body>
<nav class="theme-doc-sidebar-menu">
  <ul>
    <li><a href="/get-started/">Get Started</a></li>
    <li><a href="/get-started/install/">Install</a></li>
    <li><a href="/explore/">Explore</a></li>
  </ul>
</nav>
<main><h1>Page</h1></main>
</body></html>"""

    links = extract_navigation(html, "https://docs.example.com/")
    assert len(links) == 3
    assert links[0]["title"] == "Get Started"
    assert links[0]["url"] == "https://docs.example.com/get-started/"
    assert links[1]["url"] == "https://docs.example.com/get-started/install/"


def test_extract_navigation_no_sidebar():
    """Returns empty list when no sidebar is present."""
    from deeptutor.services.web_source.html_extractor import extract_navigation

    html = "<html><body><main><h1>Page</h1></main></body></html>"
    links = extract_navigation(html, "https://example.com/")
    assert links == []


def test_extract_navigation_dedupes():
    """Duplicate URLs should appear only once."""
    from deeptutor.services.web_source.html_extractor import extract_navigation

    html = """<html><body>
<nav class="sidebar"><ul>
<li><a href="/a/">A</a></li>
<li><a href="/a/">A again</a></li>
<li><a href="/b/">B</a></li>
</ul></nav>
</body></html>"""

    links = extract_navigation(html, "https://example.com/")
    assert len(links) == 2
    assert links[0]["title"] == "A"
    assert links[1]["title"] == "B"


def test_extract_headings_basic():
    """ATX headings should be extracted with level and slug."""
    from deeptutor.services.web_source.html_extractor import extract_headings

    md = "# Title\n\nSome text\n\n## Section\n\n### Deep\n\n```python\n# not a heading\n```"
    hs = extract_headings(md)
    assert len(hs) == 3
    assert hs[0]["level"] == 1
    assert hs[0]["text"] == "Title"
    assert hs[1]["level"] == 2
    assert hs[1]["text"] == "Section"
    assert hs[2]["level"] == 3


def test_infer_navigation_from_urls():
    """When no sidebar is found, URL paths should produce a nav list."""
    from deeptutor.services.web_source.crawler import CrawledPage, _infer_navigation

    pages = [
        CrawledPage("https://docs.example.com/", "Home", "body", "h1"),
        CrawledPage("https://docs.example.com/a/", "Section A", "body", "h2"),
        CrawledPage("https://docs.example.com/a/sub/", "Sub", "body", "h3"),
        CrawledPage("https://docs.example.com/b/", "Section B", "body", "h4"),
    ]
    nav = _infer_navigation(pages, "https://docs.example.com/")
    assert len(nav) == 4
    assert nav[0]["title"] == "Home"
    assert nav[0]["depth"] == 0
    assert nav[3]["title"] == "Section B"
    assert nav[3]["depth"] == 1


def test_navigation_tree_building():
    """Flat navigation links should produce a proper tree."""
    from deeptutor.services.web_source.sync import _flat_to_tree

    links = [
        {"title": "Root A", "url": "https://x.com/a/", "depth": 0},
        {"title": "Child 1", "url": "https://x.com/a/1/", "depth": 1},
        {"title": "Child 2", "url": "https://x.com/a/2/", "depth": 1},
        {"title": "Root B", "url": "https://x.com/b/", "depth": 0},
        {"title": "Child 3", "url": "https://x.com/b/3/", "depth": 1},
    ]
    url_to_file = {
        "https://x.com/a/": "a.md",
        "https://x.com/a/1/": "a/1.md",
        "https://x.com/a/2/": "a/2.md",
        "https://x.com/b/": "b.md",
        "https://x.com/b/3/": "b/3.md",
    }
    tree = _flat_to_tree(links, url_to_file)
    assert len(tree) == 2
    assert tree[0]["title"] == "Root A"
    assert len(tree[0]["children"]) == 2
    assert tree[0]["children"][0]["file_path"] == "a/1.md"
    assert tree[1]["title"] == "Root B"
    assert len(tree[1]["children"]) == 1


def test_navigation_manifest_empty():
    """Empty nav links should produce an empty manifest."""
    from deeptutor.services.web_source.sync import _build_navigation_manifest

    manifest = _build_navigation_manifest([], "", {}, "/")
    assert manifest["kind"] == ""
    assert manifest["nodes"] == []


@pytest.mark.asyncio
async def test_sync_persists_navigation(tmp_path: Path):
    """sync_source should persist navigation data into metadata."""
    base_dir, kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    mgr = KnowledgeBaseManager(base_dir=base_dir)
    source = mgr.add_web_source("kb", "https://example.com/docs/")

    mock_result = CrawlResult(
        pages=[
            CrawledPage(
                url="https://example.com/docs/",
                title="Home",
                markdown="# Home",
                content_hash="aaa",
            ),
            CrawledPage(
                url="https://example.com/docs/intro",
                title="Intro",
                markdown="# Intro",
                content_hash="bbb",
            ),
        ],
        navigation_links=[
            {"title": "Home", "url": "https://example.com/docs/", "path": "/docs/", "depth": 0},
            {
                "title": "Intro",
                "url": "https://example.com/docs/intro",
                "path": "/docs/intro",
                "depth": 1,
            },
        ],
        navigation_kind="original",
    )

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", new_callable=AsyncMock
    ) as mock_crawl:
        mock_crawl.return_value = mock_result
        with patch(
            "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
        ) as mock_add:
            mock_add.return_value = 2
            result = await sync_source("kb", source, base_dir=base_dir)

    assert result.ok is True

    # Verify navigation was persisted
    sources_after = mgr.get_web_sources("kb")
    assert len(sources_after) == 1
    nav = sources_after[0].get("navigation", {})
    assert nav["kind"] == "original"
    assert len(nav["nodes"]) >= 1

    # Verify get_web_navigation returns it
    nav_data = mgr.get_web_navigation("kb")
    assert len(nav_data) == 1
    assert nav_data[0]["kind"] == "original"
    assert len(nav_data[0]["nodes"]) >= 1
