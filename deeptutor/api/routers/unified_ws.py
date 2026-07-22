"""
Unified WebSocket Endpoint
==========================

Single ``/api/v1/ws`` endpoint for turn-based execution and replayable streaming.

Supported client message ``type`` values:

- ``message`` / ``start_turn`` — start a new turn from a payload.
- ``subscribe_turn`` — stream events of an existing turn (with ``after_seq``).
- ``subscribe_session`` — stream events of the active turn for a session.
- ``resume_from`` — resume an in-flight turn after reconnection.
- ``unsubscribe`` — stop a previously created subscription.
- ``cancel_turn`` — cancel a running turn.
- ``submit_user_reply`` — deliver the user's reply for an ``ask_user``
  paused turn so the agentic loop can resume on the same turn.
- ``regenerate`` — re-run the last user message in the given session as a
  brand-new turn. Replaces the trailing assistant message (if any) and
  reuses the session's stored capability/tools/preferences. Optional
  ``overrides`` field accepts ``capability``, ``tools``, ``knowledge_bases``,
  ``language``, ``config``, ``notebook_references``, ``history_references``.
  Errors: ``regenerate_busy`` (another turn is running) and
  ``nothing_to_regenerate`` (no prior user message).
- ``check_active_turn`` — report whether the session has a live running turn;
  replies with ``active_turn_info`` (``turn_id``/``status``), marking stale
  persisted "running" rows as cancelled when no live execution exists.
- ``user_input`` — deliver a learner answer to the turn's StreamBus
  (resolves a pending ``wait_for_input``, e.g. an ``ask_user`` pause).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def unified_websocket(ws: WebSocket) -> None:
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    await ws.accept()
    closed = False
    subscription_tasks: dict[str, asyncio.Task[None]] = {}

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            # default=str so one non-serializable value inside an event can
            # never poison the push channel (send_json would raise, flag the
            # socket as closed, and silently freeze the stream for the user).
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            closed = True

    async def stop_subscription(key: str) -> None:
        task = subscription_tasks.pop(key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def subscribe_turn(turn_id: str, after_seq: int = 0) -> None:
        from deeptutor.services.session import get_turn_runtime_manager

        async def _forward() -> None:
            runtime = get_turn_runtime_manager()
            async for event in runtime.subscribe_turn(turn_id, after_seq=after_seq):
                await safe_send(event)

        await stop_subscription(turn_id)
        subscription_tasks[turn_id] = asyncio.create_task(_forward())

    async def subscribe_session(session_id: str, after_seq: int = 0) -> None:
        from deeptutor.services.session import get_turn_runtime_manager

        async def _forward() -> None:
            runtime = get_turn_runtime_manager()
            async for event in runtime.subscribe_session(session_id, after_seq=after_seq):
                await safe_send(event)

        key = f"session:{session_id}"
        await stop_subscription(key)
        subscription_tasks[key] = asyncio.create_task(_forward())

    try:
        while not closed:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await safe_send({"type": "error", "content": "Invalid JSON."})
                continue

            msg_type = msg.get("type")

            if msg_type in {"message", "start_turn"}:
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                try:
                    _, turn = await runtime.start_turn(msg)
                except RuntimeError as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "source": "unified_ws",
                            "stage": "",
                            "content": str(exc),
                            "metadata": {"turn_terminal": True, "status": "rejected"},
                            "session_id": str(msg.get("session_id") or ""),
                            "turn_id": "",
                            "seq": 0,
                        }
                    )
                    continue
                await subscribe_turn(turn["id"], after_seq=0)
                continue

            if msg_type == "ping":
                # Client-side heartbeat. Respond with a lightweight pong so
                # the client knows the socket is alive; the client never
                # consumes pong as a user-visible event (see unified-ws.ts
                # filter below) but does refresh ``lastReceivedAt`` from it.
                await safe_send({"type": "pong"})
                continue

            if msg_type == "subscribe_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                await subscribe_turn(turn_id, after_seq=int(msg.get("after_seq") or 0))
                continue

            if msg_type == "subscribe_session":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                await subscribe_session(session_id, after_seq=int(msg.get("after_seq") or 0))
                continue

            if msg_type == "check_active_turn":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                active_turn = await runtime.store.get_active_turn(session_id)
                if active_turn:
                    # Verify the turn has a live execution; stale persisted
                    # "running" rows (e.g. after server restart) have none.
                    turn_id = active_turn["id"]
                    has_live = await runtime.has_live_execution(turn_id)
                    if has_live:
                        await safe_send(
                            {
                                "type": "active_turn_info",
                                "turn_id": turn_id,
                                "status": active_turn.get("status", "running"),
                            }
                        )
                    else:
                        # Stale turn from a previous process — mark it terminal
                        # so create_turn won't reject the upcoming start_turn.
                        await runtime.store.update_turn_status(
                            turn_id, "cancelled", "Stale turn after restart"
                        )
                        await safe_send(
                            {"type": "active_turn_info", "turn_id": "", "status": "none"}
                        )
                else:
                    await safe_send({"type": "active_turn_info", "turn_id": "", "status": "none"})
                continue

            if msg_type == "resume_from":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                await subscribe_turn(turn_id, after_seq=int(msg.get("seq") or 0))
                continue

            if msg_type == "unsubscribe":
                turn_id = str(msg.get("turn_id") or "").strip()
                if turn_id:
                    await stop_subscription(turn_id)
                session_id = str(msg.get("session_id") or "").strip()
                if session_id:
                    await stop_subscription(f"session:{session_id}")
                continue

            if msg_type == "cancel_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                cancelled = await runtime.cancel_turn(turn_id)
                if not cancelled:
                    await safe_send({"type": "error", "content": f"Turn not found: {turn_id}"})
                continue

            if msg_type == "submit_user_reply":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id."})
                    continue
                # Accept either the legacy ``text`` (single free-form
                # reply) or the v2 ``answers`` (list of {questionId, text}
                # pairs). Empty text is allowed (lets the user signal "I
                # have no answer" without typing).
                text = msg.get("text")
                text_str = str(text) if text is not None else None
                answers_raw = msg.get("answers")
                answers: list[dict[str, Any]] | None = None
                if isinstance(answers_raw, list):
                    cleaned: list[dict[str, Any]] = []
                    for entry in answers_raw:
                        if not isinstance(entry, dict):
                            continue
                        qid = str(entry.get("questionId") or entry.get("id") or "").strip()
                        if not qid:
                            continue
                        cleaned.append({"questionId": qid, "text": str(entry.get("text") or "")})
                    answers = cleaned or None
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                accepted = await runtime.submit_user_reply(turn_id, text=text_str, answers=answers)
                if not accepted:
                    await safe_send(
                        {
                            "type": "error",
                            "content": (f"Turn {turn_id} is not awaiting a user reply."),
                        }
                    )
                continue

            if msg_type == "regenerate":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await safe_send({"type": "error", "content": "Missing session_id."})
                    continue
                from deeptutor.services.session import get_turn_runtime_manager

                runtime = get_turn_runtime_manager()
                overrides = msg.get("overrides") if isinstance(msg.get("overrides"), dict) else None
                try:
                    _, turn = await runtime.regenerate_last_turn(
                        session_id,
                        overrides=overrides,
                    )
                except RuntimeError as exc:
                    await safe_send(
                        {
                            "type": "error",
                            "source": "unified_ws",
                            "stage": "",
                            "content": str(exc),
                            "metadata": {
                                "turn_terminal": True,
                                "status": "rejected",
                                "reason": str(exc),
                            },
                            "session_id": session_id,
                            "turn_id": "",
                            "seq": 0,
                        }
                    )
                    continue
                await subscribe_turn(turn["id"], after_seq=0)
                continue

            if msg_type == "user_input":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await safe_send({"type": "error", "content": "Missing turn_id for user_input."})
                    continue
                from deeptutor.core.stream_bus import get_bus

                bus = get_bus(turn_id)
                if bus is None:
                    await safe_send(
                        {"type": "error", "content": f"No active bus for turn: {turn_id}"}
                    )
                    continue
                bus.submit_input(str(msg.get("content") or ""))
                continue

            await safe_send({"type": "error", "content": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.debug("Client disconnected from /ws")
    except Exception as exc:
        logger.error("Unified WS error: %s", exc, exc_info=True)
        await safe_send({"type": "error", "content": str(exc)})
    finally:
        closed = True
        for key in list(subscription_tasks.keys()):
            await stop_subscription(key)
        if user_token is not None:
            reset_current_user(user_token)
