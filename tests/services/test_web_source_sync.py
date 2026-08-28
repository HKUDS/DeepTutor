"""Tests for the web source crawler and sync engine."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deeptutor.services.web_source.crawler import (
    CrawledPage,
    CrawlResult,
    _fetch_page,
    _is_internal,
    _normalise_link,
    _source_filename,
    _to_filename,
    crawl_and_diff,
)
from deeptutor.services.web_source.sync import WebSyncResult, sync_source


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


def test_to_filename_contains_traversal_and_distinguishes_queries():
    traversal = _to_filename("https://a.com/../../outside", "/")
    assert ".." not in Path(traversal).parts
    first = _to_filename("https://a.com/docs/search?q=alpha", "/docs")
    second = _to_filename("https://a.com/docs/search?q=beta", "/docs")
    assert first != second


@pytest.mark.asyncio
async def test_fetch_page_blocks_private_redirect_before_request():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with patch(
            "deeptutor.services.web_source.crawler._is_disallowed_host",
            side_effect=lambda host: host == "127.0.0.1",
        ):
            result = await _fetch_page("https://docs.example.com/start", client=client)

    assert result is None
    assert requested == ["https://docs.example.com/start"]


@pytest.mark.asyncio
async def test_process_page_resolves_relative_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.web_source.crawler import _process_page

    html = """
    <html><head><title>Introduction</title></head><body>
      <article><p><img src="../images/diagram.png" alt="Diagram"></p></article>
    </body></html>
    """

    async def fake_fetch_page(url, client):
        return html, "https://docs.example.com/guide/introduction/"

    monkeypatch.setattr("deeptutor.services.web_source.crawler._fetch_page", fake_fetch_page)

    result = await _process_page(
        "https://docs.example.com/guide/introduction",
        depth=0,
        client=None,
        sem=asyncio.Semaphore(1),
        base_host="docs.example.com",
        base_path_prefix="/guide/",
        max_depth=1,
    )

    assert result is not None
    assert (
        "![Diagram](https://docs.example.com/guide/images/diagram.png)" in result["page"].markdown
    )


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
    assert len(list(raw.rglob("docs.md"))) == 1
    assert len(list(raw.rglob("intro.md"))) == 1


@pytest.mark.asyncio
async def test_sync_source_unchanged_pages(tmp_path: Path):
    base_dir, kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    mgr = KnowledgeBaseManager(base_dir=base_dir)
    source = mgr.add_web_source("kb", "https://example.com/docs/")
    # Pre-populate hashes to simulate prior sync
    filename = _source_filename(source, "https://example.com/docs/", "/docs/")
    source["page_hashes"] = {filename: "aaa"}
    unchanged_path = kb_dir / "raw" / filename
    unchanged_path.parent.mkdir(parents=True, exist_ok=True)
    unchanged_path.write_text("# Home", encoding="utf-8")

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


@pytest.mark.asyncio
async def test_sync_source_records_crawl_failure(tmp_path: Path):
    base_dir, _kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    source = manager.add_web_source("kb", "https://example.com/docs/")
    result = CrawlResult(errors=["Disallowed host: localhost"])

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", new_callable=AsyncMock
    ) as mock_crawl:
        mock_crawl.return_value = result
        outcome = await sync_source("kb", source, base_dir=base_dir)

    assert outcome.ok is False
    assert "Disallowed host" in outcome.error
    state = manager.get_web_sources("kb")[0]
    assert state["last_sync_status"] == "error"
    assert "Disallowed host" in state["last_sync_error"]
    assert state["last_synced_at"]


@pytest.mark.asyncio
async def test_sync_source_indexing_failure_keeps_previous_hashes(tmp_path: Path):
    base_dir, _kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    source = manager.add_web_source("kb", "https://example.com/docs/")
    filename = _source_filename(source, "https://example.com/docs/", "/docs/")
    source["page_hashes"] = {filename: "old"}
    manager.update_web_source_state("kb", source["id"], page_hashes=source["page_hashes"])
    result = CrawlResult(
        pages=[
            CrawledPage(
                url="https://example.com/docs/",
                title="Home",
                markdown="# Home",
                content_hash="new",
            )
        ]
    )

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site", new_callable=AsyncMock
    ) as mock_crawl:
        mock_crawl.return_value = result
        with patch(
            "deeptutor.knowledge.add_documents.add_documents", new_callable=AsyncMock
        ) as mock_add:
            mock_add.side_effect = RuntimeError("index unavailable")
            outcome = await sync_source("kb", source, base_dir=base_dir)

    assert outcome.ok is False
    assert "index unavailable" in outcome.error
    state = manager.get_web_sources("kb")[0]
    assert state["last_sync_status"] == "error"
    assert "index unavailable" in state["last_sync_error"]
    assert state["page_hashes"] == {filename: "old"}


@pytest.mark.asyncio
async def test_sources_with_same_page_path_use_distinct_raw_files(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    source_a = {"id": "a", "url": "https://a.example/docs", "page_hashes": {}}
    source_b = {"id": "b", "url": "https://b.example/docs", "page_hashes": {}}
    crawls = [
        CrawlResult(pages=[CrawledPage("https://a.example/docs/intro", "A", "body A", "a")]),
        CrawlResult(pages=[CrawledPage("https://b.example/docs/intro", "B", "body B", "b")]),
    ]

    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site",
        new_callable=AsyncMock,
    ) as mock_crawl:
        mock_crawl.side_effect = crawls
        first = await crawl_and_diff(source_a, raw_dir)
        second = await crawl_and_diff(source_b, raw_dir)

    assert first.changed_paths != second.changed_paths
    assert all(Path(path).exists() for path in first.changed_paths + second.changed_paths)


@pytest.mark.asyncio
async def test_removed_page_is_purged_before_full_index_rebuild(tmp_path: Path):
    base_dir, kb_dir = _make_kb(tmp_path)
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    source = manager.add_web_source("kb", "https://example.com/docs/")
    old_name = _source_filename(source, "https://example.com/docs/old", "/docs/")
    source["page_hashes"] = {old_name: "old"}
    manager.update_web_source_state("kb", source["id"], page_hashes=source["page_hashes"])
    old_path = kb_dir / "raw" / old_name
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("old page", encoding="utf-8")
    metadata_path = kb_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["file_hashes"] = {old_name: "old"}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    crawl = CrawlResult(
        pages=[
            CrawledPage(
                "https://example.com/docs/current",
                "Current",
                "current page",
                "current",
            )
        ]
    )
    with patch(
        "deeptutor.services.web_source.crawler.crawl_docs_site",
        new_callable=AsyncMock,
        return_value=crawl,
    ):
        with patch(
            "deeptutor.services.rag.service.RAGService.initialize",
            new_callable=AsyncMock,
            return_value=True,
        ) as rebuild:
            outcome = await sync_source("kb", source, base_dir=base_dir)

    assert outcome.ok is True
    assert outcome.pages_removed == 1
    assert not old_path.exists()
    assert rebuild.await_count == 1
    rebuilt_paths = rebuild.await_args.kwargs["file_paths"]
    assert all(old_name not in path for path in rebuilt_paths)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert old_name not in metadata.get("file_hashes", {})


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

    assert sources_after[0]["page_count"] == 2
