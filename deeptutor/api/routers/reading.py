"""Immersive reading API — materials, unit text, annotations, export.

A thin adapter over :mod:`deeptutor.reading`: it validates HTTP inputs, maps
engine errors to status codes, and streams bytes. No reading logic lives here,
so the router and the capability's tools cannot drift apart — both call the same
service functions.

Per-user isolation comes from the path service, exactly as for notebooks: the
store resolves ``<user workspace>/reading`` at call time, so a request already
scoped to a user by the auth dependency reaches only that user's materials.

The raw-file route returns a ``FileResponse``, which serves HTTP Range requests.
That matters: it is what lets pdf.js load a large PDF incrementally instead of
pulling the whole file before rendering page one.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from deeptutor.reading import (
    ANNOTATION_COLORS,
    Annotation,
    MaterialNotFound,
    ReadingError,
    ReadingStore,
    export_material,
    render_outline,
)
from deeptutor.utils.document_validator import DocumentValidator

logger = logging.getLogger(__name__)

router = APIRouter()

# Streaming upload ceiling. Same number the extractor enforces, so a file that
# passes here cannot then be rejected deeper in with a less helpful message.
MAX_MATERIAL_BYTES = DocumentValidator.MAX_FILE_SIZE
_UPLOAD_CHUNK = 1024 * 1024


def _store() -> ReadingStore:
    return ReadingStore()


def _http_error(exc: Exception) -> HTTPException:
    """Map an engine error to the status code that describes it.

    404 for "no such material", 400 for everything the caller can fix (bad
    locator, unsupported format, no extractable text). A 500 is reserved for
    failures that are genuinely ours.
    """
    if isinstance(exc, MaterialNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ReadingError):
        return HTTPException(status_code=400, detail=str(exc))
    logger.warning("unexpected reading error", exc_info=True)
    return HTTPException(status_code=500, detail="The reader could not complete that request.")


# === Models ===================================================================


class MaterialInfo(BaseModel):
    material_id: str
    filename: str
    unit: str
    unit_count: int
    mime: str = ""
    title: str = ""
    byte_size: int = 0
    char_count: int = 0
    created_at: float = 0.0
    has_raw_view: bool = False
    annotation_count: int = 0


class MaterialDetail(MaterialInfo):
    outline: list[dict[str, Any]] = Field(default_factory=list)
    outline_text: str = ""


class UnitText(BaseModel):
    locator: int
    unit: str
    text: str


class AnnotationPayload(BaseModel):
    """An annotation as the reader sends it.

    ``rects`` are normalised to the unit box (0..1, origin top-left) by the
    client, because only the client knows the rendered geometry. They are still
    re-validated server-side — an inverted or out-of-range rectangle is ordered
    and clipped rather than trusted.
    """

    annotation_id: str = ""
    locator: int = Field(ge=1)
    kind: Literal["highlight", "underline", "note"] = "highlight"
    color: str = "yellow"
    quote: str = ""
    note: str = ""
    rects: list[list[float]] = Field(default_factory=list)

    def to_annotation(self) -> Annotation:
        return Annotation.from_dict(
            {
                "annotation_id": self.annotation_id,
                "locator": self.locator,
                "kind": self.kind,
                "color": self.color if self.color in ANNOTATION_COLORS else "yellow",
                "quote": self.quote,
                "note": self.note,
                "rects": self.rects,
                "author": "user",
            }
        )


class AnnotationInfo(BaseModel):
    annotation_id: str
    locator: int
    kind: str
    color: str
    quote: str
    note: str
    rects: list[list[float]]
    author: str
    created_at: float
    updated_at: float


class SupportedFormats(BaseModel):
    extensions: list[str]
    max_bytes: int
    raw_view_extensions: list[str]


# === Routes ===================================================================


@router.get("/supported-formats", response_model=SupportedFormats)
async def supported_formats() -> SupportedFormats:
    """What the reader accepts — the single source of truth for the file picker."""
    from deeptutor.reading.extract import RAW_VIEW_EXTENSIONS
    from deeptutor.utils.document_extractor import SUPPORTED_DOC_EXTENSIONS

    return SupportedFormats(
        extensions=sorted(SUPPORTED_DOC_EXTENSIONS),
        max_bytes=MAX_MATERIAL_BYTES,
        raw_view_extensions=sorted(RAW_VIEW_EXTENSIONS),
    )


@router.get("/materials", response_model=list[MaterialInfo])
async def list_materials() -> list[MaterialInfo]:
    store = _store()
    try:
        return [_info(store, manifest) for manifest in store.list_materials()]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials", response_model=MaterialDetail)
async def upload_material(file: UploadFile = File(...)) -> MaterialDetail:  # noqa: B008
    """Ingest an uploaded document and return it ready to read.

    The upload is streamed to a temp file with a running size check, so an
    oversized file is rejected before it is fully buffered rather than after.
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="The upload has no filename.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="dt-reading-"))
    tmp_path = tmp_dir / Path(filename).name
    written = 0
    try:
        with tmp_path.open("wb") as sink:
            while chunk := await file.read(_UPLOAD_CHUNK):
                written += len(chunk)
                if written > MAX_MATERIAL_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"{filename} exceeds the "
                            f"{MAX_MATERIAL_BYTES // (1024 * 1024)} MB limit."
                        ),
                    )
                sink.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail=f"{filename} is empty.")

        store = _store()
        manifest = store.ingest(tmp_path, filename=filename)
        return _detail(store, manifest)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/materials/{material_id}", response_model=MaterialDetail)
async def get_material(material_id: str) -> MaterialDetail:
    store = _store()
    try:
        return _detail(store, store.manifest(material_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str) -> dict[str, Any]:
    store = _store()
    try:
        removed = store.delete(material_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"material {material_id!r} not found")
    return {"status": "ok", "material_id": material_id}


@router.get("/materials/{material_id}/units/{locator}", response_model=UnitText)
async def get_unit(material_id: str, locator: int) -> UnitText:
    """One unit's text — the reader's text view, and the only view for non-PDFs."""
    store = _store()
    try:
        manifest = store.manifest(material_id)
        return UnitText(
            locator=locator,
            unit=manifest.unit,
            text=store.unit_text(material_id, locator),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/raw")
async def get_raw(material_id: str) -> FileResponse:
    """The original bytes, for the faithful viewer. Serves Range requests."""
    store = _store()
    try:
        manifest = store.manifest(material_id)
        path = store.raw_path(material_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"{manifest.filename} has no stored original to render.",
        )
    return FileResponse(
        path,
        media_type=manifest.mime or "application/octet-stream",
        filename=manifest.filename,
        content_disposition_type="inline",
    )


@router.get("/materials/{material_id}/annotations", response_model=list[AnnotationInfo])
async def list_annotations(material_id: str) -> list[AnnotationInfo]:
    store = _store()
    try:
        return [_annotation_info(row) for row in store.annotations(material_id)]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/materials/{material_id}/annotations", response_model=AnnotationInfo)
async def save_annotation(material_id: str, payload: AnnotationPayload) -> AnnotationInfo:
    """Create or update one annotation (id absent = create)."""
    store = _store()
    try:
        saved = store.save_annotation(material_id, payload.to_annotation())
    except Exception as exc:
        raise _http_error(exc) from exc
    return _annotation_info(saved)


@router.delete("/materials/{material_id}/annotations/{annotation_id}")
async def delete_annotation(material_id: str, annotation_id: str) -> dict[str, Any]:
    store = _store()
    try:
        removed = store.delete_annotation(material_id, annotation_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="annotation not found")
    return {"status": "ok", "annotation_id": annotation_id}


@router.get("/materials/{material_id}/export")
async def export(
    material_id: str,
    fmt: Literal["auto", "pdf", "markdown"] = Query("auto"),
) -> Response:
    """Download the material with its annotations applied.

    ``pdf`` writes real PDF annotations into a copy of the original, so the
    export keeps working outside DeepTutor; ``markdown`` returns the marks as
    text, which is what every non-PDF format gets.
    """
    store = _store()
    try:
        result = export_material(store, material_id, fmt=fmt)
    except Exception as exc:
        raise _http_error(exc) from exc
    return Response(
        content=result.data,
        media_type=result.media_type,
        headers={
            "Content-Disposition": _attachment_header(result.filename),
            "Content-Length": str(result.byte_size),
        },
    )


# === Helpers ==================================================================


def _info(store: ReadingStore, manifest: Any) -> MaterialInfo:
    return MaterialInfo(
        **manifest.to_dict() | {"annotation_count": len(store.annotations(manifest.material_id))}
    )


def _detail(store: ReadingStore, manifest: Any) -> MaterialDetail:
    outline = store.outline(manifest.material_id)
    return MaterialDetail(
        **manifest.to_dict()
        | {
            "annotation_count": len(store.annotations(manifest.material_id)),
            "outline": [entry.to_dict() for entry in outline],
            "outline_text": render_outline(store, manifest.material_id),
        }
    )


def _annotation_info(row: Annotation) -> AnnotationInfo:
    return AnnotationInfo(**row.to_dict())


def _attachment_header(filename: str) -> str:
    """RFC 5987 disposition so non-ASCII names survive the round trip."""
    from urllib.parse import quote

    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "export"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


__all__ = ["MAX_MATERIAL_BYTES", "router"]
