"""Unit tests for PageIndex SDK lifecycle and provider routing.

The pipeline talks to PageIndex's REST API through an injectable client, so we
    exercise the orchestration against a fake client without network calls.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from deeptutor.services.rag.factory import get_pipeline, normalize_provider_name
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
        self.modes: list[str | None] = []

    async def submit_document(self, file_path, *, mode=None) -> str:
        self.submitted.append(str(file_path))
        self.modes.append(mode)
        return f"pi-{Path(file_path).name}"

    async def delete_document(self, doc_id) -> bool:
        self.deleted.append(doc_id)
        return True


def _pipe(tmp_path, client) -> PageIndexPipeline:
    return PageIndexPipeline(kb_base_dir=str(tmp_path), client=client)


def _manifest(tmp_path, kb_name) -> dict:
    return storage.read_manifest(Path(tmp_path) / kb_name)


def test_is_supported_file() -> None:
    # Mirrors PageIndex POST /doc/ accepted formats.
    for name in ("a.pdf", "b.MD", "c.markdown", "d.docx", "e.txt", "f.XLSX", "g.pptx", "h.csv"):
        assert is_supported_file(name), name
    assert not is_supported_file("i.png")
    assert not is_supported_file("j.zip")  # containers are unpacked upstream
    assert is_supported_file("a.PDF", "pageindex-oss")
    assert not is_supported_file("b.docx", "pageindex-oss")


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
    assert not list((tmp_path / "kb1").glob("version-*"))


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


def test_oss_accepts_pdf_only_and_forwards_explicit_mode(tmp_path, monkeypatch) -> None:
    client = FakeClient()
    pipe = PageIndexPipeline(
        kb_base_dir=str(tmp_path),
        client=client,
        provider="pageindex-oss",
    )
    monkeypatch.setattr(pipe, "_processing_mode", lambda _kb: "standard")
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    docx = tmp_path / "b.docx"
    docx.write_text("y")

    assert asyncio.run(pipe.initialize("oss", [str(pdf), str(docx)])) is True
    assert [Path(path).name for path in client.submitted] == ["a.pdf"]
    assert client.modes == ["standard"]
    assert _manifest(tmp_path, "oss")["provider"] == "pageindex-oss"


def test_search_requires_reasoning_as_retrieval(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    res = asyncio.run(pipe.search("what?", "kb"))

    assert res["provider"] == "pageindex"
    assert res["error_type"] == "reasoning_as_retrieval_required"
    assert res["content"] == ""
    assert res["sources"] == []


def test_document_map_exposes_manifest(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    assert pipe.document_map("kb") == {"a.pdf": "pi-a.pdf"}
    assert pipe.document_map("missing-kb") == {}


def test_document_map_reads_legacy_version_manifest(tmp_path) -> None:
    legacy = tmp_path / "kb" / "version-1"
    legacy.mkdir(parents=True)
    manifest = storage._empty_manifest()
    storage.upsert_doc(manifest, "old.pdf", "pi-old")
    storage.write_manifest(legacy, manifest)
    (legacy / "meta.json").write_text(
        json.dumps({"provider": "pageindex", "signature": "pageindex"}),
        encoding="utf-8",
    )

    assert _pipe(tmp_path, FakeClient()).document_map("kb") == {"old.pdf": "pi-old"}


def test_search_without_documents_still_requires_agent_loop(tmp_path) -> None:
    res = asyncio.run(_pipe(tmp_path, FakeClient()).search("q", "missing-kb"))
    assert res["error_type"] == "reasoning_as_retrieval_required"
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


def test_remove_document_updates_sdk_and_manifest(tmp_path) -> None:
    client = FakeClient()
    pipe = _pipe(tmp_path, client)
    pdf = tmp_path / "a.pdf"
    pdf.write_text("x")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    assert asyncio.run(pipe.remove_document("kb", "a.pdf")) is True
    assert client.deleted == ["pi-a.pdf"]
    assert _manifest(tmp_path, "kb")["docs"] == {}


def test_factory_dispatches_by_provider(tmp_path, monkeypatch) -> None:
    # Constructing a real LlamaIndexPipeline resolves the active embedding model
    # from the catalog; CI has none, so stub the settings hook (the same way the
    # llamaindex pipeline tests do) — this test only asserts factory routing.
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    monkeypatch.setattr(LlamaIndexPipeline, "_configure_settings", lambda self: None)

    assert (
        type(get_pipeline("pageindex", kb_base_dir=str(tmp_path))).__name__ == "PageIndexPipeline"
    )
    oss = get_pipeline("pageindex-oss", kb_base_dir=str(tmp_path))
    assert type(oss).__name__ == "PageIndexPipeline"
    assert oss.provider == "pageindex-oss"
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
