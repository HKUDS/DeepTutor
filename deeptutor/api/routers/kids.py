"""Child-facing endpoints for the standalone /kids experience.

Uses a lightweight device session: the parent generates a signed token from
the management UI, which encodes the profile_id. This token is sent as a
cookie or Authorization header and gates access to only the assigned books.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any
import unicodedata

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.kids_word_hints import build_kids_word_hint
from deeptutor.immersive_reading.models import KidsQuizQuestion, KidsQuizResult
from deeptutor.immersive_reading.service import get_kids_manager
from deeptutor.immersive_reading.sight_words import detect_quiz_language
from deeptutor.kids_rewards import (
    build_kids_reward_event,
    kids_reward_snapshot,
    record_kids_reward_event,
)

logger = logging.getLogger(__name__)


async def _reject_learning_account(
    dt_token: str | None = Cookie(default=None, alias="dt_token"),
) -> None:
    """Keep the legacy device API from becoming a Learning Account bypass."""
    if not dt_token:
        return
    from deeptutor.multi_user.learning_access import learning_policy_for_user
    from deeptutor.services.auth import decode_token

    payload = decode_token(dt_token)
    if payload and learning_policy_for_user(payload.user_id, is_admin=payload.role == "admin"):
        raise HTTPException(status_code=403, detail="Use the Reading workspace for this account.")


router = APIRouter(dependencies=[Depends(_reject_learning_account)])

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
    payload = token[len(_DEVICE_TOKEN_PREFIX) :]
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
    # The cookie is HttpOnly and overwritten by the server on profile selection,
    # so it is more reliable than a stale localStorage-backed bearer token.
    if dt_kids:
        token = dt_kids
    elif authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
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


def _kids_auth_response(payload: dict, token: str) -> JSONResponse:
    """Mirror the device token so storage-restricted browsers stay signed in."""
    response = JSONResponse(payload)
    response.set_cookie(
        "dt_kids",
        token,
        httponly=True,
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return response


def _normalize_learning_anchor(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _strip_learning_whitespace(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", normalized).casefold()


def _is_visible_text_anchored(visible_text: str, section_text: str) -> bool:
    if not visible_text or not section_text:
        return False
    visible = _normalize_learning_anchor(visible_text)
    full = _normalize_learning_anchor(section_text)
    if not visible or not full:
        return False
    if visible in full:
        return True

    clean_visible = _strip_learning_whitespace(visible_text)
    clean_full = _strip_learning_whitespace(section_text)
    if not clean_visible or not clean_full:
        return False
    if clean_visible in clean_full:
        return True

    paragraphs = [p.strip() for p in re.split(r"[\n\r]+", visible_text) if p.strip()]
    for p in paragraphs:
        cp = _strip_learning_whitespace(p)
        if len(cp) >= 10 and cp in clean_full:
            return True
        norm_p = _normalize_learning_anchor(p)
        if len(norm_p) >= 20 and norm_p in full:
            return True

    if len(clean_visible) >= 20:
        for i in range(0, len(clean_visible) - 19, 10):
            chunk = clean_visible[i : i + 20]
            if chunk in clean_full:
                return True
    elif len(clean_visible) >= 6:
        if clean_visible in clean_full:
            return True

    return False


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
    pin: str = ""


@router.post("/select-profile")
async def select_profile(request: SelectProfileRequest) -> JSONResponse:
    """Return a device token for the selected profile.

    If the profile has a PIN, the parent PIN must be provided; otherwise the
    child can select directly.
    """
    manager = get_kids_manager()
    profile = manager.get_profile(request.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.pin_hash and not manager.verify_parent_pin(profile.id, request.pin):
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
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
    return _kids_auth_response({"token": token, "profile": profile_data}, token)


class ParentUnlockRequest(BaseModel):
    profile_id: str
    pin: str = Field(min_length=4, max_length=20)


@router.post("/parent-unlock")
async def parent_unlock(request: ParentUnlockRequest) -> JSONResponse:
    """Verify parent PIN and return a device token (for PIN-protected profiles)."""
    manager = get_kids_manager()
    if not manager.verify_parent_pin(request.profile_id, request.pin):
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
    token = _sign_device_token(request.profile_id)
    profile = manager.get_profile(request.profile_id)
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
    return _kids_auth_response({"token": token, "profile": profile_data}, token)


# ── Child library ───────────────────────────────────────────────────────────


@router.get("/library")
async def kids_library(profile_id: str = Depends(_require_profile)) -> dict:
    """List assigned books for the authenticated child profile."""
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"library": manager.get_kids_library(profile_id)}


@router.get("/rewards")
async def get_kids_rewards(profile_id: str = Depends(_require_profile)) -> dict:
    """Return the optional provider-owned reward snapshot."""
    reward = kids_reward_snapshot(profile_id)
    return {"reward": reward.model_dump(mode="json") if reward else None}


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
        (
            a
            for a in manager.list_assignments(profile_id)
            if a.document_id == document_id and a.status == "active"
        ),
        None,
    )
    max_index = assignment.available_through_section_index if assignment else 999
    allowed_sections = [s for s in doc.sections if s.index <= max_index]
    detail = ir.document_detail(document_id)
    chapter_texts: list[str] = []
    for section in allowed_sections:
        if section.checkpoint_kind != "chapter":
            continue
        try:
            chapter_texts.append(str(ir.get_section(document_id, section.id).get("content", "")))
        except Exception:
            continue
        if len("".join(chapter_texts)) > 3000:
            break
    detail["content_language"] = detect_quiz_language(
        "\n".join(chapter_texts), preferred_language="en"
    )
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


class KidsLearnRequest(BaseModel):
    section_id: str
    visible_text: str = Field(min_length=1, max_length=3000)
    force_refresh: bool = False


@router.post("/books/{document_id}/learn")
async def get_kids_learn(
    document_id: str,
    request: KidsLearnRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get an unscored concept guide for the currently visible page."""
    manager = get_kids_manager()
    ir = get_immersive_reading_service()
    doc = None
    try:
        doc = ir.load_document(document_id)
    except Exception:
        pass

    section = _resolve_kids_reading_section(ir, document_id, request.section_id)
    if section is None or not manager.is_section_allowed(profile_id, document_id, section.index):
        raise HTTPException(status_code=404, detail="Book not found")

    section_text = ""
    try:
        section_text = ir.get_section(document_id, section.id).get("content", "")
    except Exception:
        pass

    if not _is_visible_text_anchored(request.visible_text, section_text):
        found_section = None
        if doc and getattr(doc, "sections", None):
            for candidate in doc.sections:
                if not manager.is_section_allowed(profile_id, document_id, candidate.index):
                    continue
                try:
                    cand_text = ir.get_section(document_id, candidate.id).get("content", "")
                    if _is_visible_text_anchored(request.visible_text, cand_text):
                        found_section = candidate
                        section = candidate
                        section_text = cand_text
                        break
                except Exception:
                    continue
        if not found_section:
            raise HTTPException(status_code=400, detail="Page text does not match this chapter")

    profile = manager.get_profile(profile_id)
    age_band = profile.age_band if profile else "6-8"
    language = detect_quiz_language(
        request.visible_text,
        preferred_language=profile.help_language if profile else "en",
    )
    try:
        result = await ir.generate_kids_learn(
            document_id,
            section.id,
            request.visible_text,
            force_refresh=request.force_refresh,
            age_band=age_band,
            language=language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


def _resolve_kids_reading_section(ir, document_id: str, requested_section_id: str):
    """Resolve current section IDs and older EPUB hrefs from deployed clients."""
    try:
        doc = ir.load_document(document_id)
    except Exception:
        # Test doubles and older services may only expose quiz/section methods.
        from types import SimpleNamespace

        return SimpleNamespace(
            id=requested_section_id, index=0, title="", checkpoint_kind="chapter"
        )
    if doc is None or not getattr(doc, "sections", None):
        return None
    if not requested_section_id:
        chapter = next(
            (s for s in doc.sections if getattr(s, "checkpoint_kind", "") == "chapter"), None
        )
        return chapter or doc.sections[0]

    section = next((s for s in doc.sections if s.id == requested_section_id), None)
    if section is not None:
        return section

    requested = requested_section_id.split("?")[0].split("/")[-1].lower()
    for s in doc.sections:
        s_href = getattr(s, "source_href", None)
        if s_href and s_href.split("?")[0].split("/")[-1].lower() == requested:
            return s

    chapter_match = re.search(r"chap(?:ter)?[_-]?(\d+)", requested)
    chapters = [s for s in doc.sections if getattr(s, "checkpoint_kind", "") == "chapter"]
    if chapter_match:
        chapter_number = int(chapter_match.group(1))
        if 1 <= chapter_number <= len(chapters):
            return chapters[chapter_number - 1]

    digits_match = re.search(r"(\d+)", requested)
    if digits_match:
        file_num = int(digits_match.group(1))
        spine_1based = file_num + 1
        for s in doc.sections:
            s_start = getattr(s, "source_start", None)
            s_end = getattr(s, "source_end", None)
            if s_start is not None and s_end is not None:
                if s_start <= spine_1based <= s_end:
                    return s
        for s in doc.sections:
            s_start = getattr(s, "source_start", None)
            s_end = getattr(s, "source_end", None)
            if s_start is not None and s_end is not None:
                if s_start <= file_num <= s_end:
                    return s

    normalized = " ".join(requested.replace("-", " ").split())
    matched = next(
        (
            s
            for s in doc.sections
            if " ".join(getattr(s, "title", "").lower().split()) == normalized
        ),
        None,
    )
    if matched:
        return matched

    return None


def _fill_kids_quiz_to_three(
    ir, document_id: str, section_id: str, age_band: str, language: str, result
):
    """Guard the endpoint contract even when a provider/fake returns fewer questions."""
    if result is None:
        return None

    # Vocabulary drills belong to a separate practice flow, not a reading quiz.
    result.questions = [question for question in result.questions if question.kind != "sight_word"]
    if len(result.questions) > 3:
        result.questions = result.questions[:3]
    if len(result.questions) >= 3:
        return result

    try:
        section_text = ir.get_section(document_id, section_id).get("content", "")
    except Exception:
        section_text = ""

    from deeptutor.immersive_reading.sight_words import generate_story_comprehension_quiz

    existing = {q.question.strip().lower() for q in result.questions}
    fallbacks = generate_story_comprehension_quiz(
        section_text, age_band=age_band, num_questions=9, language=language
    )
    for i, fallback in enumerate(fallbacks, start=len(result.questions) + 1):
        if len(result.questions) == 3:
            break
        if fallback["question"].strip().lower() in existing:
            continue
        result.questions.append(
            KidsQuizQuestion(
                id=f"fallback-q{i}",
                kind=fallback["kind"],
                question=fallback["question"],
                choices=fallback["choices"],
                answer_index=fallback["answer_index"],
                explanation=fallback["explanation"],
            )
        )
        existing.add(fallback["question"].strip().lower())

    result.prompt_version = "kids-quiz-fallback-v6"
    result.generated_at = time.time()
    result.age_band = age_band
    result.language = language
    if hasattr(ir, "_save_kids_quiz_cache"):
        ir._save_kids_quiz_cache(document_id, section_id, result)
    return result


def _safe_kids_questions(result):
    return [
        {"id": q.id, "kind": q.kind, "question": q.question, "choices": q.choices}
        for q in result.questions
    ]


def _build_fallback_kids_quiz(
    document_id: str, section_id: str, section_text: str, age_band: str, language: str
) -> KidsQuizResult:
    from deeptutor.immersive_reading.sight_words import generate_story_comprehension_quiz

    fallback_qs = generate_story_comprehension_quiz(
        section_text, age_band=age_band, num_questions=3, language=language
    )
    return KidsQuizResult(
        document_id=document_id,
        section_id=section_id,
        questions=[
            KidsQuizQuestion(
                id=q["id"],
                kind=q["kind"],
                question=q["question"],
                choices=q["choices"],
                answer_index=q["answer_index"],
                explanation=q["explanation"],
            )
            for q in fallback_qs
        ],
        content_hash=hashlib.sha256(section_text.encode()).hexdigest(),
        model="story-comprehension-fallback",
        prompt_version="kids-quiz-fallback-v6",
        age_band=age_band,
        language=language,
    )


@router.post("/books/{document_id}/quiz")
async def get_kids_quiz(
    document_id: str,
    request: KidsQuizRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get quiz questions — answer_index is stripped for children."""
    manager = get_kids_manager()
    ir = get_immersive_reading_service()
    section = _resolve_kids_reading_section(ir, document_id, request.section_id)
    if section is None or not manager.is_section_allowed(profile_id, document_id, section.index):
        raise HTTPException(status_code=404, detail="Book not found")
    if section.checkpoint_kind != "chapter":
        return {"questions": [], "section_id": section.id, "message": "Read a chapter first!"}

    profile = manager.get_profile(profile_id)
    age_band = profile.age_band if profile else "6-8"
    section_text = ir.get_section(document_id, section.id).get("content", "")
    language = detect_quiz_language(
        section_text,
        preferred_language=profile.help_language if profile else "en",
    )

    should_cache_fallback = False
    try:
        result = await ir.generate_kids_quiz(
            document_id,
            section.id,
            force_refresh=request.force_refresh,
            age_band=age_band,
            language=language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM quiz failed, using deterministic fallback: %s", exc)
        result = _build_fallback_kids_quiz(
            document_id, section.id, section_text, age_band, language
        )
        should_cache_fallback = True

    result = _fill_kids_quiz_to_three(ir, document_id, section.id, age_band, language, result)
    if should_cache_fallback and result is not None and result.questions:
        ir._save_kids_quiz_cache(document_id, section.id, result)
    if not result.questions:
        return {
            "questions": [],
            "section_id": section.id,
            "language": language,
            "message": "Read more to unlock quizzes!",
        }
    return {
        "questions": _safe_kids_questions(result),
        "section_id": section.id,
        "language": language,
    }


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
    section = _resolve_kids_reading_section(ir, document_id, request.section_id)
    if section is None or not manager.is_section_allowed(profile_id, document_id, section.index):
        raise HTTPException(status_code=404, detail="Book not found")
    profile = manager.get_profile(profile_id)
    age_band = profile.age_band if profile else "6-8"
    try:
        section_text = ir.get_section(document_id, section.id).get("content", "")
    except Exception:
        section_text = ""
    language = detect_quiz_language(
        section_text,
        preferred_language=profile.help_language if profile else "en",
    )
    should_cache_fallback = False
    try:
        cached = await ir.generate_kids_quiz(
            document_id, section.id, age_band=age_band, language=language
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM quiz submit reload failed, using fallback: %s", exc)
        try:
            section_text = ir.get_section(document_id, section.id).get("content", "")
        except Exception:
            section_text = ""
        cached = _build_fallback_kids_quiz(
            document_id, section.id, section_text, age_band, language
        )
        should_cache_fallback = True

    cached = _fill_kids_quiz_to_three(ir, document_id, section.id, age_band, language, cached)
    if should_cache_fallback and cached is not None and cached.questions:
        ir._save_kids_quiz_cache(document_id, section.id, cached)

    correct = 0
    per_question: list[dict[str, Any]] = []
    for i, q in enumerate(cached.questions):
        child_answer = request.answers[i] if i < len(request.answers) else -1
        is_correct = child_answer == q.answer_index
        if is_correct:
            correct += 1
        per_question.append(
            {
                "id": q.id,
                "correct": is_correct,
                "explanation": q.explanation,
            }
        )

    total = len(cached.questions)
    completed = total > 0 and correct == total
    progress = manager.record_reading_quiz_result(
        profile_id,
        document_id,
        section.id,
        correct,
        total,
    )
    if completed:
        progress = manager.mark_section_completed(profile_id, document_id, section.id)
    quiz_event = build_kids_reward_event(
        profile_id=profile_id,
        content_type="reading",
        content_id=document_id,
        item_id=section.id,
        kind="quiz_submitted",
        score=correct,
        total=total,
        completed=completed,
    )
    reward = record_kids_reward_event(quiz_event)
    if completed:
        record_kids_reward_event(
            build_kids_reward_event(
                profile_id=profile_id,
                content_type="reading",
                content_id=document_id,
                item_id=section.id,
                kind="section_completed",
                score=correct,
                total=total,
                completed=True,
            )
        )

    return {
        "score": correct,
        "total": total,
        "reward": reward.model_dump(mode="json") if reward else None,
        "completed_section_ids": progress.completed_section_ids,
        "per_question": per_question,
        "language": language,
    }


# ── Translation (for double-tap Chinese) ────────────────────────────────────


# ── Guided word hints ───────────────────────────────────────────────────────


class KidsWordHintRequest(BaseModel):
    word: str = Field(min_length=1, max_length=80)
    section_id: str = Field(min_length=1, max_length=120)
    context: str = Field(default="", max_length=2000)


class KidsWordHintChoicesRequest(BaseModel):
    hint_id: str = Field(min_length=10, max_length=4096)


class KidsWordHintCheckRequest(KidsWordHintChoicesRequest):
    choice: str = Field(min_length=1, max_length=500)
    attempt: int = Field(default=1, ge=1, le=2)


def _hint_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _encode_word_hint_token(
    *,
    document_id: str,
    profile_id: str,
    section_id: str,
    hint,
) -> str:
    payload = {
        "v": 1,
        "document_id": document_id,
        "profile_id": profile_id,
        "section_id": section_id,
        "word": hint.word,
        "correct_choice": hint.correct_choice,
        "chinese": hint.chinese,
        "choices": list(hint.choices),
    }
    encoded = base64.urlsafe_b64encode(_hint_payload_bytes(payload)).decode().rstrip("=")
    signature = hmac.new(_DEVICE_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_word_hint_token(
    token: str, *, document_id: str, profile_id: str
) -> dict[str, Any] | None:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(_DEVICE_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if payload.get("document_id") != document_id or payload.get("profile_id") != profile_id:
        return None
    if payload.get("v") != 1 or not isinstance(payload.get("choices"), list):
        return None
    return payload


def _authorized_hint_section(document_id: str, section_id: str, profile_id: str):
    manager = get_kids_manager()
    ir = get_immersive_reading_service()
    section = _resolve_kids_reading_section(ir, document_id, section_id)
    if section is None or not manager.is_section_allowed(profile_id, document_id, section.index):
        return None
    return section


@router.post("/books/{document_id}/word-hint")
async def get_kids_word_hint(
    document_id: str,
    request: KidsWordHintRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    section = _authorized_hint_section(document_id, request.section_id, profile_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Book not found")
    profile = get_kids_manager().get_profile(profile_id)
    hint = build_kids_word_hint(request.word, profile.age_band if profile else "6-8")
    if hint is None:
        return {"available": False, "word": request.word.strip()}
    return {
        "available": True,
        "hint_id": _encode_word_hint_token(
            document_id=document_id,
            profile_id=profile_id,
            section_id=section.id,
            hint=hint,
        ),
        "word": hint.word,
        "phonetic": hint.phonetic,
        "english_hint": hint.english_hint,
    }


@router.post("/books/{document_id}/word-hint/choices")
async def get_kids_word_hint_choices(
    document_id: str,
    request: KidsWordHintChoicesRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    payload = _decode_word_hint_token(
        request.hint_id, document_id=document_id, profile_id=profile_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Word hint not found")
    return {"choices": payload["choices"]}


@router.post("/books/{document_id}/word-hint/check")
async def check_kids_word_hint(
    document_id: str,
    request: KidsWordHintCheckRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    payload = _decode_word_hint_token(
        request.hint_id, document_id=document_id, profile_id=profile_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Word hint not found")
    correct = request.choice == payload["correct_choice"]
    if correct:
        return {"correct": True, "feedback": "Yes! You thought it out."}
    if request.attempt < 2:
        return {"correct": False, "feedback": "Think again."}
    return {
        "correct": False,
        "feedback": "Let us look together.",
        "correct_choice": payload["correct_choice"],
        "chinese": payload["chinese"],
        "explanation": f'"{payload["word"]}" means {payload["correct_choice"].lower()}.',
    }


@router.post("/books/{document_id}/word-hint/reveal")
async def reveal_kids_word_hint(
    document_id: str,
    request: KidsWordHintChoicesRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    payload = _decode_word_hint_token(
        request.hint_id, document_id=document_id, profile_id=profile_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Word hint not found")
    return {
        "correct_choice": payload["correct_choice"],
        "chinese": payload["chinese"],
        "explanation": f'"{payload["word"]}" means {payload["correct_choice"].lower()}.',
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


# ── Interactive Books (Kids Math & Interactive Digital Books) ────────────────

_REASONING_MARKER = re.compile(r"\bthinking\s+process\s*:", re.IGNORECASE)
_PRIVATE_PAYLOAD_KEYS = {"bridge_text", "reasoning", "thinking_process"}


def _sanitize_child_payload(value: Any) -> Any:
    """Remove model reasoning traces before a generated page reaches a child."""
    if isinstance(value, str):
        match = _REASONING_MARKER.search(value)
        return value[: match.start()].rstrip() if match else value
    if isinstance(value, dict):
        return {
            key: _sanitize_child_payload(child)
            for key, child in value.items()
            if key not in _PRIVATE_PAYLOAD_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_child_payload(child) for child in value]
    return value


@router.get("/interactive-books/{book_id}")
async def get_kids_interactive_book(
    book_id: str,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get interactive book detail — strictly gated by active assignment and READY book status."""
    manager = get_kids_manager()
    assignment = next(
        (
            a
            for a in manager.list_assignments(profile_id)
            if (a.book_id == book_id or a.document_id == book_id)
            and a.content_type == "interactive_book"
            and a.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Interactive book not assigned or active")

    from deeptutor.book.models import BookStatus
    from deeptutor.book.storage import get_book_storage

    storage = get_book_storage()
    book = storage.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Strictly ensure book is compiled and marked READY before child can access
    status_val = book.status.value if hasattr(book.status, "value") else str(book.status)
    if status_val != BookStatus.READY.value and status_val != "ready":
        raise HTTPException(status_code=403, detail="Book is not ready yet")

    spine = storage.load_spine(book_id)
    progress = manager.load_kids_interactive_progress(profile_id, book_id)

    max_page_order = assignment.available_through_page_order
    chapters_data = []
    if spine and spine.chapters:
        for ch in spine.chapters:
            # Only include chapters that have pages within allowed range
            ch_dict = ch.model_dump(mode="json")
            chapters_data.append(ch_dict)

    return {
        "book": {
            "id": book.id,
            "title": book.title or assignment.document_title or book.id,
            "description": book.description,
            "status": status_val,
            "page_count": book.page_count,
            "chapter_count": book.chapter_count,
            "language": book.language,
        },
        "spine": {
            "book_id": book.id,
            "chapters": chapters_data,
        }
        if spine
        else None,
        "assignment": assignment.model_dump(mode="json"),
        "progress": progress.model_dump(mode="json"),
    }


@router.get("/interactive-books/{book_id}/pages/{page_id}")
async def get_kids_interactive_page(
    book_id: str,
    page_id: str,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Get interactive page content — sanitized for children (strictly strips answers from quizzes)."""
    manager = get_kids_manager()
    assignment = next(
        (
            a
            for a in manager.list_assignments(profile_id)
            if (a.book_id == book_id or a.document_id == book_id)
            and a.content_type == "interactive_book"
            and a.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Book not assigned")

    from deeptutor.book.models import BookStatus
    from deeptutor.book.storage import get_book_storage

    storage = get_book_storage()
    book = storage.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    status_val = book.status.value if hasattr(book.status, "value") else str(book.status)
    if status_val != BookStatus.READY.value and status_val != "ready":
        raise HTTPException(status_code=403, detail="Book is not ready yet")

    page = storage.load_page(book_id, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    if page.order > assignment.available_through_page_order:
        raise HTTPException(status_code=403, detail="This page is not unlocked yet")

    progress = manager.load_kids_interactive_progress(profile_id, book_id)

    # Sanitize blocks for child safety & anti-cheating
    safe_blocks = []
    for b in page.blocks:
        b_dict = b.model_dump(mode="json")
        if b.type == "quiz" or b_dict.get("type") == "quiz":
            payload = dict(b_dict.get("payload", {}))
            questions = payload.get("questions", [])
            safe_questions = []
            for q in questions:
                q_safe = dict(q)
                # Strip all answer keys and explanations from questions sent to child
                q_safe.pop("answer_index", None)
                q_safe.pop("correct_answer", None)
                q_safe.pop("answer", None)
                q_safe.pop("explanation", None)
                q_safe.pop("choice_diagnoses", None)
                safe_questions.append(q_safe)
            payload["questions"] = safe_questions
            b_dict["payload"] = payload

        if b.type == "animation" or b_dict.get("type") == "animation":
            payload = dict(b_dict.get("payload", {}))
            video_url = payload.get("video_url", "")
            if (
                video_url
                and not video_url.startswith("http")
                and not video_url.startswith("/api/v1/kids/")
            ):
                rel_path = video_url.lstrip("/")
                if rel_path.startswith(f"book_{book_id}/assets/"):
                    rel_path = rel_path[len(f"book_{book_id}/assets/") :]
                payload["video_url"] = f"/api/v1/kids/interactive-books/{book_id}/assets/{rel_path}"
                b_dict["payload"] = payload

        safe_blocks.append(_sanitize_child_payload(b_dict))

    page_data = page.model_dump(mode="json")
    page_data["blocks"] = safe_blocks

    return {
        "page": page_data,
        "progress": progress.model_dump(mode="json"),
    }


class KidsInteractiveProgressUpdate(BaseModel):
    page_id: str = ""
    page_order: int = 0
    completed: bool = False
    time_delta: float = 0.0


@router.put("/interactive-books/{book_id}/progress")
async def update_kids_interactive_progress_endpoint(
    book_id: str,
    request: KidsInteractiveProgressUpdate,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Update child interactive reading progress after verifying active assignment."""
    manager = get_kids_manager()
    assignment = next(
        (
            a
            for a in manager.list_assignments(profile_id)
            if (a.book_id == book_id or a.document_id == book_id)
            and a.content_type == "interactive_book"
            and a.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Book not assigned")

    progress = manager.update_kids_interactive_progress(
        profile_id,
        book_id,
        page_id=request.page_id,
        page_order=request.page_order,
        completed=request.completed,
        time_delta=request.time_delta,
    )
    return {"progress": progress.model_dump(mode="json")}


class KidsInteractiveQuizSubmitRequest(BaseModel):
    page_id: str
    block_id: str
    answers: list[int] = Field(default_factory=list)


@router.post("/interactive-books/{book_id}/quiz/submit")
async def submit_kids_interactive_quiz(
    book_id: str,
    request: KidsInteractiveQuizSubmitRequest,
    profile_id: str = Depends(_require_profile),
) -> dict:
    """Grade quiz block on server, award stars idempotently, without exposing raw answer indices."""
    manager = get_kids_manager()
    assignment = next(
        (
            a
            for a in manager.list_assignments(profile_id)
            if (a.book_id == book_id or a.document_id == book_id)
            and a.content_type == "interactive_book"
            and a.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Book not assigned")

    from deeptutor.book.storage import get_book_storage

    storage = get_book_storage()
    page = storage.load_page(book_id, request.page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    block = page.block_by_id(request.block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Quiz block not found")

    payload = block.payload or {}
    questions = payload.get("questions", [])
    if not questions:
        raise HTTPException(status_code=400, detail="No questions in quiz block")

    correct = 0
    per_question: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        expected_ans = q.get("answer_index", q.get("correct_answer", 0))
        child_ans = request.answers[i] if i < len(request.answers) else -1
        is_correct = child_ans == expected_ans
        if is_correct:
            correct += 1

        choice_diagnoses = q.get("choice_diagnoses", [])
        explanation = ""
        if 0 <= child_ans < len(choice_diagnoses) and choice_diagnoses[child_ans]:
            explanation = choice_diagnoses[child_ans]
        else:
            explanation = q.get("explanation", "")

        # Never leak raw correct_answer index; only provide correctness and pedagogical explanation
        per_question.append(
            {
                "id": q.get("id", str(i)),
                "correct": is_correct,
                "explanation": explanation,
            }
        )

    total = len(questions)
    progress = manager.record_interactive_quiz_result(
        profile_id, book_id, request.block_id, correct, total
    )
    reward = record_kids_reward_event(
        build_kids_reward_event(
            profile_id=profile_id,
            content_type="interactive_book",
            content_id=book_id,
            item_id=request.block_id,
            kind="quiz_submitted",
            score=correct,
            total=total,
            completed=total > 0 and correct == total,
        )
    )

    return {
        "score": correct,
        "total": total,
        "reward": reward.model_dump(mode="json") if reward else None,
        "per_question": per_question,
        "progress": progress.model_dump(mode="json"),
    }


@router.get("/interactive-books/{book_id}/assets/{asset_path:path}")
async def get_kids_interactive_asset(
    book_id: str,
    asset_path: str,
    profile_id: str = Depends(_require_profile),
):
    """Safely stream asset files (videos, images) — strictly gated by profile token, active assignment, and ready status."""
    manager = get_kids_manager()
    assignment = next(
        (
            a
            for a in manager.list_assignments(profile_id)
            if (a.book_id == book_id or a.document_id == book_id)
            and a.content_type == "interactive_book"
            and a.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Book not assigned")

    from deeptutor.book.models import BookStatus
    from deeptutor.book.storage import get_book_storage

    storage = get_book_storage()
    book = storage.load_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    status_val = book.status.value if hasattr(book.status, "value") else str(book.status)
    if status_val != BookStatus.READY.value and status_val != "ready":
        raise HTTPException(status_code=403, detail="Book is not ready yet")

    assets_dir = storage.book_root(book_id) / "assets"
    target_file = (assets_dir / asset_path).resolve()

    if not str(target_file).startswith(str(assets_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target_file.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    media_type = "application/octet-stream"
    suffix = target_file.suffix.lower()
    if suffix == ".mp4":
        media_type = "video/mp4"
    elif suffix in (".png", ".jpg", ".jpeg"):
        media_type = f"image/{suffix.lstrip('.')}"
    elif suffix == ".svg":
        media_type = "image/svg+xml"

    return FileResponse(target_file, media_type=media_type)


@router.get("/interactive-books/{book_id}/cover")
async def get_kids_interactive_cover(
    book_id: str,
    profile_id: str = Depends(_require_profile),
):
    """Get interactive book cover — gated by profile token and assignment."""
    manager = get_kids_manager()
    assignment = next(
        (
            a
            for a in manager.list_assignments(profile_id)
            if (a.book_id == book_id or a.document_id == book_id)
            and a.content_type == "interactive_book"
            and a.status == "active"
        ),
        None,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Book not assigned")

    from deeptutor.book.storage import get_book_storage

    storage = get_book_storage()
    cover_file = storage.book_root(book_id) / "cover.png"
    if cover_file.is_file():
        return FileResponse(cover_file, media_type="image/png")
    raise HTTPException(status_code=404, detail="No custom cover")


@router.get("/books/{document_id}/epub")
async def get_kids_epub(
    document_id: str,
    profile_id: str = Depends(_require_profile),
):
    """Safely stream original EPUB file for child reading — gated by assignment."""
    manager = get_kids_manager()
    if not manager.is_section_allowed(profile_id, document_id, 0):
        raise HTTPException(status_code=403, detail="Book not assigned")
    ir = get_immersive_reading_service()
    try:
        path = ir.original_path(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/epub+zip", filename=f"{document_id}.epub")
