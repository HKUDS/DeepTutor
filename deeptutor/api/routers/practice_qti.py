"""QTI item-bank import and export for the practice bank.

Import covers QTI 3.0 and the 2.1/2.2 dialects, all read through the same
canonical QuestionDocument. Export is deliberately narrower: text-only QTI
3.0, so a package can never reference media this deployment cannot store.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from deeptutor.services.practice.qti_exchange import QTI_MAX_BYTES, QtiExchange
from deeptutor.services.practice.storage import PracticeStore
from deeptutor.services.session import get_sqlite_session_store

router = APIRouter()


class QtiCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")
    selected: list[str] = Field(min_length=1, max_length=500)


class QtiExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_ids: list[int] = Field(min_length=1, max_length=500)
    version: Literal["3.0"] = "3.0"
    format: Literal["xml", "zip"] = "zip"


def _store() -> PracticeStore:
    return PracticeStore(get_sqlite_session_store().db_path)


def _download(data: bytes, media: str, filename: str) -> Response:
    return Response(
        content=data,
        media_type=media,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/import/qti/preview")
async def qti_import_preview(
    file: UploadFile = File(...),
    target: Literal["bank", "mistakes"] = Form("bank"),
):
    try:
        data = await file.read(QTI_MAX_BYTES + 1)
        return await QtiExchange(_store()).preview(data, file.filename or "", target=target)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()


@router.get("/import/qti/previews/{token}")
async def qti_preview_report(token: str):
    try:
        return await QtiExchange(_store()).report(token)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/import/qti/previews/{token}/source")
async def qti_preview_source(token: str):
    try:
        data, filename = await QtiExchange(_store()).source(token)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _download(data, "application/octet-stream", filename)


@router.post("/import/qti/commit")
async def qti_import_commit(payload: QtiCommitRequest):
    try:
        return await QtiExchange(_store()).commit(payload.token, payload.selected)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/export/qti")
async def qti_export(payload: QtiExportRequest):
    try:
        data, media, filename = await QtiExchange(_store()).export(
            payload.entry_ids, version=payload.version, fmt=payload.format
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _download(data, media, filename)
