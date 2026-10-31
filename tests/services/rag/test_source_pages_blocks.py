"""MinerU block routing: bibliography lists count as content, page furniture does not."""

from pathlib import Path

import pymupdf

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.source_pages import build_pdf_documents


def _write_pdf(path: Path, pages: int = 2) -> None:
    """Write a minimal text-layer PDF with ``pages`` pages."""
    document = pymupdf.open()
    try:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"native page {index + 1} text")
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(path))
    finally:
        document.close()


def _documents(tmp_path: Path, blocks: list[dict]) -> list:
    kb_dir = tmp_path / "kb"
    pdf_path = kb_dir / "raw" / "paper.pdf"
    _write_pdf(pdf_path)
    parsed = ParsedDocument(
        markdown="",
        blocks=blocks,
        engine="mineru",
        parser_signature="test-signature",
    )
    return build_pdf_documents(pdf_path, parsed, kb_dir)


def _page_text(documents: list, page_index: int) -> str:
    return next(
        document.text for document in documents if document.metadata.get("page_index") == page_index
    )


def test_reference_list_blocks_reach_the_indexed_page(tmp_path: Path) -> None:
    """MinerU keeps a bibliography in ``list_items``; it must not be dropped."""
    documents = _documents(
        tmp_path,
        [
            {"type": "text", "text": "Body paragraph.", "page_idx": 0},
            {
                "type": "list",
                "sub_type": "ref_text",
                "list_items": [
                    "[2] Dzmitry Bahdanau, Kyunghyun Cho, and Yoshua Bengio. "
                    "Neural machine translation by jointly learning to align "
                    "and translate. CoRR, abs/1409.0473, 2014."
                ],
                "page_idx": 1,
            },
        ],
    )

    assert "Body paragraph." in _page_text(documents, 0)
    last_page = _page_text(documents, 1)
    assert "Bahdanau" in last_page
    assert "Neural machine translation" in last_page


def test_page_numbers_and_footers_are_not_indexed(tmp_path: Path) -> None:
    """Page furniture must not become its own chunk."""
    documents = _documents(
        tmp_path,
        [
            {"type": "text", "text": "Real content.", "page_idx": 0},
            {"type": "page_number", "text": "11", "page_idx": 0},
            {"type": "footer", "text": "Preprint. Under review.", "page_idx": 0},
            {"type": "header", "text": "Running title block", "page_idx": 0},
            {"type": "page_header", "text": "v2 running title", "page_idx": 0},
        ],
    )

    page_text = _page_text(documents, 0)
    assert "Real content." in page_text
    assert "Preprint" not in page_text
    assert "Running title block" not in page_text
    assert "v2 running title" not in page_text
    # The native fallback says "native page 1 text"; a bare 11 would mean the
    # furniture block leaked in.
    assert "11" not in page_text.split()
