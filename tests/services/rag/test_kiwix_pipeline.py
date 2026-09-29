"""A connected Kiwix KB searches its original ZIM without an ingest step."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from fastapi import HTTPException
import httpx
import pytest

from deeptutor.book.agents.source_explorer import SourceExplorer
from deeptutor.book.kb_health import fingerprint_kb_documents
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_generation import _ground_knowledge_base_source
from deeptutor.services.rag.pipelines.kiwix.client import (
    KiwixClient,
    KiwixError,
    parse_catalog_xml,
    parse_search_xml,
)
from deeptutor.services.rag.pipelines.kiwix.pipeline import KiwixPipeline

SEARCH_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Jazz</title><link>/content/music/A/Jazz</link>
    <description>Music <b>jazz</b> history</description></item>
  <item><title>Other book</title><link>/content/private/A/Secret</link>
    <description>must never be read</description></item>
</channel></rss>"""


def _transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/raw/music/meta/Title":
        return httpx.Response(200, text="Music archive")
    if request.url.path == "/search":
        assert request.url.params["books.name"] == "music"
        assert request.url.params["format"] == "xml"
        return httpx.Response(200, content=SEARCH_XML, headers={"content-type": "application/xml"})
    if request.url.path == "/raw/music/content/A/Jazz":
        return httpx.Response(
            200,
            text="<html><nav>menu</nav><main><h1>Jazz</h1><p>Improvised music.</p>"
            "<script>secret()</script></main></html>",
            headers={"content-type": "text/html"},
        )
    raise AssertionError(f"Unexpected Kiwix request: {request.url}")


@pytest.mark.asyncio
async def test_connected_kb_search_returns_readable_archive_sources(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.register_kiwix_kb(
        "offline-music", "http://kiwix.test", "music", zim_title="Music archive"
    )
    pipeline = KiwixPipeline(
        str(tmp_path),
        client_factory=lambda base, name: KiwixClient(
            base, name, transport=httpx.MockTransport(_transport)
        ),
    )
    result = await pipeline.search("jazz", "offline-music")

    assert result["provider"] == "kiwix"
    assert len(result["sources"]) == 1
    assert result["sources"][0]["article_path"] == "A/Jazz"
    assert result["sources"][0]["chunk_id"] == "music:A/Jazz"
    assert result["sources"][0]["id"] == "music:A/Jazz"
    assert result["sources"][0]["source"] == "Music archive / Jazz"
    assert "Improvised music." in result["content"]
    assert "secret" not in result["content"]
    assert not (tmp_path / "offline-music").exists()
    assert manager.get_metadata("offline-music")["zim_name"] == "music"
    assert manager.get_info("offline-music")["metadata"]["zim_title"] == "Music archive"
    first_fingerprint = fingerprint_kb_documents("offline-music", manager=manager)
    assert first_fingerprint["zim-archive"].startswith("sha256:")
    manager.config["knowledge_bases"]["offline-music"]["zim_name"] = "music-updated"
    manager._save_config()
    assert fingerprint_kb_documents("offline-music", manager=manager) != first_fingerprint


@pytest.mark.asyncio
async def test_probe_and_read_one_article_without_archive_copy() -> None:
    client = KiwixClient("http://kiwix.test", "music", transport=httpx.MockTransport(_transport))
    assert await client.probe() == "Music archive"
    assert "Improvised music." in await client.read_article("A/Jazz")


def test_search_xml_rejects_foreign_links_and_path_traversal() -> None:
    xml = b"""<rss><channel>
      <item><title>external</title><link>https://evil.test/content/music/A/X</link><description>x</description></item>
      <item><title>escape</title><link>/content/music/../private/X</link><description>x</description></item>
      <item><title>good</title><link>/content/music/A/Good</link><description>safe</description></item>
    </channel></rss>"""
    hits = parse_search_xml(xml, base_url="http://kiwix.test", zim_name="music")
    assert [hit.article_path for hit in hits] == ["A/Good"]


@pytest.mark.asyncio
async def test_legacy_opds_discovers_exact_loaded_zim_names() -> None:
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Music Encyclopedia</title><name>music_2026</name></entry>
      <entry><title>Python Docs</title><link type="text/html" href="/content/python_docs_2026" /></entry>
      <entry><title>Versioned Book</title><name>book_alias</name>
        <link type="text/html" href="/content/book_2026-09" /></entry>
      <entry><title>Foreign</title><link type="text/html" href="https://other.test/content/private" /></entry>
    </feed>"""

    def catalog(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/catalog/search"
        assert request.url.params["q"] == "docs"
        assert request.url.params["count"] == "50"
        return httpx.Response(200, content=xml)

    archives = await KiwixClient.list_archives(
        "http://kiwix.test", "docs", transport=httpx.MockTransport(catalog)
    )
    assert [(item.zim_name, item.title) for item in archives] == [
        ("music_2026", "Music Encyclopedia"),
        ("python_docs_2026", "Python Docs"),
        ("book_2026-09", "Versioned Book"),
    ]
    assert len(parse_catalog_xml(xml, base_url="http://kiwix.test")) == 3


@pytest.mark.asyncio
async def test_bad_server_response_has_no_citable_source(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.register_kiwix_kb("offline-music", "http://kiwix.test", "music")
    transport = httpx.MockTransport(lambda _: httpx.Response(500, text="broken"))
    pipeline = KiwixPipeline(
        str(tmp_path),
        client_factory=lambda base, name: KiwixClient(base, name, transport=transport),
    )
    result = await pipeline.search("jazz", "offline-music")
    assert result["error_type"] == "retrieval_error"
    assert result["sources"] == []
    assert result["content"] == ""


@pytest.mark.asyncio
async def test_late_match_stays_visible_when_book_clips_long_article(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.register_kiwix_kb("long-book", "http://kiwix.test", "music", zim_title="Music archive")
    xml = b"""<rss><channel><item><title>Long article</title>
      <link>/content/music/A/Long</link>
      <description>Rare passage about quantum lattice harmony.</description>
    </item></channel></rss>"""

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, content=xml)
        if request.url.path == "/raw/music/content/A/Long":
            return httpx.Response(
                200,
                text=f"<main><p>{'ordinary introduction ' * 1000}</p>"
                "<p>Rare passage about quantum lattice harmony.</p></main>",
                headers={"content-type": "text/html"},
            )
        raise AssertionError(request.url)

    pipeline = KiwixPipeline(
        str(tmp_path),
        client_factory=lambda base, name: KiwixClient(
            base, name, transport=httpx.MockTransport(transport)
        ),
    )
    result = await pipeline.search("quantum lattice", "long-book")
    source = result["sources"][0]
    assert source["id"] == source["chunk_id"] == "music:A/Long"
    assert source["content"].startswith("Search match: Rare passage about quantum lattice harmony.")
    assert "quantum lattice" in source["content"][:1200]
    assert "quantum lattice" not in source["content"][1200:]


def test_connection_rejects_invalid_names_and_urls() -> None:
    with pytest.raises(KiwixError):
        KiwixClient("file:///etc/passwd", "music")
    with pytest.raises(KiwixError):
        KiwixClient("http://kiwix.test", "../private")
    with pytest.raises(KiwixError):
        KiwixClient("http://kiwix.test:bad", "music")
    with pytest.raises(KiwixError):
        KiwixClient("http://kiwix.test/../admin", "music")


@pytest.mark.asyncio
async def test_article_fetch_rejects_redirects_and_unbounded_bodies() -> None:
    redirect = KiwixClient(
        "http://kiwix.test",
        "music",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(302, headers={"location": "http://other.test/"})
        ),
    )
    with pytest.raises(KiwixError, match="HTTP 302"):
        await redirect.read_article("A/Jazz")

    oversized = KiwixClient(
        "http://kiwix.test",
        "music",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=b"x" * 2_000_001, headers={"content-type": "text/plain"}
            )
        ),
    )
    with pytest.raises(KiwixError, match="size limit"):
        await oversized.read_article("A/Jazz")


@pytest.mark.asyncio
async def test_book_and_mastery_use_same_access_checked_rag_search(tmp_path, monkeypatch) -> None:
    access = importlib.import_module("deeptutor.multi_user.knowledge_access")
    from deeptutor.tools.rag_tool import rag_search

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.register_kiwix_kb(
        "offline-music", "http://kiwix.test", "music", zim_title="Music archive"
    )
    resource = SimpleNamespace(base_dir=tmp_path, name="offline-music", assigned=False)
    monkeypatch.setattr(access, "resolve_for_rag", lambda _ref: resource)
    monkeypatch.setattr(access, "resolve_kb", lambda _ref, **_kwargs: resource)
    monkeypatch.setattr(
        access, "resolve_kb_metadata", lambda _ref: manager.get_metadata("offline-music")
    )
    monkeypatch.setattr(access, "resolve_kb_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        KiwixClient,
        "_client",
        lambda _self: httpx.AsyncClient(transport=httpx.MockTransport(_transport)),
    )

    result = await rag_search("jazz", "offline-music")
    assert result["provider"] == "kiwix"
    assert result["sources"][0]["id"] == "music:A/Jazz"

    explorer = object.__new__(SourceExplorer)
    explorer.chunks_per_query = 4
    explorer.skipped_knowledge_bases = []
    chunks = await explorer._retrieve_kb_chunks(["jazz"], ["offline-music"])
    assert len(chunks) == 1
    assert chunks[0].ref == "music:A/Jazz"
    assert chunks[0].text.startswith("Search match: Music jazz history")
    assert "Improvised music." in chunks[0].text
    assert explorer.skipped_knowledge_bases == []

    source = TopicSource(
        id="topic-source-1",
        kind=TopicSourceKind.KNOWLEDGE_BASE,
        source_id="offline-music",
        label="Music archive",
    )
    grounded = await _ground_knowledge_base_source(source, query="jazz")
    assert grounded.available
    assert grounded.metadata["retrieval_provider"] == "kiwix"
    assert "Improvised music" in grounded.excerpt

    def forbidden(_ref):
        raise HTTPException(status_code=403, detail="Not assigned")

    monkeypatch.setattr(access, "resolve_for_rag", forbidden)
    with pytest.raises(HTTPException) as denied:
        await rag_search("jazz", "offline-music")
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_reading_import_stores_only_selected_text_and_checks_kb_scope(
    tmp_path, monkeypatch
) -> None:
    reading = importlib.import_module("deeptutor.api.routers.reading")
    access = importlib.import_module("deeptutor.multi_user.knowledge_access")
    client_module = importlib.import_module("deeptutor.services.rag.pipelines.kiwix.client")
    workspace_knowledge = importlib.import_module("deeptutor.services.workspace.knowledge")
    workspace_resources = importlib.import_module("deeptutor.services.workspace.resources")
    from deeptutor.reading import ReadingCatalogStore, ReadingStore

    catalog = ReadingCatalogStore(tmp_path / "reading")

    def scoped_catalog():
        assert not workspace_knowledge.library_request.get()
        return catalog

    monkeypatch.setattr(reading, "_catalog", scoped_catalog)
    monkeypatch.setattr(reading, "assert_learning_material", lambda *_args, **_kwargs: None)
    resource = SimpleNamespace(id="account:kb:offline-music", name="offline-music")
    monkeypatch.setattr(
        workspace_resources, "current_resources", lambda: SimpleNamespace(knowledge_bases=[])
    )

    def library_resource(ref, **_kwargs):
        assert ref == "account:kb:offline-music"
        assert workspace_knowledge.library_request.get()
        return resource

    monkeypatch.setattr(workspace_knowledge, "resolve_qualified", library_resource)
    monkeypatch.setattr(
        access,
        "manager_for_resource",
        lambda _resource: SimpleNamespace(
            get_metadata=lambda _name: {
                "type": "kiwix",
                "server_url": "http://kiwix.test",
                "zim_name": "music",
            }
        ),
    )

    class FakeClient:
        base_url = "http://kiwix.test"
        zim_name = "music"

        def __init__(self, *_args):
            pass

        async def read_article(self, path):
            assert path == "A/Jazz"
            return "Jazz\n\nImprovised music."

    monkeypatch.setattr(client_module, "KiwixClient", FakeClient)
    payload = reading.ZimArticleImportRequest(
        kb_ref="account:kb:offline-music", article_path="A/Jazz", title="Jazz"
    )
    result = await reading.import_zim_article(payload)
    material_id = result["material"]["material_id"]
    store = ReadingStore(catalog.root)
    assert "Improvised music" in store.unit_text(material_id, 1)
    assert list((catalog.root / material_id).glob("raw/*")) == []
    assert result["workspace"]["workspace_id"]
    assert result["material"]["source_url"] == "http://kiwix.test/content/music/A/Jazz"

    def forbidden(_ref, **_kwargs):
        raise HTTPException(status_code=403, detail="Not assigned")

    monkeypatch.setattr(workspace_knowledge, "resolve_qualified", forbidden)
    with pytest.raises(HTTPException) as denied:
        await reading.import_zim_article(payload)
    assert denied.value.status_code == 403
    assert not workspace_knowledge.library_request.get()
