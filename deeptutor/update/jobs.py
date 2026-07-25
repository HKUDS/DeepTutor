"""Persistent update jobs and detached worker launch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Protocol
import uuid

from packaging.version import Version

from deeptutor.runtime.home import get_runtime_home
from deeptutor.services.file_io import atomic_write_json


class JobStatus(str, Enum):
    """Durable lifecycle of one update job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class UpdateInProgressError(RuntimeError):
    """Raised when another update job owns the active marker."""


@dataclass(frozen=True)
class UpdateJob:
    """Trusted data required to apply one PyPI update."""

    id: str
    status: JobStatus
    current_version: str
    target_version: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    schema_version: int = 1
    kind: str = "pypi"

    def to_dict(self) -> dict[str, object]:
        """Serialize the job for durable storage."""

        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> UpdateJob:
        """Validate and deserialize one stored job."""

        if payload.get("schema_version") != 1 or payload.get("kind") != "pypi":
            raise ValueError("Unsupported update job")
        return cls(
            id=str(payload["id"]),
            status=JobStatus(str(payload["status"])),
            current_version=str(payload["current_version"]),
            target_version=str(payload["target_version"]),
            created_at=str(payload["created_at"]),
            started_at=_optional_string(payload.get("started_at")),
            finished_at=_optional_string(payload.get("finished_at")),
            error=_optional_string(payload.get("error")),
        )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_version(raw: str, *, stable: bool) -> str:
    version = Version(raw)
    if stable and (version.is_prerelease or version.is_devrelease):
        raise ValueError("Update target must be a stable version")
    return str(version)


class UpdateJobStore:
    """Persist the current job and reserve the single active update slot."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.state_path = self.root / "state.json"
        self.active_path = self.root / "active"
        self.log_path = self.root / "worker.log"

    def create_pypi(self, *, current_version: str, target_version: str) -> UpdateJob:
        """Reserve the active slot for one PyPI update."""

        job = UpdateJob(
            id=uuid.uuid4().hex,
            status=JobStatus.PENDING,
            current_version=_canonical_version(current_version, stable=False),
            target_version=_canonical_version(target_version, stable=True),
            created_at=_now(),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.active_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise UpdateInProgressError("Another update job is already active") from exc
        try:
            os.write(descriptor, job.id.encode("ascii"))
        finally:
            os.close(descriptor)
        try:
            self._write(job)
        except Exception:
            self.release(job.id)
            raise
        return job

    def load(self) -> UpdateJob:
        """Load and validate the persisted job."""

        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid update job")
        return UpdateJob.from_dict(payload)

    def mark_running(self, job_id: str) -> UpdateJob:
        """Mark a pending or handed-off job as running."""

        return self._transition(job_id, JobStatus.RUNNING)

    def mark_succeeded(self, job_id: str) -> UpdateJob:
        """Finish a job successfully and release its active slot."""

        return self._transition(job_id, JobStatus.SUCCEEDED)

    def mark_failed(self, job_id: str, error: str) -> UpdateJob:
        """Finish a failed job and persist its bounded error message."""

        return self._transition(job_id, JobStatus.FAILED, error=error)

    def release(self, job_id: str) -> None:
        """Release the active marker when it still belongs to *job_id*."""

        try:
            active_job_id = self.active_path.read_text(encoding="ascii")
        except OSError:
            return
        if active_job_id == job_id:
            self.active_path.unlink(missing_ok=True)

    def _transition(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> UpdateJob:
        current = self.load()
        if current.id != job_id:
            raise RuntimeError("Update job changed while it was running")
        timestamp = _now()
        updated = replace(
            current,
            status=status,
            started_at=timestamp if status is JobStatus.RUNNING else current.started_at,
            finished_at=(
                timestamp
                if status in {JobStatus.SUCCEEDED, JobStatus.FAILED}
                else current.finished_at
            ),
            error=error[:1000] if error else None,
        )
        self._write(updated)
        if status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
            self.release(job_id)
        return updated

    def _write(self, job: UpdateJob) -> None:
        atomic_write_json(self.state_path, job.to_dict())


class WorkerLauncher(Protocol):
    """Boundary for starting the detached updater process."""

    def launch(self, store_root: Path, *, parent_pid: int) -> None:
        """Start a worker for the persisted job."""


class SubprocessWorkerLauncher:
    """Start the trusted update worker outside the current CLI process."""

    def __init__(self, python_executable: str | None = None) -> None:
        self._python_executable = python_executable or sys.executable

    def launch(self, store_root: Path, *, parent_pid: int) -> None:
        """Launch the fixed update worker as a detached process."""

        command = [
            self._python_executable,
            "-m",
            "deeptutor.update.worker",
            "--store-root",
            str(store_root.resolve()),
            "--parent-pid",
            str(parent_pid),
        ]
        store_root.mkdir(parents=True, exist_ok=True)
        log_path = store_root / "worker.log"
        kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            )
        else:
            kwargs["start_new_session"] = True
        with log_path.open("a", encoding="utf-8") as log:
            subprocess.Popen(command, stdout=log, **kwargs)  # type: ignore[arg-type,call-overload]


class UpdateScheduler:
    """Reserve and launch one PyPI update job."""

    def __init__(self, *, store: UpdateJobStore, launcher: WorkerLauncher) -> None:
        self._store = store
        self._launcher = launcher

    def schedule_pypi(
        self,
        *,
        current_version: str,
        target_version: str,
        parent_pid: int,
    ) -> UpdateJob:
        """Persist and launch one PyPI update after the CLI exits."""

        job = self._store.create_pypi(
            current_version=current_version,
            target_version=target_version,
        )
        try:
            self._launcher.launch(self._store.root, parent_pid=parent_pid)
        except Exception as exc:
            self._store.mark_failed(job.id, f"worker launch failed: {exc}")
            raise
        return job


def create_update_scheduler(home: str | Path | None = None) -> UpdateScheduler:
    """Build the production scheduler for the active runtime home."""

    root = get_runtime_home(home) / "data" / "user" / "update"
    return UpdateScheduler(
        store=UpdateJobStore(root),
        launcher=SubprocessWorkerLauncher(),
    )


__all__ = (
    "JobStatus",
    "SubprocessWorkerLauncher",
    "UpdateInProgressError",
    "UpdateJob",
    "UpdateJobStore",
    "UpdateScheduler",
    "WorkerLauncher",
    "create_update_scheduler",
)
