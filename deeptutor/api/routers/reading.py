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

import asyncio
from dataclasses import replace as dataclass_replace
from datetime import datetime
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal
from urllib.parse import urldefrag, urlparse, urlunparse

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator

from deeptutor.multi_user.learning_access import (
    assert_learning_material,
    current_learning_policy,
)
from deeptutor.reading import (
    ANNOTATION_COLORS,
    Annotation,
    BilingualGroup,
    FileSourceAdapter,
    MaterialNotFound,
    OutlineEntry,
    ReadingError,
    ReadingPosition,
    ReadingSourcePayload,
    ReadingStore,
    ReadingUpgradeConflict,
    export_material,
    localize_snapshot_images,
    markdown_payload,
    normalize_snapshot_links,
    render_outline,
    sanitize_snapshot_markdown,
)
from deeptutor.utils.document_validator import DocumentValidator

logger = logging.getLogger(__name__)

router = APIRouter()

# Streaming upload ceiling. Same number the extractor enforces, so a file that
# passes here cannot then be rejected deeper in with a less helpful message.
MAX_MATERIAL_BYTES = DocumentValidator.MAX_FILE_SIZE
_UPLOAD_CHUNK = 1024 * 1024


def _store() -> ReadingStore:
    # Resolve the authenticated workspace explicitly. ReadingStore's default
    # remains useful for CLI/engine callers, but HTTP must never fall back to
    # the process-global admin PathService.
    from deeptutor.multi_user.paths import get_current_path_service

    root = get_current_path_service().get_workspace_feature_dir("reading")  # type: ignore[arg-type]
    return ReadingStore(root)


def _http_error(exc: Exception) -> HTTPException:
    """Map an engine error to the status code that describes it.

    404 for "no such material", 400 for everything the caller can fix (bad
    locator, unsupported format, no extractable text). A 500 is reserved for
    failures that are genuinely ours.
    """
    if isinstance(exc, MaterialNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ReadingUpgradeConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ReadingError):
        return HTTPException(status_code=400, detail=str(exc))
    logger.warning("unexpected reading error", exc_info=True)
    return HTTPException(status_code=500, detail="The reader could not complete that request.")


# === Models ===================================================================


class ReadingProgressSummary(BaseModel):
    last_read_at: float
    last_locator: int
    reading_percentage: float


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
    render_mode: Literal["text", "pdf", "epub"] = "text"
    annotation_count: int = 0
    source_type: str = "upload"
    source_ref: str = ""
    source_url: str = ""
    kb_name: str = ""
    kb_path: str = ""
    revision_id: str = ""
    captured_at: float = 0.0
    previous_revision_id: str = ""
    tutorial_available: bool = False
    navigation_kind: str = ""
    content_format: Literal["plain_text", "markdown", "pdf", "epub"] = "plain_text"
    bilingual_available: bool = False
    bilingual_languages: list[str] = Field(default_factory=list)
    bilingual_pairing_ids: list[str] = Field(default_factory=list)
    reading_progress: ReadingProgressSummary | None = None


class MaterialDetail(MaterialInfo):
    outline: list[dict[str, Any]] = Field(default_factory=list)
    outline_text: str = ""
    unit_refs: list[dict[str, Any]] = Field(default_factory=list)


class UnitText(BaseModel):
    locator: int
    unit: str
    text: str


class BilingualUnit(BaseModel):
    locator: int
    groups: list[dict[str, Any]] = Field(default_factory=list)


class TextQuoteSelectorPayload(BaseModel):
    type: Literal["TextQuoteSelector"]
    exact: str = Field(min_length=1, max_length=2000)
    prefix: str = Field(default="", max_length=128)
    suffix: str = Field(default="", max_length=128)


class TextPositionSelectorPayload(BaseModel):
    type: Literal["TextPositionSelector"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> "TextPositionSelectorPayload":
        if self.end <= self.start:
            raise ValueError("selector end must be greater than start")
        return self


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
    quote: str = Field(default="", max_length=2000)
    note: str = ""
    rects: list[list[float]] = Field(default_factory=list)
    source_anchor: str = Field(default="", max_length=4096)
    selectors: list[TextQuoteSelectorPayload | TextPositionSelectorPayload] = Field(
        default_factory=list,
        max_length=2,
    )

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
                "source_anchor": self.source_anchor,
                "selectors": [selector.model_dump() for selector in self.selectors],
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
    source_anchor: str = ""
    selectors: list[dict[str, Any]] = Field(default_factory=list)
    author: str
    created_at: float
    updated_at: float
    revision_id: str = ""
    migration_status: str = "native"


class PositionPayload(BaseModel):
    locator: int = Field(ge=1)
    source_anchor: str = Field(default="", max_length=4096)
    percentage: float = Field(default=0.0, ge=0.0, le=1.0)


class PositionInfo(PositionPayload):
    updated_at: float = 0.0


class SupportedFormats(BaseModel):
    extensions: list[str]
    max_bytes: int
    raw_view_extensions: list[str]


class UrlMaterialRequest(BaseModel):
    url: str
    whole_tutorial: bool = False
    max_depth: int = Field(default=3, ge=1, le=5)
    max_pages: int = Field(default=200, ge=1, le=200)


class KbMaterialRequest(BaseModel):
    kb_name: str
    file_path: str = ""
    web_source_id: str = ""


class SaveToKbRequest(BaseModel):
    kb_name: str


class RepairEpubRequest(BaseModel):
    """Reserved for future explicit-file repair; fixed roots stay server-owned."""

    pass


class EpubPairingRequest(BaseModel):
    english_material_id: str
    chinese_material_id: str


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
        manifests = store.list_materials()
        policy = current_learning_policy()
        if policy is not None:
            has_reading = isinstance(policy.get("reading"), dict)
            reading = policy.get("reading") if has_reading else {}
            assigned = set(reading.get("material_ids") or (["*"] if not has_reading else []))
            if "*" not in assigned:
                manifests = [row for row in manifests if row.material_id in assigned]
        rows = [_info(store, manifest) for manifest in manifests]
        rows.sort(
            key=lambda row: (
                row.reading_progress.last_read_at if row.reading_progress else 0.0,
                row.created_at,
            ),
            reverse=True,
        )
        return rows
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials", response_model=MaterialDetail)
async def upload_material(file: UploadFile = File(...)) -> MaterialDetail:  # noqa: B008
    """Ingest an uploaded document and return it ready to read.

    The upload is streamed to a temp file with a running size check, so an
    oversized file is rejected before it is fully buffered rather than after.
    """
    try:
        assert_learning_material("", upload=True)
    except PermissionError as exc:
        raise _http_error(exc) from exc
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


@router.post("/materials/from-url", response_model=MaterialDetail)
async def material_from_url(payload: UrlMaterialRequest) -> MaterialDetail:
    """Capture one public web page and open its stable local snapshot."""
    try:
        assert_learning_material("", upload=True)
    except PermissionError as exc:
        raise _http_error(exc) from exc
    url = _normalise_public_url(payload.url)
    try:
        from deeptutor.services.web_source.crawler import crawl_docs_site

        result = await crawl_docs_site(
            url,
            max_depth=payload.max_depth if payload.whole_tutorial else 0,
            max_pages=payload.max_pages if payload.whole_tutorial else 1,
        )
        if not result.pages:
            detail = "; ".join(result.errors) or "No readable page was returned."
            raise ReadingError(f"The page could not be captured: {detail}")
        source = _web_crawl_payload(result, url=url, whole_tutorial=payload.whole_tutorial)
        source = await localize_snapshot_images(source)
        store = _store()
        manifest = store.ingest_source(source)
        return _detail(store, manifest)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials/from-kb", response_model=MaterialDetail)
async def material_from_kb(payload: KbMaterialRequest) -> MaterialDetail:
    """Open an access-checked KB file or a crawled tutorial in the reader."""
    if bool(payload.file_path.strip()) == bool(payload.web_source_id.strip()):
        raise HTTPException(
            status_code=400,
            detail="Choose exactly one of file_path or web_source_id.",
        )
    try:
        from deeptutor.multi_user.knowledge_access import manager_for_resource, resolve_kb

        resource = resolve_kb(payload.kb_name, require_write=False)
        manager = manager_for_resource(resource)
        kb_dir = manager.get_knowledge_base_path(resource.name)
        raw_dir = (kb_dir / "raw").resolve()
        if payload.file_path:
            target = _safe_kb_file(raw_dir, payload.file_path)
            adapter = FileSourceAdapter(
                path=target,
                filename=target.name,
                source_type="kb_file",
                source_ref=f"{resource.id}:{payload.file_path}",
                kb_name=resource.id,
                kb_path=payload.file_path,
            )
            source = await asyncio.to_thread(adapter.build)
        else:
            source = await asyncio.to_thread(
                _kb_tutorial_payload,
                manager,
                resource.id,
                resource.name,
                raw_dir,
                payload.web_source_id,
            )
        store = _store()
        source = await localize_snapshot_images(source)
        manifest = await asyncio.to_thread(store.ingest_source, source)
        return _detail(store, manifest)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}", response_model=MaterialDetail)
async def get_material(material_id: str) -> MaterialDetail:
    store = _store()
    try:
        assert_learning_material(material_id)
        manifest = store.manifest(material_id)
        if manifest.filename.lower().endswith(".epub") and manifest.render_mode == "text":
            try:
                manifest = await asyncio.to_thread(store.repair_legacy_epub, material_id)
            except ReadingError:
                # Opening still succeeds so the UI can preserve access to the
                # legacy text and offer explicit-file repair when necessary.
                pass
        return _detail(store, manifest)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials/{material_id}/repair-epub", response_model=MaterialDetail)
async def repair_legacy_epub(
    material_id: str,
    _payload: RepairEpubRequest | None = None,
) -> MaterialDetail:
    """Recover a legacy text-only EPUB when exactly one source hash matches."""
    store = _store()
    try:
        assert_learning_material(material_id)
        manifest = await asyncio.to_thread(store.repair_legacy_epub, material_id)
        return _detail(store, manifest)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/epub-pairing-candidates")
async def epub_pairing_candidates(material_id: str) -> list[dict[str, Any]]:
    store = _store()
    try:
        assert_learning_material(material_id)
        from deeptutor.reading.epub_bilingual import recommend_epub_candidates

        return await asyncio.to_thread(recommend_epub_candidates, store, material_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/epub-pairings")
async def epub_pairings() -> list[dict[str, Any]]:
    from deeptutor.reading.epub_bilingual import list_epub_pairings

    return list_epub_pairings(_store())


@router.post("/epub-pairings")
async def create_epub_pair(payload: EpubPairingRequest) -> dict[str, Any]:
    store = _store()
    try:
        assert_learning_material(payload.english_material_id)
        assert_learning_material(payload.chinese_material_id)
        from deeptutor.reading.epub_bilingual import create_epub_pairing

        pairing, manifest = await asyncio.to_thread(
            create_epub_pairing,
            store,
            payload.english_material_id,
            payload.chinese_material_id,
        )
        return {"pairing": pairing, "material": _detail(store, manifest).model_dump()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/epub-pairings/{pairing_id}")
async def remove_epub_pairing(pairing_id: str) -> dict[str, Any]:
    from deeptutor.reading.epub_bilingual import delete_epub_pairing

    if not delete_epub_pairing(_store(), pairing_id):
        raise HTTPException(status_code=404, detail="EPUB pairing not found")
    return {"status": "ok", "pairing_id": pairing_id}


@router.post("/materials/{material_id}/save-to-kb", response_model=MaterialDetail)
async def save_material_to_kb(
    material_id: str,
    payload: SaveToKbRequest,
) -> MaterialDetail:
    """Bookmark a URL snapshot in a writable KB without rebuilding it."""
    try:
        assert_learning_material(material_id)
        from deeptutor.multi_user.knowledge_access import manager_for_resource, resolve_kb

        resource = resolve_kb(payload.kb_name, require_write=True)
        store = _store()
        manifest = store.manifest(material_id)
        if manifest.source_type != "url_snapshot" or not manifest.source_url:
            raise ReadingError("Only web-page snapshots can be saved to a knowledge base.")
        manager = manager_for_resource(resource)
        manager.add_web_source(resource.name, manifest.source_url)
        linked = store.link_source_to_kb(material_id, kb_name=resource.id)
        return _detail(store, linked)
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/revisions", response_model=list[MaterialInfo])
async def list_revisions(material_id: str) -> list[MaterialInfo]:
    store = _store()
    try:
        assert_learning_material(material_id)
        return [_info(store, row, annotation_count=False) for row in store.revisions(material_id)]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/materials/{material_id}/revisions/{revision_id}/activate",
    response_model=MaterialDetail,
)
async def activate_revision(material_id: str, revision_id: str) -> MaterialDetail:
    store = _store()
    try:
        assert_learning_material(material_id)
        return _detail(store, store.switch_revision(material_id, revision_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str) -> dict[str, Any]:
    store = _store()
    try:
        assert_learning_material(material_id)
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
        assert_learning_material(material_id)
        manifest = store.manifest(material_id)
        return UnitText(
            locator=locator,
            unit=manifest.unit,
            text=store.unit_text(material_id, locator),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/materials/{material_id}/units/{locator}/bilingual",
    response_model=BilingualUnit,
)
async def get_bilingual_unit(material_id: str, locator: int) -> BilingualUnit:
    store = _store()
    try:
        assert_learning_material(material_id)
        groups = store.bilingual_groups(material_id, locator)
        return BilingualUnit(locator=locator, groups=[row.to_dict() for row in groups])
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/raw")
async def get_raw(material_id: str) -> FileResponse:
    """The original bytes, for the faithful viewer. Serves Range requests."""
    store = _store()
    try:
        assert_learning_material(material_id)
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


@router.get("/snapshot-assets/{asset_id}")
async def get_snapshot_asset(asset_id: str) -> FileResponse:
    """Serve one content-addressed, SSRF-checked image from this user's cache."""
    try:
        path, mime = _store().snapshot_asset(asset_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return FileResponse(path, media_type=mime, content_disposition_type="inline")


@router.get("/materials/{material_id}/annotations", response_model=list[AnnotationInfo])
async def list_annotations(material_id: str) -> list[AnnotationInfo]:
    store = _store()
    try:
        assert_learning_material(material_id)
        return [_annotation_info(row) for row in store.annotations(material_id)]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/position", response_model=PositionInfo)
async def get_position(material_id: str) -> PositionInfo:
    """Return the user's last durable viewport for this material."""
    store = _store()
    try:
        assert_learning_material(material_id)
        return PositionInfo(**store.position(material_id).to_dict())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/materials/{material_id}/position", response_model=PositionInfo)
async def save_position(material_id: str, payload: PositionPayload) -> PositionInfo:
    """Persist a validated numeric locator plus an optional renderer anchor."""
    store = _store()
    try:
        assert_learning_material(material_id)
        saved = store.save_position(
            material_id,
            ReadingPosition(
                locator=payload.locator,
                source_anchor=payload.source_anchor,
                percentage=payload.percentage,
            ),
        )
        return PositionInfo(**saved.to_dict())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/materials/{material_id}/annotations", response_model=AnnotationInfo)
async def save_annotation(material_id: str, payload: AnnotationPayload) -> AnnotationInfo:
    """Create or update one annotation (id absent = create)."""
    store = _store()
    try:
        assert_learning_material(material_id)
        saved = store.save_annotation(material_id, payload.to_annotation())
    except Exception as exc:
        raise _http_error(exc) from exc
    return _annotation_info(saved)


@router.delete("/materials/{material_id}/annotations/{annotation_id}")
async def delete_annotation(material_id: str, annotation_id: str) -> dict[str, Any]:
    store = _store()
    try:
        assert_learning_material(material_id)
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
        assert_learning_material(material_id)
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


def _info(
    store: ReadingStore,
    manifest: Any,
    *,
    annotation_count: bool = True,
) -> MaterialInfo:
    progress = store.stored_position(manifest.material_id)
    return MaterialInfo(
        **manifest.to_dict()
        | {
            "annotation_count": (
                len(store.annotations(manifest.material_id)) if annotation_count else 0
            ),
            "reading_progress": (
                ReadingProgressSummary(
                    last_read_at=progress.updated_at,
                    last_locator=progress.locator,
                    reading_percentage=progress.percentage,
                )
                if progress
                else None
            ),
        }
    )


def _detail(store: ReadingStore, manifest: Any) -> MaterialDetail:
    outline = store.outline(manifest.material_id)
    return MaterialDetail(
        **manifest.to_dict()
        | {
            "annotation_count": len(store.annotations(manifest.material_id)),
            "outline": [entry.to_dict() for entry in outline],
            "outline_text": render_outline(store, manifest.material_id),
            "unit_refs": [entry.to_dict() for entry in store.unit_references(manifest.material_id)],
        }
    )


def _annotation_info(row: Annotation) -> AnnotationInfo:
    return AnnotationInfo(**row.to_dict())


def _normalise_public_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Enter a complete http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Authenticated URLs are not supported.")
    clean, _ = urldefrag(raw)
    parsed = urlparse(clean)
    host = (parsed.hostname or "").lower()
    netloc = host
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The URL contains an invalid port.") from exc
    if port and not (
        parsed.scheme.lower() == "http"
        and port == 80
        or parsed.scheme.lower() == "https"
        and port == 443
    ):
        netloc += f":{port}"
    return urlunparse(
        (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )


def _normalise_stored_source_url(value: Any) -> str:
    """Normalize legacy KB source URLs without turning bad data into links."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not urlparse(raw).scheme:
        raw = f"https://{raw.lstrip('/')}"
    try:
        return _normalise_public_url(raw)
    except HTTPException:
        return ""


def _web_filename(title: str, url: str) -> str:
    import re

    candidate = re.sub(r"[^\w\-. ]+", " ", str(title or ""), flags=re.UNICODE).strip()
    if not candidate:
        candidate = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "web-page"
    return f"{candidate[:120]}.md"


def _web_crawl_payload(result: Any, *, url: str, whole_tutorial: bool) -> ReadingSourcePayload:
    """Turn a safe crawler result into one local snapshot or a site reader."""
    from deeptutor.reading.extract import split_into_sections

    first = result.pages[0]
    source_url = first.canonical_url or first.url or url
    title = first.title or urlparse(url).path.rsplit("/", 1)[-1] or urlparse(url).netloc
    navigation_kind = str(result.navigation_kind or "")
    tutorial_available = bool(
        len(result.navigation_links) > 1 or getattr(result, "truncated", False)
    )
    if not whole_tutorial:
        source = markdown_payload(
            source_type="url_snapshot",
            source_ref=url,
            title=title,
            markdown=first.markdown,
            filename=_web_filename(first.title, url),
            source_url=source_url,
        )
        return dataclass_replace(
            source,
            captured_at=_timestamp(first.fetched_at),
            tutorial_available=tutorial_available,
            navigation_kind=navigation_kind,
        )

    pages_by_url: dict[str, Any] = {}
    for page in result.pages:
        for page_url in (page.url, page.canonical_url, page.requested_url):
            if page_url:
                pages_by_url[urldefrag(page_url)[0].rstrip("/")] = page
    rows: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    for nav in result.navigation_links:
        nav_url = urldefrag(str(nav.get("url") or ""))[0]
        key = nav_url.rstrip("/")
        page = pages_by_url.get(key)
        rows.append(
            {
                "page": page,
                "title": str(nav.get("title") or getattr(page, "title", "") or nav_url),
                "url": nav_url,
                "level": max(1, int(nav.get("depth") or 0) + 1),
            }
        )
        if page is not None:
            seen_pages.add(page.canonical_url or page.url)
    for page in result.pages:
        identity = page.canonical_url or page.url
        if identity in seen_pages:
            continue
        rows.append({"page": page, "title": page.title or identity, "url": identity, "level": 1})

    units: list[str] = []
    outline: list[OutlineEntry] = []
    for row in rows:
        page = row["page"]
        start = len(units) + 1
        if page is None:
            units.append(
                "# Page unavailable\n\n"
                "This page appeared in the site navigation but could not be captured. "
                "Retry the tutorial to fetch it again."
            )
            row_title = f"{row['title']} — unavailable"
        else:
            sections = split_into_sections(sanitize_snapshot_markdown(page.markdown))
            if not sections:
                continue
            units.extend(sections)
            row_title = row["title"]
        outline.append(
            OutlineEntry(
                locator=start,
                title=str(row_title),
                level=int(row["level"]),
                synthesised=navigation_kind != "original",
                source_url=str(row["url"]),
            )
        )
    return ReadingSourcePayload(
        source_type="url_snapshot",
        source_ref=url,
        filename=_web_filename(title, url),
        title=title,
        units=tuple(units),
        unit="section",
        outline=tuple(outline),
        source_url=source_url,
        captured_at=_timestamp(first.fetched_at),
        tutorial_available=False,
        navigation_kind=navigation_kind,
    )


def _safe_kb_file(raw_dir: Path, file_path: str) -> Path:
    target = (raw_dir / file_path).resolve()
    try:
        target.relative_to(raw_dir)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Access denied") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Knowledge-base file not found")
    return target


def _navigation_rows(nodes: list[dict[str, Any]], level: int = 1) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in nodes:
        file_path = str(node.get("file_path") or "")
        if file_path:
            rows.append(
                {
                    "file_path": file_path,
                    "title": str(node.get("title") or Path(file_path).stem),
                    "level": level,
                    "url": str(node.get("url") or ""),
                    "file_path_zh": str(node.get("file_path_zh") or ""),
                    "pair_key": str(node.get("pair_key") or ""),
                }
            )
        rows.extend(_navigation_rows(node.get("children") or [], level + 1))
    return rows


def _resolve_kb_pair_key(kb_dir: Path, source: dict[str, Any] | None, source_id: str) -> str:
    """Resolve the alignment pair for a source without guessing by filename."""
    from deeptutor.services.web_source.bilingual_store import (
        list_pair_keys,
        load_pair_index,
    )
    from deeptutor.services.web_source.pairing import normalize_origin, pair_key_for

    explicit = str((source or {}).get("pairing_key") or "").strip()
    if explicit:
        return explicit

    origin = normalize_origin(str((source or {}).get("url") or ""))
    keys = set(list_pair_keys(kb_dir))
    indexes: list[tuple[str, dict[str, Any]]] = []
    for key in sorted(keys):
        index = load_pair_index(kb_dir, key)
        if index is not None:
            indexes.append((key, index))

    for key, index in indexes:
        if str(index.get("en_source_id") or "") == source_id:
            return str(index.get("pair_key") or key)

    origin_matches = [
        (key, index)
        for key, index in indexes
        if origin
        and normalize_origin(str(index.get("en_url") or index.get("origin") or "")) == origin
    ]
    if len(origin_matches) == 1:
        key, index = origin_matches[0]
        return str(index.get("pair_key") or key)

    # Older syncs can have alignment directories without a pair index. Fall
    # back only when that key unambiguously names the source's normalized origin.
    legacy_key = pair_key_for(origin) if origin else ""
    return legacy_key if legacy_key in keys else ""


def _kb_tutorial_payload(
    manager: Any,
    resource_id: str,
    kb_name: str,
    raw_dir: Path,
    source_id: str,
) -> ReadingSourcePayload:
    from deeptutor.reading.extract import split_into_sections
    from deeptutor.services.web_source import bilingual_store

    source = next(
        (row for row in manager.get_web_sources(kb_name) if row.get("id") == source_id),
        None,
    )
    page_manifest: dict[str, Any] = {}
    navigation: dict[str, Any] = {}
    if source is not None:
        page_manifest = source.get("page_manifest") or {}
        navigation = source.get("navigation") or {}
    else:
        # The navigation API may expose a merged bilingual pair id rather than
        # either concrete source id. Its sidecar still points at the canonical
        # Markdown snapshots under raw/, so it is directly readable.
        try:
            from deeptutor.services.web_source import bilingual_store

            pair_index = bilingual_store.load_pair_index(raw_dir.parent, source_id)
        except Exception:
            pair_index = None
        if pair_index:
            navigation = pair_index.get("navigation") or {}
            source = {
                "id": source_id,
                "url": pair_index.get("origin") or "",
                "last_synced_at": pair_index.get("updated_at") or "",
            }
        else:
            raise HTTPException(status_code=404, detail="Web source not found")
    if not page_manifest and not navigation.get("nodes"):
        raise ReadingError("Sync this web source before opening the tutorial.")

    rows = _navigation_rows(navigation.get("nodes") or [])
    known = {row["file_path"] for row in rows}
    for file_path, metadata in sorted(page_manifest.items()):
        if metadata.get("status") == "deleted" or file_path in known:
            continue
        section_path = metadata.get("section_path") or []
        rows.append(
            {
                "file_path": file_path,
                "title": metadata.get("title") or Path(file_path).stem,
                "level": max(1, len(section_path)),
                "url": metadata.get("canonical_url") or metadata.get("url") or "",
            }
        )

    units: list[str] = []
    outline: list[OutlineEntry] = []
    included_paths: list[str] = []
    bilingual_groups: list[BilingualGroup] = []
    pairing_ids: set[str] = set()
    default_pair_key = _resolve_kb_pair_key(raw_dir.parent, source, source_id)
    for row in rows:
        try:
            target = _safe_kb_file(raw_dir, row["file_path"])
        except HTTPException:
            # Keep the failed page in the source outline. This makes partial
            # sync visible and actionable instead of making the whole tutorial
            # disappear because one page failed or was removed.
            units.append(
                "# Page unavailable\n\n"
                f"The synced snapshot for `{row['file_path']}` is missing. "
                "Retry this web source from the Knowledge Base and reopen the tutorial."
            )
            included_paths.append(row["file_path"])
            outline.append(
                OutlineEntry(
                    locator=len(units),
                    title=f"{row['title']} — unavailable",
                    level=max(1, int(row["level"])),
                    synthesised=navigation.get("kind") != "original",
                    source_url=str(row["url"]),
                )
            )
            continue
        try:
            markdown = normalize_snapshot_links(
                sanitize_snapshot_markdown(target.read_text(encoding="utf-8")),
                str(row["url"]),
            )
        except UnicodeDecodeError as exc:
            raise ReadingError(f"{target.name} is not readable Markdown") from exc
        pair_key = str(row.get("pair_key") or default_pair_key)
        alignment = (
            bilingual_store.load_alignment(raw_dir.parent, pair_key, row["file_path"])
            if pair_key
            else None
        )
        aligned_rows = [
            item
            for item in (alignment or {}).get("groups", [])
            if isinstance(item, dict) and str(item.get("en_content") or "").strip()
        ]
        sections = (
            (
                "\n\n".join(
                    normalize_snapshot_links(
                        str(item.get("en_content") or ""), str(row["url"])
                    )
                    for item in aligned_rows
                ),
            )
            if aligned_rows
            else split_into_sections(markdown)
        )
        if not sections:
            continue
        start = len(units) + 1
        units.extend(sections)
        included_paths.append(row["file_path"])
        if aligned_rows:
            pairing_ids.add(pair_key)
            for index, item in enumerate(aligned_rows, start=1):
                bilingual_groups.append(
                    BilingualGroup(
                        group_id=str(
                            item.get("group_id") or f"{pair_key}:{row['file_path']}:{index}"
                        ),
                        locator=start,
                        source_markdown=normalize_snapshot_links(
                            str(item.get("en_content") or ""), str(row["url"])
                        ),
                        translation_markdown=normalize_snapshot_links(
                            str(item.get("zh_content") or ""), str(row["url"])
                        ),
                        confidence=float(item.get("confidence") or 0.0),
                        low_confidence=bool(item.get("low_confidence")),
                    )
                )
        outline.append(
            OutlineEntry(
                locator=start,
                title=str(row["title"]),
                level=max(1, int(row["level"])),
                synthesised=navigation.get("kind") != "original",
                source_url=str(row["url"]),
            )
        )

    if not units:
        raise ReadingError("The synced tutorial has no readable pages.")
    url = _normalise_stored_source_url(source.get("url"))
    captured_at = _timestamp(source.get("last_synced_at"))
    return ReadingSourcePayload(
        source_type="kb_web_tutorial",
        source_ref=f"{resource_id}:web:{source_id}",
        filename=f"{urlparse(url).hostname or source_id}-tutorial.md",
        title=urlparse(url).hostname or "Web tutorial",
        units=tuple(units),
        unit="section",
        outline=tuple(outline),
        source_url=url,
        kb_name=resource_id,
        kb_path="\n".join(included_paths),
        raw_bytes=b"",
        has_raw_view=False,
        captured_at=captured_at,
        content_format="markdown",
        bilingual_groups=tuple(bilingual_groups),
        bilingual_languages=("en", "zh") if bilingual_groups else (),
        bilingual_pairing_ids=tuple(sorted(pairing_ids)),
    )


def _timestamp(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _attachment_header(filename: str) -> str:
    """RFC 5987 disposition so non-ASCII names survive the round trip."""
    from urllib.parse import quote

    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "export"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


__all__ = ["MAX_MATERIAL_BYTES", "router"]
