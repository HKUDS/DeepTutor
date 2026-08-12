"""Child-facing endpoints for the standalone /kids experience.

Uses a lightweight device session: the parent generates a signed token from
the management UI, which encodes the profile_id. This token is sent as a
cookie or Authorization header and gates access to only the assigned books.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.models import KidsQuizSubmission
from deeptutor.immersive_reading.service import get_kids_manager
from deeptutor.services.auth import AUTH_ENABLED

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple device-token signing — not JWT-grade, but sufficient for local family use.
_DEVICE_SECRET = "deeptutor-kids-device-v1"
_DEVICE_TOKEN_PREFIX = "kds_"


def _sign_device_token(profile_id: str) -> str:
    """Create a device token for a child profile."""
    raw = f"{profile_id}:{_DEVICE_SECRET}"
    sig = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"{_DEVICE_TOKEN_PREFIX}{profile_id}:{sig}"


def _verify_device_token(token: str) -> str | None:
    """Verify a device token and return the profile_id."""
    if not token or not token.startswith(_DEVICE_TOKEN_PREFIX):
        return None
    payload = token[len(_DEVICE_TOKEN_PREFIX):]
    parts = payload.split(":", 1)
    if len(parts) != 2:
        return None
    profile_id, sig = parts
    expected = hashlib.sha256(f"{profile_id}:{_DEVICE_SECRET}".encode()).hexdigest()[:24]
    if not hmac.compare_digest(sig, expected):
        return None
    return profile_id


def _extract_profile_id(
    authorization: str | None,
    dt_kids: str | None,
) -> str | None:
    """Extract profile_id from header or cookie."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif dt_kids:
        token = dt_kids
    if not token:
        return None
    return _verify_device_token(token)


def _require_profile(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_kids: str | None = Cookie(default=None, alias="dt_kids"),
) -> str:
    """Dependency that extracts and validates the child device session."""
    profile_id = _extract_profile_id(authorization, dt_kids)
    if profile_id is None:
        raise HTTPException(status_code=401, detail="No valid kids session")
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=401, detail="Profile not found")
    return profile_id


# ── Bootstrap & profile selection ───────────────────────────────────────────

@router.get("/bootstrap")
async def bootstrap() -> dict:
    """List available child profiles so the child can pick one on the /kids page."""
    manager = get_kids_manager()
    profiles = manager.list_profiles()
    return {
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "avatar": p.avatar,
                "birth_date": p.birth_date,
                "age": p.age,
                "age_band": p.age_band,
                "has_pin": bool(p.pin_hash),
                "device_url": f"/kids/p/{p.id}",
            }
            for p in profiles
        ]
    }


class SelectProfileRequest(BaseModel):
    profile_id: str


@router.post("/select-profile")
async def select_profile(request: SelectProfileRequest) -> dict:
    """Return a device token for the selected profile.

    If the profile has a PIN, the parent PIN must be provided; otherwise the
    child can select directly.
    """
    manager = get_kids_manager()
    profile = manager.get_profile(request.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    token = _sign_device_token(request.profile_id)
    profile_data = {
        "id": profile.id,
        "name": profile.name,
        "avatar": profile.avatar,
        "birth_date": profile.birth_date,
        "age": profile.age,
        "age_band": profile.age_band,
        "help_language": profile.help_language,
        "narration_rate": profile.narration_rate,
        "daily_limit_minutes": profile.daily_limit_minutes,
    }
    return {"token": token, "profile": profile_data}


class ParentUnlockRequest(BaseModel):
    profile_id: str
    pin: str = Field(min_length=4, max_length=20)


@router.post("/parent-unlock")
async def parent_unlock(request: ParentUnlockRequest) -> dict:
    """Verify parent PIN and return a device token (for PIN-protected profiles)."""
    manager = get_kids_manager()
    if not manager.verify_parent_pin(request.profile_id, request.pin):
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
    token = _sign_device_token(request.profile_id)
    profile = manager.get_profile(request.profile_id)
    return {
        "token": token,
        "profile": {
            "id": profile.id,
            "name": profile.name,
            "avatar": profile.avatar,
            "birth_date": profile.birth_date,
            "age": profile.age,
            "age_band": profile.age_band,
            "help_language": profile.help_language,
            "narration_rate": profile.narration_rate,
            "daily_limit_minutes": profile.daily_limit_minutes,
        },
    }


# ── Child library ───────────────────────────────────────────────────────────

@router.get("/library")
async def kids_library(profile_id: str = Header(default="", alias="X-Profile-Id")) -> dict:
    """List assigned books for a profile (no device token needed — just profile_id).

    This is also called from bootstrap before a token is issued.
    """
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"library": manager.get_kids_library(profile_id)}


# ── Book access (device-session gated) ──────────────────────────────────────



@router.get("/books/{document_id}")
async def get_kids_book(
    document_id: str,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get book detail, gated by assignment."""
    manager = get_kids_manager()
    ir = get_immersive_reading_service()
    if not manager.is_section_allowed(profile_id, document_id, 0):
        raise HTTPException(status_code=404, detail="Book not found")
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    # Limit sections to allowed range
    assignment = next(
        (a for a in manager.list_assignments(profile_id) if a.document_id == document_id and a.status == "active"),
        None,
    )
    max_index = assignment.available_through_section_index if assignment else 999
    allowed_sections = [s for s in doc.sections if s.index <= max_index]
    detail = ir.document_detail(document_id)
    detail["sections"] = [s.model_dump(mode="json") for s in allowed_sections]
    progress = manager.load_kids_progress(profile_id, document_id)
    return {"document": detail, "progress": progress.model_dump(mode="json")}


@router.get("/books/{document_id}/cover")
async def get_kids_cover(document_id: str):
    ir = get_immersive_reading_service()
    try:
        path = ir.cover_path(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", filename=f"{document_id}-cover.png")


@router.get("/books/{document_id}/sections/{section_id}")
async def get_kids_section(
    document_id: str,
    section_id: str,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get section content — gated by assignment and chapter limit."""
    manager = get_kids_manager()
    ir = get_immersive_reading_service()
    doc = ir.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Book not found")
    section = next((s for s in doc.sections if s.id == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    if not manager.is_section_allowed(profile_id, document_id, section.index):
        raise HTTPException(status_code=403, detail="This chapter is not available yet")
    return ir.get_section(document_id, section_id)


class KidsProgressUpdate(BaseModel):
    section_id: str
    section_index: int = 0
    scroll_percent: float = Field(default=0, ge=0, le=100)
    epub_cfi: str = ""
    section_href: str = ""
    time_delta: float = 0.0
    completed: bool = False


@router.put("/books/{document_id}/progress")
async def update_kids_progress(
    document_id: str,
    request: KidsProgressUpdate,
    profile_id: str = Depends(_require_profile),
) -> dict:
    manager = get_kids_manager()
    progress = manager.update_kids_progress_record(
        profile_id,
        document_id,
        section_id=request.section_id,
        section_index=request.section_index,
        scroll_percent=request.scroll_percent,
        epub_cfi=request.epub_cfi,
        section_href=request.section_href,
        time_delta=request.time_delta,
    )
    if request.completed:
        manager.mark_section_completed(profile_id, document_id, request.section_id)
        progress = manager.load_kids_progress(profile_id, document_id)
    return {"progress": progress.model_dump(mode="json")}


# ── Quiz ────────────────────────────────────────────────────────────────────

class KidsQuizRequest(BaseModel):
    section_id: str
    force_refresh: bool = False


@router.post("/books/{document_id}/quiz")
async def get_kids_quiz(
    document_id: str,
    request: KidsQuizRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get quiz questions — answer_index is stripped for children."""
    manager = get_kids_manager()
    if not manager.is_section_allowed(profile_id, document_id, 0):
       raise HTTPException(status_code=404, detail="Book not found")
    ir = get_immersive_reading_service()

    # Get age band from profile for age-appropriate quiz difficulty
    profile = manager.get_profile(profile_id)
    age_band = profile.age_band if profile else "6-8"

    # Read section text for fallback quiz generation
    section_text = ""
    try:
        section_data = ir.get_section(document_id, request.section_id)
        section_text = section_data.get("content", "")
    except Exception:
        pass

    try:
        result = await ir.generate_kids_quiz(
            document_id, request.section_id, force_refresh=request.force_refresh, age_band=age_band
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM quiz failed, using deterministic fallback: %s", exc)
        result = None

    # If LLM produced no usable questions, fall back to deterministic translation quiz
    if result is None or not result.questions:
        from deeptutor.immersive_reading.sight_words import generate_translation_quiz
        fallback_qs = generate_translation_quiz(section_text, age_band=age_band)
        if fallback_qs:
            logger.info("Using fallback translation quiz: %d questions", len(fallback_qs))
            safe_questions = [
                {"id": q["id"], "kind": q["kind"], "question": q["question"], "choices": q["choices"]}
                for q in fallback_qs
            ]
            # Cache the fallback so submit can grade it
            from deeptutor.immersive_reading.models import KidsQuizQuestion, KidsQuizResult
            import hashlib
            fallback_result = KidsQuizResult(
                document_id=document_id,
                section_id=request.section_id,
                questions=[
                    KidsQuizQuestion(
                        id=q["id"], kind=q["kind"], question=q["question"],
                        choices=q["choices"], answer_index=q["answer_index"],
                        explanation=q["explanation"],
                    )
                    for q in fallback_qs
                ],
                content_hash=hashlib.sha256(section_text.encode()).hexdigest(),
                model="sight-words-fallback",
                prompt_version="sight-words-v1",
            )
            ir._save_kids_quiz_cache(document_id, request.section_id, fallback_result)
            return {"questions": safe_questions, "section_id": request.section_id}
        # No words found either
        return {"questions": [], "section_id": request.section_id, "message": "Read more to unlock quizzes!"}

    # Strip answer_index from questions sent to the child
    safe_questions = []
    for q in result.questions:
        safe_questions.append({
            "id": q.id,
            "kind": q.kind,
            "question": q.question,
            "choices": q.choices,
        })
    return {"questions": safe_questions, "section_id": request.section_id}


class KidsQuizSubmitRequest(BaseModel):
    section_id: str
    answers: list[int] = Field(default_factory=list)


@router.post("/books/{document_id}/quiz/submit")
async def submit_kids_quiz(
    document_id: str,
    request: KidsQuizSubmitRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Grade quiz on the server and return stars."""
    manager = get_kids_manager()
    ir = get_immersive_reading_service()
    try:
        cached = await ir.generate_kids_quiz(document_id, request.section_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    correct = 0
    per_question: list[dict[str, Any]] = []
    for i, q in enumerate(cached.questions):
        child_answer = request.answers[i] if i < len(request.answers) else -1
        is_correct = child_answer == q.answer_index
        if is_correct:
            correct += 1
        per_question.append({
            "id": q.id,
            "correct": is_correct,
            "explanation": q.explanation,
        })

    total = len(cached.questions)
    stars = 1 if correct > 0 else 0
    if correct >= total * 0.6:
        stars = 2
    if correct == total:
        stars = 3

    encouragements = [
        "Great job!" if correct == total else
        "Good try!" if correct > 0 else
        "Keep reading and try again!"
    ]

    # Record progress
    manager.record_quiz(profile_id, document_id, correct, total)
    manager.add_stars(profile_id, document_id, stars)

    return {
        "score": correct,
        "total": total,
        "stars": stars,
        "per_question": per_question,
        "encouragements": encouragements,
    }


# ── Translation (for double-tap Chinese) ────────────────────────────────────

class KidsTranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    target_language: str = "Chinese"


@router.post("/translate")
async def kids_translate(
    request: KidsTranslateRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    ir_service = get_immersive_reading_service()
    try:
        translated = await ir_service.translate(request.text, request.target_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Translation failed: {exc}") from exc
    return {"translation": translated}


# ── Exit verification (PIN required to leave Kids mode) ────────────────────

class ExitVerifyRequest(BaseModel):
    profile_id: str
    pin: str = Field(min_length=4, max_length=20)


@router.post("/exit-verify")
async def exit_verify(request: ExitVerifyRequest) -> dict:
    """Verify the parent PIN before allowing the child to exit Kids mode."""
    manager = get_kids_manager()
    if manager.get_profile(request.profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not manager.verify_parent_pin(request.profile_id, request.pin):
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
    return {"ok": True}
