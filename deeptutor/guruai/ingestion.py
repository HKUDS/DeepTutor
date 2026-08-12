"""Page-aware PDF ingestion primitives for GuruAI's local MVP.

This intentionally produces a transparent JSONL manifest first. The existing
DeepTutor KB pipeline can consume these records in the next adapter step while
we preserve exact PDF page provenance for citations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import fitz


def extract_pdf_pages(raw: bytes, filename: str) -> list[dict[str, Any]]:
    """Extract text one PDF page at a time; never lose the source page number."""
    digest = hashlib.sha256(raw).hexdigest()[:16]
    doc = fitz.open(stream=raw, filetype="pdf")
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(doc):
        text = page.get_text("text").strip()
        if not text:
            text = "[SCANNED_PAGE_REQUIRES_VISION_OCR]"
        pages.append(
            {
                "source_id": f"{digest}-p{index + 1}",
                "filename": filename,
                "pdf_page": index + 1,
                "book": Path(filename).stem,
                "text": text,
                "citation": {"book": Path(filename).stem, "page": index + 1},
            }
        )
    return pages


def write_manifest(pages: list[dict[str, Any]], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(page, ensure_ascii=False) for page in pages) + "\n",
        encoding="utf-8",
    )
    return output


def validate_citations(answer: dict[str, Any], source_ids: set[str]) -> dict[str, Any]:
    """Remove model citations that are not backed by retrieved source ids."""
    allowed: list[dict[str, Any]] = []
    for citation in answer.get("sources", []):
        if citation.get("source_id") in source_ids:
            allowed.append(citation)
    answer["sources"] = allowed
    for step in answer.get("steps", []):
        citation = step.get("citation")
        if citation and citation.get("source_id") not in source_ids:
            step["citation"] = None
    return answer
