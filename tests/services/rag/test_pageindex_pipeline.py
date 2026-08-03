"""Unit tests for the PageIndex cloud RAG pipeline + provider routing.

The pipeline talks to PageIndex's REST API through an injectable client, so we
exercise the orchestration (file filtering, manifest, outline search contract,
delete) against a fake client without any network calls. Deep retrieval is
agentic via the PageIndex MCP server and out of scope here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from deeptutor.services.rag.factory import get_pipeline, normalize_provider_name
from deeptutor.services.rag.index_versioning import resolve_storage_dir_for_read
from deeptutor.services.rag.pipelines.pageindex import storage
from deeptutor.services.rag.pipelines.pageindex.pipeline import (
    PageIndexPipeline,
    is_supported_file,
)


class FakeClient:
    """Stand-in for :class:`PageIndexClient` — records calls, no network."""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.deleted: list[str] = []
        self.trees: dict[str, list[dict]] = {}

    async def submit_document(self, file_path) -> str:
        self.submitted.append(str(file_path))
        return f"pi-{Path(file_path).name}"

    async def wait_until_ready(self, doc_id, **_kwargs) -> dict:
        return {"status": "completed", "retrieval_ready": True}

    async def get_document(self, doc_id, **_kwargs) -> dict:
        return {
            "doc_id": doc_id,
            "status": "completed",
            "retrieval_ready": True,
            "result": self.trees.get(doc_id, []),
        }

    async def delete_document(self, doc_id) -> bool:
        self.deleted.append(doc_id)
        return True


def _pipe(tmp_path, client) -> PageIndexPipeline:
    return PageIndexPipeline(kb_base_dir=str(tmp_path), client=client)


def _manifest(tmp_path, kb_name) -> dict:
    sdir = resolve_storage_dir_for_read(Path(tmp_path) / kb_name, None)
    return storage.read_manifest(sdir)


def test_is_supported_file() -> None:
    # Mirrors PageIndex POST /doc/ accepted formats.
    for name in ("a.pdf", "b.MD", "c.markdown", "d.docx", "e.txt", "f.XLSX", "g.pptx", "h.csv"):
        assert is_supported_file(name), name
    assert not is_supported_file("i.png")
    assert not is_supported_file("j.zip")  # containers are unpacked upstream


def test_initialize_submits_supported_and_skips_others(tmp_path) -> None:
    client = FakeClient()
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    docx = tmp_path / "b.docx"
    docx.write_text("y")
    png = tmp_path / "c.png"
    png.write_text("z")

    ok = asyncio.run(_pipe(tmp_path, client).initialize("kb1", [str(pdf), str(docx), str(png)]))

    assert ok is True
    assert sorted(Path(p).name for p in client.submitted) == ["a.pdf", "b.docx"]
    docs = _manifest(tmp_path, "kb1")["docs"]
    assert set(docs) == {"a.pdf", "b.docx"}
    assert docs["a.pdf"]["doc_id"] == "pi-a.pdf"


def test_initialize_no_supported_returns_false(tmp_path) -> None:
    client = FakeClient()
    png = tmp_path / "c.png"
    png.write_text("z")
    ok = asyncio.run(_pipe(tmp_path, client).initialize("kb2", [str(png)]))
    assert ok is False
    assert client.submitted == []


def test_add_documents_appends_to_manifest(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    a = tmp_path / "a.pdf"
    a.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(a)]))

    b = tmp_path / "b.pdf"
    b.write_text("y")
    ok = asyncio.run(pipe.add_documents("kb", [str(b)]))

    assert ok is True
    assert set(_manifest(tmp_path, "kb")["docs"]) == {"a.pdf", "b.pdf"}


def test_search_returns_document_outline(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    client.trees["pi-a.pdf"] = [
        {
            "title": "Introduction",
            "node_id": "n1",
            "page_index": 1,
            "prefix_summary": "What this paper is about.",
            "nodes": [
                {"title": "Background", "node_id": "n2", "page_index": 2, "summary": "History."}
            ],
        }
    ]

    res = asyncio.run(pipe.search("what?", "kb"))

    assert res["provider"] == "pageindex"
    assert "error_type" not in res
    # Real structural context: nested outline with titles, pages, summaries.
    assert "- Introduction (p.1): What this paper is about." in res["content"]
    assert "  - Background (p.2): History." in res["content"]
    assert res["answer"] == res["content"]
    # Sources come from top-level sections, anchored to the file.
    assert res["sources"][0]["title"] == "Introduction"
    assert res["sources"][0]["page"] == 1
    assert res["sources"][0]["source"] == "a.pdf"
    assert res["sources"][0]["chunk_id"] == "n1"


def test_document_map_exposes_manifest(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    assert pipe.document_map("kb") == {"a.pdf": "pi-a.pdf"}
    assert pipe.document_map("missing-kb") == {}


def test_search_without_documents_flags_reindex(tmp_path) -> None:
    res = asyncio.run(_pipe(tmp_path, FakeClient()).search("q", "missing-kb"))
    assert res["needs_reindex"] is True
    assert res["sources"] == []
    assert res["provider"] == "pageindex"


def test_delete_drops_cloud_docs_and_local_dir(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    a = tmp_path / "a.pdf"
    a.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(a)]))

    ok = asyncio.run(pipe.delete("kb"))

    assert ok is True
    assert "pi-a.pdf" in client.deleted
    assert not (tmp_path / "kb").exists()


def test_factory_dispatches_by_provider(tmp_path, monkeypatch) -> None:
    # Constructing a real LlamaIndexPipeline resolves the active embedding model
    # from the catalog; CI has none, so stub the settings hook (the same way the
    # llamaindex pipeline tests do) — this test only asserts factory routing.
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    monkeypatch.setattr(LlamaIndexPipeline, "_configure_settings", lambda self: None)

    assert (
        type(get_pipeline("pageindex", kb_base_dir=str(tmp_path))).__name__ == "PageIndexPipeline"
    )
    assert (
        type(get_pipeline("llamaindex", kb_base_dir=str(tmp_path))).__name__ == "LlamaIndexPipeline"
    )
    # Legacy / unknown providers fall back to the default engine.
    assert (
        type(get_pipeline("raganything", kb_base_dir=str(tmp_path))).__name__
        == "LlamaIndexPipeline"
    )
    assert normalize_provider_name("raganything") == "llamaindex"


def test_ragservice_resolves_provider_from_metadata(tmp_path) -> None:
    from deeptutor.services.rag.service import RAGService

    kb = tmp_path / "kbx"
    kb.mkdir()
    (kb / "metadata.json").write_text(json.dumps({"rag_provider": "pageindex"}), encoding="utf-8")

    svc = RAGService(kb_base_dir=str(tmp_path))
    assert svc._resolve_provider("kbx") == "pageindex"
    # Unknown KB → default.
    assert svc._resolve_provider("nope") == "llamaindex"
    # Explicit override wins over metadata.
    svc_override = RAGService(kb_base_dir=str(tmp_path), provider="llamaindex")
    assert svc_override._resolve_provider("kbx") == "llamaindex"
