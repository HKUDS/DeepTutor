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
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator

from deeptutor.multi_user.learning_access import (
    assert_learning_material,
    assert_learning_material_mutation,
    current_learning_policy,
)
from deeptutor.reading import (
    ANNOTATION_COLORS,
    Annotation,
    IngestionStatus,
    MaterialNotFound,
    ReadingCatalogStore,
    ReadingError,
    ReadingPosition,
    ReadingStore,
    ReadingUpgradeConflict,
    SourceKind,
    export_material,
    render_outline,
)
from deeptutor.reading.ingestion import (
    MAX_TRANSCRIPT_BYTES,
    ReadingIngestionService,
    url_material_id,
)
from deeptutor.reading.knowledge_capture import (
    organize_workspace_notes,
    send_workspace_to_notebook,
)
from deeptutor.reading.models import MAX_TEXT_SELECTOR_CHARS
from deeptutor.services.session.workspace_preferences import WORKSPACE_MODE_READING
from deeptutor.utils.document_validator import DocumentValidator

logger = logging.getLogger(__name__)

router = APIRouter()

# Streaming upload ceiling. Same number the extractor enforces, so a file that
# passes here cannot then be rejected deeper in with a less helpful message.
MAX_MATERIAL_BYTES = DocumentValidator.MAX_FILE_SIZE
_UPLOAD_CHUNK = 1024 * 1024
_MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v",
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".ogg",
    ".flac",
}


def _store() -> ReadingStore:
    return ReadingStore()


def _catalog() -> ReadingCatalogStore:
    return ReadingCatalogStore()


def _ingestion() -> ReadingIngestionService:
    catalog = _catalog()
    return ReadingIngestionService(ReadingStore(catalog.root), catalog)


def _new_material_id() -> str:
    return f"rm_{uuid.uuid4().hex[:12]}"


def _content_facts(store: ReadingStore, record: Any) -> tuple[int, int]:
    """Stored size and extracted unit count, or zeros while still processing."""
    if getattr(record.status, "value", record.status) != "ready":
        return 0, 0
    try:
        manifest = store.manifest(record.material_id)
    except Exception:  # noqa: BLE001 - a missing manifest is a zero, not a 500
        return 0, 0
    return int(manifest.byte_size), int(manifest.unit_count)


def _http_error(exc: Exception) -> HTTPException:
    """Map an engine error to the status code that describes it.

    404 for "no such material", 400 for everything the caller can fix (bad
    locator, unsupported format, no extractable text). A 500 is reserved for
    failures that are genuinely ours.
    """
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, MaterialNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ReadingUpgradeConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ReadingError):
        return HTTPException(status_code=400, detail=str(exc))
    logger.warning("unexpected reading error", exc_info=True)
    return HTTPException(status_code=500, detail="The reader could not complete that request.")


def _assigned_material_ids() -> set[str] | None:
    """Return the account allowlist, or ``None`` for unrestricted accounts."""
    policy = current_learning_policy()
    if policy is None:
        return None
    reading = policy.get("reading")
    if not isinstance(reading, dict):
        return {"*"}
    assigned = set(reading.get("material_ids") or [])
    return None if "*" in assigned else assigned


def _material_allowed(material_id: str) -> bool:
    assigned = _assigned_material_ids()
    return assigned is None or material_id in assigned


def _enforce_learning_materials(*material_ids: str) -> None:
    for material_id in material_ids:
        if material_id:
            assert_learning_material(material_id)


def _workspace_payload(row: Any) -> dict[str, Any]:
    """Hide tabs that are no longer assigned to a learning account."""
    payload = row.to_dict()
    assigned = _assigned_material_ids()
    if assigned is None:
        return payload
    payload["tabs"] = [
        tab
        for tab in payload.get("tabs", [])
        if tab.get("material", {}).get("material_id") in assigned
    ]
    if payload.get("active_material_id") not in assigned:
        payload["active_material_id"] = None
    return payload


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
    render_mode: Literal["text", "pdf", "epub", "video", "audio"] = "text"
    extractor: str = ""
    content_format: Literal["plain_text", "web_markdown"] = "plain_text"
    source_type: str = "upload"
    source_url: str = ""
    revision: int = 1
    annotation_count: int = 0


class MaterialDetail(MaterialInfo):
    outline: list[dict[str, Any]] = Field(default_factory=list)
    outline_text: str = ""
    unit_refs: list[dict[str, Any]] = Field(default_factory=list)


class UnitText(BaseModel):
    locator: int
    unit: str
    text: str


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
        if self.end - self.start > MAX_TEXT_SELECTOR_CHARS:
            raise ValueError(f"selector span must not exceed {MAX_TEXT_SELECTOR_CHARS} characters")
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
    kind: Literal["highlight", "underline", "note", "citation"] = "highlight"
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
    material_revision: int = 1
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


class PositionPayload(BaseModel):
    locator: int = Field(ge=1)
    source_anchor: str = Field(default="", max_length=4096)
    percentage: float = Field(default=0.0, ge=0.0, le=1.0)


class PositionInfo(PositionPayload):
    updated_at: float = 0.0


class BookmarkPayload(BaseModel):
    locator: int = Field(ge=1)
    label: str = Field(default="", max_length=200)
    source_anchor: str = Field(default="", max_length=4096)


class BookmarkInfo(BookmarkPayload):
    bookmark_id: str
    created_at: float = 0.0


class BookmarkList(BaseModel):
    bookmarks: list[BookmarkInfo]


class SupportedFormats(BaseModel):
    extensions: list[str]
    max_bytes: int
    raw_view_extensions: list[str]


class EpubPairingRequest(BaseModel):
    english_material_id: str
    chinese_material_id: str


class UrlImportRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    workspace_id: str = ""
    workspace_title: str = ""


class WorkspaceCreateRequest(BaseModel):
    title: str = Field(default="Untitled collection", max_length=300)
    description: str = Field(default="", max_length=2000)
    material_ids: list[str] = Field(default_factory=list, max_length=100)


class WorkspaceUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)


class WorkspaceMaterialRequest(BaseModel):
    material_id: str
    make_active: bool = False


class WorkspaceReorderRequest(BaseModel):
    material_ids: list[str] = Field(min_length=1, max_length=100)


class ReadingSessionCreateRequest(BaseModel):
    title: str = Field(default="New reading conversation", max_length=100)
    active_material_id: str = ""


class ReadingSessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class ReadingSessionLinkRequest(BaseModel):
    target_session_id: str


class DuplicateFileQuery(BaseModel):
    filename: str = Field(default="", max_length=512)
    # sha256(bytes)[:16], computed by the browser with the store's algorithm.
    content_id: str = Field(default="", max_length=64)
    size_bytes: int = 0
    mime: str = Field(default="", max_length=128)


class DuplicateCheckRequest(BaseModel):
    files: list[DuplicateFileQuery] = Field(default_factory=list, max_length=50)
    urls: list[str] = Field(default_factory=list, max_length=50)


class OrganizeNotesRequest(BaseModel):
    material_ids: list[str] = Field(default_factory=list, max_length=100)


class NotebookCaptureRequest(OrganizeNotesRequest):
    notebook_ids: list[str] = Field(min_length=1, max_length=20)
    title: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=1000)


# === Routes ===================================================================


@router.get("/library/materials")
async def list_library_materials(
    search: str = Query(default="", max_length=200),
    status: Literal["queued", "processing", "ready", "failed"] | None = None,
    library_filter: Literal["all", "unassigned", "processing", "failed"] = Query(
        default="all", alias="filter"
    ),
) -> dict[str, Any]:
    """Every material the owner has, with the collections holding each one.

    Membership travels with the row because the library view exists to answer
    "where is this used, and what did I upload that is used nowhere" — a
    question the client cannot ask one material at a time.
    """
    catalog = _catalog()
    store = _store()
    try:
        for manifest in store.list_materials():
            if catalog.get_material(manifest.material_id) is None:
                catalog.register_manifest(manifest)
        rows = [
            row
            for row in catalog.list_materials(
                search=search, status=status, library_filter=library_filter
            )
            if _material_allowed(row.material_id)
        ]
        membership = catalog.collections_for_materials([row.material_id for row in rows])
        materials: list[dict[str, Any]] = []
        for row in rows:
            payload = row.to_dict()
            payload["collections"] = membership.get(row.material_id, [])
            size_bytes, unit_count = _content_facts(store, row)
            payload["size_bytes"] = size_bytes
            payload["unit_count"] = unit_count
            materials.append(payload)
        # Counts describe every material this account may see, not only the
        # filtered page and never revoked or unassigned learner material.
        assigned = _assigned_material_ids()
        return {
            "materials": materials,
            "counts": catalog.library_counts(None if assigned is None else sorted(assigned)),
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/library/duplicate-check")
async def duplicate_check(payload: DuplicateCheckRequest) -> dict[str, Any]:
    """Say what the library already holds, before anything is uploaded.

    Identical bytes are answered from the content id the browser computed;
    a same-name-different-content upload is the genuinely ambiguous case and
    is reported separately so the client can ask instead of guessing.
    """
    catalog = _catalog()
    store = _store()

    def described(record: Any) -> dict[str, Any]:
        """The match, with the facts that let a user tell two copies apart."""
        payload_row = record.to_dict()
        size_bytes, unit_count = _content_facts(store, record)
        payload_row["size_bytes"] = size_bytes
        payload_row["unit_count"] = unit_count
        return payload_row

    try:
        matches: list[dict[str, Any]] = []
        for item in payload.files:
            kind = "same_content"
            record = catalog.find_material_by_content(item.content_id) if item.content_id else None
            if record is None and item.filename:
                record = catalog.find_ready_material_by_filename(item.filename, mime=item.mime)
                kind = "same_name"
            if record is None or not _material_allowed(record.material_id):
                continue
            matches.append(
                {
                    "query": {"filename": item.filename, "url": ""},
                    "kind": kind,
                    "material": described(record),
                    "collections": catalog.collections_for_material(record.material_id),
                }
            )
        for url in payload.urls:
            try:
                material_id = url_material_id(url)
            except Exception:  # noqa: BLE001 - a malformed URL is simply not a match
                continue
            record = catalog.get_material(material_id)
            if record is None or not _material_allowed(record.material_id):
                continue
            matches.append(
                {
                    "query": {"filename": "", "url": url},
                    "kind": "same_content",
                    "material": described(record),
                    "collections": catalog.collections_for_material(record.material_id),
                }
            )
        return {"matches": matches}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/library/import-urls", status_code=202)
async def import_urls(
    payload: UrlImportRequest, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Queue safe webpage, YouTube, or Bilibili imports into a workspace."""
    try:
        assert_learning_material("", upload=True)
    except PermissionError as exc:
        raise _http_error(exc) from exc
    service = _ingestion()
    try:
        materials = [service.queue_url(url) for url in payload.urls]
        workspace_id = payload.workspace_id.strip()
        if workspace_id:
            for material in materials:
                service.catalog.add_material(workspace_id, material.material_id)
            workspace = service.catalog.get_workspace(workspace_id)
        else:
            # Naming the collection after its first material is what keeps a
            # library from filling up with rows all called "Imported reading".
            workspace = service.catalog.create_workspace(
                payload.workspace_title
                or (materials[0].title if materials else "Reading collection"),
                [row.material_id for row in materials],
            )
        for material in materials:
            background_tasks.add_task(service.process_url, material.material_id)
        return {
            "materials": [row.to_dict() for row in materials],
            "workspace": workspace.to_dict() if workspace else None,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials/{material_id}/retry", status_code=202)
async def retry_import(material_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    service = _ingestion()
    try:
        assert_learning_material(material_id)
        material = service.catalog.get_material(material_id)
        if material is None:
            raise MaterialNotFound(f"material {material_id!r} not found")
        service.catalog.update_material_status(material_id, "queued", progress=0)
        background_tasks.add_task(service.retry, material_id)
        return {"material": service.catalog.get_material(material_id).to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces")
async def list_workspaces(
    search: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    try:
        rows = _catalog().list_workspaces(search=search)
        return {"workspaces": [_workspace_payload(row) for row in rows]}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/index")
async def list_workspace_index() -> dict[str, Any]:
    """Just enough to *name* a collection: id and title.

    The sidebar groups reading conversations under their collection and
    refreshes on every stream end. ``/workspaces`` answers with each
    collection's whole tab list — every material, its cover, its unit
    count — none of which a group heading renders.

    Declared above ``/workspaces/{workspace_id}``: that route matches any
    single segment, so a literal path below it would never be reached.
    """
    try:
        return {
            "collections": [
                {"workspace_id": row.workspace_id, "title": row.title}
                for row in _catalog().list_workspaces()
            ]
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces", status_code=201)
async def create_workspace(payload: WorkspaceCreateRequest) -> dict[str, Any]:
    try:
        _enforce_learning_materials(*payload.material_ids)
        row = _catalog().create_workspace(
            payload.title,
            payload.material_ids,
            description=payload.description,
        )
        return {"workspace": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str) -> dict[str, Any]:
    try:
        catalog = _catalog()
        row = catalog.get_workspace(workspace_id)
        if row is None:
            raise MaterialNotFound(f"reading workspace {workspace_id!r} not found")
        return {
            "workspace": _workspace_payload(row),
            "sessions": [session.to_dict() for session in catalog.list_sessions(workspace_id)],
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/ask-hint")
async def get_workspace_ask_hint(
    workspace_id: str,
    session_id: str = "",
    locator: int | None = None,
    selection: str = "",
) -> dict[str, Any]:
    """One question the learner could ask about their current reading context."""
    from deeptutor.services.reading_hints import get_ask_hint

    return await get_ask_hint(workspace_id, session_id, locator, selection)


@router.get("/workspaces/{workspace_id}/openers")
async def get_workspace_openers(
    workspace_id: str,
    locator: int | None = None,
) -> dict[str, Any]:
    """Three things a learner could open this material with.

    An empty list means the panel keeps its own generic suggestions — this is
    a nicety, never a dependency.
    """
    from deeptutor.services.reading_hints import get_openers

    return await get_openers(workspace_id, locator)


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, payload: WorkspaceUpdateRequest) -> dict[str, Any]:
    try:
        row = _catalog().update_workspace(
            workspace_id,
            title=payload.title,
            description=payload.description,
        )
        return {"workspace": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str) -> dict[str, Any]:
    from deeptutor.services.session import get_session_store

    try:
        catalog = _catalog()
        sessions = catalog.list_sessions(workspace_id)
        if not catalog.delete_workspace(workspace_id):
            raise MaterialNotFound(f"reading workspace {workspace_id!r} not found")
        session_store = get_session_store()
        for session in sessions:
            await session_store.delete_session(session.session_id)
        return {"status": "ok", "workspace_id": workspace_id}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/materials")
async def add_workspace_material(
    workspace_id: str, payload: WorkspaceMaterialRequest
) -> dict[str, Any]:
    try:
        assert_learning_material(payload.material_id)
        row = _catalog().add_material(
            workspace_id, payload.material_id, make_active=payload.make_active
        )
        return {"workspace": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/workspaces/{workspace_id}/materials/order")
async def reorder_workspace_materials(
    workspace_id: str, payload: WorkspaceReorderRequest
) -> dict[str, Any]:
    try:
        _enforce_learning_materials(*payload.material_ids)
        row = _catalog().reorder_materials(workspace_id, payload.material_ids)
        return {"workspace": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/workspaces/{workspace_id}/materials/{material_id}/active")
async def activate_workspace_material(workspace_id: str, material_id: str) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
        row = _catalog().set_active_material(workspace_id, material_id)
        return {"workspace": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/workspaces/{workspace_id}/materials/{material_id}")
async def remove_workspace_material(workspace_id: str, material_id: str) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
        row = _catalog().remove_material(workspace_id, material_id)
        return {"workspace": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/sessions")
async def list_reading_sessions(workspace_id: str) -> dict[str, Any]:
    from deeptutor.services.session import get_session_store

    try:
        catalog = _catalog()
        rows = catalog.list_sessions(workspace_id)
        # The catalog stores the title a conversation was attached with, which
        # is the placeholder every conversation starts life as: the real name
        # is written by the title model *after* that first turn finishes, into
        # the session store. Read it from there so the reader sees the same
        # name the sidebar does instead of a list of "New conversation".
        titles: dict[str, str] = {}
        try:
            summaries = await get_session_store().get_session_summaries(
                [row.session_id for row in rows]
            )
            titles = {
                str(summary.get("session_id") or summary.get("id") or ""): str(
                    summary.get("title") or ""
                )
                for summary in summaries
            }
        except Exception:
            logger.debug("reading sessions: live titles unavailable", exc_info=True)
        return {
            "sessions": [
                row.to_dict()
                | {
                    "title": titles.get(row.session_id) or row.title,
                    "linked_session_ids": catalog.list_session_links(workspace_id, row.session_id),
                }
                for row in rows
            ]
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/sessions", status_code=201)
async def create_reading_session(
    workspace_id: str, payload: ReadingSessionCreateRequest
) -> dict[str, Any]:
    from deeptutor.services.session import get_session_store

    catalog = _catalog()
    try:
        if payload.active_material_id:
            assert_learning_material(payload.active_material_id)
        workspace = catalog.get_workspace(workspace_id)
        if workspace is None:
            raise MaterialNotFound(f"reading workspace {workspace_id!r} not found")
        active_material_id = payload.active_material_id or workspace.active_material_id
        if active_material_id and active_material_id not in {
            tab.material.material_id for tab in workspace.tabs
        }:
            raise ReadingError("active material does not belong to this reading workspace")
        session_store = get_session_store()
        session = await session_store.create_session(title=payload.title)
        await session_store.update_session_preferences(
            session["id"],
            {
                "capability": "immersive_reading",
                "workspace_mode": WORKSPACE_MODE_READING,
                "session_kind": "immersive_reading",
                "reading_workspace_id": workspace_id,
                "reading_material_id": active_material_id or "",
            },
        )
        reading_session = catalog.attach_session(
            workspace_id,
            session["id"],
            title=payload.title,
            active_material_id=active_material_id,
        )
        return {"session": reading_session.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/workspaces/{workspace_id}/sessions/{session_id}")
async def rename_reading_session(
    workspace_id: str, session_id: str, payload: ReadingSessionRenameRequest
) -> dict[str, Any]:
    from deeptutor.services.session import get_session_store

    try:
        catalog = _catalog()
        row = catalog.rename_session(workspace_id, session_id, payload.title)
        await get_session_store().update_session_title(session_id, payload.title)
        return {"session": row.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/workspaces/{workspace_id}/sessions/{session_id}")
async def delete_reading_session(workspace_id: str, session_id: str) -> dict[str, Any]:
    from deeptutor.services.session import get_session_store

    try:
        catalog = _catalog()
        if not catalog.detach_session(workspace_id, session_id):
            raise MaterialNotFound("reading session not found")
        await get_session_store().delete_session(session_id)
        return {"status": "ok", "session_id": session_id}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/sessions/{session_id}/links")
async def link_reading_session(
    workspace_id: str, session_id: str, payload: ReadingSessionLinkRequest
) -> dict[str, Any]:
    try:
        catalog = _catalog()
        catalog.link_session(workspace_id, session_id, payload.target_session_id)
        return {
            "session_id": session_id,
            "linked_session_ids": catalog.list_session_links(workspace_id, session_id),
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/workspaces/{workspace_id}/sessions/{session_id}/links/{target_session_id}")
async def unlink_reading_session(
    workspace_id: str, session_id: str, target_session_id: str
) -> dict[str, Any]:
    try:
        catalog = _catalog()
        catalog.unlink_session(workspace_id, session_id, target_session_id)
        return {
            "session_id": session_id,
            "linked_session_ids": catalog.list_session_links(workspace_id, session_id),
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/notes/organize")
async def organize_reading_notes(
    workspace_id: str, payload: OrganizeNotesRequest
) -> dict[str, Any]:
    try:
        _enforce_learning_materials(*payload.material_ids)
        catalog = _catalog()
        notes = await asyncio.to_thread(
            organize_workspace_notes,
            workspace_id,
            material_ids=payload.material_ids,
            catalog=catalog,
            reading_store=ReadingStore(catalog.root),
        )
        return {"notes": notes.to_dict()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/notebook")
async def capture_reading_to_notebook(
    workspace_id: str, payload: NotebookCaptureRequest
) -> dict[str, Any]:
    try:
        _enforce_learning_materials(*payload.material_ids)
        catalog = _catalog()
        result = await asyncio.to_thread(
            send_workspace_to_notebook,
            workspace_id,
            payload.notebook_ids,
            material_ids=payload.material_ids,
            title=payload.title,
            summary=payload.summary,
            catalog=catalog,
            reading_store=ReadingStore(catalog.root),
        )
        return {"success": True, **result}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/supported-formats", response_model=SupportedFormats)
async def supported_formats() -> SupportedFormats:
    """What the reader accepts — the single source of truth for the file picker."""
    from deeptutor.reading.extract import RAW_VIEW_EXTENSIONS
    from deeptutor.utils.document_extractor import SUPPORTED_DOC_EXTENSIONS

    return SupportedFormats(
        extensions=sorted(set(SUPPORTED_DOC_EXTENSIONS) | _MEDIA_EXTENSIONS),
        max_bytes=MAX_MATERIAL_BYTES,
        raw_view_extensions=sorted(set(RAW_VIEW_EXTENSIONS) | _MEDIA_EXTENSIONS),
    )


@router.get("/materials", response_model=list[MaterialInfo])
async def list_materials() -> list[MaterialInfo]:
    store = _store()
    try:
        return [
            _info(store, manifest)
            for manifest in store.list_materials()
            if _material_allowed(manifest.material_id)
        ]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials", response_model=MaterialDetail)
async def upload_material(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008
    reuse: bool = Query(default=True),
) -> MaterialDetail:
    """Ingest an uploaded document and return it ready to read.

    The upload is streamed to a temp file with a running size check, so an
    oversized file is rejected before it is fully buffered rather than after.

    Audio and video answer as soon as the file is stored and transcription is
    queued, the same shape as a URL import. Holding the request open for the
    length of a lecture meant no progress could reach the client, the browser
    or a proxy could time the upload out after the transcription had already
    been paid for, and nothing was left on disk to retry from.
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
        if Path(filename).suffix.lower() in _MEDIA_EXTENSIONS:
            service = ReadingIngestionService(store, _catalog())
            record = await service.queue_media(tmp_path, filename=filename)
            background_tasks.add_task(service.process_media, record.material_id)
            return _detail(store, store.manifest(record.material_id))
        else:
            manifest = store.ingest(tmp_path, filename=filename)
            catalog = _catalog()
            if reuse or catalog.get_material(manifest.material_id) is None:
                catalog.register_manifest(manifest)
                return _detail(store, manifest)
            # A separate material over the same extracted content: the bytes
            # are stored once, while annotations and reading position are kept
            # apart because the user asked for a second, independent copy.
            record = catalog.upsert_material(
                content_id=manifest.material_id,
                material_id=_new_material_id(),
                filename=manifest.filename,
                title=manifest.title,
                source_kind=SourceKind.FILE,
                mime=manifest.mime,
                render_mode=manifest.render_mode,
                status=IngestionStatus.READY,
            )
            return _detail(store, store.manifest(record.material_id))
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
        assert_learning_material(material_id)
        return _detail(store, store.manifest(material_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/epub-pairing-candidates")
async def epub_pairing_candidates(material_id: str) -> list[dict[str, Any]]:
    from deeptutor.reading.epub_bilingual import recommend_epub_candidates

    try:
        assert_learning_material(material_id)
        return await asyncio.to_thread(recommend_epub_candidates, _store(), material_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/epub-pairings")
async def epub_pairings() -> list[dict[str, Any]]:
    from deeptutor.reading.epub_bilingual import list_epub_pairings

    return list_epub_pairings(_store())


@router.post("/epub-pairings")
async def create_epub_pairing(payload: EpubPairingRequest) -> dict[str, Any]:
    from deeptutor.reading.epub_bilingual import create_epub_pairing

    try:
        _enforce_learning_materials(payload.english_material_id, payload.chinese_material_id)
        pairing = await asyncio.to_thread(
            create_epub_pairing,
            _store(),
            payload.english_material_id,
            payload.chinese_material_id,
        )
        return {"pairing": pairing}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/epub-pairings/{pairing_id}")
async def remove_epub_pairing(pairing_id: str) -> dict[str, Any]:
    from deeptutor.reading.epub_bilingual import delete_epub_pairing

    try:
        removed = await asyncio.to_thread(delete_epub_pairing, _store(), pairing_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="EPUB pairing not found")
    return {"status": "ok", "pairing_id": pairing_id}


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str) -> dict[str, Any]:
    store = _store()
    catalog = _catalog()
    record = catalog.get_material(material_id)
    removed_from = catalog.collections_for_material(material_id) if record else []
    try:
        assert_learning_material_mutation(material_id)
        shared = record is not None and catalog.count_materials_for_content(record.content_id) > 1
        if shared and record is not None:
            # A sibling material still reads this content: drop this row and
            # only the annotations that belong to it.
            store.delete_material_state(material_id, content_id=record.content_id)
            removed = catalog.delete_material(material_id)
        else:
            with store.staged_delete(material_id) as staged:
                if staged:
                    catalog.delete_material(material_id)
            removed = staged or bool(record and catalog.delete_material(material_id))
    except Exception as exc:
        raise _http_error(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"material {material_id!r} not found")
    return {
        "status": "ok",
        "deleted": True,
        "material_id": material_id,
        "removed_from": removed_from,
    }


@router.get("/materials/{material_id}/transcript")
async def get_transcript(material_id: str) -> dict[str, Any]:
    """Every transcript segment of a timed material, in one response.

    The reader's transcript panel needs all of them at once. Fetching them one
    locator at a time meant a request per segment — fine when a segment was ten
    minutes long, wasteful now that they follow the speaker's own sentences.
    """
    store = _store()
    try:
        assert_learning_material(material_id)
        manifest = store.manifest(material_id)
        if manifest.render_mode not in {"video", "audio"}:
            raise ReadingError("this material has no timed transcript")
        refs = {row.locator: row for row in store.unit_references(material_id)}
        segments: list[dict[str, Any]] = []
        budget = MAX_TRANSCRIPT_BYTES
        for locator, text in store.iter_units(material_id):
            budget -= len(text.encode("utf-8"))
            if budget < 0:
                break
            ref = refs.get(locator)
            segments.append(
                {
                    "locator": locator,
                    "text": text,
                    "title": ref.title if ref else "",
                    "source_href": ref.source_href if ref else "",
                }
            )
        return {
            "material_id": material_id,
            "revision": manifest.revision,
            "unit_count": manifest.unit_count,
            "truncated": len(segments) < manifest.unit_count,
            "segments": segments,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


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


@router.get("/materials/{material_id}/revisions")
async def list_material_revisions(material_id: str) -> list[dict[str, Any]]:
    """Prior immutable snapshots retained when a URL is cleaned/refetched."""
    store = _store()
    try:
        return [row.to_dict() for row in store.revisions(material_id)]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/materials/{material_id}/revisions/{revision}/units/{locator}",
    response_model=UnitText,
)
async def get_revision_unit(material_id: str, revision: int, locator: int) -> UnitText:
    store = _store()
    try:
        manifest = next(
            (row for row in store.revisions(material_id) if row.revision == revision),
            None,
        )
        if manifest is None:
            raise MaterialNotFound(f"revision {revision} not found")
        return UnitText(
            locator=locator,
            unit=manifest.unit,
            text=store.revision_unit_text(material_id, revision, locator),
        )
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


@router.get("/materials/{material_id}/assets/{asset_name}")
async def get_snapshot_asset(material_id: str, asset_name: str) -> FileResponse:
    """Serve one authenticated, MIME-sniffed image captured with a web page."""
    from deeptutor.services.web_source.snapshot_assets import snapshot_asset_mime

    store = _store()
    try:
        assert_learning_material(material_id)
        path = store.asset_path(material_id, asset_name)
    except Exception as exc:
        raise _http_error(exc) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="Snapshot image not found.")
    data = path.read_bytes()
    mime = snapshot_asset_mime(data)
    if mime is None:
        raise HTTPException(status_code=404, detail="Snapshot image is invalid.")
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


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


@router.get("/materials/{material_id}/bookmarks", response_model=BookmarkList)
async def list_bookmarks(material_id: str) -> BookmarkList:
    """Every place the reader has kept in this material, in reading order."""
    store = _store()
    try:
        assert_learning_material(material_id)
        rows = store.bookmarks(material_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    return BookmarkList(bookmarks=[BookmarkInfo(**row.to_dict()) for row in rows])


@router.post("/materials/{material_id}/bookmarks", response_model=BookmarkInfo)
async def add_bookmark(material_id: str, payload: BookmarkPayload) -> BookmarkInfo:
    """Keep one place. Bookmarking an already-kept locator returns that one."""
    store = _store()
    try:
        assert_learning_material(material_id)
        saved = store.add_bookmark(
            material_id,
            payload.locator,
            payload.label,
            payload.source_anchor,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return BookmarkInfo(**saved.to_dict())


@router.delete("/materials/{material_id}/bookmarks/{bookmark_id}")
async def delete_bookmark(material_id: str, bookmark_id: str) -> dict[str, bool]:
    store = _store()
    try:
        assert_learning_material(material_id)
        removed = store.delete_bookmark(material_id, bookmark_id)
    except Exception as exc:
        raise _http_error(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"ok": True}


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
            "unit_refs": [entry.to_dict() for entry in store.unit_references(manifest.material_id)],
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
