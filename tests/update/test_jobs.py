from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.update.jobs import (
    JobStatus,
    UpdateInProgressError,
    UpdateJobStore,
    UpdateScheduler,
)


def test_only_one_update_job_can_be_active(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)
    first = store.create_pypi(current_version="1.5.4", target_version="1.6.0")

    with pytest.raises(UpdateInProgressError):
        store.create_pypi(current_version="1.5.4", target_version="1.6.0")

    assert store.load() == first


def test_restart_handoff_rejects_a_tampered_command(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path / "jobs")
    home = tmp_path / "home"
    job = store.create_pypi(
        current_version="1.5.4",
        target_version="1.6.0",
        restart_requested=True,
    )
    store.prepare_restart(
        job.id,
        home=home,
        restart_argv=("start", "--home", str(home.resolve()), "--dev"),
    )
    payload = json.loads(store.state_path.read_text(encoding="utf-8"))
    payload["restart_argv"].extend(["--home", str(tmp_path / "other-home")])
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid restart arguments"):
        store.load()


def test_scheduler_persists_job_before_launching_worker(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)
    observed = {}

    class Launcher:
        def launch(self, store_root: Path, *, parent_pid: int) -> None:
            observed["job"] = store.load()
            observed["store_root"] = store_root
            observed["parent_pid"] = parent_pid

    job = UpdateScheduler(store=store, launcher=Launcher()).schedule_pypi(
        current_version="1.5.4",
        target_version="1.6.0",
        parent_pid=123,
    )

    assert observed == {
        "job": job,
        "store_root": tmp_path,
        "parent_pid": 123,
    }
    assert job.status is JobStatus.PENDING


def test_scheduler_records_launch_failure_and_releases_active_job(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)

    class BrokenLauncher:
        def launch(self, store_root: Path, *, parent_pid: int) -> None:
            raise OSError("worker could not start")

    scheduler = UpdateScheduler(store=store, launcher=BrokenLauncher())

    with pytest.raises(OSError, match="worker could not start"):
        scheduler.schedule_pypi(
            current_version="1.5.4",
            target_version="1.6.0",
            parent_pid=123,
        )

    assert store.load().status is JobStatus.FAILED
    replacement = store.create_pypi(current_version="1.5.4", target_version="1.6.0")
    assert replacement.status is JobStatus.PENDING
