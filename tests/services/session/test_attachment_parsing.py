from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config.runtime_settings import ChatAttachmentLimits
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.session.attachment_parsing import parse_chat_pdf_attachments
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


@pytest.mark.asyncio
async def test_non_pdf_batch_does_not_read_parser_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_chat_attachment_limits",
        lambda: (_ for _ in ()).throw(AssertionError("settings should not be read")),
    )
    records, contexts = await parse_chat_pdf_attachments(
        [{"id": "txt", "filename": "notes.txt", "extracted_text": "hello"}],
        attachment_store=LocalDiskAttachmentStore(root=tmp_path / "attachments"),
        session_id="session",
        document_texts=["[File: notes.txt]\nhello"],
    )

    assert records[0]["extracted_text"] == "hello"
    assert contexts == ["[File: notes.txt]\nhello"]


@pytest.mark.asyncio
async def test_chat_pdf_always_uses_configured_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    await store.put(session_id="session", attachment_id="pdf", filename="notes.pdf", data=b"pdf")

    class Parser:
        def parse(self, path: Path, **_: object) -> ParsedDocument:
            assert path.name == "pdf_notes.pdf"
            return ParsedDocument(markdown="# Parsed layout\n\n![figure](image.png)")

    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_parse_service", lambda: Parser()
    )
    records, contexts = await parse_chat_pdf_attachments(
        [
            {
                "id": "pdf",
                "filename": "notes.pdf",
                "extracted_text": "native text",
                "extracted_chars": 11,
            }
        ],
        attachment_store=store,
        session_id="session",
        document_texts=["[File: notes.pdf]\nnative text"],
    )

    assert records[0]["extracted_text"] == "# Parsed layout\n\n![figure](image.png)"
    assert contexts == ["[File: notes.pdf]\n# Parsed layout\n\n![figure](image.png)"]


@pytest.mark.asyncio
async def test_configured_parser_keeps_native_image_page_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    await store.put(session_id="session", attachment_id="pdf", filename="notes.pdf", data=b"pdf")

    class Parser:
        def parse(self, path: Path, **_: object) -> ParsedDocument:
            return ParsedDocument(markdown="# Parsed layout")

    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_parse_service", lambda: Parser()
    )
    native = (
        "--- Page 1 ---\nNative text\n[图片 1: image-01.png]"
        "\n\n--- Page 2 ---\nMore text\n[图片 1: image-01.png]"
    )
    records, contexts = await parse_chat_pdf_attachments(
        [{"id": "pdf", "filename": "notes.pdf", "extracted_text": native}],
        attachment_store=store,
        session_id="session",
        document_texts=[f"[File: notes.pdf]\n{native}"],
    )

    extracted = records[0]["extracted_text"]
    assert extracted.startswith("# Parsed layout")
    assert "--- Page 1 ---\n[图片 1: image-01.png]" in extracted
    assert "--- Page 2 ---\n[图片 1: image-01.png]" in extracted
    assert contexts == [f"[File: notes.pdf]\n{extracted}"]


@pytest.mark.asyncio
async def test_image_page_markers_survive_parser_text_quota(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    await store.put(session_id="session", attachment_id="pdf", filename="notes.pdf", data=b"pdf")

    class Parser:
        def parse(self, path: Path, **_: object) -> ParsedDocument:
            return ParsedDocument(markdown="P" * 500)

    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_parse_service", lambda: Parser()
    )
    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_chat_attachment_limits",
        lambda: ChatAttachmentLimits(1000, 1000, 120, 120),
    )
    records, contexts = await parse_chat_pdf_attachments(
        [
            {
                "id": "pdf",
                "filename": "notes.pdf",
                "extracted_text": "--- Page 1 ---\n[图片 1: image-01.png]",
            }
        ],
        attachment_store=store,
        session_id="session",
        document_texts=[],
    )

    extracted = records[0]["extracted_text"]
    assert len(extracted) == records[0]["extracted_chars"] == 120
    assert extracted.endswith("--- Page 1 ---\n[图片 1: image-01.png]")
    assert contexts == [f"[File: notes.pdf]\n{extracted}"]


@pytest.mark.asyncio
async def test_scan_pdf_uses_parser_and_reports_structured_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    await store.put(session_id="session", attachment_id="scan", filename="scan.pdf", data=b"image")
    progress: list[tuple[str, str, str]] = []

    class Parser:
        def parse(self, path: Path, *, on_output=None) -> ParsedDocument:
            assert path.name == "scan_scan.pdf"
            if on_output:
                on_output("MinerU page 1/1")
            return ParsedDocument(markdown="![page](page-1.png)")

    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_parse_service", lambda: Parser()
    )
    records, contexts = await parse_chat_pdf_attachments(
        [{"id": "scan", "filename": "scan.pdf", "extracted_text": "", "extracted_chars": 0}],
        attachment_store=store,
        session_id="session",
        document_texts=[],
        on_progress=lambda aid, phase, detail: progress.append((aid, phase, detail)),
    )

    assert records[0]["extracted_text"] == "![page](page-1.png)"
    assert contexts == ["[File: scan.pdf]\n![page](page-1.png)"]
    assert [phase for _, phase, _ in progress] == [
        "submitting",
        "parsing",
        "retrieving",
        "completed",
    ]


@pytest.mark.asyncio
async def test_parser_failure_is_not_reported_as_empty_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    await store.put(session_id="session", attachment_id="bad", filename="bad.pdf", data=b"pdf")

    class Parser:
        def parse(self, path: Path, **_: object) -> ParsedDocument:
            raise RuntimeError("parser unavailable")

    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_parse_service", lambda: Parser()
    )
    records, contexts = await parse_chat_pdf_attachments(
        [{"id": "bad", "filename": "bad.pdf"}],
        attachment_store=store,
        session_id="session",
        document_texts=[],
    )

    assert records[0]["extracted_text"] == ""
    assert "parser unavailable" in records[0]["extraction_error"]
    assert "could not be read" in contexts[0]


@pytest.mark.asyncio
async def test_parser_failure_preserves_usable_native_pdf_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    await store.put(session_id="session", attachment_id="pdf", filename="notes.pdf", data=b"pdf")
    progress: list[str] = []

    class Parser:
        def parse(self, path: Path, **_: object) -> ParsedDocument:
            raise RuntimeError("configured parser offline")

    monkeypatch.setattr(
        "deeptutor.services.session.attachment_parsing.get_parse_service", lambda: Parser()
    )
    records, contexts = await parse_chat_pdf_attachments(
        [
            {
                "id": "pdf",
                "filename": "notes.pdf",
                "extracted_text": "native text",
                "extracted_chars": 11,
            }
        ],
        attachment_store=store,
        session_id="session",
        document_texts=["[File: notes.pdf]\nnative text"],
        on_progress=lambda _aid, phase, _detail: progress.append(phase),
    )

    assert records[0]["extracted_text"] == "native text"
    assert "configured parser offline" in records[0]["parser_error"]
    assert "extraction_error" not in records[0]
    assert contexts == ["[File: notes.pdf]\nnative text"]
    assert progress == ["submitting", "fallback"]
