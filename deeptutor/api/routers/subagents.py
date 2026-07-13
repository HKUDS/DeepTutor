"""Subagent connections API.

Backs the "My Agents → connected agents" feature: detect which local agent CLIs
(Claude Code / Codex) are installed on this machine, connect one as a pointer KB
the chat composer can select, and configure the consult budget. Connections are
stored as ``type: subagent`` knowledge bases (per-user, via the KB manager), so
they ride the same selection/persistence path as the other connected KB types —
the subagent capability drives them live, nothing is indexed.

The CLIs run on the host with the host user's own credentials, so detection is
machine-global; whether a connection is usable is simply "is the CLI installed
here". If it isn't, the UI just doesn't offer it.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin
from deeptutor.knowledge.kb_types import SUBAGENT_KB_TYPE
from deeptutor.multi_user.knowledge_access import current_kb_manager
from deeptutor.multi_user.partner_access import assert_partner_allowed, visible_partner_cards
from deeptutor.services.rag.linked_kb import assert_path_allowed
from deeptutor.services.subagent import (
    PARTNER_BACKEND_KIND,
    detect_all,
    list_backend_kinds,
    load_subagent_settings,
    save_subagent_settings,
    settings_from_dict,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectSubagentRequest(BaseModel):
    name: str
    agent_kind: str
    cwd: str = ""
    # For the partner backend (``agent_kind == "partner"``): which partner to
    # consult. Ignored by the local-CLI backends, which use ``cwd`` instead.
    partner_id: str = ""


class SubagentSettingsPayload(BaseModel):
    consult_budget: int | None = None
    backends: dict[str, dict] | None = Field(default=None)


class SubagentMessageRequest(BaseModel):
    chat_session_id: str = ""
    message: str


@router.get("/detect")
async def detect_subagents():
    """Report which agent CLIs are installed and usable on this machine."""
    detections = await detect_all()
    return {"backends": [d.to_dict() for d in detections]}


@router.get("/backends/options")
async def backend_options():
    """Synced model + reasoning-effort options per backend (settings page sync)."""
    from deeptutor.services.subagent.models import list_backend_options

    options = await list_backend_options()
    return {"backends": [o.to_dict() for o in options]}


@router.post("/backends/{kind}/sync")
async def sync_backend(kind: str):
    """Re-pull one backend's model catalog (the settings "sync" button).

    For Claude Code this scrapes its ``/model`` TUI live and caches the result;
    for Codex it re-reads the CLI-maintained cache.
    """
    from deeptutor.services.subagent import get_backend
    from deeptutor.services.subagent.models import sync_backend_options

    backend = get_backend(kind)
    if backend is None or not getattr(backend, "local_cli", True):
        # Only local CLIs have a model catalog to sync; partners run their own.
        raise HTTPException(status_code=400, detail=f"Unknown agent kind: {kind!r}")
    options = await sync_backend_options(kind)
    return options.to_dict()


@router.get("/partners")
async def list_visible_partners():
    """Partners the current user can connect & consult.

    Returns every partner for an admin, or just the ones an admin has assigned
    for a non-admin. The partner CRUD API (``/api/v1/partners``) stays fully
    admin-gated; this is the read surface the connect flow and the partner list
    page use, so a non-admin sees their assigned partners without a 403.
    """
    return {"partners": visible_partner_cards()}


@router.get("/connections")
async def list_connections():
    """List the current user's connected subagents."""
    manager = current_kb_manager()
    connections = []
    for name in manager.list_knowledge_bases():
        meta = manager.get_metadata(name)
        if not isinstance(meta, dict) or meta.get("type") != SUBAGENT_KB_TYPE:
            continue
        connections.append(
            {
                "name": name,
                "agent_kind": meta.get("agent_kind", ""),
                "cwd": meta.get("cwd", ""),
                "partner_id": meta.get("partner_id", ""),
                "description": meta.get("description", ""),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
            }
        )
    return {"connections": connections}


@router.post("/connections")
async def create_connection(payload: ConnectSubagentRequest):
    """Connect a subagent (a local CLI, or one of the user's partners) as a selectable KB.

    A partner connection (``agent_kind == "partner"``) binds a ``partner_id``
    instead of a working directory: consulting it opens a fresh session on that
    partner, exactly as if the user started one from the partner page. Every
    consult within one DeepTutor chat lands in that one partner session.
    """
    name = (payload.name or "").strip()
    agent_kind = (payload.agent_kind or "").strip()
    if not name or not agent_kind:
        raise HTTPException(status_code=400, detail="Both name and agent_kind are required.")
    if agent_kind not in list_backend_kinds():
        raise HTTPException(status_code=400, detail=f"Unknown agent kind: {agent_kind!r}")

    resolved_cwd = ""
    partner_id = ""
    if agent_kind == PARTNER_BACKEND_KIND:
        partner_id = (payload.partner_id or "").strip()
        if not partner_id:
            raise HTTPException(
                status_code=400, detail="A partner_id is required to connect a partner."
            )
        # Partners are admin-managed, but an admin can assign one to a user via
        # the grant system. An admin may connect any partner; a non-admin only a
        # partner assigned to them (403 otherwise). The partner still runs in its
        # own isolated scope — connecting just lets the user consult it in chat.
        assert_partner_allowed(partner_id)
        from deeptutor.services.partners import get_partner_manager

        if not get_partner_manager().partner_exists(partner_id):
            raise HTTPException(status_code=400, detail=f"No partner named {partner_id!r}.")
    else:
        raw_cwd = (payload.cwd or "").strip()
        if raw_cwd:
            try:
                resolved_cwd = str(assert_path_allowed(raw_cwd))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        manager = current_kb_manager()
        entry = manager.register_subagent_connection(
            name, agent_kind, cwd=resolved_cwd, partner_id=partner_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error connecting subagent: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "connected",
        "name": name,
        "agent_kind": entry["agent_kind"],
        "cwd": entry["cwd"],
        "partner_id": entry.get("partner_id", ""),
    }


@router.delete("/connections/{name}")
async def delete_connection(name: str):
    """Disconnect a subagent (removes the pointer KB; touches no files)."""
    manager = current_kb_manager()
    meta = manager.get_metadata(name)
    if not isinstance(meta, dict) or meta.get("type") != SUBAGENT_KB_TYPE:
        raise HTTPException(status_code=404, detail=f"No connected subagent named {name!r}.")
    try:
        manager.delete_knowledge_base(name, confirm=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error disconnecting subagent: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Drop any remembered live-session ids for this connection.
    from deeptutor.services.subagent.sessions import forget_connection

    forget_connection(name)
    return {"status": "disconnected", "name": name}


def _ndjson(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


@router.post("/connections/{name}/message")
async def message_connection(name: str, payload: SubagentMessageRequest):
    """Send a message straight to a connected subagent and stream its run.

    This is the sidebar's "talk to the agent directly" path: it resumes the same
    live session DeepTutor consults (shared via the cross-turn registry, keyed by
    chat session + connection), so the agent keeps full context. Streams the
    native run as newline-delimited JSON, in the same channel shape the chat WS
    uses, so the sidebar transcript renders it identically.
    """
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A non-empty 'message' is required.")

    manager = current_kb_manager()
    meta = manager.get_metadata(name)
    if not isinstance(meta, dict) or meta.get("type") != SUBAGENT_KB_TYPE:
        raise HTTPException(status_code=404, detail=f"No connected subagent named {name!r}.")

    from deeptutor.services.subagent import get_backend
    from deeptutor.services.subagent.sessions import get_session, remember_session, session_key

    kind = str(meta.get("agent_kind") or "")
    cwd = str(meta.get("cwd") or "")
    partner_id = str(meta.get("partner_id") or "")
    backend = get_backend(kind)
    if backend is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent kind: {kind!r}")

    config = load_subagent_settings().backend(kind)
    skey = session_key(payload.chat_session_id, name) if payload.chat_session_id else ""
    resume_id = get_session(skey) if skey else None

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event) -> None:
            await queue.put(("event", event))

        async def run() -> None:
            try:
                res = await backend.consult(
                    message,
                    on_event=on_event,
                    cwd=cwd or None,
                    session_id=resume_id,
                    config=config,
                    partner_id=partner_id or None,
                )
                await queue.put(("done", res))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("subagent message failed: %s", exc, exc_info=True)
                await queue.put(("fail", str(exc)))

        task = asyncio.create_task(run())
        # The user's own message heads the exchange.
        yield _ndjson({"channel": "user_question", "text": message})
        try:
            while True:
                kind_, item = await queue.get()
                if kind_ == "event":
                    line = {"channel": item.kind, "text": item.text}
                    merge_id = (item.meta or {}).get("merge_id")
                    if merge_id:
                        # Namespace away from the chat turn's consult merge ids.
                        line["merge_id"] = f"side:{merge_id}"
                    yield _ndjson(line)
                elif kind_ == "done":
                    if skey and item.session_id:
                        remember_session(skey, item.session_id, kind=kind, cwd=cwd)
                    yield _ndjson(
                        {"done": True, "success": item.success, "session_id": item.session_id or ""}
                    )
                    break
                else:  # fail
                    yield _ndjson({"channel": "error", "text": item})
                    yield _ndjson({"done": True, "success": False})
                    break
        finally:
            if not task.done():
                await task

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/settings")
async def get_settings():
    """Read the consult budget and per-backend run config."""
    return load_subagent_settings().to_dict()


@router.put("/settings", dependencies=[Depends(require_admin)])
async def update_settings(payload: SubagentSettingsPayload):
    """Update the subagent settings (admin-gated; deployment-wide)."""
    merged = load_subagent_settings().to_dict()
    if payload.consult_budget is not None:
        merged["consult_budget"] = payload.consult_budget
    if payload.backends is not None:
        # Merge per backend (and per field) so saving one backend's settings
        # never clobbers the other's or any unsent field.
        backends = dict(merged.get("backends") or {})
        for kind, cfg in payload.backends.items():
            backends[str(kind)] = {**(backends.get(str(kind)) or {}), **(cfg or {})}
        merged["backends"] = backends
    settings = settings_from_dict(merged)
    save_subagent_settings(settings)
    return settings.to_dict()


__all__ = ["router"]
