from __future__ import annotations

import mimetypes

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


def test_validate_upload_safety_default_policy_allows_epub() -> None:
    safe_name = DocumentValidator.validate_upload_safety("novel.epub", 1024)

    assert safe_name == "novel.epub"
    assert ".epub" in DocumentValidator.ALLOWED_EXTENSIONS
    assert "application/epub+zip" in DocumentValidator.ALLOWED_MIME_TYPES
    guessed, _ = mimetypes.guess_type("novel.epub")
    assert guessed is None or guessed in DocumentValidator.ALLOWED_MIME_TYPES
