"""Submitting, cancelling and running media jobs.

The lifecycle this module owns
------------------------------
::

    submit ──► admitted? ──no──► 402 quota
                 │yes
                 ▼
              reserve ──► enqueue ──► [worker claims]
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
                    reuse cache        render ok          failed
                       │                  │                  │
                  settle(0)          settle(actual)      refund
                                          │                  │
                       └──────────────► asset ◄─────────────┘

Three properties matter, and each is a place a naive implementation loses money
or trust:

1. **Nothing is enqueued before the hold exists.** A job in the queue is a
   promise to do work; the hold is what backs the promise. Enqueueing first and
   reserving later leaves a window where the queue can run unpaid work.
2. **Every terminal path closes the hold exactly once.** Success settles,
   failure refunds, cancellation refunds. A job that reaches a terminal state
   with an open hold is a leak that only shows up as a slowly shrinking
   balance.
3. **Cancellation is honoured mid-flight.** The queue cannot preempt a running
   handler, so the handler checks for cancellation between steps and the
   settle step re-reads the state: a job cancelled during a paid provider call
   is refunded, not charged.

Cache reuse is checked *before* the provider is called, and it settles at zero.
The point of the cache is to make a repeated request free, so charging the
estimate for a cache hit would defeat it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Mapping

from deeptutor.db.connection import Database
from deeptutor.db.jobs.queue import ClaimedJob, JobQueue
from deeptutor.services.studio import accounting
from deeptutor.services.studio.accounting import QuotaExceeded, StudioError

#: The artefact kinds this studio can produce. Adding one means adding a handler
#: and (usually) a provider; it should not mean touching the accounting.
MEDIA_KINDS = (
    "audio_overview",
    "video_lesson",
    "slide_deck",
    "mind_map",
    "infographic",
)

#: Job kinds are namespaced so the shared queue can host them beside chat jobs
#: without either side guessing at the other's names.
JOB_PREFIX = "media."


def job_kind(kind: str) -> str:
    return f"{JOB_PREFIX}{kind}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Cache identity
# ---------------------------------------------------------------------------


def cache_key(
    *,
    kind: str,
    script: str,
    source_id: str | None,
    licence_code: str,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """The identity of a rendered artefact.

    Includes the licence deliberately. An asset rendered under a licence that
    has since lapsed is *not* interchangeable with one rendered under a current
    licence, even if the script is identical: the reuse would carry the old
    terms forward invisibly. Treating licence as part of the key means a
    licence change produces a miss, which is the safe direction.

    ``extra`` is for render settings that change the output (voice, resolution).
    A different voice is a different asset, not a cache hit.
    """
    payload = json.dumps(
        {
            "kind": kind,
            "script": script,
            "source_id": source_id or "",
            "licence": licence_code,
            "extra": dict(extra or {}),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def find_cached(
    db: Database, *, user_id: str, content_hash: str
) -> dict[str, Any] | None:
    """An existing ready asset with this identity, for this owner.

    Scoped by owner: two students entitled to the same lesson each get their own
    copy, because storage is billed per user and a shared asset behind one
    owner's quota is a billing dispute waiting to happen.
    """
    with db.read() as conn:
        row = conn.query_one(
            "SELECT * FROM media_assets WHERE user_id = ? AND content_hash = ? "
            "AND status = 'ready' ORDER BY created_at DESC LIMIT 1",
            (user_id, content_hash),
        )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostEstimate:
    """What a job is expected to cost, before it runs.

    ``tokens`` is the figure held against the balance. ``non_token_cost_toman``
    is recorded but not held: a provider that bills per second of video cannot
    be reserved against a token balance without inventing an exchange rate at
    submit time, and an invented rate is worse than a recorded actual.
    """

    tokens: int
    non_token_units: float = 0.0
    non_token_unit: str = ""
    non_token_cost_toman: int = 0
    provider: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "non_token_units": self.non_token_units,
            "non_token_unit": self.non_token_unit,
            "non_token_cost_toman": self.non_token_cost_toman,
            "provider": self.provider,
        }


#: Per-kind default estimates in tokens. These are deliberately crude and
#: deliberately visible: Gate 8 asks for cost to be *documented*, and a table of
#: numbers someone can argue with is more honest than a formula nobody reads.
#: Every value here is replaced by the `actual` row once the job settles, and
#: comparing the two is how the table gets corrected.
DEFAULT_ESTIMATES: dict[str, CostEstimate] = {
    "audio_overview": CostEstimate(tokens=800, provider="tts"),
    "video_lesson": CostEstimate(tokens=2500, provider="videogen"),
    "slide_deck": CostEstimate(tokens=1200, provider="llm"),
    "mind_map": CostEstimate(tokens=600, provider="llm"),
    "infographic": CostEstimate(tokens=1500, provider="imagegen"),
}

#: Queue priority per kind, lower runs first. The order encodes what the product
#: believes: a mind map is cheap and near-instant, a video lesson is expensive
#: and slow, so a burst of video requests must not delay every mind map queued
#: behind them. Distinct priorities rather than one default is the whole point
#: of "separate priorities" in the phase scope.
KIND_PRIORITY: dict[str, int] = {
    "mind_map": 40,
    "infographic": 50,
    "slide_deck": 60,
    "audio_overview": 70,
    "video_lesson": 80,
}

#: Ceiling on retries for media jobs. Lower than the queue default (5) because
#: each attempt can cost a real provider call: five paid failures is a billing
#: incident, not resilience.
MEDIA_MAX_ATTEMPTS = 2


def estimate_for(kind: str, *, tokens: int | None = None) -> CostEstimate:
    if kind not in MEDIA_KINDS:
        raise StudioError(
            "unknown_kind", f"kind must be one of {list(MEDIA_KINDS)}", field="kind"
        )
    if tokens is not None:
        if tokens < 0:
            raise StudioError("invalid_estimate", "an estimate cannot be negative")
        base = DEFAULT_ESTIMATES[kind]
        return CostEstimate(
            tokens=tokens,
            non_token_units=base.non_token_units,
            non_token_unit=base.non_token_unit,
            non_token_cost_toman=base.non_token_cost_toman,
            provider=base.provider,
        )
    return DEFAULT_ESTIMATES[kind]


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobRequest:
    """One request to produce an artefact."""

    user_id: str
    kind: str
    script: str
    title: str = ""
    source_id: str | None = None
    chapter_title: str = ""
    licence_code: str = ""
    #: Render settings that change the output and therefore the cache identity.
    render: Mapping[str, Any] | None = None
    #: Override the default estimate. Tests and operators use this; a client
    #: should not, or it could reserve 0 and spend unbounded.
    estimate_tokens: int | None = None


def submit(
    db: Database,
    *,
    queue: JobQueue,
    request: JobRequest,
    require_entitlement: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    """Admit, reserve and enqueue one media job.

    Order is the contract: entitlement, then quota, then reserve, then enqueue.
    Any refusal before the reserve leaves no trace; a refusal *after* it would
    leave a hold nothing will ever release, so the reserve is the last thing
    that can fail before the job exists.
    """
    if not str(request.user_id or "").strip():
        raise StudioError("missing_user", "a job needs an owner", field="user_id")
    if request.kind not in MEDIA_KINDS:
        raise StudioError(
            "unknown_kind", f"kind must be one of {list(MEDIA_KINDS)}", field="kind"
        )
    if not str(request.script or "").strip():
        raise StudioError(
            "empty_script", "a media job needs a script or outline", field="script"
        )

    # 1. Entitlement: is this surface enabled for this user at all? Separate
    #    from quota on purpose -- "you may not use video" and "you cannot afford
    #    video" need different answers (403 vs 402) and different UI.
    if require_entitlement is not None and not require_entitlement(
        request.user_id, request.kind
    ):
        raise StudioError(
            "not_entitled",
            f"this account is not entitled to {request.kind}",
            field="kind",
        )

    estimate = estimate_for(request.kind, tokens=request.estimate_tokens)

    # 2. Cache first: a hit costs nothing, so it must not take a hold at all.
    key = cache_key(
        kind=request.kind,
        script=request.script,
        source_id=request.source_id,
        licence_code=request.licence_code,
        extra=request.render,
    )
    cached = find_cached(db, user_id=request.user_id, content_hash=key)
    if cached is not None:
        return {
            "cached": True,
            "asset": cached,
            "job_id": None,
            "reserved_tokens": 0,
            "estimate": estimate.as_dict(),
        }

    # 3. Reserve. Raises QuotaExceeded (a 402) if the balance, net of open
    #    holds, cannot cover it.
    reservation = accounting.reserve(
        db, user_id=request.user_id, tokens=estimate.tokens
    )

    # 4. Enqueue. If this raises, the hold must not survive: a reservation with
    #    no job is a permanent leak. Rolling back explicitly is the only way to
    #    guarantee that, since the two writes are in different tables.
    try:
        job = queue.enqueue(
            kind=job_kind(request.kind),
            payload={
                "user_id": request.user_id,
                "kind": request.kind,
                "script": request.script,
                "title": request.title,
                "source_id": request.source_id,
                "chapter_title": request.chapter_title,
                "licence_code": request.licence_code,
                "render": dict(request.render or {}),
                "reservation_id": reservation["id"],
                "content_hash": key,
            },
            # Dedupe on the cache key plus the owner: the same user asking twice
            # for the same render joins the in-flight job instead of paying for
            # it twice.
            dedupe_key=f"media:{request.user_id}:{key}",
            max_attempts=MEDIA_MAX_ATTEMPTS,
            priority=KIND_PRIORITY.get(request.kind, 100),
        )
    except Exception:
        accounting.refund(db, reservation_id=reservation["id"], reason="enqueue_failed")
        raise

    # Bind the hold to the job it pays for. Done here rather than inside
    # `reserve` because the job id does not exist until it is enqueued, and a
    # hold with no job id is a hold nothing can ever find to settle or refund --
    # which is exactly the leak this line prevents.
    accounting.attach(db, reservation_id=reservation["id"], job_id=job.id)

    record_cost(
        db,
        job_id=job.id,
        user_id=request.user_id,
        phase="estimate",
        tokens=estimate.tokens,
        non_token_units=estimate.non_token_units,
        non_token_unit=estimate.non_token_unit,
        non_token_cost_toman=estimate.non_token_cost_toman,
        provider=estimate.provider,
    )

    return {
        "cached": False,
        "asset": None,
        "job_id": job.id,
        "reservation_id": reservation["id"],
        "reserved_tokens": estimate.tokens,
        "estimate": estimate.as_dict(),
    }


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def cancel(db: Database, *, queue: JobQueue, job_id: str, user_id: str) -> dict[str, Any]:
    """Cancel a job and release its hold.

    The queue's cancel is the authority on whether the job stopped; the refund
    follows it. Refunding first and cancelling second would let a job that the
    queue refused to cancel run for free.
    """
    job = queue.get(job_id)
    if job is None or str(job.payload.get("user_id") or "") != user_id:
        raise StudioError("job_not_found", f"no job {job_id!r}", field="job_id")

    cancelled = queue.cancel(job_id)
    reservation = accounting.reservation_for_job(db, job_id)
    if cancelled and reservation is not None:
        accounting.refund(db, reservation_id=reservation["id"], reason="cancelled")

    return {
        "job_id": job_id,
        "cancelled": cancelled,
        "refunded": bool(cancelled and reservation is not None),
        "status": (queue.get(job_id).status if queue.get(job_id) else None),
    }


# ---------------------------------------------------------------------------
# Cost records
# ---------------------------------------------------------------------------


def record_cost(
    db: Database,
    *,
    job_id: str,
    user_id: str,
    phase: str,
    tokens: int = 0,
    non_token_units: float = 0.0,
    non_token_unit: str = "",
    non_token_cost_toman: int = 0,
    provider: str = "",
) -> dict[str, Any]:
    """Write an estimate or actual cost row.

    ``INSERT ... ON CONFLICT DO NOTHING`` semantics by catching the unique
    violation: a retried job re-recording its actual cost must not fail the
    job, and must not create a second row that double-counts the spend.
    """
    from deeptutor.db.connection import DatabaseError

    row_id = _new_id("cost")
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO media_job_costs "
                "(id, job_id, user_id, phase, tokens, non_token_units, non_token_unit, "
                " non_token_cost_toman, provider, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    job_id,
                    user_id,
                    phase,
                    tokens,
                    non_token_units,
                    non_token_unit,
                    non_token_cost_toman,
                    provider,
                    _now(),
                ),
            )
    except DatabaseError:
        # Already recorded for this phase.
        pass
    with db.read() as conn:
        row = conn.query_one(
            "SELECT * FROM media_job_costs WHERE job_id = ? AND phase = ?",
            (job_id, phase),
        )
    return dict(row) if row else {}


def job_costs(db: Database, job_id: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM media_job_costs WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            )
        )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# The handler
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderResult:
    """What a renderer produces. Bytes are written by the renderer itself."""

    storage_path: str
    mime_type: str
    content: str = ""
    size_bytes: int = 0
    duration_seconds: float | None = None
    #: Real cost, when the provider reported one. None means "use the estimate",
    #: which is the honest answer when a provider does not tell us.
    actual_tokens: int | None = None
    non_token_units: float = 0.0
    non_token_unit: str = ""
    non_token_cost_toman: int = 0
    provider: str = ""


def run_job(
    db: Database,
    *,
    queue: JobQueue,
    job: ClaimedJob,
    renderer: Callable[[str, Mapping[str, Any]], RenderResult],
) -> dict[str, Any]:
    """Execute one claimed media job: render, store, settle.

    Every exit path closes the hold. The failure path refunds and re-raises so
    the queue's own retry/backoff logic still owns the retry decision -- this
    function decides about *money*, the queue decides about *attempts*.

    A retry re-uses the same reservation: the hold was taken once at submit and
    a second attempt is work towards the same purchase, not a second purchase.
    Charging per attempt would make a flaky provider cost twice.
    """
    payload = dict(job.payload or {})
    user_id = str(payload.get("user_id") or "")
    kind = str(payload.get("kind") or "")
    reservation_id = str(payload.get("reservation_id") or "")

    try:
        result = renderer(kind, payload)
    except Exception as exc:
        # Whether the hold is released depends on whether this was the last
        # attempt. Refunding on every failure would close the hold and leave a
        # retry with nothing to settle against -- the user would be charged
        # twice, or not at all. So: keep the hold open while a retry is still
        # possible, release it only when the job is finally dead.
        exhausted = job.attempts >= job.max_attempts
        if exhausted:
            reservation = accounting.reservation_for_job(db, job.id)
            if reservation is not None:
                accounting.refund(
                    db, reservation_id=reservation["id"], reason="render_failed_terminal"
                )
            record_cost(
                db,
                job_id=job.id,
                user_id=user_id,
                phase="actual",
                tokens=0,
                provider="",
            )
        raise exc

    # A job cancelled while the renderer was running must not be charged. The
    # queue cannot preempt a handler, so this is the check that honours it.
    current = queue.get(job.id)
    if current is not None and current.status == "cancelled":
        reservation = accounting.reservation_for_job(db, job.id)
        if reservation is not None:
            accounting.refund(db, reservation_id=reservation["id"], reason="cancelled_midflight")
        return {"status": "cancelled", "asset_id": None}

    asset = store_asset(
        db,
        user_id=user_id,
        kind=kind,
        job_id=job.id,
        payload=payload,
        result=result,
    )

    # Settle against the real cost. A render whose actual is unknown settles at
    # the reserved estimate: the work was done and the money was committed.
    reservation = accounting.reservation_for_job(db, job.id)
    if reservation is not None:
        actual = (
            int(result.actual_tokens)
            if result.actual_tokens is not None
            else int(reservation["reserved_tokens"])
        )
        actual = min(actual, int(reservation["reserved_tokens"]))
        accounting.settle(db, reservation_id=reservation["id"], actual_tokens=actual)
        record_cost(
            db,
            job_id=job.id,
            user_id=user_id,
            phase="actual",
            tokens=actual,
            non_token_units=result.non_token_units,
            non_token_unit=result.non_token_unit,
            non_token_cost_toman=result.non_token_cost_toman,
            provider=result.provider,
        )

    return {"status": "ready", "asset_id": asset["id"]}


def store_asset(
    db: Database,
    *,
    user_id: str,
    kind: str,
    job_id: str | None,
    payload: Mapping[str, Any],
    result: RenderResult,
) -> dict[str, Any]:
    """Write the asset row. Idempotent on storage_path."""
    from deeptutor.db.connection import DatabaseError

    asset_id = _new_id("asset")
    stamp = _now()
    content_hash = str(payload.get("content_hash") or "")
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO media_assets "
                "(id, user_id, kind, job_id, title, storage_path, mime_type, size_bytes, "
                " duration_seconds, content_hash, source_id, chapter_title, licence_code, "
                " script, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)",
                (
                    asset_id,
                    user_id,
                    kind,
                    job_id,
                    str(payload.get("title") or ""),
                    result.storage_path,
                    result.mime_type,
                    int(result.size_bytes or 0),
                    result.duration_seconds,
                    content_hash,
                    payload.get("source_id"),
                    str(payload.get("chapter_title") or ""),
                    str(payload.get("licence_code") or ""),
                    str(payload.get("script") or ""),
                    stamp,
                    stamp,
                ),
            )
    except DatabaseError:
        # The same storage path already exists: a retried job produced the same
        # artefact. Return the existing row rather than failing the job.
        with db.read() as conn:
            existing = conn.query_one(
                "SELECT * FROM media_assets WHERE storage_path = ?", (result.storage_path,)
            )
        if existing is not None:
            return dict(existing)
        raise

    return get_asset(db, asset_id, user_id=user_id)


def get_asset(db: Database, asset_id: str, *, user_id: str) -> dict[str, Any]:
    """One asset, only for its owner.

    Not-found and not-yours are the same answer, the same rule Phase 6 applied
    to attempts: an opaque id is not a capability.
    """
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM media_assets WHERE id = ?", (asset_id,))
    if row is None or row["user_id"] != user_id or row["status"] != "ready":
        raise StudioError("asset_not_found", f"no asset {asset_id!r}", field="asset_id")
    return dict(row)


def list_assets(
    db: Database, *, user_id: str, kind: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """The caller's library, newest first."""
    clauses = ["user_id = ?", "status = 'ready'"]
    params: list[Any] = [user_id]
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    params.append(limit)
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM media_assets WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )
        )
    return [dict(row) for row in rows]


def delete_asset(db: Database, asset_id: str, *, user_id: str) -> bool:
    """Soft-delete. The row stays so the storage path is not reused silently."""
    get_asset(db, asset_id, user_id=user_id)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE media_assets SET status = 'deleted', updated_at = ? WHERE id = ?",
            (_now(), asset_id),
        )
    return True


__all__ = [
    "CostEstimate",
    "DEFAULT_ESTIMATES",
    "JOB_PREFIX",
    "KIND_PRIORITY",
    "JobRequest",
    "MEDIA_KINDS",
    "MEDIA_MAX_ATTEMPTS",
    "QuotaExceeded",
    "RenderResult",
    "StudioError",
    "cache_key",
    "cancel",
    "delete_asset",
    "estimate_for",
    "find_cached",
    "get_asset",
    "job_costs",
    "job_kind",
    "list_assets",
    "record_cost",
    "run_job",
    "store_asset",
    "submit",
]
