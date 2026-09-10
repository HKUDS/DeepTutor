"""Guided Learning API Router."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import html
import json
import re
import time
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from deeptutor.learning import policy as learning_policy
from deeptutor.learning import prompts as learning_prompts
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    MasteryInteraction,
    MasteryTopic,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.topic_generation import MAX_MODULE_LIMIT
from deeptutor.services.settings.interface_settings import get_response_language
from deeptutor.utils.json_parser import parse_json_response

router = APIRouter()
ws_router = APIRouter()

#: Signals that change what a topic screen shows without advancing the path's
#: revision, so they are forwarded even when the durable event tail is empty.
#: A conversation joining or leaving the topic changes its session list; a
#: deleted topic changes everything.
_SCREEN_ONLY_SIGNALS = frozenset({"session.bound", "session.released", "topic.deleted"})


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


class TopicSourceRequest(BaseModel):
    id: str = ""
    kind: TopicSourceKind
    source_id: str = ""
    label: str = Field(..., min_length=1, max_length=200)
    excerpt: str = Field(default="", max_length=8_000)
    available: bool = True
    metadata: dict = Field(default_factory=dict)


class GenerateTopicDraftRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    goal: str = Field(..., min_length=1, max_length=2_000)
    sources: list[TopicSourceRequest] = Field(default_factory=list, max_length=16)
    #: Documents a previous draft left out. Sent when the learner asks for
    #: them to be covered, so the regeneration is told what was missed rather
    #: than being asked the same question and expected to answer differently.
    must_cover: list[str] = Field(default_factory=list, max_length=40)


class ConfirmTopicRequest(GenerateTopicDraftRequest):
    # The learner states a goal and picks materials; naming is not one more
    # box to fill before they can start. An empty name is derived from the
    # goal below, and stays renameable afterwards.
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    emoji: str = Field(default="🧭", max_length=16)
    # Optional: a mastery goal is created *before* it has an outline, and the
    # outline is then designed with the tutor in the goal's first session.
    # The region ceiling is the generator's, not a second opinion: a route
    # over a fourteen-document library legitimately has more than eight, and
    # this used to reject the very draft the server had just produced.
    modules: list[dict] = Field(default_factory=list, max_length=MAX_MODULE_LIMIT)


class EditTopicMapRequest(BaseModel):
    modules: list[dict] = Field(..., min_length=1, max_length=MAX_MODULE_LIMIT)


class LearnerOverrideRequest(BaseModel):
    mastered: bool
    note: str = Field(default="", max_length=500)


def _topic_sources(items: list[TopicSourceRequest]) -> list[TopicSource]:
    return [
        TopicSource(
            id=item.id.strip() or f"source_{uuid.uuid4().hex}",
            kind=item.kind,
            source_id=item.source_id.strip()[:300],
            label=item.label.strip(),
            excerpt=item.excerpt.strip(),
            position=index,
            available=item.available,
            metadata=dict(item.metadata),
        )
        for index, item in enumerate(items)
    ]


def _review_queue(progress) -> list[dict]:
    names = {kp.id: kp.name for module in progress.modules for kp in module.knowledge_points}
    return [
        {
            "id": task.id,
            "knowledge_point_id": task.knowledge_point_id,
            "knowledge_point_name": names.get(task.knowledge_point_id, ""),
            "knowledge_type": task.knowledge_type.value,
            "due_at": task.due_at,
            "priority": task.priority,
            "due": task.due_at <= time.time(),
        }
        for task in sorted(progress.review_queue, key=lambda item: item.due_at)
    ]


def _next_step_payload(store: LearningStore, path_id: str, progress) -> dict:
    interaction = (
        store.get_active_interaction(path_id) if progress.pending_question is not None else None
    )
    return _next_step_from_interaction(progress, interaction)


def _next_step_from_interaction(
    progress: LearningProgress,
    interaction: MasteryInteraction | None,
) -> dict:
    return learning_policy.next_objective(
        progress,
        pending_session_id=interaction.session_id if interaction is not None else "",
    ).to_dict()


def _topic_payload_from_snapshot(
    progress: LearningProgress,
    topic: MasteryTopic,
    session_count: int,
    active_interaction: MasteryInteraction | None,
) -> dict:
    path_id = progress.book_id
    return {
        "path_id": path_id,
        "name": learning_policy.path_display_name(progress),
        "metadata": topic.metadata.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in topic.sources],
        "path_revision": progress.version,
        "next": _next_step_from_interaction(progress, active_interaction),
        "map": learning_policy.map_summary(progress),
        "reviews": _review_queue(progress),
        # Who this goal is for. Null until intake has happened, which is also
        # what the dashboard renders as "not asked yet".
        "learner_profile": (
            progress.learner_profile.model_dump(mode="json")
            if progress.learner_profile is not None and not progress.learner_profile.is_empty()
            else None
        ),
        "session_count": session_count,
        "updated_at": progress.updated_at,
    }


def _topic_payload(store: LearningStore, path_id: str) -> dict:
    progress = store.load(path_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Mastery topic not found")
    topic = store.get_topic(path_id, progress=progress)
    if topic is None:  # pragma: no cover - a loaded path always synthesizes metadata
        raise HTTPException(status_code=404, detail="Mastery topic not found")
    active_interaction = (
        store.get_active_interaction(path_id) if progress.pending_question is not None else None
    )
    return _topic_payload_from_snapshot(
        progress,
        topic,
        len(store.list_session_ids(path_id)),
        active_interaction,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/topics")
async def list_topics():
    store = LearningStore()
    topics = await asyncio.to_thread(
        lambda: [
            _topic_payload_from_snapshot(*snapshot)
            for snapshot in store.list_topic_snapshots(status="active")
        ]
    )
    return {"topics": topics}


@router.get("/topics/index")
async def list_topic_index():
    """Just enough to *name* a topic: id, title, emoji.

    The sidebar groups study conversations under their topic, and it refreshes
    on every stream end. ``/topics`` answers with each path's whole knowledge
    map, review queue and source excerpts — kilobytes per topic, none of which
    a group header renders. This is the same walk with the payload cut to what
    a label needs.

    Declared above ``/topics/{path_id}``: that route matches any single
    segment, so a literal path below it would never be reached.
    """
    store = LearningStore()
    return {
        "topics": await asyncio.to_thread(
            lambda: [
                {
                    "path_id": progress.book_id,
                    "name": learning_policy.path_display_name(progress),
                    "emoji": topic.metadata.emoji,
                }
                for progress, topic, _session_count, _interaction in store.list_topic_snapshots(
                    status="active"
                )
            ]
        )
    }


@router.post("/topics/draft")
async def generate_topic_route(body: GenerateTopicDraftRequest):
    from deeptutor.learning.topic_generation import TopicGenerationError, generate_topic_draft

    try:
        return await generate_topic_draft(
            name=body.name,
            goal=body.goal,
            sources=_topic_sources(body.sources),
            language=get_response_language(),
            must_cover=body.must_cover,
        )
    except TopicGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


#: Longest provisional name derived from a goal. A goal is a paragraph; a name
#: has to fit on a card.
_PROVISIONAL_NAME_CHARS = 32


def _provisional_name(goal: str) -> str:
    """A card-sized name for a goal the learner did not name themselves.

    The goal's own opening clause, because that is the sentence they wrote and
    the one they will recognise in a list. Anything is better than the storage
    id, which is what an unnamed path displayed before goals could be created
    without an outline to borrow a module name from.
    """
    head = re.split(r"[\n。.!?！？;；]", str(goal or "").strip(), maxsplit=1)[0].strip()
    if not head:
        return ""
    if len(head) <= _PROVISIONAL_NAME_CHARS:
        return head
    return head[:_PROVISIONAL_NAME_CHARS].rstrip() + "…"


@router.post("/topics")
async def create_topic(body: ConfirmTopicRequest):
    from deeptutor.learning.topic_generation import (
        TopicGenerationError,
        materialize_modules,
    )

    path_id = f"topic_{uuid.uuid4().hex}"
    modules = []
    if body.modules:
        try:
            modules = materialize_modules(
                path_id, body.modules, strict=True, module_limit=MAX_MODULE_LIMIT
            )
        except TopicGenerationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    sources = _topic_sources(body.sources)
    store = LearningStore()
    metadata = TopicMetadata(
        path_id=path_id,
        goal=body.goal.strip(),
        description=body.description.strip(),
        emoji=body.emoji.strip() or "🧭",
        map_seed=store._default_map_seed(path_id),
    )
    # A name is a different object from a goal: the goal is the sentence they
    # wrote, the name is the label they will recognise in a list months later.
    # The task model writes it; the truncated goal stands in when it cannot.
    resolved_name = body.name.strip()
    if not resolved_name:
        from deeptutor.learning.topic_naming import suggest_topic_name

        resolved_name = await suggest_topic_name(
            body.goal,
            source_labels=[source.label for source in sources],
        ) or _provisional_name(body.goal)
    progress = await asyncio.to_thread(
        LearningService(store).create_topic,
        path_id,
        name=resolved_name,
        modules=modules,
        metadata=metadata,
        sources=sources,
    )
    payload = await asyncio.to_thread(_topic_payload, store, path_id)
    payload["path_revision"] = progress.version
    return payload


@router.get("/topics/{path_id}")
async def get_topic(path_id: str):
    _validate_book_id(path_id)
    return await asyncio.to_thread(_topic_payload, LearningStore(), path_id)


@router.put("/topics/{path_id}/map")
async def edit_topic_map(path_id: str, body: EditTopicMapRequest):
    _validate_book_id(path_id)
    from deeptutor.learning.topic_generation import (
        TopicGenerationError,
        materialize_modules,
    )

    async with _exclusive_path_mutation(path_id):
        store = LearningStore()
        progress = await asyncio.to_thread(store.load, path_id)
        if progress is None:
            raise HTTPException(status_code=404, detail="Mastery topic not found")
        existing_module_ids = {module.id for module in progress.modules}
        existing_objective_ids = {
            point.id for module in progress.modules for point in module.knowledge_points
        }
        try:
            modules = materialize_modules(
                path_id,
                body.modules,
                strict=True,
                existing_module_ids=existing_module_ids,
                existing_objective_ids=existing_objective_ids,
                module_limit=MAX_MODULE_LIMIT,
            )
        except TopicGenerationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await asyncio.to_thread(
            LearningService(store).replace_modules_for_path,
            path_id,
            modules,
            event_type="topic.map_edited",
        )
    return await asyncio.to_thread(_topic_payload, LearningStore(), path_id)


@router.post("/topics/{path_id}/objectives/{kp_id}/override")
async def set_learner_override(
    path_id: str,
    kp_id: str,
    body: LearnerOverrideRequest,
):
    _validate_book_id(path_id)
    async with _exclusive_path_mutation(path_id):
        try:
            progress = await asyncio.to_thread(
                LearningService(LearningStore()).set_learner_mastery_override,
                path_id,
                kp_id,
                mastered=body.mastered,
                note=body.note,
            )
        except Exception as exc:
            from deeptutor.learning.service import MasteryInteractionError

            if isinstance(exc, MasteryInteractionError):
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise
    return {
        "status": "ok",
        "path_revision": progress.version,
        "map": learning_policy.map_summary(progress),
    }


@router.get("/topics/{path_id}/sessions")
async def list_topic_sessions(path_id: str):
    _validate_book_id(path_id)
    learning_store = LearningStore()
    if not await asyncio.to_thread(learning_store.exists, path_id):
        raise HTTPException(status_code=404, detail="Mastery topic not found")
    # The same walk chat's navigation tools use (``learning.navigation``), so
    # the atlas screen and a hand-off card can never disagree about which
    # conversations a topic has.
    from deeptutor.learning.navigation import topic_sessions

    return {
        "path_id": path_id,
        "sessions": await topic_sessions(path_id, store=learning_store),
    }


class SetSessionModeRequest(BaseModel):
    mode: str = Field(..., max_length=32)


@router.put("/topics/{path_id}/sessions/{session_id}/mode")
async def set_session_mode(path_id: str, session_id: str, body: SetSessionModeRequest):
    """Change what a conversation is doing, from the learner's own buttons.

    The same move the tutor makes with ``mastery_mode``, through the same
    admission rule — so pressing "Study" on a goal with no outline is refused
    with the sentence the tutor would have said, rather than silently putting
    the conversation somewhere its tools will then refuse to work.
    """
    from deeptutor.capabilities.mastery.mode import MODES, admission_error, normalize_mode

    _validate_book_id(path_id)
    requested = str(body.mode or "").strip().lower()
    if requested not in MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode must be one of: {', '.join(MODES)}",
        )

    store = LearningStore()
    progress = await asyncio.to_thread(store.load, path_id)
    has_outline = progress is not None and any(
        module.knowledge_points for module in progress.modules
    )
    refusal = admission_error(requested, has_outline=has_outline)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)

    from deeptutor.services.session import get_session_store

    session_store = get_session_store()
    if await session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await session_store.update_session_preferences(session_id, {"mastery_session_mode": requested})
    return {"session_id": session_id, "mode": normalize_mode(requested)}


@router.get("/topics/{path_id}/ask-hint")
async def get_topic_ask_hint(path_id: str, session_id: str = ""):
    """One question the learner could ask here, for the composer placeholder.

    Written by the task model, never blocking: an empty ``hint`` means the
    composer keeps the static placeholder it has always had.
    """
    _validate_book_id(path_id)
    from deeptutor.services.mastery_hints import get_ask_hint

    return await get_ask_hint(path_id, session_id)


@ws_router.websocket("/mastery-paths")
async def mastery_topic_websocket(ws: WebSocket) -> None:
    """Subscribe to one living topic with durable revision replay."""

    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.learning.event_hub import mastery_topic_event_hub
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return
    await ws.accept()
    send_lock = asyncio.Lock()
    subscription = None
    forward_task: asyncio.Task | None = None
    cursor = 0

    async def send(payload: dict) -> None:
        async with send_lock:
            await ws.send_json(payload)

    async def stop_forwarding() -> None:
        nonlocal subscription, forward_task
        if subscription is not None:
            subscription.close()
            subscription = None
        if forward_task is not None:
            forward_task.cancel()
            with suppress(asyncio.CancelledError):
                await forward_task
            forward_task = None

    async def forward(path_id: str, store: LearningStore) -> None:
        nonlocal cursor
        assert subscription is not None
        while True:
            signal = await subscription.get()
            events = await asyncio.to_thread(
                store.list_events,
                path_id,
                after_revision=cursor,
            )
            if events:
                cursor = max(cursor, max(event.revision for event in events))
            elif signal.revision <= cursor and signal.reason not in _SCREEN_ONLY_SIGNALS:
                continue
            cursor = max(cursor, signal.revision)
            await send(
                {
                    "type": "topic_event",
                    "path_id": path_id,
                    "revision": cursor,
                    "reason": signal.reason,
                    "sequence": signal.sequence,
                    "events": [event.model_dump(mode="json") for event in events],
                }
            )

    try:
        while True:
            try:
                message = await ws.receive_json()
            except WebSocketDisconnect:
                break
            message_type = str(message.get("type") or "").strip()
            if message_type != "subscribe":
                await send({"type": "error", "content": "Expected a subscribe message"})
                continue
            path_id = str(message.get("path_id") or "").strip()
            try:
                _validate_book_id(path_id)
            except HTTPException:
                await send({"type": "error", "content": "Invalid path_id"})
                continue
            store = LearningStore()
            if not await asyncio.to_thread(store.exists, path_id):
                await send({"type": "error", "content": "Mastery topic not found"})
                continue

            await stop_forwarding()
            requested_cursor = max(0, int(message.get("after_revision") or 0))
            progress = await asyncio.to_thread(store.load, path_id)
            current_revision = int(progress.version if progress else 0)
            # A stale browser cache must not be able to pin the subscription
            # beyond the server's durable head and suppress future updates.
            cursor = min(requested_cursor, current_revision)
            # Register before replay. A concurrent commit is therefore either
            # present in this DB tail, queued on the subscription, or both;
            # the cursor in ``forward`` removes the harmless overlap.
            subscription = mastery_topic_event_hub.subscribe(
                path_id,
                scope=store.event_scope,
            )
            events = await asyncio.to_thread(
                store.list_events,
                path_id,
                after_revision=cursor,
            )
            if events:
                cursor = max(cursor, max(event.revision for event in events))
            cursor = max(cursor, current_revision)
            await send(
                {
                    "type": "subscribed",
                    "path_id": path_id,
                    "revision": cursor,
                    "events": [event.model_dump(mode="json") for event in events],
                }
            )
            forward_task = asyncio.create_task(forward(path_id, store))
    finally:
        await stop_forwarding()
        reset_current_user(user_token)


@router.get("/progress")
async def list_all_progress():
    service = get_learning_service()
    return await asyncio.to_thread(service.list_progress)


@router.get("/progress/{book_id}")
async def get_progress(book_id: str):
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = await asyncio.to_thread(service.store.load, book_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Mastery progress not found")
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
        "next": _next_step_payload(service.store, book_id, progress),
        "map": learning_policy.map_summary(progress),
    }


@router.get("/progress/{book_id}/board")
async def get_progress_board(book_id: str):
    """The visual learning board: every knowledge point as a card, enriched
    with its next review time and a deterministic grid position derived from
    the module order. A read-only projection of the same mastery data the
    tutor and the map view use."""
    _validate_book_id(book_id)
    service = get_learning_service()
    progress = service.get_or_create(book_id)
    summary = learning_policy.map_summary(progress)

    due_by_kp = {task.knowledge_point_id: task.due_at for task in progress.review_queue}

    cards: list[dict] = []
    modules: list[dict] = []
    for module in summary["modules"]:
        module_cards: list[dict] = []
        for index, kp in enumerate(module["knowledge_points"]):
            card = {
                "id": kp["id"],
                "name": kp["name"],
                "type": kp["type"],
                "module_id": module["id"],
                "module_name": module["name"],
                "status": kp["status"],
                "mastery_level": kp["mastery"],
                "next_review_at": due_by_kp.get(kp["id"]),
                "position": {"column": module["order"], "row": index},
            }
            cards.append(card)
            module_cards.append(card)
        modules.append(
            {
                "id": module["id"],
                "name": module["name"],
                "order": module["order"],
                "mastered": module["mastered"],
                "total": module["total"],
                "cards": module_cards,
            }
        )

    return {
        "book_id": book_id,
        "name": summary["name"],
        "path_revision": progress.version,
        "cards": cards,
        "modules": modules,
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


class GenerateFromReadingRequest(BaseModel):
    workspace_id: str
    material_ids: list[str] = Field(default_factory=list, max_length=20)


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


@router.post("/progress/{book_id}/generate-from-reading")
async def generate_from_reading(book_id: str, body: GenerateFromReadingRequest):
    """Create a mastery curriculum from a private reading workspace."""
    from deeptutor.reading.knowledge_capture import mastery_source_records

    try:
        records = await asyncio.to_thread(
            mastery_source_records,
            body.workspace_id,
            material_ids=body.material_ids,
        )
    except Exception as exc:
        from deeptutor.reading import ReadingError

        if isinstance(exc, ReadingError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise
    return await generate_from_notebook(
        book_id,
        GenerateFromNotebookRequest(
            notebook_id=f"reading:{body.workspace_id}",
            records=[NotebookRecordInput(**record) for record in records],
        ),
    )
