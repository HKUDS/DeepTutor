"""HTTP endpoints for the Persistent File Library (issue #1437).

URL shape::

    GET   /files/library/              — list files (newest first)
    POST  /files/library/              — upload a file (multipart)
    GET   /files/library/search        — search by filename (query param: q)
    GET   /files/library/{file_id}     — get one entry
    GET   /files/library/{file_id}/download  — download the file
    DELETE /files/library/{file_id}     — soft-delete a file
    POST  /files/library/{file_id}/restore    — restore a soft-deleted file

The library is scoped to the authenticated user (via ``require_auth``) so
each user sees only their own files.
"""

from __future__ import annotations

import logging
import mimetypes

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.auth import TokenPayload
from deeptutor.services.storage import file_library as _fl

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_store():
    """Resolve the store at call time so tests can monkey-patch ``_fl``."""
    return _fl.get_file_library_store()


def _mime_type(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


# ── endpoints ──────────────────────────────────────────────────────────────


@router.get("/", operation_id="library_list")
async def list_library_files(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _auth: TokenPayload = Depends(require_auth),
) -> list[dict]:
    """List active library entries, newest first."""
    return await _get_store().list_files(limit=limit, offset=offset)


@router.post("/", operation_id="library_add")
async def add_library_file(
    filename: str = File(..., description="Original filename"),
    mime_type: str = Form(""),
    file: bytes = File(..., description="Raw file bytes"),
    _auth: TokenPayload = Depends(require_auth),
) -> dict:
    """Add a file to the library.

    The request must be ``multipart/form-data`` with a ``file`` field containing
    the raw bytes.  If a file with the same SHA-256 content hash already exists
    in the library, returns the existing entry (deduplication).
    """
    entry = await _get_store().add_file(
        data=file,
        filename=filename,
        mime_type=mime_type,
    )
    return entry


@router.get("/search", operation_id="library_search")
async def search_library_files(
    q: str = Query(..., min_length=1, max_length=200),
    _auth: TokenPayload = Depends(require_auth),
) -> list[dict]:
    """Search library entries by filename (case-insensitive substring)."""
    return await _get_store().search_files(query=q)


@router.get("/{file_id}", operation_id="library_get")
async def get_library_file(
    file_id: str,
    _auth: TokenPayload = Depends(require_auth),
) -> dict:
    """Get a single library entry by id (includes soft-deleted)."""
    entry = await _get_store().get_file(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")
    return entry


@router.get("/{file_id}/download", operation_id="library_download")
async def download_library_file(
    file_id: str,
    _auth: TokenPayload = Depends(require_auth),
) -> FileResponse:
    """Download a library file by id."""
    store = _get_store()
    entry = await store.get_file(file_id)
    if entry is None or entry.get("is_deleted"):
        raise HTTPException(status_code=404, detail="File not found")

    path = store.resolve_path(file_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_type = _mime_type(entry["filename"])
    return FileResponse(
        path,
        media_type=media_type,
        filename=entry["filename"],
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.head("/{file_id}/download", operation_id="library_download_head")
async def download_library_file_head(
    file_id: str,
    _auth: TokenPayload = Depends(require_auth),
) -> None:
    """Check whether a library file exists (HEAD only)."""
    store = _get_store()
    entry = await store.get_file(file_id)
    if entry is None or entry.get("is_deleted"):
        raise HTTPException(status_code=404, detail="File not found")
    path = store.resolve_path(file_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")


@router.delete("/{file_id}", operation_id="library_delete")
async def delete_library_file(
    file_id: str,
    _auth: TokenPayload = Depends(require_auth),
) -> dict:
    """Soft-delete a library file (sets is_deleted=1)."""
    deleted = await _get_store().delete_file(file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"id": file_id, "deleted": True}


@router.post("/{file_id}/restore", operation_id="library_restore")
async def restore_library_file(
    file_id: str,
    _auth: TokenPayload = Depends(require_auth),
) -> dict:
    """Restore a soft-deleted library file."""
    restored = await _get_store().restore_file(file_id)
    if not restored:
        raise HTTPException(status_code=404, detail="File not found")
    return {"id": file_id, "restored": True}
