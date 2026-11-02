"""Installed distribution snapshots and bounded launcher restart receipts."""

from __future__ import annotations

from dataclasses import replace
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

import pytest

from deeptutor.runtime.update_worker import (
    build_update_command,
    run_update_worker,
    wait_for_restart,
)
from deeptutor.services import app_update
from deeptutor.services.app_update import UpdateJobStore


def _metadata(monkeypatch, packages):
    def version(name):
        if name not in packages:
            raise importlib.metadata.PackageNotFoundError(name)
        return "1.7.1"

    monkeypatch.setattr(app_update.importlib.metadata, "version", version)


def _handoff(tmp_path, current="1.7.1", target="1.7.2"):
    store = UpdateJobStore(tmp_path / "update")
    pending = store.create(current_version=current, target_version=target)
    home = tmp_path / "home"
    home.mkdir()
    job = store.prepare_handoff(
        pending.id, home=home, restart_argv=["start", "--home", str(home.resolve())]
    )
    return store, job


@pytest.mark.parametrize(
    "packages",
    [[], ["deeptutor-server", "deeptutor-web"], ["deeptutor-parser-docling", "deeptutor-cli"]],
)
def test_snapshot_preserves_only_installed_packages_and_same_version_pins(
    monkeypatch, tmp_path, packages
):
    _metadata(monkeypatch, packages)
    store, job = _handoff(tmp_path)
    assert job.packages == tuple(sorted(packages))
    assert store.load().packages == job.packages
    # Metadata changes after handoff cannot change the already-reviewed plan.
    _metadata(monkeypatch, [])
    commands = []
    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda command, *_: commands.append(command) or 0,
            restart_launcher=lambda *_: None,
        )
        == 0
    )
    assert commands[0][7:] == ["deeptutor==1.7.2", *(f"{p}==1.7.2" for p in sorted(packages))]


def test_legacy_snapshot_matches_standard_app_without_optional_native_extras(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    _, job = _handoff(tmp_path, "1.6.15", "1.7.1")
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    expected = {
        p.split("==")[0] for p in project["tool"]["deeptutor"]["optional-dependencies"]["full"]
    }
    assert set(job.packages) == expected
    assert "deeptutor-renderer-manim" not in job.packages
    assert not any("parser-" in p for p in job.packages)


def test_manual_hint_uses_the_same_installed_set(monkeypatch):
    _metadata(monkeypatch, ["deeptutor-server", "deeptutor-parser-docling", "deeptutor-cli"])
    monkeypatch.setattr(app_update, "__version__", "1.7.1")
    hint = app_update.manual_update_command()
    assert hint.split()[5:] == [
        "deeptutor",
        "deeptutor-cli",
        "deeptutor-parser-docling",
        "deeptutor-server",
    ]


def test_disabled_module_choice_and_learning_data_survive_snapshot(monkeypatch, tmp_path):
    _metadata(monkeypatch, ["deeptutor-server", "deeptutor-web"])
    home = tmp_path / "home"
    selected = home / "data/system/modules.json"
    selected.parent.mkdir(parents=True)
    selected.write_text('{"schema_version":1,"enabled":{"web":false}}', encoding="utf-8")
    before = selected.read_bytes()
    store = UpdateJobStore(tmp_path / "update")
    pending = store.create(current_version="1.7.1", target_version="1.7.2")
    job = store.prepare_handoff(
        pending.id, home=home, restart_argv=["start", "--home", str(home.resolve())]
    )
    assert "deeptutor-web" in job.packages
    assert selected.read_bytes() == before


@pytest.mark.parametrize(
    "value",
    [
        ["requests"],
        ["deeptutor-server==9"],
        ["--index-url"],
        ["deeptutor-web", "deeptutor-web"],
        "deeptutor-web",
        [False],
    ],
)
def test_persisted_snapshot_rejects_untrusted_packages(monkeypatch, tmp_path, value):
    _metadata(monkeypatch, [])
    store, _ = _handoff(tmp_path)
    payload = json.loads(store.state_path.read_text(encoding="utf-8"))
    payload["packages"] = value
    store.state_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        store.load()


def test_real_early_exit_finishes_job_and_preserves_log_reason(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    store, _ = _handoff(tmp_path)
    children = []

    def restart(job, log_path):
        with log_path.open("a", encoding="utf-8") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "print('synthetic module startup failure', flush=True); raise SystemExit(23)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        children.append(child)
        return child

    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda *_: 0,
            restart_launcher=restart,
        )
        == 1
    )
    assert len(children) == 1 and children[0].wait(timeout=5) == 23
    failed = store.load()
    assert failed.status == "failed" and failed.finished_at
    assert "status 23" in failed.error and "synthetic module startup failure" in failed.error
    assert not store.active_path.exists()


def test_restart_timeout_is_terminal_without_second_launch(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    store, _ = _handoff(tmp_path)
    starts = []

    class Starting:
        def poll(self):
            return None

    def restart(*_):
        starts.append(True)
        return Starting()

    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda *_: 0,
            restart_launcher=restart,
            restart_timeout=0,
        )
        == 1
    )
    assert starts == [True]
    assert store.load().status == "failed"
    assert "readiness" in store.load().error


def test_only_launcher_readiness_receipt_completes_update(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    store, job = _handoff(tmp_path)

    class Ready:
        def poll(self):
            store.mark_succeeded(job.id)
            return None

    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda *_: 0,
            restart_launcher=lambda *_: Ready(),
        )
        == 0
    )
    assert store.load().status == "succeeded"


def test_pip_failure_reason_survives_recovery_failure(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    store, _ = _handoff(tmp_path)

    def broken(*_):
        raise OSError("recovery spawn failed")

    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda *_: 7,
            restart_launcher=broken,
        )
        == 1
    )
    assert store.load().error == "pip exited with status 7"


def test_legacy_cli_is_blocked_before_pip_and_manual_hint_orders_uninstall_first(
    monkeypatch, tmp_path
):
    _metadata(monkeypatch, ["deeptutor-cli"])
    store, _ = _handoff(tmp_path)
    monkeypatch.setattr(app_update.importlib.metadata, "version", lambda _: "1.6.15")
    commands = []
    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda command, *_: commands.append(command) or 0,
            restart_launcher=lambda *_: None,
        )
        == 1
    )
    assert commands == []
    assert "legacy deeptutor-cli" in store.load().error
    assert (
        app_update.manual_update_command().splitlines()[0]
        == "python -m pip uninstall deeptutor-cli"
    )


def test_restart_spawn_failure_is_terminal(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    store, _ = _handoff(tmp_path)
    starts = []

    def broken(*_):
        starts.append(True)
        raise OSError("synthetic spawn failure")

    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda *_: 0,
            restart_launcher=broken,
        )
        == 1
    )
    assert starts == [True]
    assert store.load().error == "synthetic spawn failure"


def test_restart_cannot_fail_another_jobs_state(monkeypatch, tmp_path):
    _metadata(monkeypatch, [])
    store, _ = _handoff(tmp_path)

    def replace_owner(*_):
        raw = json.loads(store.state_path.read_text(encoding="utf-8"))
        raw["id"] = "other-job"
        store.state_path.write_text(json.dumps(raw), encoding="utf-8")

        class Starting:
            def poll(self):
                return None

        return Starting()

    assert (
        run_update_worker(
            store_root=store.root,
            parent_pid=123,
            wait_for_parent=lambda _: None,
            command_runner=lambda *_: 0,
            restart_launcher=replace_owner,
        )
        == 1
    )
    assert store.load().id == "other-job"
    assert store.load().status == "restarting"
