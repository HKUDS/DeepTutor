"""Platform health and data-layer readiness.

Split by audience, because these endpoints have different consumers:

``GET /api/platform/health/live``  — public, dependency-free.
    A container orchestrator's liveness probe. Must never touch the database:
    otherwise a database outage restarts every healthy process and turns one
    problem into two.

``GET /api/platform/health/ready`` — public, honest about degradation.
    A load balancer's readiness probe. Reports the database, schema contract and
    object store. Public because a load balancer has no session, and it leaks no
    user data — only booleans and, on failure, an exception class name.

``GET /api/platform/health/backup`` — admin only.
    Migration ledger, schema verification and per-table row counts. This is the
    comparable artefact Phase 3 asks for; it is admin-only because row counts
    are deployment intelligence.

Why ``public`` for readiness and not ``learning``: the existing policy names are
``public``/``authenticated``/``learning``/``admin``. Readiness is a probe, not a
learning surface; putting it behind ``learning`` would make it unusable by the
thing that needs it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

#: Public: liveness and readiness probes. Mounted at ``/api/platform`` with the
#: ``public`` policy. These expose booleans and an exception class name at most.
router = APIRouter()

#: Admin: migration ledger, schema verification and row counts. Mounted at
#: ``/api/platform/admin`` with the ``admin`` policy. Row counts and applied
#: migration versions are deployment intelligence and must not be anonymous.
admin_router = APIRouter()


@router.get("/health/live")
async def liveness_probe() -> dict:
    """Process is up. No dependency checks, by design."""
    from deeptutor.db.health import liveness

    return liveness()


@router.get("/health/ready")
async def readiness_probe() -> JSONResponse:
    """Can this process serve real traffic right now?

    Returns 200 when every dependency is healthy and 503 when it is not, so a
    load balancer needs no body parsing. The body is always present.
    """
    from deeptutor.db.health import readiness

    payload = readiness()
    status_code = 200 if payload.get("status") == "ok" else 503
    return JSONResponse(content=payload, status_code=status_code)


@admin_router.get("/health/backup")
async def backup_evidence() -> dict:
    """Migration ledger, schema verification and row counts."""
    from deeptutor.db.health import backup_evidence as collect

    evidence = collect()
    if evidence.get("schema_ok") is False:
        # Not an HTTP error: the evidence is still useful. The caller decides.
        logger.warning("schema verification failed: %s", evidence.get("schema_problem"))
    return evidence


@admin_router.get("/health/migrations")
async def migration_status() -> dict:
    """Which migrations are applied, pending or unknown to this build."""
    from deeptutor.db.config import get_database_settings
    from deeptutor.db.connection import open_database
    from deeptutor.db.migrate import applied_migrations, discover_migrations

    settings = get_database_settings()
    if not settings.enabled:
        return {"enabled": False, "applied": [], "pending": []}
    database = open_database(settings)
    if database is None:  # pragma: no cover
        return {"enabled": False, "applied": [], "pending": []}
    try:
        with database.read() as conn:
            applied = {
                int(row["version"]): {
                    "name": row["name"],
                    "checksum": row["checksum"],
                    "applied_at": row["applied_at"],
                }
                for row in applied_migrations(conn)
            }
        pending = [
            {"version": m.version, "name": m.name}
            for m in discover_migrations()
            if m.version not in applied and m.applies_to(settings.backend)
        ]
        return {
            "enabled": True,
            "backend": settings.backend,
            "applied": [
                {"version": version, **detail} for version, detail in sorted(applied.items())
            ],
            "pending": pending,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"database unavailable: {type(exc).__name__}")
    finally:
        database.close()
