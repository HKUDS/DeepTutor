"""Built-in cron service — scheduled tasks for chat and partners.

A trimmed-down take on nanobot's CronService (docs/ref/nanobot): same job
semantics (``at`` / ``every`` / ``cron`` schedules, JSON persistence, run
bookkeeping) without the multi-process file-lock/action-log machinery —
DeepTutor runs one server process, so a single in-process scheduler owns
the store.

Jobs carry an *owner*: a chat session (the reply is appended to that
session) or a partner conversation (the prompt is injected into the
partner's message bus and the reply rides the original IM channel). The
executor lives in :mod:`deeptutor.services.cron.executor`.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Any, Awaitable, Callable
import uuid

logger = logging.getLogger(__name__)

# Re-check the schedule at least this often even when nothing is due —
# cheap, and it picks up externally-edited stores within a minute.
_MAX_SLEEP_SECONDS = 60.0
_MAX_RUN_HISTORY = 10


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class CronSchedule:
    """When a job runs: one-shot, fixed interval, or cron expression."""

    kind: str  # "at" | "every" | "cron"
    at_ms: int | None = None  # "at": epoch ms
    every_seconds: int | None = None  # "every": interval
    expr: str | None = None  # "cron": e.g. "0 9 * * *"
    tz: str | None = None  # "cron": IANA timezone


@dataclass
class CronOwner:
    """Who scheduled the job and where its output goes."""

    kind: str  # "chat" | "partner"
    user_id: str = ""  # chat: owning user
    is_admin: bool = True  # chat: scope restore
    session_id: str = ""  # chat: reply lands in this session
    language: str = "en"
    partner_id: str = ""  # partner: owning partner
    channel: str = ""  # partner: originating channel
    chat_id: str = ""  # partner: originating chat
    session_key: str = ""  # partner: conversation key
    channel_meta: dict[str, Any] = field(default_factory=dict)  # partner: thread/reply metadata

    @property
    def key(self) -> str:
        if self.kind == "partner":
            return f"partner:{self.partner_id}"
        return f"chat:{self.user_id or 'local-admin'}"


@dataclass
class CronRunRecord:
    run_at_ms: int
    status: str  # "ok" | "error" | "skipped"
    duration_ms: int = 0
    error: str | None = None


@dataclass
class CronJobState:
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: str | None = None
    last_error: str | None = None
    run_history: list[CronRunRecord] = field(default_factory=list)


@dataclass
class CronJob:
    id: str
    name: str
    message: str
    schedule: CronSchedule
    owner: CronOwner
    enabled: bool = True
    delete_after_run: bool = False
    created_at_ms: int = 0
    state: CronJobState = field(default_factory=CronJobState)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CronJob":
        state = dict(data.get("state") or {})
        state["run_history"] = [CronRunRecord(**record) for record in state.get("run_history", [])]
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or ""),
            message=str(data.get("message") or ""),
            schedule=CronSchedule(**(data.get("schedule") or {"kind": "every"})),
            owner=CronOwner(**(data.get("owner") or {"kind": "chat"})),
            enabled=bool(data.get("enabled", True)),
            delete_after_run=bool(data.get("delete_after_run", False)),
            created_at_ms=int(data.get("created_at_ms", 0)),
            state=CronJobState(**state),
        )


def compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Next due time in epoch ms, or ``None`` for never/expired."""
    if schedule.kind == "at":
        if schedule.at_ms and schedule.at_ms > now_ms:
            return schedule.at_ms
        return None

    if schedule.kind == "every":
        if not schedule.every_seconds or schedule.every_seconds <= 0:
            return None
        return now_ms + schedule.every_seconds * 1000

    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter

            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base = datetime.fromtimestamp(now_ms / 1000, tz=tz)
            next_dt = croniter(schedule.expr, base).get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except ImportError:
            raise ValueError(
                "cron expressions need the 'croniter' package — "
                "use an 'every' or 'at' schedule instead"
            ) from None
        except Exception as exc:
            raise ValueError(f"invalid cron expression {schedule.expr!r}: {exc}") from None

    return None


def validate_schedule(schedule: CronSchedule) -> None:
    """Reject schedules that could never run (raises ValueError)."""
    if schedule.kind == "at":
        if not schedule.at_ms:
            raise ValueError("'at' schedules need a time")
        if schedule.at_ms <= _now_ms():
            raise ValueError("'at' time is in the past")
        return
    if schedule.kind == "every":
        if not schedule.every_seconds or schedule.every_seconds < 30:
            raise ValueError("'every' interval must be at least 30 seconds")
        return
    if schedule.kind == "cron":
        if schedule.tz:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(schedule.tz)
            except Exception:
                raise ValueError(f"unknown timezone {schedule.tz!r}") from None
        # Raises ValueError on bad/unsupported expressions.
        if compute_next_run(schedule, _now_ms()) is None:
            raise ValueError(f"cron expression {schedule.expr!r} never fires")
        return
    raise ValueError(f"unknown schedule kind {schedule.kind!r}")


class CronService:
    """Single-process job store + scheduler."""

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Awaitable[tuple[str, str | None]]] | None = None,
    ) -> None:
        """``on_job`` returns ``(status, error)`` with status ok/error/skipped."""
        self.store_path = store_path
        self.on_job = on_job
        self._jobs: dict[str, CronJob] = {}
        self._loaded = False
        self._timer_task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._running = False

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            for raw in data.get("jobs", []):
                job = CronJob.from_dict(raw)
                self._jobs[job.id] = job
        except Exception:
            # Preserve the corrupt store for recovery; an empty in-memory
            # view would otherwise overwrite it on the next save.
            backup = self.store_path.with_suffix(f".corrupt-{int(time.time())}")
            try:
                self.store_path.rename(backup)
            except OSError:
                pass
            logger.exception("Corrupt cron store moved to %s", backup)

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "jobs": [asdict(job) for job in self._jobs.values()]}
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.store_path)

    # ── job management ────────────────────────────────────────────

    def add_job(
        self,
        *,
        name: str,
        message: str,
        schedule: CronSchedule,
        owner: CronOwner,
        delete_after_run: bool | None = None,
    ) -> CronJob:
        self._load()
        validate_schedule(schedule)
        if not message.strip():
            raise ValueError("message is required")
        job = CronJob(
            id=uuid.uuid4().hex[:10],
            name=name.strip() or message.strip()[:48],
            message=message.strip(),
            schedule=schedule,
            owner=owner,
            # One-shot jobs clean up after themselves unless told otherwise.
            delete_after_run=(
                delete_after_run if delete_after_run is not None else schedule.kind == "at"
            ),
            created_at_ms=_now_ms(),
        )
        job.state.next_run_at_ms = compute_next_run(schedule, _now_ms())
        self._jobs[job.id] = job
        self._save()
        self._wake.set()
        return job

    def list_jobs(self, owner_key: str | None = None) -> list[CronJob]:
        self._load()
        jobs = list(self._jobs.values())
        if owner_key is not None:
            jobs = [job for job in jobs if job.owner.key == owner_key]
        return sorted(jobs, key=lambda job: job.state.next_run_at_ms or 0)

    def get_job(self, job_id: str) -> CronJob | None:
        self._load()
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str, *, owner_key: str | None = None) -> bool:
        """Remove a job; ``owner_key`` scopes the cancel to its owner."""
        self._load()
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if owner_key is not None and job.owner.key != owner_key:
            return False
        del self._jobs[job_id]
        self._save()
        self._wake.set()
        return True

    def remove_owner_jobs(self, owner_key: str) -> int:
        """Drop every job belonging to *owner_key* (e.g. a destroyed partner)."""
        self._load()
        doomed = [job_id for job_id, job in self._jobs.items() if job.owner.key == owner_key]
        for job_id in doomed:
            del self._jobs[job_id]
        if doomed:
            self._save()
            self._wake.set()
        return len(doomed)

    # ── scheduler ─────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._load()
        # Re-arm interval/cron jobs whose due time passed while the server
        # was down: run once now (next_run in the past stays "due"); expired
        # one-shots are dropped.
        now = _now_ms()
        changed = False
        for job in list(self._jobs.values()):
            if job.schedule.kind == "at" and (job.schedule.at_ms or 0) <= now:
                del self._jobs[job.id]
                changed = True
        if changed:
            self._save()
        self._running = True
        self._timer_task = asyncio.create_task(self._loop(), name="cron:scheduler")
        logger.info("Cron service started (%d jobs)", len(self._jobs))

    async def stop(self) -> None:
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
            self._timer_task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cron tick failed")
            sleep_s = self._seconds_until_next_due()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=sleep_s)
            except asyncio.TimeoutError:
                pass

    def _seconds_until_next_due(self) -> float:
        due_times = [
            job.state.next_run_at_ms
            for job in self._jobs.values()
            if job.enabled and job.state.next_run_at_ms
        ]
        if not due_times:
            return _MAX_SLEEP_SECONDS
        delta_s = (min(due_times) - _now_ms()) / 1000
        return max(0.05, min(delta_s, _MAX_SLEEP_SECONDS))

    async def _tick(self) -> None:
        now = _now_ms()
        for job in list(self._jobs.values()):
            if not job.enabled or not job.state.next_run_at_ms:
                continue
            if job.state.next_run_at_ms > now:
                continue
            await self._run_job(job)

    async def _run_job(self, job: CronJob) -> None:
        started = _now_ms()
        status, error = "skipped", None
        if self.on_job is not None:
            try:
                status, error = await self.on_job(job)
            except Exception as exc:  # noqa: BLE001
                status, error = "error", f"{type(exc).__name__}: {exc}"
                logger.exception("Cron job %s (%s) crashed", job.id, job.name)

        job.state.last_run_at_ms = started
        job.state.last_status = status
        job.state.last_error = error
        job.state.run_history.append(
            CronRunRecord(
                run_at_ms=started,
                status=status,
                duration_ms=_now_ms() - started,
                error=error,
            )
        )
        job.state.run_history = job.state.run_history[-_MAX_RUN_HISTORY:]

        if job.delete_after_run or job.schedule.kind == "at":
            self._jobs.pop(job.id, None)
        else:
            job.state.next_run_at_ms = compute_next_run(job.schedule, _now_ms())
            if job.state.next_run_at_ms is None:
                self._jobs.pop(job.id, None)
        self._save()


_service: CronService | None = None


def get_cron_service() -> CronService:
    """Process-wide cron service, anchored at the admin workspace."""
    global _service
    if _service is None:
        from deeptutor.multi_user.paths import get_admin_path_service
        from deeptutor.services.cron.executor import execute_job

        store = get_admin_path_service().workspace_root / "cron" / "jobs.json"
        _service = CronService(store_path=store, on_job=execute_job)
    return _service


__all__ = [
    "CronJob",
    "CronOwner",
    "CronSchedule",
    "CronService",
    "compute_next_run",
    "get_cron_service",
    "validate_schedule",
]
