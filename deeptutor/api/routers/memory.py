"""Memory v3 API — workbench backend.

Three layers, three modes (update / audit / dedup). Long-running work
is owned by the :mod:`runs` manager so a refresh / nav-away does not
kill it; clients re-attach by polling ``/runs/{id}/events?since=N``.

- ``GET  /overview``                              → all 11 docs' state + L1 backlog
- ``GET  /doc/{layer}/{key}``                     → raw MD
- ``GET  /doc/{layer}/{key}/lines``               → line-numbered view
- ``PUT  /doc/{layer}/{key}``                     → user-edited save
- ``DELETE /doc/{layer}/{key}/entry/{id}``        → drop one entry
- ``POST /runs/start``                            → start update/audit/dedup; returns run_id
- ``GET  /runs/{id}``                             → run state
- ``GET  /runs/{id}/events?since=N``              → SSE-replay events from cursor N
- ``POST /runs/{id}/cancel``                      → cooperative cancellation
- ``POST /runs/{id}/undo``                        → restore latest run write
- ``GET  /runs?layer=L2&key=chat``                → active+recent runs for one doc
- ``GET  /settings``                              → memory: settings subtree
- ``PUT  /settings``                              → save memory: settings subtree
- ``GET  /trace/{surface}``                       → paginated L1 events
- ``DELETE /trace/{surface}/day/{date}``          → drop one day of trace
- ``DELETE /trace/{surface}``                     → drop all trace for a surface
- ``GET  /backup``                                → list v1-migration backup dirs (if any)

The legacy per-mode endpoints (``POST /doc/{layer}/{key}/update`` etc.)
are kept for the moment as thin wrappers that start a run and stream
its events — older clients keep working.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date as date_cls
import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deeptutor.services.memory import (
    L3_SLOTS,
    SURFACES,
    Surface,
    get_memory_store,
    paths,
)

_ENTRY_ID_RE = re.compile(r"^m_[0-9A-HJKMNP-TV-Z]{26}$")

logger = logging.getLogger(__name__)
router = APIRouter()

Layer = Literal["L2", "L3"]


# ── Helpers ──────────────────────────────────────────────────────────────


def _validate_doc_key(layer: Layer, key: str) -> None:
    if layer == "L2" and key not in SURFACES:
        raise HTTPException(status_code=404, detail=f"unknown surface {key!r}")
    if layer == "L3" and key not in L3_SLOTS:
        raise HTTPException(status_code=404, detail=f"unknown L3 slot {key!r}")


def _validate_layer(layer: str) -> Layer:
    if layer not in {"L2", "L3"}:
        raise HTTPException(status_code=400, detail="layer must be L2 or L3")
    return layer  # type: ignore[return-value]


def _validate_surface(surface: str) -> Surface:
    if surface not in SURFACES:
        raise HTTPException(status_code=404, detail=f"unknown surface {surface!r}")
    return surface  # type: ignore[return-value]


# ── Overview / list ──────────────────────────────────────────────────────


@router.get("/overview")
async def get_overview():
    store = get_memory_store()
    rows = [asdict(r) for r in store.overview()]
    backup_dir = paths.backup_root()
    backups: list[str] = []
    if backup_dir.exists():
        backups = sorted(p.name for p in backup_dir.iterdir() if p.is_dir())
    return {"docs": rows, "backups": backups}


@router.get("/resolve_entry/{entry_id}")
async def resolve_entry(entry_id: str):
    """Find which L2 doc owns this entry id.

    L3 docs cite L2 entries by their ``m_<ULID>`` entry id; the workbench
    UI uses this resolver to turn an L3 footnote click into a navigation
    to the right L2 surface + scroll-to anchor.

    Scans the seven L2 mds in order; first hit wins. 404 if no L2 doc
    contains the id (e.g. the entry was deleted or the id is stale).
    """
    if not _ENTRY_ID_RE.match(entry_id):
        raise HTTPException(status_code=400, detail="not a valid entry id")
    from deeptutor.services.memory.document import parse

    for surface in SURFACES:
        path = paths.l2_file(surface)
        if not path.exists():
            continue
        try:
            doc = parse(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — malformed L2 should not 500 the resolver
            continue
        for entry in doc.all_entries():
            if entry.id == entry_id:
                return {"layer": "L2", "key": surface, "entry_id": entry_id}
    raise HTTPException(status_code=404, detail="entry not found in any L2 doc")


@router.get("/backup")
async def list_backups():
    backup_dir = paths.backup_root()
    if not backup_dir.exists():
        return {"backups": []}
    out: list[dict] = []
    for entry in sorted(backup_dir.iterdir()):
        if entry.is_dir():
            files = sorted(p.name for p in entry.iterdir())
            out.append({"name": entry.name, "files": files})
    return {"backups": out}


# ── Doc read / write / delete ────────────────────────────────────────────


@router.get("/doc/{layer}/{key}")
async def get_doc(layer: str, key: str):
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    return {"layer": lyr, "key": key, "content": get_memory_store().read_raw(lyr, key)}


class DocWriteRequest(BaseModel):
    content: str


@router.put("/doc/{layer}/{key}")
async def put_doc(layer: str, key: str, payload: DocWriteRequest):
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    await get_memory_store().overwrite_doc(lyr, key, payload.content)
    return {"layer": lyr, "key": key, "saved": True}


@router.delete("/doc/{layer}/{key}/entry/{entry_id}")
async def delete_entry(layer: str, key: str, entry_id: str):
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    ok = await get_memory_store().delete_entry(lyr, key, entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"layer": lyr, "key": key, "deleted": entry_id}


@router.post("/doc/{layer}/{key}/reset")
async def reset_doc(layer: str, key: str):
    """Wipe the doc + its meta sidecar so the next update starts fresh.

    Destructive — the caller has confirmed. After this returns the .md
    file is gone *and* the ``seen_entity_refs`` set is cleared, so a
    subsequent ``run_update`` re-ingests every L1 entity instead of
    treating them as already-seen.

    Refuses while a consolidator run is active on this doc; the caller
    can cancel first.
    """
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)

    from deeptutor.services.memory.consolidator.runs import get_run_manager

    if get_run_manager().active_for(lyr, key) is not None:
        raise HTTPException(
            status_code=409,
            detail="cancel the active run before resetting this doc",
        )

    from deeptutor.services.memory.consolidator import meta as meta_mod

    doc_path = paths.l2_file(key) if lyr == "L2" else paths.l3_file(key)  # type: ignore[arg-type]
    meta_path = (
        meta_mod.l2_meta_path(key)  # type: ignore[arg-type]
        if lyr == "L2"
        else meta_mod.l3_meta_path(key)  # type: ignore[arg-type]
    )

    removed_doc = False
    removed_meta = False
    try:
        if doc_path.exists():
            doc_path.unlink()
            removed_doc = True
        if meta_path.exists():
            meta_path.unlink()
            removed_meta = True
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"reset failed: {exc}") from exc

    return {
        "layer": lyr,
        "key": key,
        "reset": True,
        "removed_doc": removed_doc,
        "removed_meta": removed_meta,
    }


# ── Doc update (SSE-streamed consolidator) ───────────────────────────────


class LLMSelectionPayload(BaseModel):
    profile_id: str
    model_id: str


class RunStartRequest(BaseModel):
    layer: str
    key: str
    mode: Literal["update", "audit", "dedup", "merge"]
    language: str = "en"
    budget: int | None = None
    iterations: int | None = None
    llm_selection: LLMSelectionPayload | None = None


def _runner_for(req: RunStartRequest):
    """Return an ``async on_event → None`` runner for the requested mode."""
    from deeptutor.services.memory.consolidator import (
        run_audit,
        run_dedup,
        run_merge,
        run_update,
    )

    selection = (
        {"profile_id": req.llm_selection.profile_id, "model_id": req.llm_selection.model_id}
        if req.llm_selection
        else None
    )

    if req.mode == "update":

        async def go(on_event):
            await run_update(
                req.layer,
                req.key,
                language=req.language,
                budget=req.budget,
                llm_selection=selection,
                on_event=on_event,
            )

        return go
    if req.mode == "audit":

        async def go(on_event):
            await run_audit(
                req.layer,
                req.key,
                language=req.language,
                budget=req.budget,
                llm_selection=selection,
                on_event=on_event,
            )

        return go
    if req.mode == "dedup":

        async def go(on_event):
            await run_dedup(
                req.layer,
                req.key,
                language=req.language,
                iterations=req.iterations,
                llm_selection=selection,
                on_event=on_event,
            )

        return go
    if req.mode == "merge":

        async def go(on_event):
            await run_merge(
                req.layer,
                req.key,
                language=req.language,
                on_event=on_event,
            )

        return go
    raise HTTPException(status_code=400, detail=f"unknown mode {req.mode!r}")


@router.post("/runs/start")
async def start_run(req: RunStartRequest):
    """Start one consolidator mode and return a run handle.

    The run survives client disconnects; reconnect via
    ``GET /runs/{id}/events?since=N``.
    """
    lyr = _validate_layer(req.layer)
    _validate_doc_key(lyr, req.key)
    if lyr == "L3" and req.key == "preferences" and req.mode not in ("dedup", "merge"):
        raise HTTPException(
            status_code=405,
            detail="preferences is written by the write_memory tool, not consolidated",
        )
    from deeptutor.services.memory.consolidator.runs import (
        RunBusyError,
        get_run_manager,
    )

    manager = get_run_manager()
    runner = _runner_for(req)
    selection = (
        {"profile_id": req.llm_selection.profile_id, "model_id": req.llm_selection.model_id}
        if req.llm_selection
        else None
    )
    try:
        run = await manager.start(
            layer=lyr,
            key=req.key,
            mode=req.mode,
            runner=runner,
            params={
                "budget": req.budget,
                "iterations": req.iterations,
                "language": req.language,
                "llm_selection": selection,
            },
            language=req.language,
        )
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return run.to_dict()


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    from deeptutor.services.memory.consolidator.runs import get_run_manager

    run = get_run_manager().get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return run.to_dict()


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    from deeptutor.services.memory.consolidator.runs import get_run_manager

    ok = await get_run_manager().cancel(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="not active")
    return {"run_id": run_id, "cancelled": True}


@router.post("/runs/{run_id}/undo")
async def undo_run_edit(run_id: str):
    from deeptutor.services.memory.consolidator.runs import (
        RunBusyError,
        get_run_manager,
    )

    manager = get_run_manager()
    try:
        event = await manager.undo_last(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown run_id")
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if event is None:
        raise HTTPException(status_code=409, detail="nothing to undo")
    run = manager.get(run_id)
    return {
        "run_id": run_id,
        "undone": True,
        "undo_count": len(run.undo_stack) if run else 0,
        "event": {"seq": event.seq, "ts": event.ts, **event.payload},
    }


@router.get("/runs")
async def list_runs(layer: str | None = None, key: str | None = None):
    from deeptutor.services.memory.consolidator.runs import get_run_manager

    lyr = _validate_layer(layer) if layer is not None else None
    if lyr and key is not None:
        _validate_doc_key(lyr, key)
    runs = get_run_manager().list_for(layer=lyr, key=key)
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, since: int = 0):
    """SSE-replay events from ``since`` (exclusive) until the run ends.

    Reconnecting after a refresh: pass the largest ``seq`` previously
    observed. The manager replays the buffered tail, then blocks on
    new events until the run reaches a terminal state.
    """
    from deeptutor.services.memory.consolidator.runs import get_run_manager

    manager = get_run_manager()
    run = manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run_id")

    async def producer():
        cursor = max(0, since)
        # Initial backfill (if any) is delivered as a batch up front.
        while True:
            events = await manager.wait_for_events(run, since=cursor)
            for ev in events:
                yield (
                    "data: "
                    + json.dumps(
                        {"seq": ev.seq, "ts": ev.ts, **ev.payload},
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            cursor = max(cursor, run.events[-1].seq + 1 if run.events else cursor)
            if not run.active:
                # Drain any final events that arrived between wait return and now.
                final = run.events[cursor:]
                for ev in final:
                    yield (
                        "data: "
                        + json.dumps(
                            {"seq": ev.seq, "ts": ev.ts, **ev.payload},
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                break

    return StreamingResponse(producer(), media_type="text/event-stream")


# ── Legacy per-mode endpoints (kept as thin wrappers over /runs/start) ──


def _legacy_run_stream(req: RunStartRequest) -> StreamingResponse:
    """Old contract: POST /doc/{layer}/{key}/<mode> streams events inline."""
    from deeptutor.services.memory.consolidator.runs import (
        RunBusyError,
        get_run_manager,
    )

    async def producer():
        manager = get_run_manager()
        runner = _runner_for(req)
        selection = (
            {"profile_id": req.llm_selection.profile_id, "model_id": req.llm_selection.model_id}
            if req.llm_selection
            else None
        )
        try:
            run = await manager.start(
                layer=req.layer,
                key=req.key,
                mode=req.mode,
                runner=runner,
                params={
                    "budget": req.budget,
                    "iterations": req.iterations,
                    "language": req.language,
                    "llm_selection": selection,
                },
                language=req.language,
            )
        except RunBusyError as exc:
            yield (
                "data: "
                + json.dumps({"stage": "error", "message": str(exc)}, ensure_ascii=False)
                + "\n\n"
            )
            return
        cursor = 0
        while True:
            events = await manager.wait_for_events(run, since=cursor)
            for ev in events:
                yield (
                    "data: "
                    + json.dumps({**ev.payload, "seq": ev.seq}, ensure_ascii=False)
                    + "\n\n"
                )
                cursor = ev.seq + 1
            if not run.active:
                break

    return StreamingResponse(producer(), media_type="text/event-stream")


class UpdateRequest(BaseModel):
    language: str = "en"
    budget: int | None = None
    llm_selection: LLMSelectionPayload | None = None


class AuditRequest(BaseModel):
    language: str = "en"
    budget: int | None = None
    llm_selection: LLMSelectionPayload | None = None


class DedupRequest(BaseModel):
    language: str = "en"
    iterations: int | None = None
    llm_selection: LLMSelectionPayload | None = None


@router.post("/doc/{layer}/{key}/update")
async def update_doc(layer: str, key: str, payload: UpdateRequest | None = None):
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    req = RunStartRequest(
        layer=lyr,
        key=key,
        mode="update",
        language=(payload.language if payload else "en") or "en",
        budget=payload.budget if payload else None,
        llm_selection=payload.llm_selection if payload else None,
    )
    return _legacy_run_stream(req)


@router.post("/doc/{layer}/{key}/audit")
async def audit_doc(layer: str, key: str, payload: AuditRequest | None = None):
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    req = RunStartRequest(
        layer=lyr,
        key=key,
        mode="audit",
        language=(payload.language if payload else "en") or "en",
        budget=payload.budget if payload else None,
        llm_selection=payload.llm_selection if payload else None,
    )
    return _legacy_run_stream(req)


@router.post("/doc/{layer}/{key}/dedup")
async def dedup_doc(layer: str, key: str, payload: DedupRequest | None = None):
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    req = RunStartRequest(
        layer=lyr,
        key=key,
        mode="dedup",
        language=(payload.language if payload else "en") or "en",
        iterations=payload.iterations if payload else None,
        llm_selection=payload.llm_selection if payload else None,
    )
    return _legacy_run_stream(req)


@router.get("/doc/{layer}/{key}/lines")
async def get_doc_lines(layer: str, key: str):
    """Return the line-numbered, footnote-stripped view of a doc.

    Used by the workbench's "show line numbers" toggle so the same line
    indices the audit/dedup LLMs see are visible to the user. Footnote
    block is omitted because edit ops never reference it directly.
    """
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    from deeptutor.services.memory import paths
    from deeptutor.services.memory.consolidator.line_doc import render_view
    from deeptutor.services.memory.document import Document, parse

    path = paths.l2_file(key) if lyr == "L2" else paths.l3_file(key)  # type: ignore[arg-type]
    doc = (
        parse(path.read_text(encoding="utf-8"))
        if path.exists()
        else Document(title=_default_title(lyr, key))
    )
    view = render_view(doc)
    return {
        "layer": lyr,
        "key": key,
        "lines": [
            {
                "number": line.number,
                "kind": line.kind,
                "text": line.text,
                "entry_id": line.entry_id,
                "section": line.section,
            }
            for line in view.lines
        ],
    }


# ── Settings ────────────────────────────────────────────────────────────


@router.get("/settings")
async def get_memory_settings_endpoint():
    """Return the current ``memory:`` subtree (defaults merged in)."""
    from deeptutor.services.memory.settings import memory_settings_dict

    return memory_settings_dict()


@router.put("/settings")
async def put_memory_settings(payload: dict):
    """Merge the payload into the ``memory:`` subtree and persist."""
    from deeptutor.services.memory.settings import (
        memory_settings_dict,
        save_memory_settings,
    )

    save_memory_settings(payload)
    return memory_settings_dict()


def _default_title(layer: str, key: str) -> str:
    if layer == "L2":
        return f"{key} memory"
    return {
        "recent": "Recent summary",
        "profile": "User profile",
        "scope": "Knowledge scope",
        "preferences": "Preferences",
    }.get(key, f"{key} memory")


class ApplyOpsRequest(BaseModel):
    ops: list[dict]


@router.post("/doc/{layer}/{key}/apply")
async def apply_doc_ops(layer: str, key: str, payload: ApplyOpsRequest):
    """Commit a list of previously-previewed ops to a doc atomically."""
    lyr = _validate_layer(layer)
    _validate_doc_key(lyr, key)
    if lyr == "L3" and key == "preferences":
        raise HTTPException(
            status_code=405,
            detail="preferences is written by the write_memory tool, not consolidated",
        )
    if not payload.ops:
        return {"accepted": True, "reason": "no ops to apply", "results": []}

    report = await get_memory_store().apply_ops_payload(lyr, key, payload.ops)
    return {
        "accepted": report.accepted,
        "reason": report.reason,
        "results": [
            {
                "status": r.status,
                "entry_id": r.entry_id,
                "detail": r.detail,
            }
            for r in report.results
        ],
    }


# ── Trace browser ────────────────────────────────────────────────────────


@router.get("/trace/{surface}")
async def get_trace(surface: str, limit: int = 200, offset: int = 0):
    surf = _validate_surface(surface)
    from deeptutor.services.memory.trace import iter_since

    events = []
    for i, event in enumerate(iter_since(surf)):
        if i < offset:
            continue
        if len(events) >= max(1, min(limit, 1000)):
            break
        events.append(asdict(event))
    return {"surface": surf, "events": events, "offset": offset, "limit": limit}


@router.delete("/trace/{surface}")
async def clear_trace(surface: str):
    surf = _validate_surface(surface)
    removed = 0
    for path in paths.trace_dir(surf).glob("*.jsonl"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return {"surface": surf, "removed_files": removed}


@router.delete("/trace/{surface}/day/{day}")
async def clear_trace_day(surface: str, day: str):
    surf = _validate_surface(surface)
    try:
        parsed = date_cls.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
    path = paths.trace_file(surf, parsed)
    if not path.exists():
        raise HTTPException(status_code=404, detail="no trace for that day")
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"surface": surf, "day": day, "deleted": True}


# ── Snapshot (L1 workspace mirror) ───────────────────────────────────────


@router.get("/snapshot/{surface}")
async def get_snapshot(surface: str):
    """Return the current entity list for ``surface`` from workspace.

    Snapshot is always derived live from workspace at call time. The response
    also includes ``pending_changes`` — the diff vs the last persisted state.
    Refresh commits these pending changes into ``changes.jsonl``.
    """
    surf = _validate_surface(surface)
    from deeptutor.services.memory import snapshot as snap

    entities = snap.read_snapshot(surf)
    pending = snap.pending_changes(surf, entities)
    state = snap.current_state(surf)
    return {
        "surface": surf,
        "entities": [e.to_dict() for e in entities],
        "last_refresh": state.get("last_refresh"),
        "pending_changes": [c.to_dict() for c in pending],
    }


@router.post("/snapshot/{surface}/refresh")
async def refresh_snapshot(surface: str):
    """Reconcile persisted state with current workspace; record diffs."""
    surf = _validate_surface(surface)
    from deeptutor.services.memory import snapshot as snap

    changes = snap.refresh_snapshot(surf)
    state = snap.current_state(surf)
    return {
        "surface": surf,
        "changes": [c.to_dict() for c in changes],
        "last_refresh": state.get("last_refresh"),
    }


@router.get("/snapshot/{surface}/changes")
async def get_changes(surface: str, limit: int = 200, offset: int = 0):
    surf = _validate_surface(surface)
    from deeptutor.services.memory import snapshot as snap

    entries = snap.read_changes(surf, limit=limit, offset=offset)
    return {
        "surface": surf,
        "changes": [c.to_dict() for c in entries],
        "limit": limit,
        "offset": offset,
    }


@router.delete("/snapshot/{surface}/changes")
async def clear_snapshot_changes(surface: str):
    surf = _validate_surface(surface)
    from deeptutor.services.memory import snapshot as snap

    snap.clear_changes(surf)
    return {"surface": surf, "cleared": True}
