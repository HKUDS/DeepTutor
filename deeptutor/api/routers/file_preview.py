"""Authenticated, same-origin Office document preview as a paginated PDF."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from deeptutor.api.utils.http_headers import content_disposition
from deeptutor.multi_user.paths import get_current_path_service
from deeptutor.services.office_preview import (
    MAX_OFFICE_BYTES,
    OFFICE_SUFFIXES,
    OfficePreviewConversionFailed,
    OfficePreviewInvalid,
    OfficePreviewTimeout,
    OfficePreviewUnavailable,
    render_office_pdf,
)
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.models import WorkspaceError

router = APIRouter()


def _source_path(source: str, request: Request) -> tuple[Path, str, Path]:
    """Resolve only local URLs using their existing authorization boundaries."""
    if len(source) > 8192:
        raise HTTPException(status_code=400, detail="Invalid preview source")
    parsed = urlsplit(source)
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith("/"):
        raise HTTPException(status_code=400, detail="Preview source must be a local file URL")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(
        name not in {"dt_workspace", "workspace", "resource_library"} or len(values) != 1
        for name, values in query.items()
    ):
        raise HTTPException(status_code=400, detail="Invalid preview source query")
    pinned_scope = query.get("dt_workspace", [None])[0]
    legacy_scope = query.get("workspace", [None])[0]
    if pinned_scope is not None and legacy_scope is not None and pinned_scope != legacy_scope:
        raise HTTPException(status_code=400, detail="Conflicting workspace scopes")
    inner_scope = pinned_scope if pinned_scope is not None else legacy_scope
    outer_scopes = request.query_params.getlist("dt_workspace")
    if len(outer_scopes) > 1:
        raise HTTPException(status_code=400, detail="Conflicting workspace scopes")
    outer_scope = outer_scopes[0] if outer_scopes else request.headers.get("x-deeptutor-workspace")
    if inner_scope is not None and outer_scope is not None and inner_scope != outer_scope:
        raise HTTPException(status_code=400, detail="Conflicting workspace scopes")
    library = query.get("resource_library", ["false"])[0]
    if library not in {"true", "false"}:
        raise HTTPException(status_code=400, detail="Invalid preview source query")
    if library == "true" and not parsed.path.startswith("/api/knowledge-bases/"):
        raise HTTPException(status_code=400, detail="Invalid preview source query")

    # The authentication dependency selects the outer request scope. Historic
    # file URLs may carry only an inner scope, so restore that scope here after
    # auth; workspace_context validates that it belongs to the caller.
    if library == "true":
        # The canonical knowledge-base route selects the account library,
        # independent of the currently selected content workspace.
        context = workspace_context("")
    elif inner_scope is not None and outer_scope is None:
        context = workspace_context(inner_scope)
    else:
        context = nullcontext()
    canonical_path = unquote(parsed.path)
    _assert_surface("reading" if canonical_path.startswith("/api/knowledge-bases/") else "chat")
    try:
        with context:
            target, filename = _resolve_authorized_file(canonical_path, query)
            return target, filename, _cache_dir()
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail="Preview source not found") from exc


def _resolve_authorized_file(path: str, query: dict[str, list[str]]) -> tuple[Path, str]:
    if match := re.fullmatch(r"/files/attachments/([^/]+)/([^/]+)/([^/]+)", path):
        from deeptutor.services.storage import LocalDiskAttachmentStore, get_attachment_store

        store = get_attachment_store()
        if not isinstance(store, LocalDiskAttachmentStore):
            raise HTTPException(status_code=501, detail="Attachment backend not servable")
        target = store.resolve_path(
            session_id=match.group(1), attachment_id=match.group(2), filename=match.group(3)
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Preview source not found")
        return target, match.group(3)

    if path.startswith("/files/outputs/"):
        from deeptutor.api.routers.outputs import (
            _request_path_service,
            _resolve_output,
            _resolve_partner_output,
        )

        relative = path.removeprefix("/files/outputs/")
        try:
            target = _resolve_output(_request_path_service(), relative)
        except HTTPException:
            target = _resolve_partner_output(relative)
            if target is None:
                raise HTTPException(status_code=404, detail="Preview source not found")
        return target, target.name

    if match := re.fullmatch(r"/files/workspace-items/([^/]+)/([^/]+)", path):
        from deeptutor.api.routers.workspace import _resolve_partner_item
        from deeptutor.services.workspace import get_content_workspace_service

        try:
            target, item = get_content_workspace_service().resolve_published_item(*match.groups())
        except WorkspaceError:
            resolved = _resolve_partner_item(*match.groups())
            if resolved is None:
                raise HTTPException(status_code=404, detail="Preview source not found")
            target, item = resolved
        return target, item.filename

    if match := re.fullmatch(r"/api/knowledge-bases/([^/]+)/files/(.+)", path):
        from deeptutor.api.routers.knowledge import _resolve_kb_raw_file_or_404
        from deeptutor.services.workspace.knowledge import library_request

        library = query.get("resource_library", ["false"])[0]
        token = library_request.set(library == "true")
        try:
            target = _resolve_kb_raw_file_or_404(match.group(1), match.group(2))
        finally:
            library_request.reset(token)
        return target, target.name

    raise HTTPException(status_code=400, detail="Unsupported preview source URL")


def _cache_dir() -> Path:
    return get_current_path_service().get_user_root() / "cache" / "office_previews"


def _read_bounded(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            return source.read(MAX_OFFICE_BYTES + 1)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Preview source not found") from exc


def _assert_surface(surface: str) -> None:
    from deeptutor.multi_user.learning_access import assert_learning_surface

    try:
        assert_learning_surface(surface)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _pdf_response(data: bytes, filename: str, cache_dir: Path) -> Response:
    if Path(filename).suffix.lower() not in OFFICE_SUFFIXES:
        raise HTTPException(status_code=415, detail="Unsupported Office file type")
    try:
        pdf = await render_office_pdf(data, filename, cache_dir)
    except OfficePreviewInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OfficePreviewUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OfficePreviewTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except OfficePreviewConversionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    pdf_name = "".join(char if char.isprintable() else "_" for char in Path(filename).stem) + ".pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(pdf_name),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/pdf")
async def preview_office_source(source: str, request: Request) -> Response:
    """Render a file URL that this same authenticated user could open."""
    path, filename, cache_dir = _source_path(source, request)
    data = await asyncio.to_thread(_read_bounded, path)
    return await _pdf_response(data, filename, cache_dir)


@router.post("/pdf")
async def preview_office_upload(file: UploadFile = File(...)) -> Response:
    """Render a bounded pending Blob/data attachment that has no file URL."""
    _assert_surface("chat")
    filename = file.filename or ""
    if Path(filename).suffix.lower() not in OFFICE_SUFFIXES:
        raise HTTPException(status_code=415, detail="Unsupported Office file type")
    try:
        data = await file.read(MAX_OFFICE_BYTES + 1)
    finally:
        await file.close()
    return await _pdf_response(data, filename, _cache_dir())
