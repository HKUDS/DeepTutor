"""Durable web-source sync jobs shared by API and scheduler.

Both the manual API endpoint and the periodic scheduler submit jobs through
``submit_web_sync``.  Keeping the queue executor here prevents scheduled work
from bypassing progress persistence, cancellation, and single-flight checks.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

_WEB_SYNC_JOBS: dict[str, dict[str, Any]] = {}
_WEB_SYNC_TASKS: dict[str, asyncio.Task] = {}
_WEB_SYNC_ACTIVE: set[str] = set()
_WEB_SYNC_JOB_LIMIT = 50
_ACTIVE_STATUSES = {"queued", "running", "cancelling"}


class WebSyncConflictError(RuntimeError):
    """Raised when a KB already has an active web-source sync job."""

    def __init__(self, job: dict[str, Any]) -> None:
        super().__init__(f"Web source sync already running: {job.get('job_id', '')}")
        self.job = job


def web_sync_job_path(kb_base_dir: Path | str, kb_name: str) -> Path:
    return Path(kb_base_dir) / kb_name / ".web_sync_jobs.json"


def load_web_sync_jobs(kb_base_dir: Path | str, kb_name: str) -> dict[str, dict[str, Any]]:
    path = web_sync_job_path(kb_base_dir, kb_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_web_sync_job(kb_base_dir: Path | str, job: dict[str, Any]) -> dict[str, Any]:
    kb_base_dir = Path(kb_base_dir)
    jobs = load_web_sync_jobs(kb_base_dir, job["kb_name"])
    jobs[job["job_id"]] = job
    ordered = dict(sorted(jobs.items(), key=lambda item: item[1].get("created_at", "")))
    while len(ordered) > _WEB_SYNC_JOB_LIMIT:
        ordered.pop(next(iter(ordered)))
    atomic_write_json(web_sync_job_path(kb_base_dir, job["kb_name"]), ordered)
    _WEB_SYNC_JOBS[job["job_id"]] = job
    return job


def _new_web_sync_job(kb_name: str, trigger: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": f"web-sync-{uuid4().hex[:16]}",
        "kb_name": kb_name,
        "trigger": trigger,
        "status": "queued",
        "progress": 0,
        "message": "Queued",
        "result": None,
        "error": None,
        "created_at": now,
        "started_at": "",
        "finished_at": "",
        "pid": os.getpid(),
    }


def update_web_sync_job(
    kb_base_dir: Path | str,
    kb_name: str,
    job_id: str,
    **fields: Any,
) -> dict[str, Any]:
    job = _WEB_SYNC_JOBS.get(job_id) or load_web_sync_jobs(kb_base_dir, kb_name).get(job_id)
    if not job:
        raise KeyError(job_id)
    job.update(fields)
    return _save_web_sync_job(kb_base_dir, job)


def get_web_sync_job(kb_base_dir: Path | str, kb_name: str, job_id: str) -> dict[str, Any] | None:
    job = _WEB_SYNC_JOBS.get(job_id) or load_web_sync_jobs(kb_base_dir, kb_name).get(job_id)
    if not job or job.get("kb_name") != kb_name:
        return None
    if (
        job.get("status") in _ACTIVE_STATUSES
        and int(job.get("pid") or 0) != os.getpid()
        and job_id not in _WEB_SYNC_TASKS
        and job_id not in _WEB_SYNC_ACTIVE
    ):
        job = update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="interrupted",
            message="Web source sync was interrupted by a server restart",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    return job


def _active_job(kb_base_dir: Path | str, kb_name: str) -> dict[str, Any] | None:
    persisted = load_web_sync_jobs(kb_base_dir, kb_name)
    for job in persisted.values():
        if job.get("kb_name") != kb_name or job.get("status") not in _ACTIVE_STATUSES:
            continue
        if int(job.get("pid") or 0) != os.getpid():
            job = update_web_sync_job(
                kb_base_dir,
                kb_name,
                job["job_id"],
                status="interrupted",
                message="Web source sync was interrupted by a server restart",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            continue
        return job
    return None


def _result_payload(kb_result: Any, source_count: int) -> dict[str, Any]:
    payload = asdict(kb_result) if is_dataclass(kb_result) else dict(kb_result)
    payload["message"] = (
        f"Synced {source_count} source(s) in {len(payload.get('pair_results', []))} pair(s)"
    )
    return payload


async def _run_web_sync_job(
    job_id: str,
    kb_name: str,
    sources: list[dict[str, Any]],
    kb_base_dir: Path | str,
) -> None:
    from deeptutor.knowledge.manager import KnowledgeBaseManager
    from deeptutor.services.web_source.orchestrator import sync_kb_sources_safe

    _WEB_SYNC_ACTIVE.add(job_id)

    def report_progress(percent: int, message: str) -> None:
        current = _WEB_SYNC_JOBS.get(job_id, {})
        update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="running",
            progress=max(0, min(int(percent), 99)),
            message=message,
            started_at=current.get("started_at")
            or datetime.now(timezone.utc).isoformat(),
        )

    try:
        update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="running",
            progress=2,
            message="Starting web source sync",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        kb_result = await sync_kb_sources_safe(
            kb_name=kb_name,
            sources=sources,
            base_dir=str(kb_base_dir),
            progress=report_progress,
        )
        payload = _result_payload(kb_result, len(sources))
        failed = bool(not kb_result.ok or kb_result.index_error)
        update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="failed" if failed else "succeeded",
            progress=100,
            message=payload["message"],
            result=payload,
            error=kb_result.index_error or None,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

        manager = KnowledgeBaseManager(base_dir=str(kb_base_dir))
        for source in sources:
            manager.update_web_source_state(kb_name, source.get("id", ""), latest_sync_job=job_id)
    except asyncio.CancelledError:
        update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="cancelled",
            progress=_WEB_SYNC_JOBS.get(job_id, {}).get("progress", 0),
            message="Web source sync cancelled",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        raise
    except Exception as exc:
        logger.exception("Web source sync job failed KB=%s job=%s", kb_name, job_id)
        update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="failed",
            progress=100,
            message="Web source sync failed",
            error=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        _WEB_SYNC_ACTIVE.discard(job_id)


def submit_web_sync(
    *,
    kb_name: str,
    sources: list[dict[str, Any]],
    kb_base_dir: Path | str,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Persist and dispatch one sync job; manual and scheduled callers share this path."""
    if trigger not in {"manual", "scheduled"}:
        raise ValueError(f"Unsupported web sync trigger: {trigger}")

    active = _active_job(kb_base_dir, kb_name)
    if active is not None:
        raise WebSyncConflictError(active)

    enabled = [source for source in sources if source.get("enabled", True)]
    job = _new_web_sync_job(kb_name, trigger)
    if not enabled:
        job.update(
            status="succeeded",
            progress=100,
            message="No enabled web sources",
            finished_at=job["created_at"],
            result={
                "message": "No enabled web sources",
                "ok": True,
                "pair_results": [],
                "index_rebuilt": False,
                "index_error": None,
                "total_pages": 0,
            },
        )
        _save_web_sync_job(kb_base_dir, job)
        return job

    _save_web_sync_job(kb_base_dir, job)
    task = asyncio.create_task(
        _run_web_sync_job(job["job_id"], kb_name, enabled, kb_base_dir),
        name=job["job_id"],
    )
    _WEB_SYNC_TASKS[job["job_id"]] = task
    task.add_done_callback(
        lambda done, job_id=job["job_id"]: _WEB_SYNC_TASKS.pop(job_id, None)
    )
    return job


async def cancel_web_sync_job(
    kb_base_dir: Path | str,
    kb_name: str,
    job_id: str,
) -> dict[str, Any]:
    job = get_web_sync_job(kb_base_dir, kb_name, job_id)
    if job is None:
        raise KeyError(job_id)
    if job.get("status") not in _ACTIVE_STATUSES:
        return job

    task = _WEB_SYNC_TASKS.get(job_id)
    if task is None:
        return update_web_sync_job(
            kb_base_dir,
            kb_name,
            job_id,
            status="cancelled",
            message="Web source sync cancelled",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    job = update_web_sync_job(
        kb_base_dir,
        kb_name,
        job_id,
        status="cancelling",
        message="Cancelling web source sync",
    )
    task.cancel()
    return job


def reset_web_sync_job_state_for_tests() -> None:
    _WEB_SYNC_JOBS.clear()
    _WEB_SYNC_TASKS.clear()
    _WEB_SYNC_ACTIVE.clear()


__all__ = [
    "WebSyncConflictError",
    "cancel_web_sync_job",
    "get_web_sync_job",
    "load_web_sync_jobs",
    "reset_web_sync_job_state_for_tests",
    "submit_web_sync",
    "web_sync_job_path",
]
