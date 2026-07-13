"""
Book Engine API Router
======================

REST + WebSocket endpoints for the ``BookEngine``. Phase 1 surface:
create / confirm / compile / read / delete + a per-book event stream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from deeptutor.book import (
    BlockType,
    BookProposal,
    Spine,
    get_book_engine,
)
from deeptutor.book.models import ContentType
from deeptutor.book.streaming import SOURCE as BOOK_SOURCE
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────


class CreateBookRequest(BaseModel):
    user_intent: str = Field(default="")
    chat_session_id: str = Field(default="")
    chat_selections: list[dict[str, Any]] = Field(default_factory=list)
    notebook_refs: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_bases: list[str] = Field(default_factory=list)
    question_categories: list[int] = Field(default_factory=list)
    question_entries: list[int] = Field(default_factory=list)
    language: str = Field(default="en")


class ConfirmProposalRequest(BaseModel):
    book_id: str
    proposal: dict[str, Any] | None = None  # full edited BookProposal payload


class ConfirmSpineRequest(BaseModel):
    book_id: str
    spine: dict[str, Any] | None = None
    auto_compile: bool = True


class CompilePageRequest(BaseModel):
    book_id: str
    page_id: str
    force: bool = False


class RegenerateBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    params_override: dict[str, Any] | None = None


class InsertBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_type: str
    params: dict[str, Any] | None = None
    position: int | None = None
    compile_now: bool = True


class DeleteBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str


class MoveBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    new_position: int


class ChangeBlockTypeRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    new_type: str
    params_override: dict[str, Any] | None = None


class DeepDiveRequest(BaseModel):
    book_id: str
    parent_page_id: str
    topic: str
    block_id: str | None = None
    content_type: str = "concept"


class QuizAttemptRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    question_id: str = ""
    user_answer: str = ""
    is_correct: bool = False
    request_remediation: bool = False


class SupplementRequest(BaseModel):
    book_id: str
    page_id: str
    topic: str


class PageChatSessionRequest(BaseModel):
    book_id: str
    page_id: str
    session_id: str


class RebuildBookRequest(BaseModel):
    book_id: str
    auto_compile: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "book"}


@router.get("/books")
async def list_books() -> dict[str, Any]:
    engine = get_book_engine()
    return {"books": [b.model_dump(mode="json") for b in engine.list_books()]}


@router.get("/books/{book_id}")
async def get_book(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    book = engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    spine = engine.load_spine(book_id)
    pages = engine.list_pages(book_id)
    progress = engine.load_progress(book_id)
    return {
        "book": book.model_dump(mode="json"),
        "spine": spine.model_dump(mode="json") if spine else None,
        "pages": [p.model_dump(mode="json") for p in pages],
        "progress": progress.model_dump(mode="json"),
    }


@router.get("/books/{book_id}/spine")
async def get_spine(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    spine = engine.load_spine(book_id)
    if spine is None:
        raise HTTPException(status_code=404, detail="Spine not found")
    return {"spine": spine.model_dump(mode="json")}


@router.get("/books/{book_id}/pages/{page_id}")
async def get_page(book_id: str, page_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    page = engine.load_page(book_id, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"page": page.model_dump(mode="json")}


@router.delete("/books/{book_id}")
async def delete_book(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    ok = engine.delete_book(book_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"deleted": True, "book_id": book_id}


@router.post("/books")
async def create_book(req: CreateBookRequest) -> dict[str, Any]:
    """Stage 1: capture inputs + run IdeationAgent."""
    if not req.user_intent.strip():
        raise HTTPException(status_code=400, detail="user_intent is required")
    engine = get_book_engine()
    try:
        book, proposal = await engine.create_book(
            user_intent=req.user_intent,
            chat_session_id=req.chat_session_id,
            chat_selections=req.chat_selections,
            notebook_refs=req.notebook_refs,
            knowledge_bases=req.knowledge_bases,
            question_categories=req.question_categories,
            question_entries=req.question_entries,
            language=req.language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"create_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "book": book.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
    }


@router.post("/books/confirm-proposal")
async def confirm_proposal(req: ConfirmProposalRequest) -> dict[str, Any]:
    """Stage 2: user confirms (and possibly edits) the proposal → SpineAgent."""
    engine = get_book_engine()
    edited: BookProposal | None = None
    if req.proposal:
        try:
            edited = BookProposal.model_validate(req.proposal)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid proposal: {exc}")
    try:
        book, spine = await engine.confirm_proposal(book_id=req.book_id, edited_proposal=edited)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"confirm_proposal failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "book": book.model_dump(mode="json"),
        "spine": spine.model_dump(mode="json"),
    }


@router.post("/books/confirm-spine")
async def confirm_spine(req: ConfirmSpineRequest) -> dict[str, Any]:
    """Stage 3: user confirms the spine → create pending page shells."""
    engine = get_book_engine()
    edited: Spine | None = None
    if req.spine:
        try:
            edited = Spine.model_validate(req.spine)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spine: {exc}")
    try:
        pages = await engine.confirm_spine(
            book_id=req.book_id,
            edited_spine=edited,
            auto_compile=req.auto_compile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"confirm_spine failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages]}


@router.post("/books/compile-page")
async def compile_page(req: CompilePageRequest) -> dict[str, Any]:
    """Drive the compiler for the page the user just opened (current-page priority)."""
    engine = get_book_engine()
    try:
        page = await engine.compile_page(book_id=req.book_id, page_id=req.page_id, force=req.force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"compile_page failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"page": page.model_dump(mode="json")}


@router.post("/books/regenerate-block")
async def regenerate_block(req: RegenerateBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    try:
        block = await engine.regenerate_block(
            book_id=req.book_id,
            page_id=req.page_id,
            block_id=req.block_id,
            params_override=req.params_override,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"regenerate_block failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"block": block.model_dump(mode="json")}


def _coerce_block_type(name: str) -> BlockType:
    try:
        return BlockType(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown block type: {name}") from exc


def _coerce_content_type(name: str) -> ContentType:
    try:
        return ContentType(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {name}") from exc


@router.post("/books/insert-block")
async def insert_block(req: InsertBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    block_type = _coerce_block_type(req.block_type)
    try:
        block = await engine.insert_block(
            book_id=req.book_id,
            page_id=req.page_id,
            block_type=block_type,
            params=req.params,
            position=req.position,
            compile_now=req.compile_now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"insert_block failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Page or chapter not found")
    return {"block": block.model_dump(mode="json")}


@router.post("/books/delete-block")
async def delete_block(req: DeleteBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    ok = await engine.delete_block(book_id=req.book_id, page_id=req.page_id, block_id=req.block_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True}


@router.post("/books/move-block")
async def move_block(req: MoveBlockRequest) -> dict[str, Any]:
    engine = get_book_engine()
    ok = await engine.move_block(
        book_id=req.book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        new_position=req.new_position,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True}


@router.post("/books/change-block-type")
async def change_block_type(req: ChangeBlockTypeRequest) -> dict[str, Any]:
    engine = get_book_engine()
    new_type = _coerce_block_type(req.new_type)
    try:
        block = await engine.change_block_type(
            book_id=req.book_id,
            page_id=req.page_id,
            block_id=req.block_id,
            new_type=new_type,
            params_override=req.params_override,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"change_block_type failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"block": block.model_dump(mode="json")}


@router.post("/books/deep-dive")
async def deep_dive(req: DeepDiveRequest) -> dict[str, Any]:
    engine = get_book_engine()
    content_type = _coerce_content_type(req.content_type)
    try:
        page = await engine.create_deep_dive_subpage(
            book_id=req.book_id,
            parent_page_id=req.parent_page_id,
            topic=req.topic,
            block_id=req.block_id,
            content_type=content_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"deep_dive failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if page is None:
        raise HTTPException(status_code=404, detail="Parent page not found")
    return {"page": page.model_dump(mode="json")}


@router.post("/books/quiz-attempt")
async def quiz_attempt(req: QuizAttemptRequest) -> dict[str, Any]:
    engine = get_book_engine()
    progress = await engine.record_quiz_attempt(
        book_id=req.book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        question_id=req.question_id,
        user_answer=req.user_answer,
        is_correct=req.is_correct,
    )
    return {"progress": progress.model_dump(mode="json")}


@router.get("/books/{book_id}/health")
async def book_health(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    drift = engine.kb_drift_report(book_id)
    log = engine.log_health(book_id)
    return {"kb_drift": drift, "log_health": log}


@router.post("/books/{book_id}/refresh-fingerprints")
async def refresh_fingerprints(book_id: str) -> dict[str, Any]:
    engine = get_book_engine()
    result = engine.refresh_kb_fingerprints(book_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return result


@router.post("/books/supplement")
async def supplement(req: SupplementRequest) -> dict[str, Any]:
    engine = get_book_engine()
    try:
        block = await engine.supplement_for_weakness(
            book_id=req.book_id,
            page_id=req.page_id,
            topic=req.topic,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"supplement failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"block": block.model_dump(mode="json")}


@router.post("/books/page-chat-session")
async def set_page_chat_session(req: PageChatSessionRequest) -> dict[str, Any]:
    engine = get_book_engine()
    book = engine.set_page_chat_session(
        book_id=req.book_id,
        page_id=req.page_id,
        session_id=req.session_id,
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book or page not found")
    return {"book": book.model_dump(mode="json")}


@router.post("/books/rebuild")
async def rebuild_book(req: RebuildBookRequest) -> dict[str, Any]:
    engine = get_book_engine()
    try:
        pages = await engine.rebuild_book(book_id=req.book_id, auto_compile=req.auto_compile)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"rebuild_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages]}


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket – streamed Book events
# ─────────────────────────────────────────────────────────────────────────────


def _serialize_event(event) -> dict[str, Any]:
    return {
        "type": event.type.value if hasattr(event.type, "value") else str(event.type),
        "source": event.source,
        "stage": event.stage,
        "content": event.content,
        "metadata": event.metadata or {},
    }


@router.websocket("/ws")
async def book_websocket(ws: WebSocket) -> None:
    """Streaming endpoint.

    Client message protocol::

        {"type": "create",          ...CreateBookRequest fields}
        {"type": "confirm_proposal", "book_id": "...", "proposal": {...}}
        {"type": "confirm_spine",    "book_id": "...", "spine": {...}, "auto_compile": true}
        {"type": "compile_page",     "book_id": "...", "page_id": "..."}
        {"type": "regenerate_block", "book_id": "...", "page_id": "...", "block_id": "...", "params_override": {}}
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    await ws.accept()
    closed = False

    async def send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            await ws.send_json(data)
        except Exception:
            closed = True

    async def stream_into_socket(bus: StreamBus) -> asyncio.Task:
        async def _forward() -> None:
            async for event in bus.subscribe():
                if event.source != BOOK_SOURCE:
                    continue
                await send(_serialize_event(event))
                if event.type == StreamEventType.STAGE_END and event.stage in {
                    "ideation",
                    "spine",
                    "compilation",
                }:
                    pass  # keep streaming – multiple stages per task

        return asyncio.create_task(_forward())

    try:
        engine = get_book_engine()
        while not closed:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                break
            except Exception as exc:
                await send({"type": "error", "content": f"Bad message: {exc}"})
                continue

            msg_type = str(data.get("type") or "").strip()
            if not msg_type:
                await send({"type": "error", "content": "Missing 'type' field"})
                continue

            bus = StreamBus()
            forward_task = await stream_into_socket(bus)

            try:
                if msg_type == "create":
                    book, proposal = await engine.create_book(
                        user_intent=str(data.get("user_intent") or ""),
                        chat_session_id=str(data.get("chat_session_id") or ""),
                        chat_selections=data.get("chat_selections") or [],
                        notebook_refs=data.get("notebook_refs") or [],
                        knowledge_bases=data.get("knowledge_bases") or [],
                        question_categories=[
                            int(c) for c in (data.get("question_categories") or [])
                        ],
                        question_entries=[int(e) for e in (data.get("question_entries") or [])],
                        language=str(data.get("language") or "en"),
                        stream=bus,
                    )
                    await send(
                        {
                            "type": "create_result",
                            "book": book.model_dump(mode="json"),
                            "proposal": proposal.model_dump(mode="json"),
                        }
                    )

                elif msg_type == "confirm_proposal":
                    edited: BookProposal | None = None
                    if data.get("proposal"):
                        edited = BookProposal.model_validate(data["proposal"])
                    book, spine = await engine.confirm_proposal(
                        book_id=str(data.get("book_id") or ""),
                        edited_proposal=edited,
                        stream=bus,
                    )
                    await send(
                        {
                            "type": "confirm_proposal_result",
                            "book": book.model_dump(mode="json"),
                            "spine": spine.model_dump(mode="json"),
                        }
                    )

                elif msg_type == "confirm_spine":
                    edited_spine: Spine | None = None
                    if data.get("spine"):
                        edited_spine = Spine.model_validate(data["spine"])
                    pages = await engine.confirm_spine(
                        book_id=str(data.get("book_id") or ""),
                        edited_spine=edited_spine,
                        auto_compile=bool(data.get("auto_compile", True)),
                        stream=bus,
                    )
                    await send(
                        {
                            "type": "confirm_spine_result",
                            "pages": [p.model_dump(mode="json") for p in pages],
                        }
                    )

                elif msg_type == "compile_page":
                    page = await engine.compile_page(
                        book_id=str(data.get("book_id") or ""),
                        page_id=str(data.get("page_id") or ""),
                        stream=bus,
                        force=bool(data.get("force", False)),
                    )
                    await send(
                        {
                            "type": "compile_page_result",
                            "page": page.model_dump(mode="json"),
                        }
                    )

                elif msg_type == "regenerate_block":
                    block = await engine.regenerate_block(
                        book_id=str(data.get("book_id") or ""),
                        page_id=str(data.get("page_id") or ""),
                        block_id=str(data.get("block_id") or ""),
                        params_override=data.get("params_override"),
                        stream=bus,
                    )
                    await send(
                        {
                            "type": "regenerate_block_result",
                            "block": block.model_dump(mode="json") if block else None,
                        }
                    )

                else:
                    await send({"type": "error", "content": f"Unknown message type: {msg_type}"})

            except Exception as exc:
                logger.error(f"book ws action {msg_type} failed: {exc}", exc_info=True)
                await send({"type": "error", "content": str(exc)})
            finally:
                await bus.close()
                forward_task.cancel()
                try:
                    await forward_task
                except (asyncio.CancelledError, Exception):
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Book WS connection error: {exc}", exc_info=True)
    finally:
        closed = True
        try:
            await ws.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
