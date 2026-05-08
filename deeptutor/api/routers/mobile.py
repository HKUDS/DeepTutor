"""
Mobile HTTP facade for replayable turn events.

Mini Programs cannot always keep a WebSocket connection alive in preview,
background, or constrained network modes. These endpoints expose the same
``TurnRuntimeManager`` used by ``/api/v1/ws`` through start + long-poll HTTP
calls, so mobile clients do not need a separate chat engine.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from deeptutor.services.session import get_turn_runtime_manager

router = APIRouter()


def _should_append_content(event: dict[str, Any]) -> bool:
    if event.get("type") != "content":
        return False
    metadata = event.get("metadata") or {}
    call_id = metadata.get("call_id")
    if not call_id:
        return True
    return metadata.get("call_kind") == "llm_final_response"


def _terminal_status(event: dict[str, Any]) -> str:
    metadata = event.get("metadata") or {}
    if event.get("type") == "error":
        return str(metadata.get("status") or "failed")
    if event.get("type") == "done":
        return str(metadata.get("status") or "completed")
    return ""


def _next_seq(after_seq: int, events: list[dict[str, Any]]) -> int:
    return max([after_seq, *[int(event.get("seq") or 0) for event in events]])


async def _collect_turn_events(
    turn_id: str,
    *,
    after_seq: int = 0,
    timeout_seconds: float = 25.0,
) -> tuple[list[dict[str, Any]], str]:
    runtime = get_turn_runtime_manager()
    events: list[dict[str, Any]] = []
    status = "running"

    async def collect() -> None:
        nonlocal status
        async for event in runtime.subscribe_turn(turn_id, after_seq=after_seq):
            events.append(event)
            terminal = _terminal_status(event)
            if terminal:
                status = terminal
            if event.get("type") in {"done", "error"}:
                break

    try:
        await asyncio.wait_for(collect(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        status = "running"

    return events, status


@router.post("/mobile/chat/turn")
async def start_mobile_chat_turn(
    payload: dict[str, Any] = Body(default_factory=dict),
    wait: bool = Query(True),
    timeout_seconds: float = Query(55.0, ge=1.0, le=180.0),
) -> dict[str, Any]:
    """Start a real DeepTutor turn and optionally long-poll its events."""

    runtime = get_turn_runtime_manager()
    message = {
        **payload,
        "type": payload.get("type") or "start_turn",
        "language": payload.get("language") or "zh",
    }

    try:
        session, turn = await runtime.start_turn(message)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_id = str(session.get("id") or "")
    turn_id = str(turn.get("id") or "")

    if not wait:
        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "status": "running",
            "content": "",
            "events": [],
            "next_seq": 0,
        }

    events, status = await _collect_turn_events(
        turn_id,
        after_seq=0,
        timeout_seconds=timeout_seconds,
    )
    content = "".join(str(event.get("content") or "") for event in events if _should_append_content(event))

    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "status": status,
        "content": content,
        "events": events,
        "next_seq": _next_seq(0, events),
    }


@router.get("/mobile/turns/{turn_id}/events")
async def get_mobile_turn_events(
    turn_id: str,
    after_seq: int = Query(0, ge=0),
    timeout_seconds: float = Query(25.0, ge=0.0, le=60.0),
) -> dict[str, Any]:
    """Long-poll replayable turn events for HTTP-only clients."""

    events, status = await _collect_turn_events(
        turn_id,
        after_seq=after_seq,
        timeout_seconds=timeout_seconds,
    )
    content = "".join(str(event.get("content") or "") for event in events if _should_append_content(event))

    return {
        "turn_id": turn_id,
        "status": status,
        "content": content,
        "events": events,
        "next_seq": _next_seq(after_seq, events),
    }


@router.post("/mobile/turns/{turn_id}/cancel")
async def cancel_mobile_turn(turn_id: str) -> dict[str, Any]:
    """Cancel a running mobile turn."""

    cancelled = await get_turn_runtime_manager().cancel_turn(turn_id)
    return {"turn_id": turn_id, "cancelled": cancelled}
