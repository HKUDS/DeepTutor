"""Goal mode API router."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from deeptutor.agents.goal.models import Feedback, GoalConfig
from deeptutor.agents.goal.orchestrator import GoalOrchestrator

router = APIRouter()
_orchestrator: GoalOrchestrator | None = None


def get_orchestrator() -> GoalOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = GoalOrchestrator()
    return _orchestrator


def ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def api_error(code: str, message: str, detail: dict | None = None) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"ok": False, "error": {"code": code, "message": message, "detail": detail or {}}},
    )


class CreateSessionRequest(BaseModel):
    kb_name: str
    goal_config: GoalConfig


class SubmitFeedbackRequest(BaseModel):
    feedback_id: str = Field(default="fb_001")
    task_id: str
    completion: str
    actual_minutes: int | None = None
    quiz: dict | None = None
    reflection: str = ""


class ReplanRequest(BaseModel):
    reason: str | None = None
    strategy: str = "rule_based"


class GeneratePracticeRequest(BaseModel):
    count: int = 3
    difficulty: str = "medium"
    question_type: str = "choice"

class GenerateInteractivePageRequest(BaseModel):
    force: bool = False

class InteractiveChatRequest(BaseModel):
    question: str


class ExamAnalysisResponse(BaseModel):
    session_id: str
    analysis: dict
    artifact_path: str


@router.post("/create_session")
async def create_session(request: CreateSessionRequest):
    try:
        session = await get_orchestrator().create_session(request.kb_name, request.goal_config)
    except ValueError as exc:
        raise api_error("INVALID_GOAL_CONFIG", str(exc)) from exc
    return ok({"session_id": session.session_id, "status": session.status})


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    try:
        session = get_orchestrator().storage.load_session(session_id)
    except FileNotFoundError as exc:
        raise api_error("SESSION_NOT_FOUND", f"Session not found: {session_id}") from exc
    return ok(
        {
            "session_id": session.session_id,
            "status": session.status,
            "plan_version": session.plan_version,
        }
    )


@router.get("/session/{session_id}/plan")
async def get_plan(session_id: str):
    try:
        plan = get_orchestrator().storage.load_plan(session_id)
    except FileNotFoundError as exc:
        raise api_error("PLAN_NOT_READY", f"Plan not found for session: {session_id}") from exc
    return ok(plan.model_dump(mode="json", by_alias=True))


@router.get("/session/{session_id}/day/{day_index}")
async def get_day_plan_detail(session_id: str, day_index: int):
    orchestrator = get_orchestrator()
    try:
        orchestrator.storage.load_session(session_id)
    except FileNotFoundError as exc:
        raise api_error("SESSION_NOT_FOUND", f"Session not found: {session_id}") from exc

    try:
        detail = orchestrator.get_day_plan_detail(session_id, day_index)
    except FileNotFoundError as exc:
        raise api_error("PLAN_NOT_READY", f"Plan not found for session: {session_id}") from exc
    except ValueError as exc:
        raise api_error("DAY_NOT_FOUND", str(exc)) from exc
    return ok(detail.model_dump(mode="json"))


@router.post("/session/{session_id}/run_plan")
async def run_plan(session_id: str):
    try:
        plan = await get_orchestrator().run_plan(session_id)
    except ValueError as exc:
        raise api_error("PLAN_FAILED", str(exc)) from exc
    return ok({"plan_id": plan.plan_id, "plan_version": plan.plan_version, "status": plan.status})


@router.post("/session/{session_id}/feedback")
async def submit_feedback(session_id: str, request: SubmitFeedbackRequest):
    try:
        feedback = Feedback.model_validate(
            {
                "feedback_id": request.feedback_id,
                "session_id": session_id,
                "task_id": request.task_id,
                "completion": request.completion,
                "actual_minutes": request.actual_minutes,
                "quiz": request.quiz,
                "reflection": request.reflection,
                "timestamp": __import__("datetime").datetime.now().astimezone().isoformat(),
            }
        )
        result = await get_orchestrator().submit_feedback(session_id, feedback)
    except ValueError as exc:
        raise api_error("INVALID_GOAL_CONFIG", str(exc)) from exc
    return ok(result)


@router.post("/session/{session_id}/replan")
async def replan(session_id: str, request: ReplanRequest):
    try:
        plan = await get_orchestrator().replan(session_id, request.reason)
    except ValueError as exc:
        raise api_error("REPLAN_FAILED", str(exc)) from exc
    diff = plan.diff.model_dump(mode="json") if plan.diff else {"added_tasks": [], "moved_tasks": [], "dropped_tasks": []}
    return ok({"plan_version": plan.plan_version, "diff": diff})


@router.post("/session/{session_id}/task/{task_id}/generate_practice")
async def generate_practice(session_id: str, task_id: str, request: GeneratePracticeRequest):
    try:
        result = await get_orchestrator().generate_practice(session_id, task_id, count=request.count)
    except ValueError as exc:
        raise api_error("TASK_NOT_FOUND", str(exc)) from exc
    return ok(result)


@router.post("/session/{session_id}/day/{day_index}/interactive_page")
async def generate_interactive_page(
    session_id: str,
    day_index: int,
    request: GenerateInteractivePageRequest,
):
    orchestrator = get_orchestrator()
    try:
        orchestrator.storage.load_session(session_id)
    except FileNotFoundError as exc:
        raise api_error("SESSION_NOT_FOUND", f"Session not found: {session_id}") from exc
    try:
        result = await orchestrator.generate_day_interactive_page(
            session_id=session_id,
            day_index=day_index,
            force=request.force,
        )
    except FileNotFoundError as exc:
        raise api_error("PLAN_NOT_READY", f"Plan not found for session: {session_id}") from exc
    except ValueError as exc:
        raise api_error("INTERACTIVE_PAGE_FAILED", str(exc)) from exc
    return ok(result)


@router.post("/session/{session_id}/day/{day_index}/interactive_chat")
async def interactive_chat(
    session_id: str,
    day_index: int,
    request: InteractiveChatRequest,
):
    orchestrator = get_orchestrator()
    try:
        orchestrator.storage.load_session(session_id)
    except FileNotFoundError as exc:
        raise api_error("SESSION_NOT_FOUND", f"Session not found: {session_id}") from exc
    try:
        result = await orchestrator.answer_day_interactive_question(
            session_id=session_id,
            day_index=day_index,
            question=request.question,
        )
    except FileNotFoundError as exc:
        raise api_error("PLAN_NOT_READY", f"Plan not found for session: {session_id}") from exc
    except ValueError as exc:
        raise api_error("INTERACTIVE_CHAT_FAILED", str(exc)) from exc
    return ok(result)


@router.post("/session/{session_id}/exam_analysis")
async def analyze_exam_materials(
    session_id: str,
    pasted_text: str = Form(default=""),
    files: list[UploadFile] = File(default_factory=list),
):
    orchestrator = get_orchestrator()
    try:
        orchestrator.storage.load_session(session_id)
    except FileNotFoundError as exc:
        raise api_error("SESSION_NOT_FOUND", f"Session not found: {session_id}") from exc

    uploads: list[dict] = []
    for item in files:
        data = await item.read()
        if not data:
            continue
        uploads.append(
            {
                "name": item.filename or "upload",
                "content_type": item.content_type or "application/octet-stream",
                "data": data,
            }
        )

    if not pasted_text.strip() and not uploads:
        raise api_error("EMPTY_EXAM_INPUT", "Please provide pasted text or upload exam materials.")

    try:
        result = await orchestrator.analyze_exam_materials(
            session_id=session_id,
            pasted_text=pasted_text,
            uploads=uploads,
        )
    except ValueError as exc:
        raise api_error("EXAM_ANALYSIS_FAILED", str(exc)) from exc
    return ok(result)


@router.websocket("/ws/{session_id}")
async def goal_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    orchestrator = get_orchestrator()

    async def emit_events() -> None:
        event_path = orchestrator.storage.get_session_dir(session_id) / "events.jsonl"
        if not event_path.exists():
            return
        for line in event_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                await websocket.send_json(json.loads(line))

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "run_plan":
                await orchestrator.run_plan(session_id)
                await emit_events()
                plan = orchestrator.storage.load_plan(session_id)
                await websocket.send_json({"type": "plan", "data": plan.model_dump(mode="json", by_alias=True)})
                await websocket.send_json({"type": "complete"})
                continue

            if msg_type == "get_plan":
                plan = orchestrator.storage.load_plan(session_id)
                await websocket.send_json({"type": "plan", "data": plan.model_dump(mode="json", by_alias=True)})
                continue

            if msg_type == "submit_feedback":
                feedback = Feedback.model_validate(message.get("feedback", {}))
                await orchestrator.submit_feedback(session_id, feedback)
                await websocket.send_json({"type": "accepted", "task_id": feedback.task_id})
                continue

            if msg_type == "replan":
                plan = await orchestrator.replan(session_id, message.get("reason"))
                await websocket.send_json({"type": "plan", "data": plan.model_dump(mode="json", by_alias=True)})
                await websocket.send_json({"type": "complete"})
                continue

            await websocket.send_json({"type": "error", "code": "UNKNOWN_MESSAGE", "content": str(msg_type)})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "code": "PLAN_FAILED", "content": str(exc)})
