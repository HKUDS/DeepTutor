"""Tests for LlamaIndex document loading.

Parser-backed files (PDF / Office / e-book) are routed through the shared
parse layer, so these tests exercise the *routing* — that the loader turns a
``ParsedDocument`` into text ``Document``s and feeds engine-extracted images
into the multimodal ``ImageNode`` path. Real per-format text extraction is
covered by ``tests/utils/test_document_extractor.py`` and the parse-engine
tests under ``tests/services/parsing/``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _install_stub_parse_service(monkeypatch, results: dict[str, "object"]) -> None:
    """Point ``get_parse_service`` at a stub keyed by source file name.

    ``results`` maps a file name to either a ``ParsedDocument`` to return or an
    exception instance to raise (e.g. ``ParserError``).
    """
    import deeptutor.services.parsing as parsing

    class _StubService:
        def parse(self, source_path, **_kwargs):
            outcome = results[Path(source_path).name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(parsing, "get_parse_service", lambda: _StubService())


def test_loader_routes_parser_files_through_active_parse_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("llama_index.core")
    from deeptutor.services.parsing.types import ParsedDocument
    from deeptutor.services.rag.pipelines.llamaindex.document_loader import (
        LlamaIndexDocumentLoader,
    )

    docx_path = tmp_path / "notes.docx"
    docx_path.write_bytes(b"stub")
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"stub")

    _install_stub_parse_service(
        monkeypatch,
        {
            "notes.docx": ParsedDocument(markdown="Docx body text"),
            # No markdown, only structured blocks -> block-text fallback.
            "paper.pdf": ParsedDocument(
                markdown="",
                blocks=[{"type": "text", "text": "Block one"}, {"content": "Block two"}],
            ),
        },
    )

    documents = asyncio.run(LlamaIndexDocumentLoader().load([str(docx_path), str(pdf_path)]))

    by_name = {doc.metadata["file_name"]: doc.text for doc in documents}
    assert by_name["notes.docx"] == "Docx body text"
    assert "Block one" in by_name["paper.pdf"]
    assert "Block two" in by_name["paper.pdf"]


def test_loader_skips_document_when_active_engine_cannot_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip("llama_index.core")
    from deeptutor.services.parsing.types import ParserError
    from deeptutor.services.rag.pipelines.llamaindex.document_loader import (
        LlamaIndexDocumentLoader,
    )

    docx_path = tmp_path / "unsupported.docx"
    docx_path.write_bytes(b"stub")

    _install_stub_parse_service(
        monkeypatch,
        {"unsupported.docx": ParserError("the 'pymupdf4llm' engine doesn't support .docx files")},
    )

    with caplog.at_level("WARNING"):
        documents = asyncio.run(LlamaIndexDocumentLoader().load([str(docx_path)]))

    assert documents == []
    assert "Skipped unsupported.docx" in caplog.text
    assert "Settings" in caplog.text


def test_loader_indexes_images_extracted_from_parsed_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("llama_index.core")
    from llama_index.core.schema import ImageNode

    from deeptutor.services.parsing.types import ParsedDocument
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"stub")
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    (asset_dir / "figure-1.png").write_bytes(b"\x89PNG\r\n")
    (asset_dir / "notes.txt").write_text("not an image", encoding="utf-8")  # ignored

    _install_stub_parse_service(
        monkeypatch,
        {"paper.pdf": ParsedDocument(markdown="Paper body", asset_dir=asset_dir)},
    )

    class _MultimodalEmbeddingClient:
        config = type("Config", (), {"binding": "siliconflow", "model": "qwen3-vl"})()

        def supports_multimodal_contents(self) -> bool:
            return True

        async def embed_contents(self, contents):
            return [[0.4, 0.5, 0.6] for _ in contents]

    class _VisionClient:
        config = type("Config", (), {"binding": "openai", "model": "gpt-4o"})()

        def supports_multimodal_images(self) -> bool:
            return True

        async def complete(self, prompt, **kwargs):
            return "Figure showing a bar chart."

    monkeypatch.setattr(loader_module, "get_embedding_client", lambda: _MultimodalEmbeddingClient())
    monkeypatch.setattr(loader_module, "get_llm_client", lambda: _VisionClient())

    documents = asyncio.run(loader_module.LlamaIndexDocumentLoader().load([str(pdf_path)]))

    text_docs = [doc for doc in documents if not isinstance(doc, ImageNode)]
    image_nodes = [doc for doc in documents if isinstance(doc, ImageNode)]

    assert len(text_docs) == 1
    assert text_docs[0].text == "Paper body"

    assert len(image_nodes) == 1
    node = image_nodes[0]
    assert node.embedding == [0.4, 0.5, 0.6]
    assert node.metadata["content_type"] == "image"
    # Provenance: the extracted image cites the source document, not the cache asset.
    assert node.metadata["file_name"] == "paper.pdf"
    assert node.image_path == str(asset_dir / "figure-1.png")
    assert "Figure showing a bar chart." in node.text


def test_loader_skips_images_when_embedding_provider_is_text_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n")

    class _TextOnlyClient:
        config = type("Config", (), {"binding": "openai", "model": "text-embedding-3-small"})()

        def supports_multimodal_contents(self) -> bool:
            return False

    monkeypatch.setattr(loader_module, "get_embedding_client", lambda: _TextOnlyClient())

    documents = asyncio.run(loader_module.LlamaIndexDocumentLoader().load([str(image_path)]))

    assert documents == []


def test_loader_embeds_images_when_embedding_provider_is_multimodal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("llama_index.core")
    from llama_index.core.schema import ImageNode

    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n")
    captured: dict[str, object] = {}

    class _MultimodalClient:
        config = type("Config", (), {"binding": "siliconflow", "model": "qwen3-vl"})()

        def supports_multimodal_contents(self) -> bool:
            return True

        async def embed_contents(self, contents):
            captured["contents"] = contents
            return [[0.1, 0.2, 0.3]]

    class _VisionClient:
        config = type("Config", (), {"binding": "openai", "model": "gpt-4o"})()

        def supports_multimodal_images(self) -> bool:
            return True

        async def complete(self, prompt, **kwargs):
            captured["llm_prompt"] = prompt
            captured["llm_kwargs"] = kwargs
            return "A logo image with visible HKU text."

    monkeypatch.setattr(loader_module, "get_embedding_client", lambda: _MultimodalClient())
    monkeypatch.setattr(loader_module, "get_llm_client", lambda: _VisionClient())

    documents = asyncio.run(loader_module.LlamaIndexDocumentLoader().load([str(image_path)]))

    assert len(documents) == 1
    assert isinstance(documents[0], ImageNode)
    assert documents[0].embedding == [0.1, 0.2, 0.3]
    assert documents[0].metadata["content_type"] == "image"
    assert documents[0].metadata["image_description"] == "A logo image with visible HKU text."
    assert "A logo image with visible HKU text." in documents[0].text
    assert captured["contents"][0]["image"].startswith("data:image/png;base64,")
    assert captured["llm_kwargs"]["image_mime_type"] == "image/png"


def test_loader_skips_images_when_llm_is_text_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n")

    class _MultimodalEmbeddingClient:
        config = type("Config", (), {"binding": "siliconflow", "model": "qwen3-vl"})()

        def supports_multimodal_contents(self) -> bool:
            return True

    class _TextOnlyLLMClient:
        config = type("Config", (), {"binding": "openai", "model": "gpt-3.5-turbo"})()

        def supports_multimodal_images(self) -> bool:
            return False

    monkeypatch.setattr(loader_module, "get_embedding_client", lambda: _MultimodalEmbeddingClient())
    monkeypatch.setattr(loader_module, "get_llm_client", lambda: _TextOnlyLLMClient())

    documents = asyncio.run(loader_module.LlamaIndexDocumentLoader().load([str(image_path)]))

    assert documents == []


def test_loader_logs_all_missing_multimodal_image_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n")

    class _TextOnlyEmbeddingClient:
        config = type("Config", (), {"binding": "openai", "model": "text-embedding-3-small"})()

        def supports_multimodal_contents(self) -> bool:
            return False

    class _TextOnlyLLMClient:
        config = type("Config", (), {"binding": "openai", "model": "gpt-3.5-turbo"})()

        def supports_multimodal_images(self) -> bool:
            return False

    monkeypatch.setattr(loader_module, "get_embedding_client", lambda: _TextOnlyEmbeddingClient())
    monkeypatch.setattr(loader_module, "get_llm_client", lambda: _TextOnlyLLMClient())

    with caplog.at_level("WARNING"):
        documents = asyncio.run(loader_module.LlamaIndexDocumentLoader().load([str(image_path)]))

    assert documents == []
    assert "requires both multimodal embedding and multimodal LLM support" in caplog.text
    assert "embedding provider/model does not support multimodal contents" in caplog.text
    assert "LLM provider/model does not support multimodal image input" in caplog.text
    assert "text-embedding-3-small" in caplog.text
    assert "gpt-3.5-turbo" in caplog.text
