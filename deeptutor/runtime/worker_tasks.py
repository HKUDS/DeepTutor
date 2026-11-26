"""Fixed, importable tasks executed through :mod:`isolated_worker`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.reading.models import MaterialManifest


def extract_document_text(
    source_path: str,
    *,
    filename_hint: str | None = None,
    max_bytes: int | None,
    max_chars: int | None,
) -> str:
    from deeptutor.utils.document_extractor import extract_text_from_path

    return extract_text_from_path(
        source_path,
        filename_hint=filename_hint,
        max_bytes=max_bytes,
        max_chars=max_chars,
    )


def extract_document_to_markdown(
    source_path: str,
    output_path: str,
    *,
    max_bytes: int | None,
    max_chars: int | None,
) -> None:
    source = Path(source_path)
    text = extract_document_text(
        source_path,
        max_bytes=max_bytes,
        max_chars=max_chars,
    )
    if source.suffix.lower() == ".bib":
        from deeptutor.utils.bibtex_converter import bibtex_to_markdown

        text = bibtex_to_markdown(text, source.stem)
    Path(output_path).write_text(text, encoding="utf-8")


def ingest_reading_material(
    source_path: str, *, root: str, filename: str | None = None
) -> MaterialManifest:
    """Extract and persist a document in the explicitly selected workspace."""
    from deeptutor.reading.store import ReadingStore

    return ReadingStore(root).ingest(source_path, filename=filename)


def test_allocate_bytes(size: int) -> int:
    """Small deterministic task used by the parent-memory regression test."""

    payload = bytearray(size)
    for offset in range(0, size, 4096):
        payload[offset] = 1
    if payload:
        payload[-1] = 1
    return len(payload)


__all__ = ["extract_document_text", "extract_document_to_markdown", "ingest_reading_material"]
