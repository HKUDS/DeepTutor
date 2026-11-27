"""Health, readiness and backup evidence for the data layer.

Three questions, deliberately answered by three different functions, because
conflating them is how a service ends up with one boolean that is always green:

``liveness``
    Is the process able to serve at all? Never touches a dependency, so it stays
    ``ok`` while the database is down — a database outage must not make the
    orchestrator kill and restart a perfectly healthy process.

``readiness``
    Can this process do its real work right now? Checks the database, the
    schema contract and the object store. This is what a load balancer should
    gate on.

``backup_evidence``
    What would we restore from, and does the migration ledger agree with the
    schema? This is the artefact ROADMAP Phase 3 asks for ("backup restore
    نتیجه قابل مقایسه ارائه دهد"): a comparable, printable record the operator can
    diff between two points in time.

None of these ever raises: a health endpoint that can 500 is not a health
endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from deeptutor.db.config import get_database_settings
from deeptutor.db.connection import Database, open_database
from deeptutor.db.migrate import applied_migrations, discover_migrations
from deeptutor.db.schema_check import SchemaMismatch, verify_schema

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def liveness() -> dict[str, Any]:
    """Process is up. No dependency checks by design."""
    return {"status": "ok", "checked_at": _now()}


def readiness(db: Database | None = None) -> dict[str, Any]:
    """Everything needed to serve traffic."""
    settings = get_database_settings()
    payload: dict[str, Any] = {
        "checked_at": _now(),
        "database": {"enabled": settings.enabled, "backend": settings.backend},
        "object_store": {"ok": True},
        "schema": {"ok": True},
    }
    ok = True

    if settings.enabled or db is not None:
        database = db
        own = False
        try:
            if database is None:
                database = open_database(settings)
                own = True
            if database is None:  # pragma: no cover
                ok = False
                payload["database"].update({"ok": False, "reason": "not_constructed"})
            else:
                reachable, detail = database.ping()
                payload["database"].update({"ok": reachable, "backend": database.backend})
                if not reachable:
                    ok = False
                    payload["database"]["reason"] = detail
                else:
                    try:
                        verify_schema(database)
                    except SchemaMismatch as exc:
                        ok = False
                        payload["schema"] = {"ok": False, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            ok = False
            payload["database"].update({"ok": False, "reason": type(exc).__name__})
        finally:
            if own and database is not None:
                database.close()

    try:
        from deeptutor.db.storage import get_object_store

        store = get_object_store()
        probe = store.put(b"health-probe", namespace="_health")
        store.delete(probe)
        payload["object_store"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        ok = False
        payload["object_store"] = {"ok": False, "reason": type(exc).__name__}

    payload["status"] = "ok" if ok else "degraded"
    return payload


def backup_evidence(db: Database | None = None) -> dict[str, Any]:
    """A comparable snapshot of what is deployed and what would be restored.

    Contains no user data — only schema shape, migration ledger and row counts
    per table, which is exactly enough to diff two environments ("did the
    restore come back the same?") without copying personal data around.
    """
    settings = get_database_settings()
    evidence: dict[str, Any] = {
        "captured_at": _now(),
        "database": settings.describe(),
        "migrations": [],
        "tables": {},
        "schema_ok": None,
    }
    # An explicitly supplied database always wins. ``settings.enabled`` only
    # decides whether to *look one up* — it must not skip a handle the caller
    # already holds, which is how a test (or an admin tool pointed at a staging
    # DSN) would otherwise silently receive "no database configured".
    if db is None and not settings.enabled:
        evidence["note"] = "no database configured; file stores only"
        return evidence

    database = db
    own = False
    try:
        if database is None:
            database = open_database(settings)
            own = True
        if database is None:  # pragma: no cover
            return evidence
        evidence["database"] = {
            "enabled": True,
            "backend": database.backend,
            "host": settings.describe()["host"],
            "pool_size": settings.pool_size,
            "statement_timeout_ms": settings.statement_timeout_ms,
            "migration_url_configured": bool(settings.migration_url),
        }

        files = {m.version: m.name for m in discover_migrations()}
        with database.read() as conn:
            evidence["migrations"] = [
                {
                    "version": int(row["version"]),
                    "name": row["name"],
                    "checksum": row["checksum"],
                    "applied_at": row["applied_at"],
                    "known_to_source": int(row["version"]) in files,
                }
                for row in applied_migrations(conn)
            ]
        try:
            verify_schema(database)
            evidence["schema_ok"] = True
        except SchemaMismatch as exc:
            evidence["schema_ok"] = False
            evidence["schema_problem"] = str(exc)
        evidence["tables"] = _row_counts(database)
    except Exception as exc:  # noqa: BLE001
        evidence["error"] = type(exc).__name__
    finally:
        if own and database is not None:
            database.close()
    return evidence


def _row_counts(database: Database) -> dict[str, int]:
    """Row count per public table. Naming is restricted to the catalog, so the
    only interpolated text is a table name the database itself returned."""
    import re

    safe = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    counts: dict[str, int] = {}
    with database.read() as conn:
        if conn.backend == "sqlite":
            names = [
                str(r["name"])
                for r in conn.query(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).rows
            ]
        else:
            names = [
                str(r["table_name"])
                for r in conn.query(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                ).rows
            ]
        for name in names:
            if not safe.match(name):
                continue
            try:
                counts[name] = int(conn.scalar(f'SELECT COUNT(*) AS n FROM "{name}"') or 0)
            except Exception:  # noqa: BLE001 - one bad table must not hide the rest
                counts[name] = -1
    return counts
