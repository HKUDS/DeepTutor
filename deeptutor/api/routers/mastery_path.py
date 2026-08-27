"""Guided Learning API Router."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import html
import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from deeptutor.learning import policy as learning_policy
from deeptutor.learning import prompts as learning_prompts
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.settings.interface_settings import get_response_language
from deeptutor.utils.json_parser import parse_json_response

router = APIRouter()


def get_learning_service() -> LearningService:
    # Create a fresh store + service per request to avoid object-level race conditions.
    store = LearningStore()
    return LearningService(store)


def _validate_book_id(book_id: str) -> None:
    """Reject empty or path-traversal-bearing book ids (shared by all endpoints)."""
    if not book_id or ".." in book_id or "/" in book_id or "\\" in book_id or ":" in book_id:
        raise HTTPException(status_code=400, detail="Invalid book_id")


def _parse_modules(body_modules: list[dict]) -> list[LearningModule]:
    """Parse raw module dicts into LearningModule objects (shared by init/replace)."""
    modules: list[LearningModule] = []
    for i, m in enumerate(body_modules):
        kps_data = m.get("knowledge_points", [])
        try:
            kps = [KnowledgePoint(**kp) for kp in kps_data]
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid knowledge_point data in modules[{i}]: {exc.errors()}",
            ) from exc
        # Remove knowledge_points from m to avoid duplicate argument to LearningModule.
        m_clean = {k: v for k, v in m.items() if k != "knowledge_points"}
        try:
            modules.append(LearningModule(knowledge_points=kps, **m_clean))
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid module data in modules[{i}]: {exc.errors()}",
            ) from exc
    return modules


def _validate_runnable_modules(modules: list[LearningModule], *, status_code: int = 400) -> None:
    if not modules:
        raise HTTPException(
            status_code=status_code, detail="At least one learning module is required"
        )
    for mod in modules:
        if not mod.knowledge_points:
            raise HTTPException(
                status_code=status_code,
                detail=f"Module {mod.id!r} must contain at least one knowledge point",
            )


async def _cancel_active_learning_turn(book_id: str) -> None:
    from deeptutor.services.session import get_turn_runtime_manager

    learning_store = LearningStore()
    runtime = get_turn_runtime_manager()
    lease = await asyncio.to_thread(learning_store.get_path_lease, book_id)
    if lease is not None:
        if lease.session_id == "__path_api__":
            # Another administrative mutation owns the path. The caller's
            # acquisition attempt will return a deterministic HTTP 409.
            return
        await runtime.cancel_turn(lease.turn_id)
        # ``cancel_turn`` can finalize a restart orphan without an in-memory
        # task, so its normal runtime ``finally`` cannot release the lease.
        await asyncio.to_thread(
            learning_store.release_path_lease,
            book_id,
            turn_id=lease.turn_id,
        )
        return

    # Compatibility for turns started before explicit path leases existed.
    session_ids = await asyncio.to_thread(learning_store.list_session_ids, book_id)
    if book_id not in session_ids:
        session_ids.append(book_id)
    for session_id in session_ids:
        for turn in await runtime.store.list_active_turns(session_id):
            if str(turn.get("capability") or "") == "mastery_path":
                await runtime.cancel_turn(turn["id"])


@asynccontextmanager
async def _exclusive_path_mutation(book_id: str):
    """Cancel the tutor, then exclude a newly racing tutor/API write."""
    from deeptutor.learning.storage import PathLeaseConflictError

    await _cancel_active_learning_turn(book_id)
    store = LearningStore()
    operation_id = f"api-{uuid.uuid4().hex}"
    try:
        await asyncio.to_thread(
            store.acquire_path_lease,
            book_id,
            "__path_api__",
            operation_id,
            bind_session=False,
        )
    except PathLeaseConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Mastery path changed activity while the operation was starting; "
                f"active session: {exc.lease.session_id}"
            ),
        ) from exc
    try:
        yield
    finally:
        await asyncio.to_thread(
            store.release_path_lease,
            book_id,
            turn_id=operation_id,
        )


# ── Request models ───────────────────────────────────────────────────────────


class InitModulesRequest(BaseModel):
    modules: list[dict]  # list of LearningModule-compatible dicts


class RenamePathRequest(BaseModel):
    """An empty name is a valid request: it restores the derived display name."""

    name: str = ""


class ChapterImport(BaseModel):
    title: str
    knowledge_points: list[str] = []


class ImportFromBookRequest(BaseModel):
    chapters: list[ChapterImport]


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/progress")
async def list_all_progress():
    service = get_learning_service()
    return service.list_progress()


@router.get("/progress/{book_id}")
async def get_progress(book_id: str):
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    payload = progress.model_dump(mode="json")
    if progress.pending_question is not None:
        from deeptutor.learning.pending import public_pending_question

        payload["pending_question"] = public_pending_question(progress.pending_question).to_dict()
    return payload


@router.get("/progress/{book_id}/map")
async def get_progress_map(book_id: str):
    """The dashboard view of a path: the gate-decided next step plus a map of
    every objective's status (new / learning / mastered). The per-type gate
    lives in ``learning.policy`` so the dashboard and the tutor agree."""
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    return {
        "book_id": book_id,
        "name": learning_policy.path_display_name(progress),
        "path_revision": progress.version,
        "next": learning_policy.next_objective(progress).to_dict(),
        "map": learning_policy.map_summary(progress),
    }


@router.get("/progress/{book_id}/objectives/{kp_id}")
async def get_objective_report(book_id: str, kp_id: str):
    """The evidence behind one objective: attempts, schedule, errors, prompts.

    ``policy.objective_report`` is pure over the aggregate, so the questions
    themselves — which live in the durable interaction log, not the aggregate —
    are joined on here, redacted of their answer keys.
    """
    _validate_book_id(book_id)
    store = LearningStore()
    progress = await asyncio.to_thread(store.load, book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    report = learning_policy.objective_report(progress, kp_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Objective not found")

    from deeptutor.learning.pending import public_pending_question

    interactions = await asyncio.to_thread(store.list_interactions, book_id)
    prompts = {
        interaction.interaction_id: public_pending_question(interaction.question).prompt
        for interaction in interactions
    }
    for attempt in report["attempts"]:
        attempt["prompt"] = prompts.get(attempt["question_id"], "")
    return {"book_id": book_id, "path_revision": progress.version, "objective": report}


@router.get("/progress/{book_id}/events")
async def get_progress_events(book_id: str, after_revision: int = 0):
    """Ordered, redacted domain events for reconnect and incremental UI sync."""
    _validate_book_id(book_id)
    store = LearningStore()
    progress = await asyncio.to_thread(store.load, book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found")
    events = await asyncio.to_thread(
        store.list_events,
        book_id,
        after_revision=max(0, after_revision),
    )
    return {
        "book_id": book_id,
        "events": [event.model_dump(mode="json") for event in events],
    }


@router.get("/progress/{book_id}/sessions")
async def get_progress_sessions(book_id: str):
    """Expose the explicit conversation associations for this path."""
    _validate_book_id(book_id)
    store = LearningStore()
    if not await asyncio.to_thread(store.exists, book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    session_ids = await asyncio.to_thread(store.list_session_ids, book_id)
    return {"book_id": book_id, "session_ids": session_ids}


@router.post("/progress/{book_id}/init-modules")
async def init_modules(book_id: str, body: InitModulesRequest):
    _validate_book_id(book_id)
    modules = _parse_modules(body.modules)
    _validate_runnable_modules(modules)
    async with _exclusive_path_mutation(book_id):
        service = get_learning_service()
        progress = await asyncio.to_thread(service.replace_modules_for_path, book_id, modules)
    return {
        "status": "ok",
        "module_count": len(modules),
        "path_revision": progress.version,
    }


@router.post("/progress/{book_id}/import-from-book")
async def import_from_book(book_id: str, body: ImportFromBookRequest):
    _validate_book_id(book_id)
    modules = []
    for i, ch in enumerate(body.chapters):
        kps = [
            KnowledgePoint(
                id=f"{book_id}_ch{i}_kp{j}",
                name=kp_name,
                type=KnowledgeType("concept"),
                module_id=f"{book_id}_ch{i}",
            )
            for j, kp_name in enumerate(ch.knowledge_points)
        ]
        modules.append(
            LearningModule(
                id=f"{book_id}_ch{i}",
                name=ch.title or f"Chapter {i + 1}",
                order=i,
                pass_threshold=0.7,
                knowledge_points=kps,
            )
        )
    _validate_runnable_modules(modules)
    async with _exclusive_path_mutation(book_id):
        service = get_learning_service()
        progress = await asyncio.to_thread(service.replace_modules_for_path, book_id, modules)
    return {
        "status": "ok",
        "module_count": len(modules),
        "path_revision": progress.version,
    }


@router.patch("/progress/{book_id}")
async def rename_progress(book_id: str, body: RenamePathRequest):
    """Rename a path — the only edit that is the learner's rather than the tutor's.

    Guarded like every other path mutation so a rename cannot interleave with a
    tutoring turn's own commit, and emitted as an event so the activity feed
    records who called it what.
    """
    _validate_book_id(book_id)
    store = LearningStore()
    if not await asyncio.to_thread(store.exists, book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    async with _exclusive_path_mutation(book_id):
        progress = await asyncio.to_thread(LearningService(store).rename_path, book_id, body.name)
    return {
        "status": "ok",
        "name": learning_policy.path_display_name(progress),
        "path_revision": progress.version,
    }


@router.delete("/progress/{book_id}")
async def delete_progress(book_id: str):
    _validate_book_id(book_id)
    store = LearningStore()
    if not await asyncio.to_thread(store.exists, book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    async with _exclusive_path_mutation(book_id):
        await asyncio.to_thread(store.delete, book_id)
    return {"status": "ok"}


@router.post("/progress/{book_id}/skip-question")
async def skip_pending_question(book_id: str):
    """Drop an outstanding question the learner can no longer answer.

    The narrow escape hatch for a path stalled on ``answer_pending``; unlike
    ``redo`` it keeps every mastery level and review the learner has earned.
    """
    _validate_book_id(book_id)
    store = LearningStore()
    if not await asyncio.to_thread(store.exists, book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    async with _exclusive_path_mutation(book_id):
        progress, skipped = await asyncio.to_thread(
            LearningService(store).abandon_active_question, book_id
        )
    return {"status": "ok", "skipped": skipped, "path_revision": progress.version}


@router.post("/progress/{book_id}/redo")
async def redo_progress(book_id: str):
    _validate_book_id(book_id)
    store = LearningStore()
    if not await asyncio.to_thread(store.exists, book_id):
        raise HTTPException(status_code=404, detail="Progress not found")
    async with _exclusive_path_mutation(book_id):
        progress = await asyncio.to_thread(LearningService(store).reset_path, book_id)
    return {"status": "ok", "path_revision": progress.version}


class NotebookRecordInput(BaseModel):
    id: str
    type: str = "note"
    title: str = ""
    output: str = ""


class GenerateFromNotebookRequest(BaseModel):
    notebook_id: str
    records: list[NotebookRecordInput]


@router.post("/progress/{book_id}/generate-from-notebook")
async def generate_from_notebook(book_id: str, body: GenerateFromNotebookRequest):
    _validate_book_id(book_id)
    if not body.records:
        raise HTTPException(status_code=400, detail="No records provided")

    records_data = [
        {
            "type": html.escape(r.type[:50], quote=False),
            "title": html.escape(r.title[:200], quote=False),
            "output": html.escape(r.output[:500], quote=False),
        }
        for r in body.records[:20]
    ]
    records_json = json.dumps(records_data, ensure_ascii=False)
    from deeptutor.services.llm import complete

    language = get_response_language()
    system_prompt, prompt = learning_prompts.notebook_generation_prompts(language, records_json)
    response = await complete(prompt=prompt, system_prompt=system_prompt)
    # LLMs commonly fence/slightly-malform JSON; use the shared fence-stripping
    # repair parser instead of bare json.loads so the common case isn't a 502.
    data = parse_json_response(response, fallback=None)
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM returned invalid JSON")

    modules_raw = data.get("modules", [])
    if not isinstance(modules_raw, list):
        raise HTTPException(
            status_code=502, detail="LLM returned invalid structure: modules is not a list"
        )
    _ALLOWED_KP_TYPES = {"memory", "concept", "procedure", "design"}
    modules = []
    for i, m in enumerate(modules_raw):
        if not isinstance(m, dict) or "name" not in m:
            continue
        fallback_name = learning_prompts.default_module_name(language, i + 1)
        module_name = str(m.get("name") or fallback_name).strip()[:200] or fallback_name
        kps = []
        for j, kp in enumerate(m.get("knowledge_points", [])):
            if not isinstance(kp, dict) or "name" not in kp:
                continue
            kp_name = str(kp["name"]).strip()[:200]
            if len(kp_name) < 2:
                continue
            kp_type = str(kp.get("type", "concept")).strip()
            if kp_type not in _ALLOWED_KP_TYPES:
                kp_type = "concept"
            kps.append(
                KnowledgePoint(
                    id=f"{book_id}_nb{i}_kp{j}",
                    name=kp_name,
                    type=KnowledgeType(kp_type),
                    module_id=f"{book_id}_nb{i}",
                )
            )
        modules.append(
            LearningModule(
                id=f"{book_id}_nb{i}",
                name=module_name,
                order=i,
                pass_threshold=0.7,
                knowledge_points=kps,
            )
        )
    _validate_runnable_modules(modules, status_code=502)
    async with _exclusive_path_mutation(book_id):
        service = get_learning_service()
        progress = await asyncio.to_thread(service.replace_modules_for_path, book_id, modules)
    return {
        "status": "ok",
        "module_count": len(modules),
        "modules": [m.model_dump() for m in modules],
        "path_revision": progress.version,
    }
