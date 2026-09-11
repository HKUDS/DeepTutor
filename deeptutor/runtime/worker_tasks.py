"""Fixed, importable tasks executed through :mod:`isolated_worker`."""

from __future__ import annotations

from pathlib import Path


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
    text = extract_document_text(
        source_path,
        max_bytes=max_bytes,
        max_chars=max_chars,
    )
    Path(output_path).write_text(text, encoding="utf-8")


def test_allocate_bytes(size: int) -> int:
    """Small deterministic task used by the parent-memory regression test."""

    payload = bytearray(size)
    for offset in range(0, size, 4096):
        payload[offset] = 1
    if payload:
        payload[-1] = 1
    return len(payload)


__all__ = ["extract_document_text", "extract_document_to_markdown"]
