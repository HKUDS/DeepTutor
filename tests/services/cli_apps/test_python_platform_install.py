"""Platform-dependent venv layout (Windows vs POSIX) for pip installs.

The subprocess is fully faked: the venv "command" creates a plain interpreter
file, the pip "command" must address that exact interpreter and writes the
console script the layout demands. Only ``paths.os`` is patched — ``name``
drives the layout, ``chmod`` stays real. Expected paths are built by hand so
a bug in a production layout helper cannot hide behind this test.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.services.cli_apps import installer
from deeptutor.services.cli_apps import paths as cli_paths
from deeptutor.services.cli_apps import runner as cli_runner
from deeptutor.services.cli_apps.models import CliAppEntry, InstallKind
from deeptutor.services.cli_apps.state import load_installed
from deeptutor.services.sandbox.spec import ExecResult, Mount
from tests.services.cli_apps.test_installer import _entry

_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


class _FakeRunner:
    """Stands in for ``installer._run``; no command is ever executed."""

    def __init__(self, interpreter: Path, console: Path) -> None:
        self.interpreter = interpreter
        self.console = console
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.pip_code = 0
        self.pip_console: bytes | None = b"#!/bin/sh\n"

    def __call__(self, argv: list[str], *, env: dict[str, str]) -> tuple[int, str]:
        self.calls.append((list(argv), dict(env)))
        if "venv" in argv:
            self.interpreter.parent.mkdir(parents=True, exist_ok=True)
            self.interpreter.write_text("", encoding="utf-8")
            return 0, "ok"
        assert argv[0] == str(self.interpreter), argv
        if "pip" in argv:
            if self.pip_console is not None:
                self.console.parent.mkdir(parents=True, exist_ok=True)
                self.console.write_bytes(self.pip_console)
            return self.pip_code, "boom" if self.pip_code else "ok"
        raise AssertionError(f"unexpected command handed to the fake runner: {argv}")


def _layout(
    name: str, cli_app_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    monkeypatch.setattr(cli_paths, "os", SimpleNamespace(name=name, chmod=os.chmod))
    envdir = Path(cli_app_roots) / "cli-apps" / "apps" / "demo" / "venv"
    if name == "nt":
        return (
            envdir,
            envdir / "Scripts" / "python.exe",
            envdir / "Scripts" / "cli-anything-demo.exe",
        )
    return envdir, envdir / "bin" / "python", envdir / "bin" / "cli-anything-demo"


def _pip_entry() -> CliAppEntry:
    return _entry(kind=InstallKind.PIP, target="demo-package")


@pytest.mark.parametrize("name", ["nt", "posix"])
def test_successful_install_records_state_for_the_platform_layout(
    name: str, cli_app_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _envdir, interpreter, console = _layout(name, cli_app_roots, monkeypatch)
    runner = _FakeRunner(interpreter, console)
    monkeypatch.setattr(installer, "_run", runner)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret-value")

    outcome = asyncio.run(installer.install_app(_pip_entry()))

    assert outcome.ok
    assert console.read_bytes() == b"#!/bin/sh\n"
    assert "demo" in load_installed()
    for _argv, env in runner.calls:
        assert not [key for key in env if any(m in key for m in _SECRET_MARKERS)]
        assert "OPENAI_API_KEY" not in env
        assert "fixture-secret-value" not in "".join(env.values())


@pytest.mark.parametrize("name", ["nt", "posix"])
def test_exit_zero_without_console_script_is_a_failed_install(
    name: str, cli_app_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _envdir, interpreter, console = _layout(name, cli_app_roots, monkeypatch)
    runner = _FakeRunner(interpreter, console)
    runner.pip_console = None
    monkeypatch.setattr(installer, "_run", runner)

    outcome = asyncio.run(installer.install_app(_pip_entry()))

    assert not outcome.ok
    assert not console.exists()
    assert not load_installed()


@pytest.mark.parametrize("name", ["nt", "posix"])
def test_failed_update_restores_the_previous_install(
    name: str, cli_app_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envdir, interpreter, console = _layout(name, cli_app_roots, monkeypatch)
    runner = _FakeRunner(interpreter, console)
    monkeypatch.setattr(installer, "_run", runner)
    entry = _pip_entry()

    first = asyncio.run(installer.install_app(entry))
    assert first.ok
    old_console = console.read_bytes()
    old_state = load_installed()
    assert "demo" in old_state

    runner.pip_code = 1
    runner.pip_console = b"partial write"
    outcome = asyncio.run(installer.install_app(entry))

    assert not outcome.ok
    assert console.read_bytes() == old_console
    assert load_installed() == old_state
    assert not (envdir.parent / "venv.old").exists()


@pytest.mark.parametrize("name", ["nt", "posix"])
def test_run_app_sends_a_literal_argv_and_no_host_secrets(
    name: str, cli_app_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envdir, interpreter, console = _layout(name, cli_app_roots, monkeypatch)
    fake_install = _FakeRunner(interpreter, console)
    monkeypatch.setattr(installer, "_run", fake_install)
    outcome = asyncio.run(installer.install_app(_pip_entry()))
    assert outcome.ok
    app = outcome.app

    fake_service = SimpleNamespace(run=AsyncMock(return_value=ExecResult(stdout="ok")))
    monkeypatch.setattr("deeptutor.services.sandbox.get_sandbox_service", lambda: fake_service)
    pathsep = ";" if name == "nt" else ":"
    host_path = "C:\\host\\bin" if name == "nt" else "/usr/host/bin"
    monkeypatch.setattr(
        cli_runner,
        "os",
        SimpleNamespace(
            environ={"PATH": host_path, "OPENAI_API_KEY": "fixture-secret-value"},
            pathsep=pathsep,
        ),
    )

    args = ["--name", "two words", "; echo no"]
    result = asyncio.run(cli_runner.run_app(app, args, user_id="u_test"))

    assert result.stdout == "ok"
    fake_service.run.assert_awaited_once()
    assert fake_service.run.await_args.kwargs == {"user_id": "u_test"}
    request = fake_service.run.await_args.args[0]
    assert request.argv == (str(console), "--name", "two words", "; echo no")
    assert request.argv[1:] == tuple(args)
    assert request.env["PATH"].split(pathsep)[0] == str(console.parent)
    assert Mount(host_path=str(envdir), sandbox_path=str(envdir)) in request.mounts
    assert "OPENAI_API_KEY" not in request.env
    assert "fixture-secret-value" not in "".join(request.env.values())
