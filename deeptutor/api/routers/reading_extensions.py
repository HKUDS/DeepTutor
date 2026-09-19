"""Authenticated transport for schema-driven Immersive Reading extensions."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deeptutor.multi_user.learning_access import (
    allowed_reading_extensions,
    assert_learning_material,
)
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingContext,
    ReadingExtensionResult,
    get_reading_extension_registry,
)
from deeptutor.services.llm.exceptions import LLMError

logger = logging.getLogger(__name__)
router = APIRouter()
# Quiz / translation / vocabulary all call an LLM. Thirty seconds is enough to
# trip a hanging *sync* plugin, but too short for a grounded three-question
# quiz on a reasoning model — and a timeout used to circuit-break the extension
# for the rest of the process.
ACTION_TIMEOUT_S = 120


def _unavailable_detail(
    *,
    reason: str = "",
    message: str = "This reading action is temporarily unavailable.",
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "message": message,
        "recoverable": True,
    }
    if reason:
        detail["reason"] = reason[:500]
    return detail


class ActionPayload(BaseModel):
    locator: int = Field(ge=1)
    selection: str = Field(default="", max_length=10_000)
    locale: str = Field(default="en", max_length=32)


class QuizAnswerItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str = Field(min_length=1)
    selected_index: int


class QuizAnswersPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    locator: int = Field(ge=1)
    source_anchor: str = Field(default="", max_length=2_000)
    section_title: str = Field(default="", max_length=500)
    session_id: str = ""
    turn_id: str = ""
    answers: list[QuizAnswerItem] = Field(min_length=1)


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _verified_selection(candidate: str, unit_text: str) -> str:
    value = _normal(candidate)
    return value if value and value in _normal(unit_text) else ""


@router.get("/extensions")
async def list_extensions() -> list[dict[str, Any]]:
    allowed = allowed_reading_extensions()
    return [
        extension.manifest.model_dump()
        for extension in get_reading_extension_registry().all()
        if allowed is None or extension.manifest.id in allowed
    ]


@router.post("/materials/{material_id}/extensions/{extension_id}/actions/{action}")
async def run_extension_action(
    material_id: str,
    extension_id: str,
    action: str,
    payload: ActionPayload,
) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    allowed = allowed_reading_extensions()
    if allowed is not None and extension_id not in allowed:
        raise HTTPException(status_code=403, detail="This reading extension is not allowed.")

    registry = get_reading_extension_registry()
    extension = registry.get(extension_id)
    if extension is None:
        raise HTTPException(status_code=404, detail="Reading extension not found.")
    declared_action = next((row for row in extension.manifest.actions if row.id == action), None)
    if declared_action is None:
        raise HTTPException(status_code=404, detail="Reading extension action not found.")
    store = ReadingStore()
    try:
        unit_text = store.unit_text(material_id, payload.locator)
        position = store.position(material_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    selection = _verified_selection(payload.selection, unit_text)
    if "selection" in declared_action.requires and not selection:
        raise HTTPException(status_code=400, detail="Select text from the visible unit first.")
    try:
        context = ReadingContext(
            material_id=material_id,
            locator=payload.locator,
            source_anchor=(position.source_anchor if position.locator == payload.locator else ""),
            locale=payload.locale,
            selection=selection,
            visible_text=unit_text,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="This reading unit is too large for the extension protocol.",
        ) from exc
    # Sync plugins run on a private worker we cannot kill; a timeout must
    # open the circuit so later clicks do not queue behind the stuck call.
    # Async plugins (quiz, translation, …) are cancelled with the request,
    # so a slow LLM must not disable the button for the rest of the process.
    run = extension.run_action
    sync_plugin = not inspect.iscoroutinefunction(run)
    if not registry.begin_action(extension_id, circuit_break=sync_plugin):
        raise HTTPException(
            status_code=503,
            detail=_unavailable_detail(reason="busy_or_circuit_open"),
        )
    try:
        async with asyncio.timeout(ACTION_TIMEOUT_S):
            if sync_plugin:
                loop = asyncio.get_running_loop()
                value = await loop.run_in_executor(
                    registry.executor_for(extension_id),
                    run,
                    action,
                    context,
                )
                if inspect.isawaitable(value):
                    value = await value
            else:
                value = await run(action, context)
        result = (
            value
            if isinstance(value, ReadingExtensionResult)
            else ReadingExtensionResult.model_validate(value)
        )
        if result.type not in extension.manifest.result_types:
            raise ValueError(f"Extension returned undeclared result type {result.type!r}.")
        dumped = result.model_dump()
        quiz_payload = dumped.get("payload")
        if dumped.get("type") == "quiz" and isinstance(quiz_payload, dict):
            await _persist_reading_quiz_pending(material_id, payload.locator, quiz_payload)
        return dumped
    except TimeoutError as exc:
        if sync_plugin:
            registry.mark_timed_out(extension_id)
        logger.warning(
            "Reading extension %s action %s timed out after %ss (sync=%s)",
            extension_id,
            action,
            ACTION_TIMEOUT_S,
            sync_plugin,
        )
        raise HTTPException(
            status_code=503,
            detail=_unavailable_detail(reason="timed_out"),
        ) from exc
    except LLMError as exc:
        logger.warning(
            "Reading extension %s action %s failed via language model: %s",
            extension_id,
            action,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail=_unavailable_detail(
                reason=str(exc),
                message="This reading action needs a working language model.",
            ),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Reading extension %s action %s failed",
            extension_id,
            action,
        )
        raise HTTPException(
            status_code=503,
            detail=_unavailable_detail(reason=str(exc)),
        ) from exc
    finally:
        registry.finish_action(extension_id)


def _choice_map(choices: list[Any]) -> dict[str, str]:
    return {
        chr(65 + index): str(choice)
        for index, choice in enumerate(choices)
        if isinstance(choice, str) or choice is not None
    }


def _material_title(material_id: str) -> str:
    try:
        manifest = ReadingStore().manifest(material_id)
    except Exception:
        return ""
    return str(getattr(manifest, "title", "") or getattr(manifest, "filename", "") or "")


async def _persist_reading_quiz_pending(
    material_id: str, locator: int, payload: dict[str, Any]
) -> None:
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return
    try:
        from deeptutor.services.session import get_sqlite_session_store

        await get_sqlite_session_store().put_reading_quiz_pending(material_id, locator, questions)
    except Exception:
        logger.warning(
            "Failed to persist reading quiz keys for material %s locator %s",
            material_id,
            locator,
            exc_info=True,
        )


@router.post("/materials/{material_id}/extensions/quiz/answers")
async def submit_quiz_answers(material_id: str, payload: QuizAnswersPayload) -> dict[str, Any]:
    try:
        assert_learning_material(material_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    from deeptutor.learning.assessment import (
        AssessmentRecord,
        RecordAssessmentError,
        is_correct_to_result,
        record_assessment,
    )
    from deeptutor.services.session import get_sqlite_session_store

    store = get_sqlite_session_store()
    question_ids = [item.question_id.strip() for item in payload.answers]
    pending = await store.get_reading_quiz_pending(material_id, payload.locator, question_ids)
    missing = [qid for qid in question_ids if qid not in pending]
    if missing:
        raise HTTPException(status_code=409, detail="This reading quiz has expired.")

    session_id = payload.session_id.strip()
    persist = bool(session_id) and await store.get_session(session_id) is not None
    turn_id = payload.turn_id.strip() or f"loc:{payload.locator}"
    section_title = payload.section_title.strip() or payload.source_anchor.strip()
    material_title = _material_title(material_id)
    graded: list[dict[str, Any]] = []
    for item in payload.answers:
        question = pending[item.question_id.strip()]
        choices = question.get("choices") if isinstance(question.get("choices"), list) else []
        try:
            correct_index = int(question.get("correct_choice_index"))
        except (TypeError, ValueError):
            correct_index = -1
        is_correct = item.selected_index == correct_index
        result = is_correct_to_result(is_correct)
        options = _choice_map(choices)
        selected_text = (
            str(choices[item.selected_index]) if 0 <= item.selected_index < len(choices) else ""
        )
        correct_text = str(choices[correct_index]) if 0 <= correct_index < len(choices) else ""
        if persist:
            try:
                await record_assessment(
                    AssessmentRecord(
                        session_id=session_id,
                        turn_id=turn_id,
                        question_id=item.question_id.strip(),
                        question=str(question.get("prompt") or "Reading quiz"),
                        question_type="choice",
                        options=options,
                        user_answer=selected_text,
                        correct_answer=correct_text,
                        is_correct=is_correct,
                        result=result,
                        source="immersive_reading",
                        assessment_type="focus_check",
                        material_id=material_id,
                        material_title=material_title,
                        section_id=str(payload.locator),
                        section_title=section_title,
                    )
                )
            except RecordAssessmentError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        graded.append(
            {
                "question_id": item.question_id.strip(),
                "is_correct": is_correct,
                "result": result,
            }
        )
    return {"answers": graded}


__all__ = ["router"]
