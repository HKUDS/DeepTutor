"""Tests for FileTypeRouter classification and helper methods."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.rag.file_routing import (
    DocumentType,
    FileTypeRouter,
)


class TestExtensionClassification:
    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("doc.pdf", DocumentType.PDF),
            ("DOC.PDF", DocumentType.PDF),  # case-insensitive
            ("notes.md", DocumentType.TEXT),
            ("readme.MARKDOWN", DocumentType.TEXT),
            ("data.json", DocumentType.TEXT),
            ("script.py", DocumentType.TEXT),
            ("config.yaml", DocumentType.TEXT),
            ("paper.docx", DocumentType.DOCX),
            ("sheet.xlsx", DocumentType.SPREADSHEET),
            ("deck.pptx", DocumentType.PRESENTATION),
            ("photo.png", DocumentType.IMAGE),
        ],
    )
    def test_known_extensions(self, filename: str, expected: DocumentType) -> None:
        assert FileTypeRouter.get_document_type(filename) == expected


class TestUnknownExtensionFallback:
    def test_unknown_extension_with_text_content_is_text(self, tmp_path: Path) -> None:
        path = tmp_path / "data.weirdext"
        path.write_text("hello world", encoding="utf-8")
        assert FileTypeRouter.get_document_type(str(path)) == DocumentType.TEXT

    def test_unknown_extension_with_binary_content_is_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "blob.bin"
        path.write_bytes(b"\x00\x01\x02\xff")
        assert FileTypeRouter.get_document_type(str(path)) == DocumentType.UNKNOWN


class TestClassifyFiles:
    def test_routes_pdf_to_parser_text_to_text(self, tmp_path: Path) -> None:
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        docx = tmp_path / "a.docx"
        docx.write_bytes(b"PK\x03\x04")
        xlsx = tmp_path / "a.xlsx"
        xlsx.write_bytes(b"PK\x03\x04")
        pptx = tmp_path / "a.pptx"
        pptx.write_bytes(b"PK\x03\x04")
        txt = tmp_path / "a.txt"
        txt.write_text("hi")
        png = tmp_path / "a.png"
        png.write_bytes(b"\x89PNG\r\n")

        cls = FileTypeRouter.classify_files(
            [str(pdf), str(docx), str(xlsx), str(pptx), str(txt), str(png)]
        )
        assert cls.parser_files == [str(pdf), str(docx), str(xlsx), str(pptx)]
        assert cls.text_files == [str(txt)]
        assert cls.image_files == [str(png)]
        assert cls.unsupported == []

    def test_empty_input_yields_empty_groups(self) -> None:
        cls = FileTypeRouter.classify_files([])
        assert cls.parser_files == []
        assert cls.text_files == []
        assert cls.image_files == []
        assert cls.unsupported == []


class TestSupportedExtensionsAndGlobs:
    def test_get_supported_extensions_covers_pdf_and_text(self) -> None:
        exts = FileTypeRouter.get_supported_extensions()
        assert ".pdf" in exts
        assert ".docx" in exts
        assert ".xlsx" in exts
        assert ".pptx" in exts
        assert ".md" in exts
        assert ".txt" in exts
        assert ".png" in exts

    def test_glob_patterns_match_supported_extensions(self) -> None:
        exts = FileTypeRouter.get_supported_extensions()
        patterns = FileTypeRouter.get_glob_patterns()
        assert {f"*{ext}" for ext in exts} == set(patterns)
        # Glob output should be deterministic / sorted
        assert patterns == sorted(patterns)

    def test_collect_supported_files_is_case_insensitive(self, tmp_path: Path) -> None:
        lower = tmp_path / "notes.md"
        lower.write_text("notes", encoding="utf-8")
        upper = tmp_path / "REPORT.PDF"
        upper.write_bytes(b"%PDF-1.4")
        nested = tmp_path / "nested"
        nested.mkdir()
        nested_upper = nested / "README.MD"
        nested_upper.write_text("nested", encoding="utf-8")
        deck = tmp_path / "DECK.PPTX"
        deck.write_bytes(b"PK\x03\x04")
        image = tmp_path / "image.PNG"
        image.write_bytes(b"\x89PNG\r\n")

        assert [path.name for path in FileTypeRouter.collect_supported_files(tmp_path)] == [
            "DECK.PPTX",
            "image.PNG",
            "notes.md",
            "REPORT.PDF",
        ]
        assert [
            path.name for path in FileTypeRouter.collect_supported_files(tmp_path, recursive=True)
        ] == ["DECK.PPTX", "image.PNG", "README.MD", "notes.md", "REPORT.PDF"]


class TestQuickHelpers:
    def test_needs_parser_for_pdf(self) -> None:
        assert FileTypeRouter.needs_parser("paper.pdf") is True

    def test_needs_parser_for_office_documents(self) -> None:
        assert FileTypeRouter.needs_parser("paper.docx") is True
        assert FileTypeRouter.needs_parser("sheet.xlsx") is True
        assert FileTypeRouter.needs_parser("deck.pptx") is True

    def test_needs_parser_false_for_text(self) -> None:
        assert FileTypeRouter.needs_parser("notes.md") is False

    def test_is_text_readable_for_text(self) -> None:
        assert FileTypeRouter.is_text_readable("readme.md") is True

    def test_is_text_readable_false_for_pdf(self) -> None:
        assert FileTypeRouter.is_text_readable("doc.pdf") is False


class TestReadTextFile:
    def test_reads_utf8(self, tmp_path: Path) -> None:
        path = tmp_path / "u.txt"
        path.write_text("héllo", encoding="utf-8")
        content = asyncio.run(FileTypeRouter.read_text_file(str(path)))
        assert content == "héllo"

    def test_reads_gbk_fallback(self, tmp_path: Path) -> None:
        path = tmp_path / "g.txt"
        path.write_bytes("中文测试".encode("gbk"))
        content = asyncio.run(FileTypeRouter.read_text_file(str(path)))
        assert "中文" in content
