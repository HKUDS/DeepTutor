from __future__ import annotations

import mimetypes

import pytest

from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.utils.document_validator import DocumentValidator


def test_validate_upload_safety_preserves_unicode_and_lowercases_extension() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "中文资料/数学 讲义#1(最终版).PDF",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "数学 讲义#1(最终版).pdf"


def test_validate_upload_safety_strips_windows_path_components() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        r"C:\Users\frank\资料\报告.MD",
        128,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "报告.md"


def test_validate_upload_safety_accepts_chat_office_formats_for_kb_policy() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "Lecture Notes.DOCX",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "Lecture Notes.docx"


def test_validate_upload_safety_custom_policy_allows_supported_code_mimes() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "solver.PY",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "solver.py"


def test_validate_upload_safety_custom_policy_allows_images() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "diagram.PNG",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "diagram.png"


def test_validate_upload_safety_kb_policy_allows_epub() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "Textbook.EPUB",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "Textbook.epub"


def test_validate_upload_safety_preserves_compound_docling_extension() -> None:
    safe_name = DocumentValidator.validate_upload_safety(
        "METS Export.TAR.GZ",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "METS Export.tar.gz"


def test_validate_upload_safety_default_policy_allows_epub() -> None:
    safe_name = DocumentValidator.validate_upload_safety("novel.epub", 1024)

    assert safe_name == "novel.epub"
    assert ".epub" in DocumentValidator.ALLOWED_EXTENSIONS
    assert "application/epub+zip" in DocumentValidator.ALLOWED_MIME_TYPES
    guessed, _ = mimetypes.guess_type("novel.epub")
    assert guessed is None or guessed in DocumentValidator.ALLOWED_MIME_TYPES


def test_validate_upload_safety_empty_policy_delegates_extension_detection() -> None:
    assert (
        DocumentValidator.validate_upload_safety(
            "vendor/Document.CUSTOM-BINARY", 1024, allowed_extensions=set()
        )
        == "Document.custom-binary"
    )
    assert (
        DocumentValidator.validate_upload_safety("extensionless", 1024, allowed_extensions=set())
        == "extensionless"
    )
    with pytest.raises(ValueError, match="Invalid filename"):
        DocumentValidator.validate_upload_safety(".hidden", 1024, allowed_extensions=set())


def test_mdx_is_a_supported_text_extension() -> None:
    """MDX docs must pass the same gates as .md (GitHub source sync, #2552).

    The registry behind upload/sync/reindex silently dropped .mdx, so a
    GitHub source with ``glob: *.mdx`` synced 0 files while reporting
    success, and a later re-index died with ``KB has no source files``.
    """
    from deeptutor.utils.file_types import DocumentType, FileTypeRouter

    assert ".mdx" in FileTypeRouter.get_supported_extensions()

    path = "docs/Guide.mdx"
    assert FileTypeRouter.has_supported_extension(path)
    assert FileTypeRouter.get_document_type(path) is DocumentType.TEXT
    assert FileTypeRouter.is_text_readable(path)
    assert not FileTypeRouter.needs_parser(path)

    classification = FileTypeRouter.classify_files([path])
    assert classification.text_files == [path]
    assert classification.unsupported == []


def test_mdx_and_md_suffixes_resolve_without_collision() -> None:
    """Compound-suffix matching must pick the longest suffix, so .mdx never
    degrades into a bare .md lookup (which would still work, but only by
    accident of suffix order)."""
    from deeptutor.utils.file_types import FileTypeRouter

    assert FileTypeRouter.get_extension("notes.mdx") == ".mdx"
    assert FileTypeRouter.get_extension("notes.md") == ".md"
    assert FileTypeRouter.get_extension("notes.MDX") == ".mdx"
