"""Local GuruAI endpoints for page-aware syllabus and past-paper uploads."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from deeptutor.guruai.ingestion import extract_pdf_pages, write_manifest

router = APIRouter()
MAX_PDF_BYTES = 25 * 1024 * 1024
MANIFEST_DIR = Path("data/user/guruai/sources")


@router.post("/sources/preview")
async def preview_source(file: UploadFile = File(...)):
    """Return page-aware text for confirmation before indexing."""
    if file.content_type != "application/pdf":
        raise HTTPException(415, "GuruAI currently accepts PDF files only")
    raw = await file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF is larger than the 25 MB local prototype limit")
    pages = extract_pdf_pages(raw, file.filename or "uploaded.pdf")
    return {
        "filename": file.filename,
        "page_count": len(pages),
        "ocr_required_pages": [p["pdf_page"] for p in pages if "SCANNED_PAGE" in p["text"]],
        "pages": pages[:5],
    }


@router.post("/sources/ingest")
async def ingest_source(file: UploadFile = File(...), source_type: str = "syllabus"):
    """Persist a transparent JSONL manifest; the next adapter indexes it in the KB."""
    if file.content_type != "application/pdf":
        raise HTTPException(415, "GuruAI currently accepts PDF files only")
    raw = await file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF is larger than the 25 MB local prototype limit")
    pages = extract_pdf_pages(raw, file.filename or "uploaded.pdf")
    for page in pages:
        page["source_type"] = source_type
    safe_name = Path(file.filename or "uploaded.pdf").stem.replace(" ", "_")
    manifest = write_manifest(pages, MANIFEST_DIR / f"{safe_name}.jsonl")
    return {
        "status": "ready_for_indexing",
        "filename": file.filename,
        "source_type": source_type,
        "page_count": len(pages),
        "manifest": str(manifest),
        "citations": [p["citation"] for p in pages[:3]],
    }
