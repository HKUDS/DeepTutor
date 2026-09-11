"""CRUD and live discussion API for first-class Partner Groups."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from deeptutor.services.partner_groups import (
    discussion_mode_registry,
    get_partner_group_manager,
    shared_memory_registry,
)

router = APIRouter()
ws_router = APIRouter()


class CreatePartnerGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    member_ids: list[str] = Field(..., min_length=2)
    discussion_mode: str = "panel_parallel"
    shared_memory: str = "whiteboard"
    emoji: str = "👥"
    color: str = "#6366f1"


class UpdatePartnerGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    member_ids: list[str] | None = None
    discussion_mode: str | None = None
    shared_memory: str | None = None
    emoji: str | None = None
    color: str | None = None


class PartnerGroupMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    session_key: str = Field(default="default", min_length=1, max_length=120)
    # ``None`` means parse @mentions from content; [] deliberately means no
    # explicit mentions and therefore follows the @all default.
    mentions: list[str] | None = None


class PartnerInvocationActionRequest(BaseModel):
    session_key: str = Field(default="default", min_length=1, max_length=120)


class CreatePartnerInvocationRequest(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=120)
    requester_partner_id: str = Field(..., min_length=1, max_length=80)
    target_partner_id: str = Field(..., min_length=1, max_length=80)
    question: str = Field(..., min_length=1, max_length=2_000)


class WhiteboardPinRequest(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=128)


class PartnerSeatRetryRequest(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=120)


class RoundSummaryRequest(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=120)
    partner_id: str = Field(..., min_length=1, max_length=80)


def _group_or_404(group_id: str):
    group = get_partner_group_manager().get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Partner Group not found")
    return group


@router.get("")
async def list_partner_groups():
    return get_partner_group_manager().list_groups()


@router.get("/discussion-modes")
async def list_discussion_modes():
    return discussion_mode_registry.describe()


@router.get("/shared-memory-types")
async def list_shared_memory_types():
    return shared_memory_registry.describe()


@router.post("")
async def create_partner_group(payload: CreatePartnerGroupRequest):
    try:
        group = get_partner_group_manager().create_group(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return get_partner_group_manager().describe_group(group)


@router.get("/{group_id}")
async def get_partner_group(group_id: str):
    group = _group_or_404(group_id)
    return get_partner_group_manager().describe_group(group)


@router.patch("/{group_id}")
async def update_partner_group(group_id: str, payload: UpdatePartnerGroupRequest):
    _group_or_404(group_id)
    try:
        group = get_partner_group_manager().update_group(
            group_id, payload.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return get_partner_group_manager().describe_group(group)


@router.delete("/{group_id}")
async def delete_partner_group(group_id: str):
    _group_or_404(group_id)
    get_partner_group_manager().delete_group(group_id)
    return {"deleted": True, "group_id": group_id}


@router.get("/{group_id}/history")
async def partner_group_history(
    group_id: str,
    session_key: str = Query("default", min_length=1, max_length=120),
    limit: int = Query(200, ge=1, le=500),
):
    _group_or_404(group_id)
    return get_partner_group_manager().history(group_id, session_key, limit=limit)


@router.get("/{group_id}/sessions")
async def list_partner_group_sessions(group_id: str):
    _group_or_404(group_id)
    return get_partner_group_manager().list_sessions(group_id)


@router.post("/{group_id}/sessions", status_code=201)
async def create_partner_group_session(group_id: str):
    _group_or_404(group_id)
    return get_partner_group_manager().create_session(group_id)


@router.delete("/{group_id}/sessions/{session_key}")
async def delete_partner_group_session(group_id: str, session_key: str):
    _group_or_404(group_id)
    try:
        deleted = get_partner_group_manager().delete_session(group_id, session_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if not deleted:
        raise HTTPException(status_code=404, detail="Partner Group session not found")
    return {"deleted": True, "session_key": session_key}


@router.get("/{group_id}/whiteboard")
async def partner_group_whiteboard(
    group_id: str,
    limit: int = Query(200, ge=1, le=500),
):
    _group_or_404(group_id)
    return get_partner_group_manager().whiteboard(group_id, limit=limit)


@router.post("/{group_id}/whiteboard/pins")
async def pin_partner_group_whiteboard(group_id: str, payload: WhiteboardPinRequest):
    _group_or_404(group_id)
    try:
        return get_partner_group_manager().pin_whiteboard(group_id, payload.event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.delete("/{group_id}/whiteboard/pins/{event_id}")
async def unpin_partner_group_whiteboard(group_id: str, event_id: str):
    _group_or_404(group_id)
    if not get_partner_group_manager().unpin_whiteboard(group_id, event_id):
        raise HTTPException(status_code=404, detail="Whiteboard pin not found")
    return {"deleted": True, "event_id": event_id}


@router.get("/{group_id}/invocations")
async def partner_group_invocations(
    group_id: str,
    session_key: str = Query("default", min_length=1, max_length=120),
    limit: int = Query(200, ge=1, le=500),
):
    _group_or_404(group_id)
    return get_partner_group_manager().invocations(group_id, session_key, limit=limit)


@router.post("/{group_id}/invocations")
async def create_partner_invocation(
    group_id: str,
    payload: CreatePartnerInvocationRequest,
):
    _group_or_404(group_id)
    try:
        invocation = get_partner_group_manager().create_invocation(
            group_id,
            session_key=payload.session_key,
            requester_partner_id=payload.requester_partner_id,
            target_partner_id=payload.target_partner_id,
            question=payload.question,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return invocation.to_dict()


@router.post("/{group_id}/messages")
async def send_partner_group_message(group_id: str, payload: PartnerGroupMessageRequest):
    _group_or_404(group_id)
    try:
        result = await get_partner_group_manager().send_message(
            group_id,
            content=payload.content,
            session_key=payload.session_key,
            mentions=payload.mentions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return result.to_dict()


@router.post("/{group_id}/turns/{turn_id}/partners/{partner_id}/retry")
async def retry_partner_group_seat(
    group_id: str,
    turn_id: str,
    partner_id: str,
    payload: PartnerSeatRetryRequest,
):
    _group_or_404(group_id)
    try:
        live = get_partner_group_manager().start_live_retry(
            group_id,
            turn_id=turn_id,
            partner_id=partner_id,
            session_key=payload.session_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    assert live.task is not None
    await live.task
    failure = next((frame for frame in reversed(live.frames) if frame.get("type") == "error"), None)
    if failure is not None:
        raise HTTPException(status_code=500, detail=str(failure.get("content") or "Retry failed"))
    done = next((frame for frame in reversed(live.frames) if frame.get("type") == "done"), None)
    if done is None:
        raise HTTPException(status_code=500, detail="Retry ended without a result")
    return done["result"]


@router.post("/{group_id}/rounds/{turn_id}/summary")
async def summarize_partner_group_round(
    group_id: str,
    turn_id: str,
    payload: RoundSummaryRequest,
):
    _group_or_404(group_id)
    try:
        live = get_partner_group_manager().start_live_summary(
            group_id,
            turn_id=turn_id,
            partner_id=payload.partner_id,
            session_key=payload.session_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        status_code = 409 if "still in progress" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from None
    assert live.task is not None
    await live.task
    failure = next((frame for frame in reversed(live.frames) if frame.get("type") == "error"), None)
    if failure is not None:
        raise HTTPException(
            status_code=500,
            detail=str(failure.get("content") or "Round summary failed"),
        )
    done = next((frame for frame in reversed(live.frames) if frame.get("type") == "done"), None)
    if done is None:
        raise HTTPException(status_code=500, detail="Round summary ended without a result")
    return done["result"]


@router.post("/{group_id}/invocations/{invocation_id}/approve")
async def approve_partner_invocation(
    group_id: str,
    invocation_id: str,
    payload: PartnerInvocationActionRequest,
):
    _group_or_404(group_id)
    try:
        reply = await get_partner_group_manager().approve_invocation(
            group_id,
            invocation_id,
            session_key=payload.session_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return reply.to_dict()


@router.post("/{group_id}/invocations/{invocation_id}/reject")
async def reject_partner_invocation(
    group_id: str,
    invocation_id: str,
    payload: PartnerInvocationActionRequest,
):
    _group_or_404(group_id)
    try:
        invocation = get_partner_group_manager().reject_invocation(
            group_id,
            invocation_id,
            session_key=payload.session_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return invocation.to_dict()


@ws_router.websocket("/{group_id}")
async def partner_group_ws(ws: WebSocket, group_id: str):
    """Stream Group messages plus owner-visible, speaker-scoped traces.

    ``partner_trace`` frames are never persisted into public context or shown
    to peer Partners. ``invoke_other`` remains a proposal until this socket (or
    the REST endpoint) receives an explicit approve action.
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return
    if get_partner_group_manager().get_group(group_id) is None:
        if user_token is not None:
            reset_current_user(user_token)
        await ws.close(code=4404)
        return

    await ws.accept()
    manager = get_partner_group_manager()
    send_lock = asyncio.Lock()
    push_tasks: dict[int, asyncio.Task] = {}

    async def send(frame: dict) -> None:
        async with send_lock:
            await ws.send_json(frame)

    async def push_live(live) -> None:
        queue = live.subscribe()
        try:
            while True:
                frame = await queue.get()
                await send(frame)
                if frame.get("type") in {"done", "error", "cancelled"}:
                    break
        finally:
            live.unsubscribe(queue)

    def attach(live) -> None:
        key = id(live)
        previous = push_tasks.get(key)
        if previous is not None and not previous.done():
            return
        task = asyncio.create_task(push_live(live))
        push_tasks[key] = task

        def forget(done: asyncio.Task) -> None:
            push_tasks.pop(key, None)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(forget)

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            try:
                data = json.loads(raw)
            except Exception:
                await send({"type": "error", "content": "Invalid Group message"})
                continue
            session_key = str(data.get("session_key") or "default")[:120]
            action = str(data.get("action") or "")
            if action == "attach":
                for live in manager.subscribe_live_turns(group_id, session_key):
                    attach(live)
                continue
            elif action == "create_invocation":
                try:
                    invocation = manager.create_invocation(
                        group_id,
                        session_key=session_key,
                        requester_partner_id=str(data.get("requester_partner_id") or ""),
                        target_partner_id=str(data.get("target_partner_id") or ""),
                        question=str(data.get("question") or ""),
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
                await send({"type": "invocation_updated", "invocation": invocation.to_dict()})
                continue
            elif action == "approve_invocation":
                try:
                    live = manager.start_live_invocation(
                        group_id,
                        invocation_id=str(data.get("invocation_id") or ""),
                        session_key=session_key,
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
            elif action == "reject_invocation":
                try:
                    invocation = manager.reject_invocation(
                        group_id,
                        str(data.get("invocation_id") or ""),
                        session_key=session_key,
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
                await send({"type": "invocation_updated", "invocation": invocation.to_dict()})
                continue
            elif action == "retry_partner":
                try:
                    live = manager.start_live_retry(
                        group_id,
                        turn_id=str(data.get("turn_id") or ""),
                        partner_id=str(data.get("partner_id") or ""),
                        session_key=session_key,
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
            elif action == "summarize_round":
                try:
                    live = manager.start_live_summary(
                        group_id,
                        turn_id=str(data.get("turn_id") or ""),
                        partner_id=str(data.get("partner_id") or ""),
                        session_key=session_key,
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
            elif action == "cancel":
                try:
                    live = manager.cancel_live_turn(
                        group_id,
                        session_key,
                        invocation_id=str(data.get("invocation_id") or ""),
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
                attach(live)
                await send(
                    {
                        "type": "cancel_requested",
                        "operation": live.operation,
                        "invocation_id": live.invocation_id,
                    }
                )
                continue
            else:
                try:
                    payload = PartnerGroupMessageRequest.model_validate(data)
                except Exception:
                    await send({"type": "error", "content": "Invalid Group message"})
                    continue
                try:
                    live = manager.start_live_turn(
                        group_id,
                        content=payload.content,
                        session_key=payload.session_key,
                        mentions=payload.mentions,
                    )
                except (LookupError, ValueError) as exc:
                    await send({"type": "error", "content": str(exc)})
                    continue
            # Push frames in a separate task so this receive loop remains able
            # to approve/reject/cancel while Partners are still running.
            attach(live)
    finally:
        for task in tuple(push_tasks.values()):
            task.cancel()
        if push_tasks:
            await asyncio.gather(*tuple(push_tasks.values()), return_exceptions=True)
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass


__all__ = ["router"]
