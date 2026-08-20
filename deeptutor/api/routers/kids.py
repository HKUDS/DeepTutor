"""Child-facing endpoints for the standalone /kids experience."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.models import KidsBookAssignment, ReadingSection
from deeptutor.immersive_reading.service import KidsManager, get_kids_manager

router = APIRouter()
logger = logging.getLogger(__name__)

_SESSION_COOKIE = "dt_kids"
_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


def _profile_dict(profile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "avatar": profile.avatar,
        "age": profile.age,
        "age_band": profile.age_band,
        "has_pin": bool(profile.pin_hash),
        "help_language": profile.help_language,
        "narration_rate": profile.narration_rate,
        "daily_limit_minutes": profile.daily_limit_minutes,
    }


def _extract_token(authorization: str | None, dt_kids: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return dt_kids


def _require_profile(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_kids: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> str:
    manager = get_kids_manager()
    session = manager.validate_device_session(_extract_token(authorization, dt_kids) or "")
    if session is None:
        raise HTTPException(status_code=401, detail="No valid kids session")
    return session.profile_id


def _require_active_profile(profile_id: str = Depends(_require_profile)) -> str:
    manager = get_kids_manager()
    try:
        usage = manager.usage_status(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Profile not found") from exc
    if usage["limit_reached"]:
        raise HTTPException(
            status_code=403,
            detail={"code": "daily_limit_reached", **{key: value for key, value in usage.items() if key != "date"}},
        )
    return profile_id


def _issue_session(
    manager: KidsManager, profile_id: str, response: Response
) -> dict[str, Any]:
    session, token = manager.create_device_session(profile_id, ttl_seconds=_SESSION_TTL_SECONDS)
    response.set_cookie(
        _SESSION_COOKIE,
        token,
        max_age=_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {
        "token": token,
        "expires_at": session.expires_at,
        "profile": _profile_dict(manager.get_profile(profile_id)),
    }


def _active_assignment(manager: KidsManager, profile_id: str, document_id: str) -> KidsBookAssignment:
    assignment = next(
        (
            item
            for item in manager.list_assignments(profile_id)
            if item.document_id == document_id and item.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return assignment


def _resolve_section(document, section_id: str) -> ReadingSection:
    section = next(
        (
            item
            for item in document.sections
            if item.id == section_id or (item.source_href and item.source_href == section_id)
        ),
        None,
    )
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@router.get("/bootstrap")
async def bootstrap() -> dict:
    """Expose only the minimal data needed to render the child profile picker."""
    profiles = get_kids_manager().list_profiles()
    return {
        "profiles": [
            {
                "id": profile.id,
                "name": profile.name,
                "avatar": profile.avatar,
                "age_band": profile.age_band,
                "has_pin": bool(profile.pin_hash),
                "device_url": f"/kids/p/{profile.id}",
            }
            for profile in profiles
        ]
    }


class SelectProfileRequest(BaseModel):
    profile_id: str


@router.post("/select-profile")
async def select_profile(request: SelectProfileRequest, response: Response) -> dict:
    manager = get_kids_manager()
    profile = manager.get_profile(request.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.pin_hash:
        raise HTTPException(status_code=403, detail="PIN required")
    return _issue_session(manager, profile.id, response)


class ParentUnlockRequest(BaseModel):
    profile_id: str
    pin: str = Field(min_length=4, max_length=20)


@router.post("/parent-unlock")
async def parent_unlock(request: ParentUnlockRequest, response: Response) -> dict:
    manager = get_kids_manager()
    if not manager.verify_parent_pin(request.profile_id, request.pin):
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
    return _issue_session(manager, request.profile_id, response)


@router.post("/session/logout")
async def logout_session(
    response: Response,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_kids: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
    profile_id: str = Depends(_require_profile),
) -> dict:
    manager = get_kids_manager()
    token = _extract_token(authorization, dt_kids)
    if token:
        manager.revoke_device_session(token)
    response.delete_cookie(_SESSION_COOKIE, path="/")
    del profile_id
    return {"ok": True}


@router.get("/library")
async def kids_library(profile_id: str = Depends(_require_active_profile)) -> dict:
    manager = get_kids_manager()
    return {"library": manager.get_kids_library(profile_id), "usage": manager.usage_status(profile_id)}


@router.get("/books/{document_id}")
async def get_kids_book(
    document_id: str,
    profile_id: str = Depends(_require_active_profile),
) -> dict:
    manager = get_kids_manager()
    assignment = _active_assignment(manager, profile_id, document_id)
    ir = get_immersive_reading_service()
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    allowed_sections = [
        section
        for section in doc.sections
        if 0 <= section.index <= assignment.available_through_section_index
    ]
    progress = manager.load_kids_progress(profile_id, document_id)
    total_sections = max(1, len(doc.sections))
    completed = min(len(progress.completed_section_ids), total_sections)
    return {
        "document": {
            **doc.model_dump(mode="json"),
            "sections": [section.model_dump(mode="json") for section in allowed_sections],
            "cover_url": f"/api/v1/kids/books/{document_id}/cover" if doc.has_cover else "",
            "progress": progress.model_dump(mode="json"),
            "progress_percent": round(completed / total_sections * 100, 1),
        },
        "progress": progress.model_dump(mode="json"),
        "usage": manager.usage_status(profile_id),
    }


@router.get("/books/{document_id}/cover")
async def get_kids_cover(
    document_id: str,
    profile_id: str = Depends(_require_active_profile),
) -> FileResponse:
    _active_assignment(get_kids_manager(), profile_id, document_id)
    ir = get_immersive_reading_service()
    try:
        path = ir.cover_path(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Book not found") from exc
    return FileResponse(path, media_type="image/png", filename=f"{document_id}-cover.png")


@router.get("/books/{document_id}/epub")
async def get_kids_epub(
    document_id: str,
    profile_id: str = Depends(_require_active_profile),
) -> Response:
    manager = get_kids_manager()
    assignment = _active_assignment(manager, profile_id, document_id)
    try:
        content = get_immersive_reading_service().kids_epub(
            document_id, assignment.available_through_section_index
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Book not found") from exc
    return Response(
        content=content,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'inline; filename="{document_id}-kids.epub"'},
    )


@router.get("/books/{document_id}/sections/{section_id}")
async def get_kids_section(
    document_id: str,
    section_id: str,
    profile_id: str = Depends(_require_active_profile),
) -> dict:
    manager = get_kids_manager()
    assignment = _active_assignment(manager, profile_id, document_id)
    ir = get_immersive_reading_service()
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    section = _resolve_section(doc, section_id)
    if section.index > assignment.available_through_section_index:
        raise HTTPException(status_code=403, detail="This chapter is not available yet")
    return ir.get_section(document_id, section.id)


class KidsProgressUpdate(BaseModel):
    section_id: str
    section_index: int = 0
    scroll_percent: float = Field(default=0, ge=0, le=100)
    epub_cfi: str = ""
    section_href: str = ""
    completed: bool = False


@router.put("/books/{document_id}/progress")
async def update_kids_progress(
    document_id: str,
    request: KidsProgressUpdate,
    profile_id: str = Depends(_require_active_profile),
) -> dict:
    manager = get_kids_manager()
    assignment = _active_assignment(manager, profile_id, document_id)
    ir = get_immersive_reading_service()
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    section = _resolve_section(doc, request.section_id)
    if section.index > assignment.available_through_section_index:
        raise HTTPException(status_code=403, detail="This chapter is not available yet")
    progress = manager.update_kids_progress_record(
        profile_id,
        document_id,
        section_id=section.id,
        section_index=section.index,
        scroll_percent=request.scroll_percent,
        epub_cfi=request.epub_cfi,
        section_href=request.section_href,
    )
    if request.completed:
        manager.mark_section_completed(profile_id, document_id, section.id)
        progress = manager.load_kids_progress(profile_id, document_id)
    return {"progress": progress.model_dump(mode="json")}


class KidsQuizRequest(BaseModel):
    section_id: str
    force_refresh: bool = False


@router.post("/books/{document_id}/quiz")
async def get_kids_quiz(
    document_id: str,
    request: KidsQuizRequest,
    profile_id: str = Depends(_require_active_profile),
) -> dict:
    manager = get_kids_manager()
    assignment = _active_assignment(manager, profile_id, document_id)
    ir = get_immersive_reading_service()
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    section = _resolve_section(doc, request.section_id)
    if section.index > assignment.available_through_section_index:
        raise HTTPException(status_code=403, detail="This chapter is not available yet")
    profile = manager.get_profile(profile_id)
    age_band = profile.age_band if profile else "6-8"
    try:
        section_data = ir.get_section(document_id, section.id)
        section_text = section_data.get("content", "")
    except ValueError:
        section_text = ""

    try:
        result = await ir.generate_kids_quiz(
            document_id,
            section.id,
            force_refresh=request.force_refresh,
            age_band=age_band,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM quiz failed, using deterministic fallback: %s", exc)
        result = None

    if result is None or not result.questions:
        from deeptutor.immersive_reading.models import KidsQuizQuestion, KidsQuizResult
        from deeptutor.immersive_reading.sight_words import generate_translation_quiz

        fallback_questions = generate_translation_quiz(section_text, age_band=age_band)
        if not fallback_questions:
            return {"questions": [], "section_id": section.id, "message": "Read more to unlock quizzes!"}
        result = KidsQuizResult(
            document_id=document_id,
            section_id=section.id,
            questions=[
                KidsQuizQuestion(
                    id=item["id"],
                    kind=item["kind"],
                    question=item["question"],
                    choices=item["choices"],
                    answer_index=item["answer_index"],
                    explanation=item["explanation"],
                )
                for item in fallback_questions
            ],
            content_hash=hashlib.sha256(section_text.encode()).hexdigest(),
            model="sight-words-fallback",
            prompt_version="sight-words-v1",
        )
        ir._save_kids_quiz_cache(document_id, section.id, result)

    return {
        "questions": [
            {"id": item.id, "kind": item.kind, "question": item.question, "choices": item.choices}
            for item in result.questions
        ],
        "section_id": section.id,
    }


class KidsQuizSubmitRequest(BaseModel):
    section_id: str
    answers: list[int] = Field(default_factory=list, max_length=100)


@router.post("/books/{document_id}/quiz/submit")
async def submit_kids_quiz(
    document_id: str,
    request: KidsQuizSubmitRequest,
    profile_id: str = Depends(_require_active_profile),
) -> dict:
    manager = get_kids_manager()
    assignment = _active_assignment(manager, profile_id, document_id)
    ir = get_immersive_reading_service()
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    section = _resolve_section(doc, request.section_id)
    if section.index > assignment.available_through_section_index:
        raise HTTPException(status_code=403, detail="This chapter is not available yet")
    try:
        cached = await ir.generate_kids_quiz(document_id, section.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Quiz is unavailable") from exc

    if not cached.questions:
        raise HTTPException(status_code=400, detail="Quiz is not ready")
    if len(request.answers) > len(cached.questions):
        raise HTTPException(status_code=400, detail="Invalid quiz answer")
    if any(answer < -1 or answer >= len(cached.questions[i].choices) for i, answer in enumerate(request.answers)):
        raise HTTPException(status_code=400, detail="Invalid quiz answer")

    correct = 0
    per_question: list[dict[str, Any]] = []
    for index, question in enumerate(cached.questions):
        child_answer = request.answers[index] if index < len(request.answers) else -1
        is_correct = child_answer == question.answer_index
        correct += int(is_correct)
        per_question.append(
            {"id": question.id, "correct": is_correct, "explanation": question.explanation}
        )

    total = len(cached.questions)
    stars = 1 if correct > 0 else 0
    if correct >= total * 0.6:
        stars = 2
    if correct == total:
        stars = 3
    earned = manager.record_quiz_result(profile_id, document_id, correct, total, stars)
    encouragement = (
        "Great job!" if correct == total else "Good try!" if correct else "Keep reading and try again!"
    )
    return {
        "score": correct,
        "total": total,
        "stars": stars,
        "earned_stars": earned,
        "per_question": per_question,
        "encouragements": [encouragement],
    }


class KidsTranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    target_language: str = "Chinese"


@router.post("/translate")
async def kids_translate(
    request: KidsTranslateRequest,
    profile_id: str = Depends(_require_active_profile),
) -> dict:
    del profile_id
    try:
        translated = await get_immersive_reading_service().translate(
            request.text, request.target_language
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Translation failed: {exc}") from exc
    return {"translation": translated}


class HeartbeatRequest(BaseModel):
    active: bool = True
    document_id: str = ""


@router.post("/session/heartbeat")
async def kids_heartbeat(
    request: HeartbeatRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_kids: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> dict:
    manager = get_kids_manager()
    session = manager.validate_device_session(_extract_token(authorization, dt_kids) or "")
    if session is None:
        raise HTTPException(status_code=401, detail="No valid kids session")
    return manager.record_reading_heartbeat(session, document_id=request.document_id)


class ExitVerifyRequest(BaseModel):
    profile_id: str
    pin: str = Field(min_length=4, max_length=20)


@router.post("/exit-verify")
async def exit_verify(request: ExitVerifyRequest) -> dict:
    manager = get_kids_manager()
    if manager.get_profile(request.profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not manager.verify_parent_pin(request.profile_id, request.pin):
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
    return {"ok": True}
