"""Regression tests for the ways a rollback can destroy the good copy.

``_install_blocking`` moves the working environment to ``<env>.old`` before
building. These tests pin that when a rebuild goes wrong — or a previous one
never finished — the install must report failure without losing the backup,
the working environment, or the recorded state.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil

import pytest

import deeptutor.services.cli_apps.installer as installer
from deeptutor.services.cli_apps.installer import InstallOutcome, install_app
from deeptutor.services.cli_apps.models import AppRuntime
from deeptutor.services.cli_apps.paths import runtime_dir
from deeptutor.services.cli_apps.state import load_installed
from tests.services.cli_apps.test_installer import _entry, _Recorder

ORIGINAL = "#!/bin/sh\necho original\n"
PARTIAL = "#!/bin/sh\necho partial\n"


def test_a_rollback_that_cannot_clear_the_partial_env_still_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry()
    venv = runtime_dir("demo", AppRuntime.PYTHON)
    backup = venv.with_name(f"{venv.name}.old")
    executable = venv / "bin" / "cli-anything-demo"

    monkeypatch.setattr(installer, "_run", _Recorder())
    assert asyncio.run(install_app(entry)).ok
    executable.write_text(ORIGINAL, encoding="utf-8")
    old_state = load_installed()

    def partial_then_fail(argv: list[str], *, env: dict[str, str]) -> tuple[int, str]:
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text(PARTIAL, encoding="utf-8")
        return 1, "boom"

    real_rmtree = shutil.rmtree

    def refusing_rmtree(path: str | Path, *, ignore_errors: bool = False) -> None:
        if Path(path) == venv:
            if ignore_errors:
                return
            raise PermissionError(13, "simulated locked environment", str(path))
        real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(installer, "_run", partial_then_fail)
    monkeypatch.setattr("deeptutor.services.cli_apps.installer.shutil.rmtree", refusing_rmtree)

    outcome = asyncio.run(install_app(entry))

    assert isinstance(outcome, InstallOutcome)
    assert not outcome.ok
    assert outcome.code == "cli.install_failed"
    assert "for recovery" in outcome.message
    assert load_installed() == old_state
    assert (backup / "bin" / "cli-anything-demo").read_text(encoding="utf-8") == ORIGINAL
    assert executable.read_text(encoding="utf-8") == PARTIAL


def test_a_blocked_restore_reports_both_failures_and_keeps_the_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry()
    venv = runtime_dir("demo", AppRuntime.PYTHON)
    backup = venv.with_name(f"{venv.name}.old")
    executable = venv / "bin" / "cli-anything-demo"

    monkeypatch.setattr(installer, "_run", _Recorder())
    assert asyncio.run(install_app(entry)).ok
    executable.write_text(ORIGINAL, encoding="utf-8")
    old_state = load_installed()

    def partial_then_fail(argv: list[str], *, env: dict[str, str]) -> tuple[int, str]:
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text(PARTIAL, encoding="utf-8")
        return 1, "boom"

    real_replace = os.replace

    def refusing_replace(src: str | Path, dst: str | Path) -> None:
        if Path(src) == backup and Path(dst) == venv:
            raise PermissionError("simulated restore blocked")
        real_replace(src, dst)

    monkeypatch.setattr(installer, "_run", partial_then_fail)
    monkeypatch.setattr(installer.os, "replace", refusing_replace)

    outcome = asyncio.run(install_app(entry))

    assert isinstance(outcome, InstallOutcome)
    assert not outcome.ok
    assert outcome.code == "cli.install_failed"
    assert "exited 1" in outcome.message
    assert "simulated restore blocked" in outcome.message
    assert "for recovery" in outcome.message
    assert load_installed() == old_state
    assert (backup / "bin" / "cli-anything-demo").read_text(encoding="utf-8") == ORIGINAL
    assert not venv.exists()


def test_a_stale_backup_with_a_partial_env_is_refused_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry()
    venv = runtime_dir("demo", AppRuntime.PYTHON)
    backup = venv.with_name(f"{venv.name}.old")
    executable = venv / "bin" / "cli-anything-demo"

    monkeypatch.setattr(installer, "_run", _Recorder())
    assert asyncio.run(install_app(entry)).ok
    executable.write_text(ORIGINAL, encoding="utf-8")
    venv.rename(backup)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(PARTIAL, encoding="utf-8")
    state = load_installed()

    run = _Recorder()
    monkeypatch.setattr(installer, "_run", run)

    outcome = asyncio.run(install_app(entry))

    assert isinstance(outcome, InstallOutcome)
    assert not outcome.ok
    assert run.calls == []
    assert (backup / "bin" / "cli-anything-demo").read_text(encoding="utf-8") == ORIGINAL
    assert executable.read_text(encoding="utf-8") == PARTIAL
    assert load_installed() == state


def test_a_stale_backup_without_a_current_env_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal cannot depend on whether a partial env also exists: with
    only the backup left, an install would still be building on a guess."""
    entry = _entry()
    venv = runtime_dir("demo", AppRuntime.PYTHON)
    backup = venv.with_name(f"{venv.name}.old")

    monkeypatch.setattr(installer, "_run", _Recorder())
    assert asyncio.run(install_app(entry)).ok
    (venv / "bin" / "cli-anything-demo").write_text(ORIGINAL, encoding="utf-8")
    venv.rename(backup)
    state = load_installed()

    run = _Recorder()
    monkeypatch.setattr(installer, "_run", run)

    outcome = asyncio.run(install_app(entry))

    assert isinstance(outcome, InstallOutcome)
    assert not outcome.ok
    assert outcome.code == "cli.install_failed"
    assert run.calls == []
    assert not venv.exists()
    assert (backup / "bin" / "cli-anything-demo").read_text(encoding="utf-8") == ORIGINAL
    assert load_installed() == state


def test_a_move_aside_that_fails_leaves_the_working_install_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry()
    venv = runtime_dir("demo", AppRuntime.PYTHON)
    backup = venv.with_name(f"{venv.name}.old")
    executable = venv / "bin" / "cli-anything-demo"

    monkeypatch.setattr(installer, "_run", _Recorder())
    assert asyncio.run(install_app(entry)).ok
    executable.write_text(ORIGINAL, encoding="utf-8")
    state = load_installed()

    real_replace = os.replace

    def refusing_replace(src: str | Path, dst: str | Path) -> None:
        if Path(src) == venv and Path(dst) == backup:
            raise PermissionError(13, "simulated locked environment", str(src))
        real_replace(src, dst)

    monkeypatch.setattr(installer.os, "replace", refusing_replace)

    run = _Recorder()
    monkeypatch.setattr(installer, "_run", run)

    outcome = asyncio.run(install_app(entry))

    assert isinstance(outcome, InstallOutcome)
    assert not outcome.ok
    assert outcome.code == "cli.install_failed"
    assert run.calls == []
    assert executable.read_text(encoding="utf-8") == ORIGINAL
    assert not backup.exists()
    assert load_installed() == state
