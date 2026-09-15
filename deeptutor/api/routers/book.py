"""
Book Engine API Router
======================

REST + WebSocket endpoints for the ``BookEngine``. Phase 1 surface:
create / confirm / compile / read / delete + a per-book event stream.
"""

from __future__ import annotations

_MAX_RECITATION_AUDIO_BYTES = 25 * 1024 * 1024

import asyncio
import hashlib
import logging
import time
from typing import Any, Literal
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin_or_teacher
from deeptutor.api.utils.http_headers import content_disposition
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.book import progress as progress_ops
from deeptutor.book.backfill import (
    BackfillJob,
    fail_backfill_job,
    get_backfill_job,
    plan_backfill,
    run_backfill,
)
from deeptutor.book.errors import BookPausedError
from deeptutor.book.export import export_filename, render_book_markdown
from deeptutor.book.importer import TocImportError, layout_to_spine, toc_to_spine
from deeptutor.book.models import (
    BlockStatus,
    BlockType,
    Book,
    BookProposal,
    BookStatus,
    ContentType,
    LearningCapture,
    LearningCaptureStatus,
    Page,
    PageStatus,
    Spine,
)
from deeptutor.book.recitation import (
    resolve_target_lines,
    score_recitation,
    stt_failed_attempt,
    update_recitation_summary,
)
from deeptutor.book.storage import get_book_storage, resolve_book_storage_layer
from deeptutor.book.streaming import SOURCE as BOOK_SOURCE
from deeptutor.multi_user.audit import log_admin_action, log_usage
from deeptutor.multi_user.book_access import (
    ResolvedBook,
    accessible_books,
    book_share_grants,
    can_create_book,
    resolve_book,
    share_candidate_users,
)
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.identity import (
    get_user,
    get_user_by_id,
    remove_book_permission_overrides,
    set_book_grant,
)
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.auth import TokenPayload
from deeptutor.services.voice import transcribe_audio

router = APIRouter()
ws_router = APIRouter()
logger = logging.getLogger(__name__)


def get_book_engine():
    """Resolve the large compilation engine only when a book route uses it."""

    from deeptutor.book.engine import get_book_engine as resolve

    return resolve()


def _book_paused_http(exc: BookPausedError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "book_paused", "message": str(exc)},
    )


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
    fallback_language: str = Field(default="en")
    depth: str = Field(default="standard")


class ConfirmProposalRequest(BaseModel):
    book_id: str
    proposal: dict[str, Any] | None = None  # full edited BookProposal payload
    expected_revision: int | None = Field(default=None, ge=1)


class ConfirmSpineRequest(BaseModel):
    book_id: str
    spine: dict[str, Any] | None = None
    auto_compile: bool = True
    block_types: list[str] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class SpineImportRequest(BaseModel):
    """Import a textbook TOC as the spine (deterministic, no SpineAgent)."""

    book_id: str
    toc: list[dict[str, Any]] | None = None  # recursive: [{title, children?}]
    layout: dict[str, Any] | None = None  # MinerU layout.json → 页脚法重建
    source: str = "toc_json"  # "toc_json" | "layout_json"
    auto_compile: bool = False


class ImportedPageSpec(BaseModel):
    """One page of a bulk pages-import: title + verbatim blocks."""

    title: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class PagesImportRequest(BaseModel):
    """Bulk-import verbatim pages under one chapter (zero-LLM canon channel)."""

    book_id: str
    chapter_id: str
    pages: list[ImportedPageSpec]
    mark_ready: bool = True  # pages whose blocks are all READY become READY


class CanonicalizeChapterSpec(BaseModel):
    """Verbatim pages destined for one chapter of the imported spine.

    The chapter is addressed by its position in the flattened TOC
    (``chapter_index``) or by exact title (``chapter_title``); ids are not
    knowable to the caller because the spine is created by this same call.
    """

    chapter_index: int | None = Field(default=None, ge=0)
    chapter_title: str = ""
    pages: list[ImportedPageSpec] = Field(default_factory=list)


class CanonicalizeRequest(BaseModel):
    """One-shot textbook canonicalization: book + spine + verbatim pages.

    Deterministic end to end — the IdeationAgent and SpineAgent never run, so
    every title comes from the textbook itself. This is the orchestrator's
    single entry point: what would otherwise be three calls (create, spine
    import, pages import) with two round-trips to learn the generated ids.
    """

    title: str
    description: str = ""
    toc: list[dict[str, Any]] | None = None
    layout: dict[str, Any] | None = None
    source: str = "toc_json"  # "toc_json" | "layout_json"
    language: str = "zh"
    knowledge_bases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chapters: list[CanonicalizeChapterSpec] = Field(default_factory=list)
    mark_ready: bool = True


class CompilePageRequest(BaseModel):
    book_id: str
    page_id: str
    force: bool = False
    expected_revision: int | None = Field(default=None, ge=1)


class RegenerateBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    params_override: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class InsertBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_type: str
    params: dict[str, Any] | None = None
    position: int | None = None
    compile_now: bool = True
    expected_revision: int | None = Field(default=None, ge=1)


class DeleteBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    expected_revision: int | None = Field(default=None, ge=1)


class MoveBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    new_position: int
    expected_revision: int | None = Field(default=None, ge=1)


class ChangeBlockTypeRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    new_type: str
    params_override: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class DeepDiveRequest(BaseModel):
    book_id: str
    parent_page_id: str
    topic: str
    block_id: str | None = None
    content_type: str = "concept"
    expected_revision: int | None = Field(default=None, ge=1)


class QuizAttemptRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    question_id: str = ""
    user_answer: str = ""
    # ``None`` = revealed but not graded (a written answer the reader skipped
    # self-assessing). Distinct from ``False``, which means they got it wrong.
    is_correct: bool | None = None


def _focus_check_question(
    questions: list[dict[str, Any]], requested_id: str, block_id: str
) -> tuple[str, dict[str, Any]] | None:
    """Resolve the durable question behind a Focus-Check submission."""
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id") or "").strip()
        if requested_id and question_id == requested_id:
            return question_id, question
        if not requested_id and not question_id:
            return f"{block_id}:{index + 1}", question
    if requested_id:
        return requested_id, {}
    return None


class UpdateBlockRequest(BaseModel):
    book_id: str
    page_id: str
    block_id: str
    title: str | None = None
    body: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class ProgressRequest(BaseModel):
    book_id: str
    page_id: str


class SupplementRequest(BaseModel):
    book_id: str
    page_id: str
    topic: str
    expected_revision: int | None = Field(default=None, ge=1)


class PageChatSessionRequest(BaseModel):
    book_id: str
    page_id: str
    session_id: str


class RebuildBookRequest(BaseModel):
    book_id: str
    auto_compile: bool = True
    block_types: list[str] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class ResumeBookRequest(BaseModel):
    book_id: str
    expected_revision: int | None = Field(default=None, ge=1)


class PauseBookRequest(BaseModel):
    book_id: str
    expected_revision: int | None = Field(default=None, ge=1)


def _auth_enabled() -> bool:
    from deeptutor.services.auth import AUTH_ENABLED

    return bool(AUTH_ENABLED)


def _resolve_book_or_404(
    book_id: str,
    *,
    edit: bool = False,
    delete: bool = False,
) -> ResolvedBook:
    resolved = resolve_book(book_id)
    # Several embedders and focused tests run the router without auth and
    # inject an engine directly. Preserve that single-user extension point.
    if resolved is None and not _auth_enabled():
        engine = get_book_engine()
        if engine.load_book(book_id) is not None:
            storage = getattr(engine, "storage", get_book_storage())
            resolved = ResolvedBook(
                engine=engine,
                source="own",
                permission="edit",
                can_edit=True,
                can_delete=True,
                learning=storage,
            )
    if resolved is None:
        raise HTTPException(status_code=404, detail="Book not found")
    # Denials deliberately use the same 404 as an unknown id so an untrusted
    # caller cannot probe which shared books exist.
    if edit and not resolved.can_edit:
        raise HTTPException(status_code=404, detail="Book not found")
    if delete and not resolved.can_delete:
        raise HTTPException(status_code=404, detail="Book not found")
    return resolved


def _book_payload(book: Any, resolved: ResolvedBook) -> dict[str, Any]:
    data = book.model_dump(mode="json")
    data.update(resolved.capabilities())
    if resolved.is_shared:
        metadata = dict(data.get("metadata") or {})
        metadata["page_chat_sessions"] = resolved.learning.load_page_chat_sessions(book.id)
        data["metadata"] = metadata
    return data


class ShareBookRequest(BaseModel):
    user_id: str
    level: Literal["read", "edit"]


def _require_share_owner(book_id: str) -> ResolvedBook:
    """Only the owner of a personal book may manage who it is shared with.

    Every denial — unknown book, another user's book, auth off — answers with
    the same 404 an unknown id gets, so the share surface cannot be probed
    either for a book's existence or for who owns it.
    """

    if not _auth_enabled():
        raise HTTPException(status_code=404, detail="Book not found")
    resolved = _resolve_book_or_404(book_id)
    if resolved.source != "own":
        raise HTTPException(status_code=404, detail="Book not found")
    return resolved


def _resolve_share_target(raw_user_id: str) -> tuple[str, dict[str, Any]]:
    """Resolve the ACL target account, accepting username or account id.

    Returns the users.json key (username) plus its record; raises 404 when no
    account matches, so a typo'd target never silently no-ops.
    """

    raw = (raw_user_id or "").strip()
    record = get_user(raw) if raw else None
    if record is not None:
        return raw, record
    found = get_user_by_id(raw)
    if found is not None:
        return found
    raise HTTPException(status_code=404, detail="User not found")


@router.get("/books/{book_id}/share")
async def list_book_shares(book_id: str) -> dict[str, Any]:
    _require_share_owner(book_id)
    return {
        "book_id": book_id,
        "shares": book_share_grants(book_id),
        "candidates": share_candidate_users(),
    }


@router.post("/books/{book_id}/share")
async def share_book(book_id: str, req: ShareBookRequest) -> dict[str, Any]:
    _require_share_owner(book_id)
    username, record = _resolve_share_target(req.user_id)
    user = get_current_user()
    if username == user.username:
        raise HTTPException(status_code=400, detail="Cannot share a book with yourself")
    if str(record.get("role") or "user") == "admin":
        raise HTTPException(status_code=400, detail="Admin accounts already access every book")
    if bool(record.get("disabled", False)):
        raise HTTPException(status_code=404, detail="User not found")
    # Explicitly per-user, per-level; there is deliberately no public or
    # role-wide mode here. The grant lands in the target's existing
    # book_permission record, so admin-set defaults survive untouched.
    if not set_book_grant(username, book_id, req.level):
        raise HTTPException(status_code=404, detail="User not found")
    log_usage(
        "book",
        book_id,
        "book_share",
        {"target_user_id": str(record.get("id") or ""), "level": req.level},
    )
    return {
        "book_id": book_id,
        "user_id": str(record.get("id") or ""),
        "username": username,
        "level": req.level,
    }


@router.delete("/books/{book_id}/share/{user_id}")
async def revoke_book_share(book_id: str, user_id: str) -> dict[str, Any]:
    _require_share_owner(book_id)
    username, record = _resolve_share_target(user_id)
    set_book_grant(username, book_id, "none")
    log_usage(
        "book",
        book_id,
        "book_share_revoke",
        {"target_user_id": str(record.get("id") or "")},
    )
    return {
        "book_id": book_id,
        "user_id": str(record.get("id") or ""),
        "username": username,
        "revoked": True,
    }


def _claim_content_mutation(
    resolved: ResolvedBook,
    book_id: str,
    expected_revision: int | None,
    action: str,
    *,
    extra: dict[str, Any] | None = None,
    strict: bool = True,
) -> int:
    """Reserve the next canonical revision before a content mutation.

    Shared editors must prove which snapshot they edited. Personal books and
    admin operations stay backward compatible, but still advance the token so
    a later shared editor detects the intervening change.

    ``strict=False`` is for *generation commands* — compile this chapter,
    pause, resume. Those overwrite nobody's writing: a chapter shell fills
    itself in, and two readers both asking for it is not a conflict (the
    engine coalesces them onto one run). Guarding them was actively harmful,
    because generation advances the revision itself: ``confirm_spine`` claims
    a token and then queues the compile that the very next request has to
    match, so the first chapter of every book failed with a conflict against
    its own predecessor. They still claim a revision — a later shared edit
    should know the book moved — they just do not refuse a stale one.
    """

    book = resolved.engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    current = max(1, int(book.revision or 1))
    if strict and resolved.is_shared and expected_revision is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "book_revision_required",
                "message": "Refresh the shared book before editing.",
                "current_revision": current,
            },
        )
    if strict and expected_revision is not None and expected_revision != current:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "book_revision_conflict",
                # A personal book has no collaborators, so blaming one was a
                # lie the reader could not act on. Same guard, honest cause:
                # their view is simply behind the book.
                "message": (
                    "The book was updated by another collaborator."
                    if resolved.is_shared
                    else "This book changed since your last action — reloading the latest version."
                ),
                "expected_revision": expected_revision,
                "current_revision": current,
            },
        )

    book.revision = current + 1
    book.updated_at = time.time()
    storage = getattr(resolved.engine, "storage", None)
    if storage is None:
        # Lightweight embedded engines used by SDK hosts may not expose their
        # persistence object; they are single-user and have no shared writes.
        return current
    storage.save_book(book)
    summary = {
        "book_id": book_id,
        "action": action,
        "before_revision": current,
        "after_revision": book.revision,
        **(extra or {}),
    }
    if resolved.is_shared:
        log_usage("book", book_id, "shared_edit", summary)
    elif get_current_user().is_admin:
        log_admin_action("book_edit", summary=summary)
    return book.revision


def _normalize_block_types(values: list[str]) -> list[str]:
    normalized = [BlockType.SECTION.value]
    seen = {BlockType.SECTION}
    for value in values:
        try:
            block_type = BlockType(value.strip().lower())
        except ValueError:
            continue
        if block_type in seen:
            continue
        seen.add(block_type)
        normalized.append(block_type.value)
    return normalized


def _persist_requested_block_types(
    resolved: ResolvedBook,
    book_id: str,
    requested: list[str] | None,
) -> None:
    if requested is None:
        return

    book = resolved.engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    metadata = dict(book.metadata or {})
    if requested:
        metadata["block_types"] = _normalize_block_types(requested)
    else:
        metadata.pop("block_types", None)
    book.metadata = metadata
    book.updated_at = time.time()
    storage = getattr(resolved.engine, "storage", None) or get_book_storage()
    storage.save_book(book)


def _normalize_capture_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _build_capture_hash(book_id: str, page_id: str, block_id: str, locator: str, text: str) -> str:
    payload = "|".join(
        [
            book_id,
            page_id,
            block_id,
            locator,
            _normalize_capture_text(text),
        ],
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _coerce_capture_status(raw: str | None) -> LearningCaptureStatus | None:
    if raw is None:
        return None
    try:
        return LearningCaptureStatus(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid capture status: {raw}",
        ) from exc


_CAPTURE_TRANSITIONS: dict[LearningCaptureStatus, set[LearningCaptureStatus]] = {
    LearningCaptureStatus.CAPTURED: {
        LearningCaptureStatus.CAPTURED,
        LearningCaptureStatus.DRAFTED,
        LearningCaptureStatus.PENDING_CONFIRMATION,
        LearningCaptureStatus.APPROVED,
        LearningCaptureStatus.REJECTED,
    },
    LearningCaptureStatus.DRAFTED: {
        LearningCaptureStatus.DRAFTED,
        LearningCaptureStatus.PENDING_CONFIRMATION,
        LearningCaptureStatus.APPROVED,
        LearningCaptureStatus.REJECTED,
    },
    LearningCaptureStatus.PENDING_CONFIRMATION: {
        LearningCaptureStatus.PENDING_CONFIRMATION,
        LearningCaptureStatus.APPROVED,
        LearningCaptureStatus.REJECTED,
    },
    LearningCaptureStatus.APPROVED: {
        LearningCaptureStatus.APPROVED,
        LearningCaptureStatus.DELIVERED,
    },
    LearningCaptureStatus.DELIVERED: {
        LearningCaptureStatus.DELIVERED,
        LearningCaptureStatus.IMPORTED,
    },
    LearningCaptureStatus.IMPORTED: {LearningCaptureStatus.IMPORTED},
    LearningCaptureStatus.REJECTED: {LearningCaptureStatus.REJECTED},
}


def _is_capture_transition_allowed(
    current: LearningCaptureStatus,
    requested: LearningCaptureStatus,
) -> bool:
    return requested in _CAPTURE_TRANSITIONS.get(current, set())


def _derive_capture_title_values(
    resolved: ResolvedBook,
    book_id: str,
    page_id: str,
    block_id: str,
) -> tuple[str, str, str]:
    engine = resolved.engine
    book = engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    page = engine.load_page(book_id, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    spine = engine.load_spine(book_id)
    chapter_title = page.title
    if spine is not None and page.chapter_id:
        for chapter in spine.chapters:
            if chapter.id == page.chapter_id:
                chapter_title = chapter.title
                break

    base_locator = f"/books/{book_id}/pages/{page_id}"
    source_locator = f"{base_locator}/block/{block_id}" if block_id else base_locator
    return book.title, chapter_title, source_locator


def _find_capture_duplicate(
    storage: Any,
    book_id: str,
    page_id: str,
    content_hash: str,
) -> LearningCapture | None:
    for capture in storage.load_learning_captures(book_id):
        if capture.page_id != page_id:
            continue
        if capture.content_hash != content_hash:
            continue
        if capture.status == LearningCaptureStatus.REJECTED:
            continue
        return capture
    return None


class LearningCaptureCreateRequest(BaseModel):
    page_id: str
    block_id: str = ""
    source_text: str
    context_before: str = ""
    context_after: str = ""
    source_locator: str = ""
    book_title: str = ""
    chapter_title: str = ""
    user_note: str = ""
    status: str | None = None


class LearningCaptureUpdateRequest(BaseModel):
    status: str | None = None
    user_note: str | None = None
    rejected_reason: str | None = None


def _capture_payload(capture: LearningCapture) -> dict[str, object]:
    return capture.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/books/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "book"}


@router.get("/books/estimate-basis")
async def estimate_basis(depth: str = "standard") -> dict[str, Any]:
    """Per-chapter generation cost, keyed by content type.

    The spine editor sums this over whatever chapters currently exist, so the
    estimate stays live while the user edits without a request per keystroke —
    and stays honest, because the numbers come from the same templates the
    architect plans from.
    """
    from deeptutor.book.estimate import chapter_basis

    return {"depth": depth, "basis": chapter_basis(depth)}


@router.get("/books/block-types")
async def block_types() -> dict[str, list[dict[str, str | bool]]]:
    from deeptutor.book.agents.page_planner import (
        PLANNABLE_BLOCK_TYPES,
        PLANNER_DEFAULT_BLOCK_TYPES,
    )

    return {
        "block_types": [
            {
                "value": block_type.value,
                "planner_default": block_type in PLANNER_DEFAULT_BLOCK_TYPES,
            }
            for block_type in sorted(PLANNABLE_BLOCK_TYPES, key=lambda item: item.value)
        ]
    }


@router.get("/books")
async def list_books() -> dict[str, Any]:
    def _collect() -> list[dict[str, Any]]:
        books: list[dict[str, Any]] = []
        for book, resolved in accessible_books():
            data = _book_payload(book, resolved)
            # Lets the library card say "continue reading" and show how far in
            # the reader is, instead of treating every book as untouched.
            data["reading"] = resolved.reading_summary(book)
            data["generation"] = resolved.engine.generation_overview(book)
            books.append(data)
        return books

    # One manifest read per book plus one progress read per book — off-loop.
    return {
        "books": await asyncio.to_thread(_collect),
        "can_create": can_create_book(),
    }


@router.get("/books/{book_id}/learning-captures")
async def list_learning_captures(
    book_id: str,
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    resolved = _resolve_book_or_404(book_id)

    parsed_status = _coerce_capture_status(status) if status is not None else None
    storage = resolved.learning
    captures = storage.load_learning_captures(book_id, status=parsed_status)
    return {"captures": [_capture_payload(capture) for capture in captures]}


@router.post("/books/{book_id}/learning-captures")
async def create_learning_capture(
    book_id: str,
    req: LearningCaptureCreateRequest,
) -> dict[str, Any]:
    resolved = _resolve_book_or_404(book_id)
    engine = resolved.engine

    page = engine.load_page(book_id, req.page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    source_text = _normalize_capture_text(req.source_text)
    if not source_text:
        raise HTTPException(status_code=400, detail="source_text is required")

    book_title, chapter_title, default_source_locator = _derive_capture_title_values(
        resolved=resolved,
        book_id=book_id,
        page_id=req.page_id,
        block_id=req.block_id,
    )

    source_locator = req.source_locator.strip() or default_source_locator
    status = _coerce_capture_status(req.status) or LearningCaptureStatus.CAPTURED

    content_hash = _build_capture_hash(
        book_id,
        req.page_id,
        req.block_id,
        source_locator,
        source_text,
    )

    storage = resolved.learning
    duplicate = _find_capture_duplicate(storage, book_id, req.page_id, content_hash)
    if duplicate is not None:
        return {"capture": _capture_payload(duplicate)}

    capture = LearningCapture(
        book_id=book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        source_text=source_text,
        context_before=_normalize_capture_text(req.context_before),
        context_after=_normalize_capture_text(req.context_after),
        source_locator=source_locator,
        book_title=req.book_title or book_title,
        chapter_title=req.chapter_title or chapter_title,
        user_note=req.user_note.strip(),
        content_hash=content_hash,
        status=status,
    )
    storage.upsert_learning_capture(capture)
    return {"capture": _capture_payload(capture)}


@router.patch("/books/{book_id}/learning-captures/{capture_id}")
async def update_learning_capture(
    book_id: str,
    capture_id: str,
    req: LearningCaptureUpdateRequest,
) -> dict[str, Any]:
    resolved = _resolve_book_or_404(book_id)
    storage = resolved.learning
    capture = storage.load_learning_capture(book_id, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Learning capture not found")

    requested_status = _coerce_capture_status(req.status) if req.status is not None else None
    if requested_status is not None and not _is_capture_transition_allowed(
        capture.status,
        requested_status,
    ):
        raise HTTPException(
            status_code=400,
            detail=(f"Invalid state transition: {capture.status} -> {requested_status}"),
        )

    changed = False
    updated = capture.model_copy(deep=True)

    if requested_status is not None and requested_status != capture.status:
        updated.status = requested_status
        changed = True
    if req.user_note is not None and req.user_note != capture.user_note:
        updated.user_note = req.user_note
        changed = True
    if req.rejected_reason is not None and req.rejected_reason != capture.rejected_reason:
        updated.rejected_reason = req.rejected_reason
        changed = True

    if not changed:
        return {"capture": _capture_payload(capture)}

    updated.version = capture.version + 1
    updated.updated_at = time.time()
    storage.upsert_learning_capture(updated)
    return {"capture": _capture_payload(updated)}


def _page_summary(page) -> dict[str, Any]:
    """Page metadata without block payloads.

    A compiled page carries its full rendered content — SVG, Mermaid, prose —
    so a book's blocks run to hundreds of kilobytes. Views that only need the
    chapter list (sidebar, library, progress) ask for summaries instead.
    """
    data = page.model_dump(mode="json")
    blocks = data.pop("blocks", []) or []
    data["block_count"] = len(blocks)
    data["blocks"] = []
    return data


@router.get("/books/{book_id}")
async def get_book(book_id: str, include_blocks: bool = True) -> dict[str, Any]:
    resolved = _resolve_book_or_404(book_id)
    engine = resolved.engine
    book = engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Opening a book is the correctly-scoped moment to notice that its
    # compilation died with a previous process and pick it back up.
    if not resolved.is_shared:
        await engine.maybe_resume_on_open(book_id)
    book = engine.load_book(book_id) or book

    def _read() -> tuple[Any, list[Any], Any]:
        return (
            engine.load_spine(book_id),
            engine.list_pages(book_id),
            resolved.load_progress(book_id),
        )

    # A compiled book is hundreds of KB across one file per page.
    spine, pages, progress = await asyncio.to_thread(_read)
    return {
        "book": _book_payload(book, resolved),
        "spine": spine.model_dump(mode="json") if spine else None,
        "pages": [
            (p.model_dump(mode="json") if include_blocks else _page_summary(p)) for p in pages
        ],
        "progress": progress.model_dump(mode="json"),
        "generation": engine.generation_summary(book_id, book=book, pages=pages),
    }


@router.get("/books/{book_id}/assets/{asset_path:path}")
async def get_book_asset(book_id: str, asset_path: str) -> FileResponse:
    """Serve a file from the book's ``assets/`` dir (figure backfill, P5).

    Mirrors the visualizer-asset route's hardening: ids are validated, the
    resolved path must stay inside the book root, and responses are nosniffed.
    """
    try:
        # A shared textbook's files live in the admin layer regardless of who
        # is asking — get_book_storage() would 404 every reader but the owner.
        root = resolve_book_storage_layer(book_id).book_root(book_id) / "assets"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target = (root / asset_path).resolve()
    if not str(target).startswith(str(root.resolve()) + "/"):
        raise HTTPException(status_code=400, detail="invalid asset path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(
        target,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/books/{book_id}/spine")
async def get_spine(book_id: str) -> dict[str, Any]:
    engine = _resolve_book_or_404(book_id).engine
    spine = engine.load_spine(book_id)
    if spine is None:
        raise HTTPException(status_code=404, detail="Spine not found")
    return {"spine": spine.model_dump(mode="json")}


@router.get("/books/{book_id}/pages/{page_id}")
async def get_page(book_id: str, page_id: str) -> dict[str, Any]:
    engine = _resolve_book_or_404(book_id).engine
    page = engine.load_page(book_id, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"page": page.model_dump(mode="json")}


@router.delete("/books/{book_id}")
async def delete_book(book_id: str) -> dict[str, Any]:
    resolved = _resolve_book_or_404(book_id, delete=True)
    engine = resolved.engine
    ok = engine.delete_book(book_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Book not found")
    if get_current_user().is_admin:
        affected = remove_book_permission_overrides(book_id)
        log_admin_action(
            "book_delete",
            summary={"book_id": book_id, "acl_users_cleaned": len(affected)},
        )
    elif resolved.source == "own" and _auth_enabled():
        # An owner-deleted personal book must not leave dangling peer grants.
        remove_book_permission_overrides(book_id)
    return {"deleted": True, "book_id": book_id}


@router.post("/books")
async def create_book(req: CreateBookRequest) -> dict[str, Any]:
    """Stage 1: capture inputs + run IdeationAgent."""
    if not req.user_intent.strip():
        raise HTTPException(status_code=400, detail="user_intent is required")
    if not can_create_book():
        raise HTTPException(status_code=403, detail="Book creation is not allowed")
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
            fallback_language=req.fallback_language,
            depth=req.depth,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"create_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "book": book.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
    }


async def _import_pages_into_chapter(
    engine: Any,
    book_id: str,
    spine: Spine,
    chapter: Any,
    specs: list[ImportedPageSpec],
    *,
    mark_ready: bool,
) -> list[Page]:
    """Create verbatim pages under ``chapter`` and return what was persisted.

    Shared by the bulk pages-import endpoint and the one-shot canonicalize
    endpoint. Blocks go through ``insert_block(compile_now=False)``, so
    verbatim generators (reading / user_note) materialize immediately and the
    compiler is never invoked.

    P5: reading bodies pass through ``delimit_bare_latex`` first so the bare
    LaTeX fragments MinerU leaves in Chinese prose render on the frontend
    KaTeX chain instead of leaking as raw text.
    """
    from deeptutor.book.latex_delimit import delimit_bare_latex

    created: list[Page] = []
    for spec in specs:
        page = Page(
            book_id=book_id,
            chapter_id=chapter.id,
            title=spec.title,
            content_type=chapter.content_type,
            order=chapter.order,
            status=PageStatus.PENDING,
        )
        engine.storage.save_page(page)
        chapter.page_ids.append(page.id)
        engine.storage.save_spine(spine)
        all_ready = True
        for blk in spec.blocks:
            params = dict(blk.get("params") or {})
            if str(blk.get("block_type") or "") == "reading" and isinstance(
                params.get("body"), str
            ):
                params["body"] = delimit_bare_latex(params["body"])
            block = await engine.insert_block(
                book_id=book_id,
                page_id=page.id,
                block_type=_coerce_block_type(str(blk.get("block_type") or "")),
                params=params,
                compile_now=False,
            )
            if block is None:
                raise ValueError(f"failed to insert block into page {page.id}")
            if block.status != BlockStatus.READY:
                all_ready = False
        if mark_ready and all_ready and spec.blocks:
            # Reload before promoting: insert_block persisted blocks onto the
            # stored page — the in-memory shell is stale now.
            saved = engine.storage.load_page(book_id, page.id)
            if saved is not None:
                saved.status = PageStatus.READY
                saved.updated_at = time.time()
                engine.storage.save_page(saved)
                created.append(saved)
                continue
        created.append(page)
    return created


@router.post("/books/canonicalize")
async def canonicalize_book(req: CanonicalizeRequest) -> dict[str, Any]:
    """Turn one parsed textbook into a canonical Book in a single call.

    Collapses create → spine import → pages import. Fully deterministic: the
    book title is the caller's, chapters come from the textbook's own TOC (or
    a MinerU layout via the running-header rebuild), and page blocks are
    verbatim. No agent invents anything, so an orchestrator can run this
    unattended over a shelf of books.
    """
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not can_create_book():
        raise HTTPException(status_code=403, detail="Book creation is not allowed")

    engine = get_book_engine()
    book = Book(
        title=title,
        description=req.description,
        status=BookStatus.DRAFT,
        knowledge_bases=list(req.knowledge_bases),
        language=req.language,
        metadata={**req.metadata, "canonical_source": req.source},
    )
    engine.storage.save_book(book)

    try:
        if req.source == "layout_json" or req.layout is not None:
            if req.layout is None:
                raise HTTPException(status_code=400, detail="source=layout_json requires layout")
            spine = layout_to_spine(book.id, req.layout, title=req.title)
        else:
            if not req.toc:
                raise HTTPException(status_code=400, detail="toc is required for source=toc_json")
            spine = toc_to_spine(book.id, req.toc)
    except TocImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        await engine.confirm_spine(book_id=book.id, edited_spine=spine, auto_compile=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"canonicalize spine import failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # Re-read: confirm_spine owns page-shell creation and may rewrite chapters,
    # so the ids the page import addresses must come from what was persisted.
    saved_spine = engine.load_spine(book.id) or spine

    chapter_reports: list[dict[str, Any]] = []
    pages_created = 0
    try:
        for spec in req.chapters:
            chapter = _resolve_canonical_chapter(saved_spine, spec)
            pages = await _import_pages_into_chapter(
                engine,
                book.id,
                saved_spine,
                chapter,
                spec.pages,
                mark_ready=req.mark_ready,
            )
            pages_created += len(pages)
            chapter_reports.append(
                {
                    "chapter_id": chapter.id,
                    "chapter_title": chapter.title,
                    "pages": [p.model_dump(mode="json") for p in pages],
                }
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(f"canonicalize pages import failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    final_spine = engine.load_spine(book.id) or saved_spine
    book.chapter_count = len(final_spine.chapters)
    book.page_count = pages_created
    # READY only once real content landed; a spine-only import stays DRAFT so
    # the library never advertises an empty book as readable.
    book.status = BookStatus.READY if pages_created else BookStatus.DRAFT
    book.updated_at = time.time()
    engine.storage.save_book(book)

    # P0: auto-cache the canonical KP tree. The textbook's doc_intel 目级 tree
    # (docstore doc_tree metadata from the source KBs) is the one import-from-book
    # prefers over the chapter-level mechanical sketch. Best-effort: no tree, a
    # degraded doc_tree tier, or any storage failure only logs a warning — the
    # canonicalized book itself is unaffected.
    from deeptutor.book.canonical_tree import (
        cache_canonical_tree_for_book,
        rebuild_canonical_tree_from_layout,
    )

    if not cache_canonical_tree_for_book(book.id, req.knowledge_bases, storage=engine.storage):
        # P7【1】inline rebuild: the KB docstore had no usable doc_tree (the
        # 大部头 downgraded-tier case the p1-cache-tree patch used to bridge by
        # hand). The request itself carries the MinerU layout, so rebuild the
        # doc_intel tree from its para_blocks right here — no patch script, no
        # restart. Only reached when the P0 path failed; failures are logged
        # and swallowed so canonicalization stays unaffected.
        rebuild_canonical_tree_from_layout(
            book.id,
            req.layout or {},
            filename=title,
            storage=engine.storage,
        )

    return {
        "book": book.model_dump(mode="json"),
        "spine": final_spine.model_dump(mode="json"),
        "chapters": chapter_reports,
        "pages_created": pages_created,
    }


def _resolve_canonical_chapter(spine: Spine, spec: CanonicalizeChapterSpec) -> Any:
    """Find the chapter a canonicalize page-group addresses, or 404."""
    if spec.chapter_index is not None:
        if spec.chapter_index >= len(spine.chapters):
            raise HTTPException(
                status_code=404,
                detail=f"chapter_index {spec.chapter_index} is out of range "
                f"({len(spine.chapters)} chapters)",
            )
        return spine.chapters[spec.chapter_index]
    wanted = spec.chapter_title.strip()
    if not wanted:
        raise HTTPException(
            status_code=400, detail="each chapter group needs chapter_index or chapter_title"
        )
    for chapter in spine.chapters:
        if chapter.title.strip() == wanted:
            return chapter
    raise HTTPException(status_code=404, detail=f"Chapter titled {wanted!r} not found")


@router.post("/books/confirm-proposal")
async def confirm_proposal(req: ConfirmProposalRequest) -> dict[str, Any]:
    """Stage 2: user confirms (and possibly edits) the proposal → SpineAgent."""
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "confirm_proposal",
    )
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
        "book_revision": revision,
    }


@router.post("/books/confirm-spine")
async def confirm_spine(req: ConfirmSpineRequest) -> dict[str, Any]:
    """Stage 3: user confirms the spine → create pending page shells."""
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "confirm_spine",
    )
    edited: Spine | None = None
    if req.spine:
        try:
            edited = Spine.model_validate(req.spine)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spine: {exc}")
    _persist_requested_block_types(resolved, req.book_id, req.block_types)
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
    return {"pages": [p.model_dump(mode="json") for p in pages], "book_revision": revision}


@router.post("/books/{book_id}/spine/import")
async def import_spine(book_id: str, req: SpineImportRequest) -> dict[str, Any]:
    """Import a textbook TOC as the book's spine (deterministic canon path).

    Complements the generated-spine flow: chapter titles come from the
    textbook's own table of contents instead of SpineAgent invention, then the
    confirmed-spine machinery (overview injection, page shells) runs unchanged.
    """
    engine = get_book_engine()
    if req.book_id != book_id:
        raise HTTPException(status_code=400, detail="book_id mismatch between path and body")
    try:
        if req.source == "layout_json" or req.layout is not None:
            if req.layout is None:
                raise HTTPException(status_code=400, detail="source=layout_json requires layout")
            spine = layout_to_spine(book_id, req.layout, title=req.title)
        else:
            if not req.toc:
                raise HTTPException(status_code=400, detail="toc is required for source=toc_json")
            spine = toc_to_spine(book_id, req.toc)
    except TocImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        pages = await engine.confirm_spine(
            book_id=book_id,
            edited_spine=spine,
            auto_compile=req.auto_compile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"spine import failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    saved = engine.load_spine(book_id)
    return {
        "pages": [p.model_dump(mode="json") for p in pages],
        "spine": saved.model_dump(mode="json") if saved else None,
    }


@router.post("/books/{book_id}/pages/import")
async def import_pages(book_id: str, req: PagesImportRequest) -> dict[str, Any]:
    """Bulk-import verbatim pages under one chapter (zero-LLM canon channel).

    Blocks are inserted through the standard insert-block machinery with
    ``compile_now=False``; verbatim generators (reading/user_note) materialize
    immediately, so pages whose blocks are all READY are marked READY without
    ever invoking the compiler.
    """
    engine = get_book_engine()
    spine = engine.load_spine(book_id)
    if spine is None:
        raise HTTPException(status_code=404, detail=f"No spine for book {book_id}")
    chapter = spine.chapter_by_id(req.chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Chapter {req.chapter_id} not found")

    created: list[Page] = []
    try:
        created = await _import_pages_into_chapter(
            engine,
            book_id,
            spine,
            chapter,
            req.pages,
            mark_ready=req.mark_ready,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(f"pages import failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in created]}


@router.post("/books/compile-page")
async def compile_page(req: CompilePageRequest) -> dict[str, Any]:
    """Drive the compiler for the page the user just opened (current-page priority)."""
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "compile_page",
        extra={"page_id": req.page_id, "force": req.force},
        # Generation command, not an edit — see `_claim_content_mutation`.
        strict=False,
    )
    try:
        page = await engine.compile_page(book_id=req.book_id, page_id=req.page_id, force=req.force)
    except BookPausedError as exc:
        raise _book_paused_http(exc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"compile_page failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"page": page.model_dump(mode="json"), "book_revision": revision}


@router.post("/books/regenerate-block")
async def regenerate_block(req: RegenerateBlockRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "regenerate_block",
        extra={"page_id": req.page_id, "block_id": req.block_id},
    )
    try:
        block = await engine.regenerate_block(
            book_id=req.book_id,
            page_id=req.page_id,
            block_id=req.block_id,
            params_override=req.params_override,
        )
    except BookPausedError as exc:
        raise _book_paused_http(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"regenerate_block failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"block": block.model_dump(mode="json"), "book_revision": revision}


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
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "insert_block",
        extra={"page_id": req.page_id, "block_type": req.block_type},
    )
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
    except BookPausedError as exc:
        raise _book_paused_http(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"insert_block failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Page or chapter not found")
    return {"block": block.model_dump(mode="json"), "book_revision": revision}


@router.post("/books/delete-block")
async def delete_block(req: DeleteBlockRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "delete_block",
        extra={"page_id": req.page_id, "block_id": req.block_id},
    )
    ok = await engine.delete_block(book_id=req.book_id, page_id=req.page_id, block_id=req.block_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True, "book_revision": revision}


@router.post("/books/move-block")
async def move_block(req: MoveBlockRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "move_block",
        extra={"page_id": req.page_id, "block_id": req.block_id},
    )
    ok = await engine.move_block(
        book_id=req.book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        new_position=req.new_position,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True, "book_revision": revision}


@router.post("/books/change-block-type")
async def change_block_type(req: ChangeBlockTypeRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "change_block_type",
        extra={"page_id": req.page_id, "block_id": req.block_id},
    )
    new_type = _coerce_block_type(req.new_type)
    try:
        block = await engine.change_block_type(
            book_id=req.book_id,
            page_id=req.page_id,
            block_id=req.block_id,
            new_type=new_type,
            params_override=req.params_override,
        )
    except BookPausedError as exc:
        raise _book_paused_http(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"change_block_type failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"block": block.model_dump(mode="json"), "book_revision": revision}


@router.post("/books/deep-dive")
async def deep_dive(req: DeepDiveRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "deep_dive",
        extra={"page_id": req.parent_page_id, "topic": req.topic},
    )
    content_type = _coerce_content_type(req.content_type)
    try:
        page = await engine.create_deep_dive_subpage(
            book_id=req.book_id,
            parent_page_id=req.parent_page_id,
            topic=req.topic,
            block_id=req.block_id,
            content_type=content_type,
        )
    except BookPausedError as exc:
        raise _book_paused_http(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"deep_dive failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if page is None:
        raise HTTPException(status_code=404, detail="Parent page not found")
    return {"page": page.model_dump(mode="json"), "book_revision": revision}


@router.post("/books/quiz-attempt")
async def quiz_attempt(req: QuizAttemptRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id)
    book = resolved.engine.load_book(req.book_id)
    page = next(
        (item for item in resolved.engine.list_pages(req.book_id) if item.id == req.page_id), None
    )
    block = page.block_by_id(req.block_id) if page is not None else None
    questions = (
        [item for item in block.payload.get("questions", []) if isinstance(item, dict)]
        if block is not None
        else []
    )
    resolved_question = _focus_check_question(questions, req.question_id, req.block_id)
    progress = progress_ops.record_attempt(
        resolved.load_progress(req.book_id),
        page_id=req.page_id,
        block_id=req.block_id,
        question_id=req.question_id,
        user_answer=req.user_answer,
        is_correct=req.is_correct,
        page_to_chapter={
            page.id: page.chapter_id
            for page in resolved.engine.list_pages(req.book_id)
            if page.chapter_id
        },
    )
    resolved.learning.save_progress(progress)
    if req.is_correct is not None and resolved_question is not None and book is not None:
        question_id, question = resolved_question
        try:
            from deeptutor.services.session import get_sqlite_session_store

            store = get_sqlite_session_store()
            metadata = book.metadata if isinstance(book.metadata, dict) else {}
            page_sessions = metadata.get("page_chat_sessions")
            session_id = str(
                (page_sessions.get(req.page_id) if isinstance(page_sessions, dict) else "")
                or book.chat_session_id
                or ""
            ).strip()
            # Notebook entries belong to real conversations. Creating a hidden
            # ``book_<id>`` chat solely to satisfy the FK polluted history and
            # made a Book Focus Check look like Immersive Reading. If the page
            # has no conversation yet, progress still persists and the optional
            # review sync waits for a later attempt after chat exists.
            if session_id and await store.get_session(session_id) is not None:
                await store.upsert_notebook_entries(
                    session_id,
                    [
                        {
                            "turn_id": req.block_id,
                            "question_id": question_id,
                            "question": str(
                                question.get("question") or block.title or "Focus check"
                            ),
                            "question_type": str(question.get("question_type") or ""),
                            "options": question.get("options") or {},
                            "correct_answer": str(question.get("correct_answer") or ""),
                            "explanation": str(question.get("explanation") or ""),
                            "difficulty": str(question.get("difficulty") or ""),
                            "user_answer": req.user_answer,
                            "is_correct": bool(req.is_correct),
                            "source": "book",
                            "material_id": req.book_id,
                            "material_title": book.title,
                            "section_id": req.page_id,
                            "section_title": page.title if page is not None else "",
                        }
                    ],
                )
        except Exception:
            logger.warning(
                "Failed to sync Focus-Check %s to question bank for book %s",
                req.question_id,
                req.book_id,
                exc_info=True,
            )
    return {"progress": progress.model_dump(mode="json")}


@router.post("/books/update-block")
async def update_block(req: UpdateBlockRequest) -> dict[str, Any]:
    """Edit a block's prose in place.

    Scoped deliberately narrow — title and body only. Fixing a typo shouldn't
    require regenerating a whole block and hoping for a better roll, but a book
    is not a document editor either; substantial rewrites belong in Co-Writer.
    """
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "update_block",
        extra={"page_id": req.page_id, "block_id": req.block_id},
    )
    block = await engine.update_block(
        book_id=req.book_id,
        page_id=req.page_id,
        block_id=req.block_id,
        title=req.title,
        body=req.body,
    )
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found or not editable")
    return {"block": block.model_dump(mode="json"), "book_revision": revision}


@router.post("/books/progress/visit")
async def mark_visited(req: ProgressRequest) -> dict[str, Any]:
    """Remember the reader's position so the book can be resumed later."""
    resolved = _resolve_book_or_404(req.book_id)
    progress = resolved.load_progress(req.book_id)
    if progress_ops.mark_visited(progress, req.page_id):
        resolved.learning.save_progress(progress)
    return {"progress": progress.model_dump(mode="json")}


@router.post("/books/progress/bookmark")
async def toggle_bookmark(req: ProgressRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id)
    progress = resolved.load_progress(req.book_id)
    progress_ops.toggle_bookmark(progress, req.page_id)
    resolved.learning.save_progress(progress)
    return {"progress": progress.model_dump(mode="json")}


@router.get("/books/{book_id}/export")
async def export_book(book_id: str) -> Response:
    """Download the whole book as a single Markdown file."""
    engine = _resolve_book_or_404(book_id).engine
    book = engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    markdown = await asyncio.to_thread(
        lambda: render_book_markdown(book, engine.load_spine(book_id), engine.list_pages(book_id))
    )
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(
                export_filename(book), disposition="attachment"
            )
        },
    )


@router.get("/books/{book_id}/health")
async def book_health(book_id: str) -> dict[str, Any]:
    resolved = _resolve_book_or_404(book_id)
    engine = resolved.engine
    if resolved.is_shared and not resolved.can_edit:
        # Drift detection persists stale-page state on the canonical Book. A
        # read-only collaborator may inspect it, but must not mutate it merely
        # by opening the health banner.
        book = engine.load_book(book_id)
        stale_page_ids = list(book.stale_page_ids) if book is not None else []
        drift = {
            "book_id": book_id,
            "has_drift": bool(stale_page_ids),
            "new_kbs": [],
            "removed_kbs": [],
            "changed_kbs": [],
            "stale_page_ids": stale_page_ids,
            "cached": True,
        }
    else:
        drift = engine.kb_drift_report(book_id)
    log = engine.log_health(book_id)
    generation = engine.generation_summary(book_id)
    return {"kb_drift": drift, "log_health": log, "generation": generation}


@router.post("/books/{book_id}/refresh-fingerprints")
async def refresh_fingerprints(
    book_id: str,
    force: bool = False,
    expected_revision: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """Mark the current KB state as seen.

    409s while pages the last drift flagged are still awaiting recompilation.
    ``force=true`` dismisses them anyway — stale detection over-marks on
    purpose when an anchor cannot be resolved, so the user needs a way out.
    """
    resolved = _resolve_book_or_404(book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        book_id,
        expected_revision,
        "refresh_fingerprints",
        extra={"force": force},
    )
    try:
        result = engine.refresh_kb_fingerprints(book_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return {**result, "book_revision": revision}


@router.post("/books/supplement")
async def supplement(req: SupplementRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "supplement",
        extra={"page_id": req.page_id, "topic": req.topic},
    )
    try:
        block = await engine.supplement_for_weakness(
            book_id=req.book_id,
            page_id=req.page_id,
            topic=req.topic,
        )
    except BookPausedError as exc:
        raise _book_paused_http(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"supplement failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    if block is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"block": block.model_dump(mode="json"), "book_revision": revision}


@router.post("/books/page-chat-session")
async def set_page_chat_session(req: PageChatSessionRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id)
    engine = resolved.engine
    if resolved.is_shared:
        book = engine.load_book(req.book_id)
        page = engine.load_page(req.book_id, req.page_id)
        if book is not None and page is not None and req.session_id.strip():
            resolved.learning.set_page_chat_session(req.book_id, req.page_id, req.session_id)
            log_usage("book", req.book_id, "page_chat", {"page_id": req.page_id})
            book = book.model_copy(deep=True)
        else:
            book = None
    else:
        book = engine.set_page_chat_session(
            book_id=req.book_id,
            page_id=req.page_id,
            session_id=req.session_id,
        )
    if book is None:
        raise HTTPException(status_code=404, detail="Book or page not found")
    return {"book": _book_payload(book, resolved)}


@router.post("/books/resume")
async def resume_book(req: ResumeBookRequest) -> dict[str, Any]:
    """Re-queue unfinished pages without discarding what already compiled."""
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "resume",
        strict=False,
    )
    try:
        pages = await engine.resume_book(book_id=req.book_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"resume_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages], "book_revision": revision}


@router.post("/books/pause")
async def pause_book(req: PauseBookRequest) -> dict[str, Any]:
    """Persist a manual pause, cancel in-flight work, and keep completed output."""
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "pause",
        strict=False,
    )
    try:
        pages = await engine.pause_book(book_id=req.book_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"pause_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages], "book_revision": revision}


@router.post("/books/rebuild")
async def rebuild_book(req: RebuildBookRequest) -> dict[str, Any]:
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    engine = resolved.engine
    revision = _claim_content_mutation(
        resolved,
        req.book_id,
        req.expected_revision,
        "rebuild",
    )
    _persist_requested_block_types(resolved, req.book_id, req.block_types)
    try:
        pages = await engine.rebuild_book(book_id=req.book_id, auto_compile=req.auto_compile)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"rebuild_book failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"pages": [p.model_dump(mode="json") for p in pages], "book_revision": revision}


# ─────────────────────────────────────────────────────────────────────────────
# 存量书增量补缺（P1-E D2）：只补缺失块，不做全书 rebuild
# ─────────────────────────────────────────────────────────────────────────────


class BackfillBlocksRequest(BaseModel):
    dry_run: bool = Field(default=False, description="true=只返回补缺计划（零写入）")
    concurrency: int = Field(default=2, ge=1, le=8, description="LLM 并发上限")
    limit_page: int | None = Field(default=None, ge=1, description="最多处理前 N 页（试点控量）")


#: 持有后台补产任务引用，防止 asyncio.Task 被垃圾回收。
_backfill_tasks: set[asyncio.Task[None]] = set()


async def _backfill_worker(book_id: str, task_id: str, req: BackfillBlocksRequest) -> None:
    task_manager = TaskIDManager.get_instance()
    try:
        job = await asyncio.to_thread(
            run_backfill,
            book_id,
            concurrency=req.concurrency,
            limit_page=req.limit_page,
            task_id=task_id,
        )
        if job.stage in ("error", "failed"):
            task_manager.update_task_status(task_id, "error", error=job.error)
        else:
            task_manager.update_task_status(task_id, "completed")
    except Exception as exc:  # noqa: BLE001 — 后台任务异常落在任务状态里
        logger.error(f"backfill_blocks task {task_id} failed: {exc}", exc_info=True)
        task_manager.update_task_status(task_id, "error", error=str(exc))
        # P4-B：线程外崩溃也必须把内存 job 拉离 running——否则同书互斥检查
        # 永远命中 409，这本书被锁死，且状态端点对停摆毫无提示。
        fail_backfill_job(book_id, str(exc))


@router.post("/books/{book_id}/backfill-blocks")
async def backfill_book_blocks(
    book_id: str,
    req: BackfillBlocksRequest,
    _current: TokenPayload = Depends(require_admin_or_teacher),
) -> dict[str, Any]:
    """存量书增量补缺：对照页型模板检测缺失块，只补缺，不动已有块。

    ``dry_run=true`` 同步返回计划（零写入）；否则后台任务执行补产，
    返回 ``task_id``，进度见 ``GET /books/{book_id}/backfill-blocks/status``。
    服务层单一真源：``deeptutor/book/backfill.py``。
    """
    _resolve_book_or_404(book_id)
    if req.dry_run:
        try:
            # 服务层用 asyncio.run 驱动引擎协程，须丢到无事件循环的线程里执行。
            plan = await asyncio.to_thread(plan_backfill, book_id, limit_page=req.limit_page)
        except KeyError:
            raise HTTPException(status_code=404, detail="Book not found")
        return {"dry_run": True, "plan": plan}

    existing = get_backfill_job(book_id)
    if existing is not None and existing.stage == "running":
        # P4-B：互斥语义要明确——返回在跑任务的 task_id 与实时状态，
        # 不让调用方误以为新任务已 started。
        snapshot = existing.snapshot()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "backfill_running",
                "message": "该书已有补缺任务在运行，请稍后或查询状态端点",
                "task_id": existing.task_id,
                "task_status": snapshot.get("task_status"),
                "job": snapshot,
            },
        )
    task_manager = TaskIDManager.get_instance()
    # task_key 带随机后缀：同一本书的每次补产都是独立任务，不与历史任务撞 id。
    task_id = task_manager.generate_task_id(
        "book_backfill", f"book_backfill:{book_id}:{uuid.uuid4().hex[:8]}"
    )
    task_manager.update_task_status(task_id, "running")
    worker = asyncio.create_task(_backfill_worker(book_id, task_id, req))
    _backfill_tasks.add(worker)
    worker.add_done_callback(_backfill_tasks.discard)
    return {
        "dry_run": False,
        "task_id": task_id,
        "book_id": book_id,
        "status": "started",
    }


@router.get("/books/{book_id}/backfill-blocks/status")
async def backfill_blocks_status(
    book_id: str,
    _current: TokenPayload = Depends(require_admin_or_teacher),
) -> dict[str, Any]:
    """查询存量书补缺进度（页/块成败计数、阶段）。"""
    _resolve_book_or_404(book_id)
    job: BackfillJob | None = get_backfill_job(book_id)
    if job is None:
        return {"book_id": book_id, "stage": "idle"}
    return job.snapshot()


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
        "seq": event.seq,
        "timestamp": event.timestamp,
    }


class _SocketFanout:
    """Forwards several buses into one socket, at most one task per bus.

    A client watching a book needs events from two places: the book's
    long-lived stream (background compilation) and, while a book is still being
    created, a connection-scoped stream (no book id exists yet). Both are
    attached here; neither producer needs to know a socket is listening.

    Attaching is idempotent — re-subscribing to a book already being forwarded
    is a no-op rather than a second, duplicating reader.
    """

    def __init__(self, send) -> None:
        self._send = send
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def attach(self, bus: StreamBus, *, after_seq: int = 0) -> None:
        key = id(bus)
        existing = self._tasks.get(key)
        if existing is not None and not existing.done():
            return
        self._tasks[key] = asyncio.create_task(self._forward(bus, after_seq=after_seq))

    async def _forward(self, bus: StreamBus, *, after_seq: int) -> None:
        async for event in bus.subscribe(after_seq=after_seq):
            if event.source != BOOK_SOURCE:
                continue
            await self._send(_serialize_event(event))

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()


@ws_router.websocket("/books")
async def book_websocket(ws: WebSocket) -> None:
    """Streaming endpoint.

    Two kinds of client message:

    **Subscribe** — attach this socket to a book's long-lived stream. Recent
    history is replayed on attach, so a reader who refreshes mid-compilation
    catches up instead of watching a frozen page::

        {"type": "subscribe", "book_id": "..."}

    **Actions** — run an engine operation and reply with a single result::

        {"type": "create",           ...CreateBookRequest fields}
        {"type": "confirm_proposal", "book_id": "...", "proposal": {...}}
        {"type": "confirm_spine",    "book_id": "...", "spine": {...}, "auto_compile": true}
        {"type": "compile_page",     "book_id": "...", "page_id": "...", "force": false}
        {"type": "regenerate_block", "book_id": "...", "page_id": "...", "block_id": "..."}

    Actions publish into the book's own stream (see :mod:`deeptutor.book.event_hub`),
    so their progress reaches *every* subscriber, and work they leave running in
    the background keeps streaming long after the action has replied. The socket
    only ever closes streams it created itself.
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.book.event_hub import get_book_bus
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

    fanout = _SocketFanout(send)
    # Book creation has no book id to stream into yet, so ideation events go
    # through a connection-scoped bus. It is the only bus this socket owns.
    creation_bus = StreamBus()
    fanout.attach(creation_bus)

    try:
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

            book_id = str(data.get("book_id") or "").strip()
            resolved: ResolvedBook | None = None
            if book_id:
                try:
                    resolved = _resolve_book_or_404(book_id)
                except HTTPException:
                    await send({"type": "error", "content": f"Book not found: {book_id}"})
                    continue

            try:
                if msg_type == "subscribe":
                    if not book_id:
                        await send({"type": "error", "content": "subscribe requires book_id"})
                    else:
                        bus = get_book_bus(book_id)
                        try:
                            requested_cursor = max(0, int(data.get("after_seq") or 0))
                        except (TypeError, ValueError):
                            requested_cursor = 0
                        reset_cursor = requested_cursor > bus.latest_seq
                        effective_cursor = 0 if reset_cursor else requested_cursor
                        # Acknowledge the effective cursor before replay starts,
                        # so the client can reset stale local state first.
                        await send(
                            {
                                "type": "subscribed",
                                "book_id": book_id,
                                "latest_seq": bus.latest_seq,
                                "reset": reset_cursor,
                            }
                        )
                        fanout.attach(bus, after_seq=effective_cursor)

                elif msg_type == "create":
                    if not can_create_book():
                        await send({"type": "error", "content": "Book creation is not allowed"})
                        continue
                    engine = get_book_engine()
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
                        fallback_language=str(data.get("fallback_language") or "en"),
                        depth=str(data.get("depth") or "standard"),
                        stream=creation_bus,
                    )
                    # From here on this book has a stream of its own.
                    created_bus = get_book_bus(book.id)
                    fanout.attach(created_bus, after_seq=created_bus.latest_seq)
                    await send(
                        {
                            "type": "create_result",
                            "book": book.model_dump(mode="json"),
                            "proposal": proposal.model_dump(mode="json"),
                        }
                    )

                elif msg_type == "confirm_proposal":
                    if resolved is None or not resolved.can_edit:
                        raise ValueError("Book not found")
                    engine = resolved.engine
                    action_bus = get_book_bus(book_id)
                    fanout.attach(action_bus, after_seq=action_bus.latest_seq)
                    revision = _claim_content_mutation(
                        resolved,
                        book_id,
                        data.get("expected_revision"),
                        "confirm_proposal",
                    )
                    edited: BookProposal | None = None
                    if data.get("proposal"):
                        edited = BookProposal.model_validate(data["proposal"])
                    book, spine = await engine.confirm_proposal(
                        book_id=book_id,
                        edited_proposal=edited,
                    )
                    await send(
                        {
                            "type": "confirm_proposal_result",
                            "book": book.model_dump(mode="json"),
                            "spine": spine.model_dump(mode="json"),
                            "book_revision": revision,
                        }
                    )

                elif msg_type == "confirm_spine":
                    if resolved is None or not resolved.can_edit:
                        raise ValueError("Book not found")
                    engine = resolved.engine
                    action_bus = get_book_bus(book_id)
                    fanout.attach(action_bus, after_seq=action_bus.latest_seq)
                    revision = _claim_content_mutation(
                        resolved,
                        book_id,
                        data.get("expected_revision"),
                        "confirm_spine",
                    )
                    edited_spine: Spine | None = None
                    if data.get("spine"):
                        edited_spine = Spine.model_validate(data["spine"])
                    pages = await engine.confirm_spine(
                        book_id=book_id,
                        edited_spine=edited_spine,
                        auto_compile=bool(data.get("auto_compile", True)),
                    )
                    await send(
                        {
                            "type": "confirm_spine_result",
                            "pages": [p.model_dump(mode="json") for p in pages],
                            "book_revision": revision,
                        }
                    )

                elif msg_type == "compile_page":
                    if resolved is None or not resolved.can_edit:
                        raise ValueError("Book not found")
                    engine = resolved.engine
                    action_bus = get_book_bus(book_id)
                    fanout.attach(action_bus, after_seq=action_bus.latest_seq)
                    revision = _claim_content_mutation(
                        resolved,
                        book_id,
                        data.get("expected_revision"),
                        "compile_page",
                        extra={"page_id": str(data.get("page_id") or "")},
                        strict=False,
                    )
                    page = await engine.compile_page(
                        book_id=book_id,
                        page_id=str(data.get("page_id") or ""),
                        force=bool(data.get("force", False)),
                    )
                    await send(
                        {
                            "type": "compile_page_result",
                            "page": page.model_dump(mode="json"),
                            "book_revision": revision,
                        }
                    )

                elif msg_type == "regenerate_block":
                    if resolved is None or not resolved.can_edit:
                        raise ValueError("Book not found")
                    engine = resolved.engine
                    action_bus = get_book_bus(book_id)
                    fanout.attach(action_bus, after_seq=action_bus.latest_seq)
                    revision = _claim_content_mutation(
                        resolved,
                        book_id,
                        data.get("expected_revision"),
                        "regenerate_block",
                        extra={
                            "page_id": str(data.get("page_id") or ""),
                            "block_id": str(data.get("block_id") or ""),
                        },
                    )
                    block = await engine.regenerate_block(
                        book_id=book_id,
                        page_id=str(data.get("page_id") or ""),
                        block_id=str(data.get("block_id") or ""),
                        params_override=data.get("params_override"),
                    )
                    await send(
                        {
                            "type": "regenerate_block_result",
                            "block": block.model_dump(mode="json") if block else None,
                            "book_revision": revision,
                        }
                    )

                else:
                    await send({"type": "error", "content": f"Unknown message type: {msg_type}"})

            except BookPausedError as exc:
                await send(
                    {
                        "type": "error",
                        "content": str(exc),
                        "status": 409,
                        "code": "book_paused",
                    }
                )
            except HTTPException as exc:
                detail = exc.detail
                payload: dict[str, Any] = {
                    "type": "error",
                    "content": (
                        str(detail.get("message") or detail.get("code") or "Book action failed")
                        if isinstance(detail, dict)
                        else str(detail)
                    ),
                    "status": exc.status_code,
                }
                if isinstance(detail, dict):
                    payload.update(
                        {key: detail[key] for key in ("code", "current_revision") if key in detail}
                    )
                await send(payload)
            except Exception as exc:
                logger.error(f"book ws action {msg_type} failed: {exc}", exc_info=True)
                await send({"type": "error", "content": str(exc)})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"Book WS connection error: {exc}", exc_info=True)
    finally:
        closed = True
        await fanout.close()
        await creation_bus.close()
        try:
            await ws.close()
        except Exception:
            logger.debug("Book WebSocket was already closed", exc_info=True)
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                logger.debug("Could not reset Book WebSocket user context", exc_info=True)


@router.post("/books/recitation")
async def submit_recitation(
    book_id: str = Form(...),
    block_id: str = Form(...),
    line_ids: list[str] = Form(...),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    """Transcribe and score selected poetry lines without accepting answer text."""

    engine = get_book_engine()
    book = engine.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    page_and_block = next(
        (
            (page, block)
            for page in engine.list_pages(book_id)
            for block in page.blocks
            if block.id == block_id
        ),
        None,
    )
    if page_and_block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    page, block = page_and_block
    if block.type != BlockType.POETRY:
        raise HTTPException(status_code=400, detail="Block is not a poetry block")

    try:
        target_lines = resolve_target_lines(block.payload.get("lines"), line_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audio_bytes = await audio.read()
    await audio.close()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if len(audio_bytes) > _MAX_RECITATION_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio exceeds the 25 MB limit.")

    try:
        transcript = await transcribe_audio(
            audio_bytes,
            filename=audio.filename or "recitation.webm",
            content_type=audio.content_type or "application/octet-stream",
            language=book.language or None,
        )
    except Exception as exc:  # noqa: BLE001 - provider/config failures are an explicit state
        logger.warning("Poetry recitation STT failed: %s", exc)
        attempt = stt_failed_attempt(
            book_id=book_id,
            block_id=block_id,
            target_line_ids=[line_id for line_id, _ in target_lines],
        )
    else:
        attempt = score_recitation(
            book_id=book_id,
            block_id=block_id,
            target_lines=target_lines,
            transcript=transcript,
        )

    summary = update_recitation_summary(block.metadata.get("recitation"), attempt)
    block.metadata = {
        **block.metadata,
        "recitation": summary.model_dump(mode="json"),
    }
    block.updated_at = attempt.created_at
    page.updated_at = attempt.created_at
    engine.storage.save_page(page)
    return {
        "attempt": attempt.model_dump(mode="json"),
        "summary": summary.model_dump(mode="json"),
    }
