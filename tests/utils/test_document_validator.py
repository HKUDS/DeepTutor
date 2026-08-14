from __future__ import annotations

from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.utils.document_validator import DocumentValidator


def test_validate_upload_safety_preserves_unicode_and_lowercases_extension() -> None:
    """Preserve Unicode names while normalizing an uppercase extension."""
    safe_name = DocumentValidator.validate_upload_safety(
        "中文资料/数学 讲义#1(最终版).PDF",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "数学 讲义#1(最终版).pdf"


def test_validate_upload_safety_strips_windows_path_components() -> None:
    """Remove Windows path components before applying the filename policy."""
    safe_name = DocumentValidator.validate_upload_safety(
        r"C:\Users\frank\资料\报告.MD",
        128,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "报告.md"


def test_validate_upload_safety_accepts_chat_office_formats_for_kb_policy() -> None:
    """Allow office extensions included by the knowledge-base policy."""
    safe_name = DocumentValidator.validate_upload_safety(
        "Lecture Notes.DOCX",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "Lecture Notes.docx"


def test_validate_upload_safety_custom_policy_allows_supported_code_mimes() -> None:
    """Allow code extensions even when their MIME type is outside the default policy."""
    safe_name = DocumentValidator.validate_upload_safety(
        "solver.PY",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "solver.py"


def test_validate_upload_safety_custom_policy_allows_images() -> None:
    """Allow image extensions included by the knowledge-base policy."""
    safe_name = DocumentValidator.validate_upload_safety(
        "diagram.PNG",
        1024,
        allowed_extensions=FileTypeRouter.get_supported_extensions(),
    )

    assert safe_name == "diagram.png"


def test_validate_upload_safety_strips_edge_whitespace_around_filename() -> None:
    """Ignore surrounding whitespace when validating the filename extension."""
    safe_name = DocumentValidator.validate_upload_safety("  notes.PDF  ", 1024)
    assert safe_name == "notes.pdf"
