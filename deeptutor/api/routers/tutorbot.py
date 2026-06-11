"""
TutorBot management API.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deeptutor.services.tutorbot import get_tutorbot_manager
from deeptutor.services.tutorbot.manager import (
    BotConfig,
    TutorBotInstance,
    mask_channel_secrets,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# Per-bot async locks used to dedupe concurrent WebSocket-driven auto-starts.
# `manager.start_bot` already short-circuits when the bot is already running,
# but that check is not async-safe: two coroutines that both observe a stopped
# bot will each run the full start sequence. Serializing on a per-bot lock
# avoids the duplicated work and noisy logs.
_start_locks: dict[str, asyncio.Lock] = {}
_start_locks_mutex = asyncio.Lock()


async def _get_start_lock(bot_id: str) -> asyncio.Lock:
    async with _start_locks_mutex:
        lock = _start_locks.get(bot_id)
        if lock is None:
            lock = asyncio.Lock()
            _start_locks[bot_id] = lock
        return lock


async def _ensure_running_bot(bot_id: str) -> TutorBotInstance:
    mgr = get_tutorbot_manager()
    instance = mgr.get_bot(bot_id)
    if instance and instance.running:
        return instance

    config = mgr.load_bot_config(bot_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Bot not found")

    lock = await _get_start_lock(bot_id)
    async with lock:
        instance = mgr.get_bot(bot_id)
        if instance and instance.running:
            return instance
        try:
            return await mgr.start_bot(bot_id, config)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        except Exception as exc:
            logger.exception("Failed to auto-start bot '%s'", bot_id)
            raise HTTPException(status_code=500, detail="Failed to start bot") from exc


class CreateBotRequest(BaseModel):
    bot_id: str
    name: str | None = None
    description: str | None = None
    persona: str | None = None
    channels: dict | None = None
    model: str | None = None
    llm_selection: dict[str, str] | None = None


class UpdateBotRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    persona: str | None = None
    channels: dict | None = None
    model: str | None = None
    llm_selection: dict[str, str] | None = None
    allow_shell_exec: bool | None = None


class FileUpdateRequest(BaseModel):
    content: str


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(..., min_length=1)
    session_id: str | None = None
    chat_id: str | None = None
    llm_selection: dict[str, str] | None = Field(default=None, alias="llmSelection")


class SoulCreateRequest(BaseModel):
    id: str
    name: str
    content: str


class SoulUpdateRequest(BaseModel):
    name: str | None = None
    content: str | None = None


# ── Soul template library (must be before /{bot_id} routes) ───


@router.get("/souls")
async def list_souls():
    return get_tutorbot_manager().list_souls()


@router.post("/souls")
async def create_soul(payload: SoulCreateRequest):
    mgr = get_tutorbot_manager()
    if mgr.get_soul(payload.id):
        raise HTTPException(status_code=409, detail=f"Soul '{payload.id}' already exists")
    return mgr.create_soul(payload.id, payload.name, payload.content)


@router.get("/souls/{soul_id}")
async def get_soul(soul_id: str):
    soul = get_tutorbot_manager().get_soul(soul_id)
    if not soul:
        raise HTTPException(status_code=404, detail="Soul not found")
    return soul


@router.put("/souls/{soul_id}")
async def update_soul(soul_id: str, payload: SoulUpdateRequest):
    result = get_tutorbot_manager().update_soul(soul_id, payload.name, payload.content)
    if not result:
        raise HTTPException(status_code=404, detail="Soul not found")
    return result


@router.delete("/souls/{soul_id}")
async def delete_soul(soul_id: str):
    if not get_tutorbot_manager().delete_soul(soul_id):
        raise HTTPException(status_code=404, detail="Soul not found")
    return {"id": soul_id, "deleted": True}


# ── Bot management (static paths before /{bot_id} parameterized routes) ──


@router.get("")
async def list_bots():
    return get_tutorbot_manager().list_bots()


@router.get("/recent")
async def recent_bots(limit: int = 3):
    """Return the most recently active bots with their last message preview."""
    return get_tutorbot_manager().get_recent_active_bots(limit=limit)


@router.get("/channels/schema")
async def list_channel_schemas():
    """Return JSON-Schema metadata for every available channel.

    Powers the schema-driven Channels tab in the Web UI: lets it render a
    generic form for ANY channel (built-in or plugin) without per-channel
    front-end code. Secret-looking fields are flagged via ``secret_fields``
    so the UI can mask them.

    Shape:
        {
          "channels": {
            "telegram": {
              "name": "telegram",
              "display_name": "Telegram",
              "default_config": {...},
              "secret_fields": ["token"],
              "json_schema": {...}
            },
            ...
          },
          "global": {"json_schema": {...}, "secret_fields": []}
        }
    """
    from deeptutor.api.routers._tutorbot_channel_schema import (
        all_channel_schemas,
        global_channels_schema,
    )

    return {
        "channels": all_channel_schemas(),
        "global": global_channels_schema(),
    }


@router.post("")
async def create_and_start_bot(payload: CreateBotRequest):
    mgr = get_tutorbot_manager()
    # Only fields the client actually sent are forwarded as overrides; this lets
    # users explicitly clear values (e.g. ``description=""``) while *omitted*
    # fields fall back to the on-disk config — preventing the historical bug
    # where each restart wiped out user-configured channels.
    overrides = payload.model_dump(exclude_unset=True, exclude={"bot_id"})
    if "llm_selection" in overrides:
        overrides["llm_selection"] = _validate_llm_selection_payload(overrides["llm_selection"])
    config = mgr.merge_bot_config(payload.bot_id, overrides)
    try:
        instance = await mgr.start_bot(payload.bot_id, config)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    # Response is masked — secrets are only revealed via the explicit
    # GET /{bot_id}?include_secrets=true edit-form route.
    return instance.to_dict(mask_secrets=True)


def _stopped_bot_dict(
    bot_id: str,
    cfg: BotConfig,
    *,
    include_secrets: bool = False,
) -> dict:
    """Serialise a stopped bot — secret fields masked unless explicitly opted-in."""
    if include_secrets:
        channels: object = cfg.channels
    else:
        channels = mask_channel_secrets(cfg.channels)
    return {
        "bot_id": bot_id,
        "name": cfg.name,
        "description": cfg.description,
        "persona": cfg.persona,
        "channels": channels,
        "model": cfg.model,
        "llm_selection": cfg.llm_selection,
        "allow_shell_exec": cfg.allow_shell_exec,
        "running": False,
        "started_at": None,
        "last_reload_error": None,
    }


@router.get("/{bot_id}")
async def get_bot(
    bot_id: str,
    include_secrets: bool = Query(
        False,
        description=(
            "Return raw channel secrets (tokens, passwords). Required by the "
            "admin edit form; default response masks all secret-looking fields."
        ),
    ),
):
    mgr = get_tutorbot_manager()
    instance = mgr.get_bot(bot_id)
    if instance:
        return instance.to_dict(
            include_secrets=include_secrets,
            mask_secrets=not include_secrets,
        )
    cfg = mgr.load_bot_config(bot_id)
    if cfg:
        return _stopped_bot_dict(bot_id, cfg, include_secrets=include_secrets)
    raise HTTPException(status_code=404, detail="Bot not found")


@router.delete("/{bot_id}")
async def stop_bot(bot_id: str):
    stopped = await get_tutorbot_manager().stop_bot(bot_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Bot not found or not running")
    return {"bot_id": bot_id, "stopped": True}


@router.delete("/{bot_id}/destroy")
async def destroy_bot(bot_id: str):
    destroyed = await get_tutorbot_manager().destroy_bot(bot_id)
    if not destroyed:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"bot_id": bot_id, "destroyed": True}


def _validate_channels_payload(channels: dict) -> None:
    """Reject malformed channel configs at the API boundary (returns 422).

    Without this check, the bad config would still hit disk and only blow up
    later inside ``reload_channels`` / next ``start_bot`` — leaving a confusing
    500 with no guidance to the caller.
    """
    from deeptutor.tutorbot.config.schema import ChannelsConfig

    try:
        ChannelsConfig(**channels)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid channels config", "errors": exc.errors()},
        ) from None
    except TypeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid channels config: {exc}",
        ) from None


def _validate_llm_selection_payload(
    value: dict[str, str] | None,
) -> dict[str, str] | None:
    """Validate a bot model selection against the shared LLM catalog."""
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.model_selection import apply_llm_selection_to_catalog
    from deeptutor.services.tutorbot.model_runtime import normalize_tutorbot_llm_selection

    try:
        selection = normalize_tutorbot_llm_selection(value)
        if selection:
            apply_llm_selection_to_catalog(get_model_catalog_service().load(), selection)
        return selection
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _apply_payload(target: BotConfig | TutorBotInstance, payload: UpdateBotRequest) -> None:
    """Apply non-None fields from ``payload`` onto a ``BotConfig`` (or instance.config)."""
    cfg: BotConfig = getattr(target, "config", target)
    if payload.name is not None:
        cfg.name = payload.name
    if payload.description is not None:
        cfg.description = payload.description
    if payload.persona is not None:
        cfg.persona = payload.persona
    if payload.channels is not None:
        cfg.channels = payload.channels
    if payload.model is not None:
        cfg.model = payload.model
    if "llm_selection" in payload.model_fields_set:
        cfg.llm_selection = _validate_llm_selection_payload(payload.llm_selection)
    if payload.allow_shell_exec is not None:
        cfg.allow_shell_exec = payload.allow_shell_exec


@router.patch("/{bot_id}")
async def update_bot(bot_id: str, payload: UpdateBotRequest):
    if payload.channels is not None:
        _validate_channels_payload(payload.channels)
    if "llm_selection" in payload.model_fields_set:
        _validate_llm_selection_payload(payload.llm_selection)

    mgr = get_tutorbot_manager()
    llm_changed = bool({"llm_selection", "model"} & payload.model_fields_set)
    instance = mgr.get_bot(bot_id)
    if instance:
        _apply_payload(instance, payload)
        mgr.save_bot_config(bot_id, instance.config)
        if payload.channels is not None:
            try:
                await mgr.reload_channels(bot_id)
            except Exception as exc:
                logger.exception("reload_channels failed for bot '%s'", bot_id)
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Channels saved but failed to restart listeners "
                        f"({type(exc).__name__}); try stopping and starting the bot."
                    ),
                ) from None
        if llm_changed:
            try:
                reload_llm = getattr(mgr, "reload_llm", None)
                if reload_llm is not None:
                    await reload_llm(bot_id)
            except Exception as exc:
                logger.exception("reload_llm failed for bot '%s'", bot_id)
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "LLM config saved but failed to reload "
                        f"({type(exc).__name__}); try stopping and starting the bot."
                    ),
                ) from None
        # NOTE: response masks secrets — front-end should re-fetch with
        # ``?include_secrets=true`` if it needs the raw token to refill its form.
        return instance.to_dict(mask_secrets=True)

    cfg = mgr.load_bot_config(bot_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Bot not found")

    _apply_payload(cfg, payload)
    mgr.save_bot_config(bot_id, cfg)
    return _stopped_bot_dict(bot_id, cfg)


# ── Workspace file endpoints ──────────────────────────────────


@router.get("/{bot_id}/files")
async def list_bot_files(bot_id: str):
    return get_tutorbot_manager().read_all_bot_files(bot_id)


@router.get("/{bot_id}/files/{filename}")
async def read_bot_file(bot_id: str, filename: str):
    content = get_tutorbot_manager().read_bot_file(bot_id, filename)
    if content is None:
        raise HTTPException(status_code=400, detail=f"Not an editable file: {filename}")
    return {"filename": filename, "content": content}


@router.put("/{bot_id}/files/{filename}")
async def write_bot_file(bot_id: str, filename: str, payload: FileUpdateRequest):
    ok = get_tutorbot_manager().write_bot_file(bot_id, filename, payload.content)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Not an editable file: {filename}")
    return {"filename": filename, "saved": True}


# ── Chat history & WebSocket ──────────────────────────────────


@router.get("/{bot_id}/history")
async def get_bot_history(bot_id: str, limit: int = 100):
    """Read chat history from the bot's per-bot JSONL session files."""
    return get_tutorbot_manager().get_bot_history(bot_id, limit=limit)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _resolve_http_session(payload: ChatMessageRequest) -> tuple[str, str]:
    """Return ``(session_id, chat_id)`` for HTTP/SSE TutorBot conversations."""
    explicit_session = (payload.session_id or "").strip()
    explicit_chat = (payload.chat_id or "").strip()
    if explicit_session:
        return explicit_session, explicit_chat or explicit_session
    if explicit_chat:
        return explicit_chat, explicit_chat
    session_id = uuid4().hex
    return session_id, session_id


@router.post("/{bot_id}/chat")
async def bot_chat_http(bot_id: str, payload: ChatMessageRequest) -> dict[str, Any]:
    """Send one HTTP message to a specified TutorBot with persistent session context."""
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    await _ensure_running_bot(bot_id)
    mgr = get_tutorbot_manager()
    session_id, chat_id = _resolve_http_session(payload)
    try:
        response = await mgr.send_message(
            bot_id,
            content,
            chat_id=chat_id,
            session_id=session_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "bot_id": bot_id,
        "session_id": session_id,
        "content": response,
    }


async def _bot_chat_stream(
    bot_id: str,
    payload: ChatMessageRequest,
) -> AsyncGenerator[str, None]:
    mgr = get_tutorbot_manager()
    content = payload.content.strip()
    if not content:
        yield _sse("error", {"detail": "content is required"})
        return
    session_id, chat_id = _resolve_http_session(payload)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    done = asyncio.Event()
    holder: dict[str, Any] = {}

    async def on_progress(text: str) -> None:
        await queue.put({"event": "thinking", "payload": {"content": text}})

    async def run() -> None:
        try:
            holder["content"] = await mgr.send_message(
                bot_id,
                content,
                chat_id=chat_id,
                session_id=session_id,
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            holder["error"] = str(exc)
        finally:
            done.set()

    yield _sse("session", {"bot_id": bot_id, "session_id": session_id})
    task = asyncio.create_task(run())
    try:
        while not done.is_set():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.15)
            except asyncio.TimeoutError:
                continue
            yield _sse(item["event"], item["payload"])
        while not queue.empty():
            item = queue.get_nowait()
            yield _sse(item["event"], item["payload"])
        if holder.get("error"):
            yield _sse("error", {"detail": holder["error"]})
            return
        yield _sse("content", {"content": holder.get("content", "")})
        yield _sse("done", {"bot_id": bot_id, "session_id": session_id})
    finally:
        if not task.done():
            task.cancel()


@router.post("/{bot_id}/chat/execute-stream")
async def bot_chat_http_stream(bot_id: str, payload: ChatMessageRequest):
    """Stream one HTTP message to a specified TutorBot as server-sent events."""
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    await _ensure_running_bot(bot_id)
    return StreamingResponse(
        _bot_chat_stream(bot_id, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/{bot_id}/ws")
async def bot_chat_ws(ws: WebSocket, bot_id: str):
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    disconnected = asyncio.Event()

    async def _safe_send(payload: dict) -> bool:
        try:
            await ws.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError):
            disconnected.set()
            return False

    mgr = get_tutorbot_manager()
    instance = mgr.get_bot(bot_id)

    await ws.accept()

    if not instance or not instance.running:
        config = mgr.load_bot_config(bot_id)
        if config is None:
            await _safe_send({"type": "error", "content": "Bot not found"})
            await ws.close(code=4004, reason="Bot not found")
            return
        # Serialize concurrent starts of the same bot so only one
        # WebSocket connection actually triggers `start_bot`; the rest
        # observe the now-running instance and reuse it.
        lock = await _get_start_lock(bot_id)
        async with lock:
            instance = mgr.get_bot(bot_id)
            if not instance or not instance.running:
                try:
                    instance = await mgr.start_bot(bot_id, config)
                except Exception:
                    logger.exception("Failed to auto-start bot '%s' for websocket", bot_id)
                    await _safe_send({"type": "error", "content": "Failed to start bot"})
                    await ws.close(code=1011, reason="Failed to start bot")
                    return

    logger.info("WebSocket connected for bot '%s'", bot_id)

    async def _handle_user_messages():
        while not disconnected.is_set():
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                disconnected.set()
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                if not await _safe_send({"type": "error", "content": "Invalid JSON"}):
                    break
                continue

            content = data.get("content", "").strip()
            if not content:
                continue

            async def on_progress(text: str) -> None:
                # Best-effort: never raise. If the client is gone, just stop
                # forwarding progress; the surrounding loop will notice the
                # `disconnected` event and exit. Raising here would leak
                # WebSocketDisconnect into `mgr.send_message`, which catches
                # `Exception` broadly and would swallow the disconnect signal,
                # leaving the bot to finish an expensive turn for nobody.
                await _safe_send({"type": "thinking", "content": text})

            try:
                chat_id_value = data.get("chat_id", "web")
                session_id_value = data.get("session_id")
                response = await mgr.send_message(
                    bot_id,
                    content,
                    chat_id=chat_id_value,
                    session_id=session_id_value,
                    on_progress=on_progress,
                )
                if not await _safe_send({"type": "content", "content": response}):
                    break
                if not await _safe_send({"type": "done"}):
                    break
            except RuntimeError as exc:
                if not await _safe_send({"type": "error", "content": str(exc)}):
                    break
            except WebSocketDisconnect:
                disconnected.set()
                break
            except Exception:
                logger.exception("Error processing message for bot '%s'", bot_id)
                if not await _safe_send({"type": "error", "content": "Internal error"}):
                    break

    async def _handle_notifications():
        # Race the queue read against the disconnect signal so this loop
        # cooperates with client disconnects detected by the other task.
        while not disconnected.is_set():
            get_task = asyncio.create_task(instance.notify_queue.get())
            wait_task = asyncio.create_task(disconnected.wait())
            done, pending = await asyncio.wait(
                {get_task, wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if get_task not in done:
                break
            content = get_task.result()
            if not await _safe_send({"type": "proactive", "content": content}):
                break

    user_task = asyncio.create_task(_handle_user_messages())
    notify_task = asyncio.create_task(_handle_notifications())
    try:
        done, pending = await asyncio.wait(
            [user_task, notify_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        disconnected.set()
        for t in pending:
            t.cancel()
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                logger.exception(
                    "WebSocket task error for bot '%s'", bot_id, exc_info=t.exception()
                )
    except Exception:
        disconnected.set()
        user_task.cancel()
        notify_task.cancel()
    finally:
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
    logger.info("WebSocket closed for bot '%s'", bot_id)
