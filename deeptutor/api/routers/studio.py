"""Learning Studio API: media jobs and the asset library.

Two audiences, and the split is the security model:

``router`` — mounted at ``/api/studio`` with the ``learning`` policy.
    What a student does: ask for an artefact, watch the job, list their library,
    download what they own, delete it.

``admin_router`` — mounted at ``/api/studio/admin`` with the ``admin`` policy.
    Queue depth, cost reconciliation and the operator's view of what the media
    pipeline is costing. Separated because an operator needs to see spend across
    users, and a student must never be able to.

Identity comes from the session
-------------------------------
Every endpoint resolves the caller through ``caller_id``. A ``user_id`` query
parameter survives only for the single-operator dev configuration; with
authentication on it is discarded. This is the rule Phase 6 learned the hard
way and Phase 7 applied from the start.

Why submitting is not a 200
---------------------------
It returns 202: the request is *accepted*, not completed. The artefact does not
exist yet and may never exist. Returning 200 with a null asset would tell a
client the work is done when the only thing that has happened is that money has
been committed.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.db.jobs.queue import JobQueue, JobQueueUnavailable
from deeptutor.services import entitlements
from deeptutor.services.scope import ScopeError, as_http, caller_id
from deeptutor.services.studio import accounting, licences, pricing, tokens
from deeptutor.services.studio import jobs as studio

router = APIRouter()
admin_router = APIRouter()

#: Declared with Annotated so the bound lives in the signature's *type* rather
#: than in a ``Query(...)`` default. Calling an endpoint as a plain coroutine --
#: which the HTTP tests do -- then receives a real ``int``, not a ``Query``
#: object that only FastAPI knows how to resolve.
_Limit = Annotated[int, Query(ge=1, le=1000)]
_LimitSmall = Annotated[int, Query(ge=1, le=500)]
_UserParam = Annotated[str | None, Query()]



def _database() -> Any:
    from deeptutor.db.config import get_database_settings

    settings = get_database_settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=503, detail="database is not configured; set DEEPTUTOR_DATABASE_URL"
        )
    database = open_database(settings)
    if database is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="database is unavailable")
    return database


def _queue(database: Any) -> JobQueue:
    try:
        return JobQueue(database)
    except JobQueueUnavailable as exc:  # pragma: no cover - database exists here
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, accounting.QuotaExceeded):
        # 402, not 403 or 422: the request is well-formed and the caller is
        # allowed to make it. They cannot afford it. A client distinguishes
        # "top up" from "you may not do this" by the status, so conflating them
        # sends the user to the wrong screen.
        return HTTPException(
            status_code=402,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, studio.StudioError):
        not_found = {"asset_not_found", "job_not_found", "reservation_not_found"}
        if exc.rule in not_found:
            return HTTPException(
                status_code=404,
                detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
            )
        if exc.rule == "not_entitled":
            return HTTPException(
                status_code=403,
                detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
            )
        if exc.rule in {"reservation_closed"}:
            return HTTPException(
                status_code=409,
                detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
            )
        return HTTPException(
            status_code=422,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, ScopeError):
        return as_http(exc)
    if isinstance(exc, DatabaseError):
        return HTTPException(status_code=503, detail="database unavailable")
    raise exc


def _caller(user_id: str | None) -> str:
    resolved = caller_id(user_id)
    if not resolved:
        raise HTTPException(
            status_code=401,
            detail={"rule": "missing_user", "message": "a caller id is required"},
        )
    return resolved


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class ScriptPayload(BaseModel):
    """A request to draft the script *without* rendering anything.

    Free by construction: it takes no hold and calls no provider. A client uses
    it to show the student what the lesson will say before committing tokens to
    the render -- which is the cheapest possible place to catch a bad outline.
    """

    kind: str
    prompt: str = ""
    source_text: str = ""
    source_id: str | None = None
    chapter_title: str = ""
    licence_code: str = ""
    audience: str = ""
    instructions: str = ""


class SubmitPayload(BaseModel):
    kind: str = Field(..., description=f"one of {list(studio.MEDIA_KINDS)}")
    script: str = Field(..., min_length=1, max_length=40000)
    title: str = ""
    source_id: str | None = None
    chapter_title: str = ""
    licence_code: str = ""
    render: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scripts (free: no hold, no provider)
# ---------------------------------------------------------------------------


@router.get("/kinds")
async def list_kinds() -> dict:
    """What can be produced, what it costs to estimate, and in what order.

    The priority is exposed deliberately: a client showing a queue to a student
    should be able to explain why their video is behind five mind maps.
    """
    return {
        "kinds": [
            {
                "kind": kind,
                **studio.DEFAULT_ESTIMATES[kind].as_dict(),
                "priority": studio.KIND_PRIORITY.get(kind, 100),
            }
            for kind in studio.MEDIA_KINDS
        ]
    }


@router.get("/kinds/{kind}/checklist")
async def kind_checklist(kind: str) -> dict:
    """The human review checklist for a kind, as data."""
    from deeptutor.services.studio.script import quality_checklist

    if kind not in studio.MEDIA_KINDS:
        raise HTTPException(status_code=404, detail={"rule": "unknown_kind"})
    items = quality_checklist(kind)
    return {"kind": kind, "items": items, "count": len(items)}


@router.post("/script")
async def draft_script(payload: ScriptPayload, user_id: str | None = Query(None)) -> dict:
    """Draft the script that a render would use. Costs nothing.

    Separate from submission so a student can iterate on wording without paying
    for a render each time, and so the Persian can be reviewed before tokens
    are committed.
    """
    from deeptutor.services.studio.script import (
        ScriptRequest,
        build_script,
        estimate_duration,
    )

    _caller(user_id)
    try:
        script = build_script(
            ScriptRequest(
                kind=payload.kind,
                prompt=payload.prompt,
                source_text=payload.source_text,
                source_id=payload.source_id,
                chapter_title=payload.chapter_title,
                licence_code=payload.licence_code,
                audience=payload.audience,
                instructions=payload.instructions,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"rule": "invalid_script", "message": str(exc)}
        ) from exc

    return {
        **script.as_dict(),
        "estimated_duration_seconds": estimate_duration(payload.kind, script.text),
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.post("/jobs", status_code=202)
async def submit_job(payload: SubmitPayload, user_id: _UserParam = None) -> dict:
    """Ask for an artefact. Accepted, not completed.

    Admission runs in this order and each step can refuse: entitlement (403),
    then quota (402), then the reservation. Nothing is enqueued until the money
    is committed, so a queue can never be holding work nobody can pay for.
    """
    database = _database()
    try:
        owner = _caller(user_id)
        result = studio.submit(
            database,
            queue=_queue(database),
            # The gate is passed, not inherited. `submit` accepted this callable
            # since Phase 8 and no caller ever supplied it, so this line is the
            # difference between an entitlement check and a parameter.
            require_entitlement=entitlements.studio_gate(database),
            request=studio.JobRequest(
                user_id=owner,
                kind=payload.kind,
                script=payload.script,
                title=payload.title,
                source_id=payload.source_id,
                chapter_title=payload.chapter_title,
                licence_code=payload.licence_code,
                render=payload.render,
            ),
        )
        return result
    except (studio.StudioError, accounting.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user_id: _UserParam = None) -> dict:
    """One job's state, only for the caller who submitted it."""
    database = _database()
    try:
        owner = _caller(user_id)
        job = _queue(database).get(job_id)
        if job is None or str(job.payload.get("user_id") or "") != owner:
            raise studio.StudioError("job_not_found", f"no job {job_id!r}", field="job_id")
        return {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "last_error": job.last_error,
            "result": job.result,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "completed_at": job.completed_at,
        }
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user_id: _UserParam = None) -> dict:
    """Cancel a job and release its hold.

    A cancellation that leaves the hold open charges the user for work they
    stopped, which is why the refund follows the queue's answer rather than
    running before it.
    """
    database = _database()
    try:
        return studio.cancel(
            database, queue=_queue(database), job_id=job_id, user_id=_caller(user_id)
        )
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Asset library
# ---------------------------------------------------------------------------


@router.get("/assets")
async def list_assets(
    user_id: _UserParam = None,
    kind: str | None = None,
    limit: _LimitSmall = 100,
) -> dict:
    """The caller's library."""
    database = _database()
    try:
        assets = studio.list_assets(database, user_id=_caller(user_id), kind=kind, limit=limit)
        return {"assets": assets, "count": len(assets)}
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, user_id: _UserParam = None) -> dict:
    """One asset's metadata, only for its owner."""
    database = _database()
    try:
        return studio.get_asset(database, asset_id, user_id=_caller(user_id))
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, user_id: _UserParam = None) -> dict:
    database = _database()
    try:
        return {"deleted": studio.delete_asset(database, asset_id, user_id=_caller(user_id))}
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/assets/{asset_id}/content")
async def asset_content(asset_id: str, user_id: _UserParam = None):
    """Stream an asset's bytes, only to its owner.

    The ownership check is the *same* one :func:`get_asset` makes, called before
    a byte is read. Serving straight from the storage path by id -- which is
    what a "just fetch the file" handler does -- would make the id a capability
    and leave every asset in the system readable by anyone who ever saw one.

    Bytes are streamed rather than buffered: a video lesson can be large, and
    holding it in memory to hand it to one client is a self-inflicted outage.
    """
    from fastapi.responses import FileResponse

    database = _database()
    try:
        asset = studio.get_asset(database, asset_id, user_id=_caller(user_id))
        from deeptutor.db.storage import get_object_store

        store = get_object_store()
        path = store.open_path(str(asset["storage_path"]))
        return FileResponse(
            path,
            media_type=str(asset["mime_type"]),
            filename=f"{asset['kind']}-{asset['id']}{path.suffix}",
        )
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Sharing: the "or someone authorized" half
# ---------------------------------------------------------------------------


class GrantPayload(BaseModel):
    grantee_id: str
    expires_at: str | None = None


@router.post("/assets/{asset_id}/grants")
async def create_grant(
    asset_id: str, payload: GrantPayload, user_id: str | None = Query(None)
) -> dict:
    """Share one asset with one person. Owner only."""
    database = _database()
    try:
        return studio.grant_access(
            database,
            asset_id=asset_id,
            owner_id=_caller(user_id),
            grantee_id=payload.grantee_id,
            expires_at=payload.expires_at,
        )
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.delete("/assets/{asset_id}/grants/{grantee_id}")
async def delete_grant(
    asset_id: str, grantee_id: str, user_id: str | None = Query(None)
) -> dict:
    """Revoke a share. A timestamp, not a delete, so history survives."""
    database = _database()
    try:
        return {
            "revoked": studio.revoke_access(
                database, asset_id=asset_id, owner_id=_caller(user_id), grantee_id=grantee_id
            )
        }
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/assets/{asset_id}/grants")
async def list_grants(asset_id: str, user_id: str | None = Query(None)) -> dict:
    database = _database()
    try:
        rows = studio.list_grants(database, asset_id=asset_id, owner_id=_caller(user_id))
        return {"grants": rows, "count": len(rows)}
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/shared")
async def shared_with_me(user_id: str | None = Query(None), limit: int = 100) -> dict:
    """Assets other people shared with the caller, still live.

    Separate from ``/assets`` on purpose: the library is what you made, this is
    what was given to you. Merging them would make "delete" ambiguous.
    """
    database = _database()
    try:
        rows = studio.list_shared_with_me(database, user_id=_caller(user_id), limit=int(limit))
        return {"assets": rows, "count": len(rows)}
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Quality review: recording the human verdict
# ---------------------------------------------------------------------------


class ReviewPayload(BaseModel):
    item_id: str
    verdict: str
    comment: str = ""
    reviewer_id: str | None = None


@router.post("/assets/{asset_id}/reviews")
async def create_review(
    asset_id: str, payload: ReviewPayload, user_id: str | None = Query(None)
) -> dict:
    """Record one checklist verdict.

    ``reviewer_id`` lets someone other than the owner answer -- which is the
    whole point, since a self-review is not independent evidence. The owner
    still has to be the caller: a review is attached to an asset by whoever is
    responsible for it.
    """
    database = _database()
    try:
        return studio.record_review(
            database,
            asset_id=asset_id,
            user_id=_caller(user_id),
            item_id=payload.item_id,
            verdict=payload.verdict,
            comment=payload.comment,
            reviewer_id=payload.reviewer_id,
        )
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/assets/{asset_id}/reviews")
async def get_reviews(asset_id: str, user_id: str | None = Query(None)) -> dict:
    """The review state, including whether any of it is independent."""
    database = _database()
    try:
        return studio.review_status(database, asset_id, user_id=_caller(user_id))
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/quota")
async def quota(user_id: _UserParam = None) -> dict:
    """What the caller can still afford, net of open holds."""
    database = _database()
    try:
        owner = _caller(user_id)
        with database.read() as conn:
            wallet = conn.query_one(
                "SELECT tokens_remaining, storage_used_bytes, storage_quota_bytes "
                "FROM user_wallets WHERE user_id = ?",
                (owner,),
            )
        return {
            "tokens_remaining": int((wallet or {}).get("tokens_remaining") or 0),
            "tokens_held": accounting.open_holds(database, owner),
            "tokens_available": accounting.available_tokens(database, owner),
            "storage_used_bytes": int((wallet or {}).get("storage_used_bytes") or 0),
            "storage_quota_bytes": int((wallet or {}).get("storage_quota_bytes") or 0),
        }
    except (studio.StudioError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/licences")
async def licence_catalogue() -> dict:
    """What each licence code permits, and what each kind requires.

    Public because a client has to know *before* submitting whether a source is
    usable: failing at submit with ``licence_insufficient`` is the enforcement
    point, but a catalogue that explains it turns a rejection into a fix. The
    requirement table is included so a UI can grey out kinds that a given code
    cannot produce, instead of offering them and then refusing.
    """
    return {
        "licences": licences.describe_all(),
        "requirements": {
            kind: sorted(licences.requirements_for(kind))
            for kind in studio.MEDIA_KINDS
        },
    }


@router.get("/pricing")
async def price_list(model: str = Query("nvidia/nemotron-3.5-super-vl")) -> dict:
    """Every endpoint's published price for a model, and the daily ceiling.

    Prices come from the provider's public catalogue and carry the date they
    were read. The ceiling is part of the answer, not a footnote: a free
    endpoint costs nothing per lesson and serves fifty lessons a day, and a
    client that only heard the first half would plan against a limit that is
    not money.
    """
    try:
        options = pricing.endpoints_for(model)
        entry = pricing.CATALOGUE[model]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "model": model,
        "read_at": entry["read_at"],
        "source": entry["source"],
        "context_length": entry["context_length"],
        "endpoints": [
            {
                "endpoint": option.endpoint,
                "prompt_usd_per_token": option.prompt_usd_per_token,
                "completion_usd_per_token": option.completion_usd_per_token,
                "uptime_1d": option.uptime_1d,
                "free": option.prompt_usd_per_token == 0,
            }
            for option in options
        ],
        "daily_ceiling": _ceiling(model),
    }


def _ceiling(model: str) -> dict:
    try:
        if all(p.prompt_usd_per_token == 0 for p in pricing.endpoints_for(model)):
            return pricing.daily_ceiling(model)
        cheapest = pricing.cheapest_paid(model)
        return {
            "free": False,
            "binding_constraint": "budget",
            "lessons_per_day": None,
            "note": (
                "a paid model is capped by budget, not by requests; pass a "
                "daily budget to pricing.daily_ceiling to get a lesson count. "
                f"cheapest endpoint is {cheapest.endpoint}"
            ),
        }
    except (KeyError, ValueError) as exc:  # pragma: no cover - defensive
        return {"error": str(exc)}


@router.get("/cost/method")
async def cost_method() -> dict:
    """How the token figures in the cost ledger are obtained.

    Exposed rather than buried because the number has an error bar. If the real
    tokenizer is usable the uncertainty is zero; otherwise the estimator reports
    the error it was calibrated to, measured against ``cl100k_base``.
    """
    counter = tokens.counter()
    return {
        "tokenizer": "cl100k_base" if counter is not None else "studio:offline-v1",
        "exact": counter is not None,
        "uncertainty": 0.0 if counter is not None else tokens.CALIBRATION.get(
            "per_sentence_error_mean", 0.0
        ),
        "calibration": {
            key: value
            for key, value in tokens.CALIBRATION.items()
            if key != "known_limits"
        },
        "known_limits": tokens.CALIBRATION.get("known_limits", ""),
    }


# ---------------------------------------------------------------------------
# Operator surface
# ---------------------------------------------------------------------------


@admin_router.get("/queue")
async def queue_health() -> dict:
    """Queue depth by state, plus what the media kinds are costing."""
    database = _database()
    try:
        queue = _queue(database)
        with database.read() as conn:
            by_kind = list(
                conn.query(
                    "SELECT kind, status, COUNT(*) AS count FROM jobs "
                    "WHERE kind LIKE 'media.%' GROUP BY kind, status ORDER BY kind, status"
                )
            )
            spend = list(
                conn.query(
                    "SELECT phase, COUNT(*) AS rows, COALESCE(SUM(tokens), 0) AS tokens, "
                    "COALESCE(SUM(non_token_cost_toman), 0) AS toman "
                    "FROM media_job_costs GROUP BY phase"
                )
            )
            holds = conn.scalar(
                "SELECT COALESCE(SUM(reserved_tokens), 0) FROM media_reservations "
                "WHERE state = 'open'"
            )
        return {
            "depth": queue.stats(),
            "by_kind": [dict(row) for row in by_kind],
            "cost": [dict(row) for row in spend],
            "open_holds_tokens": int(holds or 0),
        }
    finally:
        database.close()


@admin_router.get("/costs")
async def cost_rows(limit: _Limit = 200) -> dict:
    """Recent estimate/actual pairs, for the cost reconciliation Gate 8 asks for."""
    database = _database()
    try:
        with database.read() as conn:
            rows = list(
                conn.query(
                    "SELECT job_id, phase, tokens, non_token_units, non_token_unit, "
                    "non_token_cost_toman, provider, created_at FROM media_job_costs "
                    "ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                )
            )
        return {"costs": [dict(row) for row in rows], "count": len(rows)}
    finally:
        database.close()


@admin_router.get("/assets")
async def admin_assets(limit: _Limit = 200) -> dict:
    """Every asset, across users, for storage accounting.

    Metadata only. An operator needs to know how many bytes exist and for whom;
    they do not need the lessons themselves, and giving them the bytes would
    turn an accounting view into a surveillance one.
    """
    database = _database()
    try:
        with database.read() as conn:
            rows = list(
                conn.query(
                    "SELECT id, user_id, kind, size_bytes, duration_seconds, status, created_at "
                    "FROM media_assets ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                )
            )
            total = conn.scalar("SELECT COALESCE(SUM(size_bytes), 0) FROM media_assets "
                                "WHERE status = 'ready'")
        return {"assets": [dict(row) for row in rows], "count": len(rows), "total_bytes": int(total or 0)}
    finally:
        database.close()
