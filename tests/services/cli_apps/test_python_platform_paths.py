"""How the CLI app tree follows the host OS — and where it deliberately does not.

A venv's executables live where the interpreter that built it puts them:
``Scripts`` with ``.exe`` console scripts on Windows, ``bin`` with
extension-less scripts elsewhere. A node prefix is the deployment's own
layout, so it keeps ``node/bin`` on every host. These tests pin that matrix
with a module-local OS proxy — the global ``os.name`` is never swapped,
because every other module in the process reads it too.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath, PureWindowsPath
import sys
from types import SimpleNamespace

import pytest

from deeptutor.services.cli_apps.installer import _steps
from deeptutor.services.cli_apps.models import (
    AppRuntime,
    AppTrust,
    CliAppEntry,
    InstallKind,
    InstallPlan,
)
from deeptutor.services.cli_apps.paths import bin_dir, executable_path

_TARGET = "some-package"

_ROOT = {
    "nt": PureWindowsPath("C:/dt/cli-apps"),
    "posix": PurePosixPath("/dt/cli-apps"),
}
#: Where a venv keeps its executables, per host.
_VENV_BIN = {"nt": "Scripts", "posix": "bin"}
#: The interpreter an installed venv is driven through, per host.
_VENV_PYTHON = {"nt": "python.exe", "posix": "python"}
#: What a console script's file name ends in, per host.
_SUFFIX = {"nt": ".exe", "posix": ""}


@pytest.fixture(params=("nt", "posix"))
def host(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run ``paths`` as if the process sat on one host OS at a time.

    The proxy replaces only what ``paths`` itself reads; the real ``os``
    module — and every other module importing it — keeps seeing the true
    platform.
    """
    from deeptutor.services.cli_apps import paths

    name = request.param
    monkeypatch.setattr(paths, "os", SimpleNamespace(name=name, chmod=os.chmod))
    monkeypatch.setattr(paths, "cli_apps_root", lambda: _ROOT[name])
    return name


def _python_entry() -> CliAppEntry:
    return CliAppEntry(
        id="demo",
        display_name="Demo",
        description="A demo app",
        category="utility",
        origin="harness",
        entry_point="demo",
        install=InstallPlan(
            kind=InstallKind.PIP,
            runtime=AppRuntime.PYTHON,
            trust=AppTrust.THIRD_PARTY,
            target=_TARGET,
        ),
    )


# ── the python layout ─────────────────────────────────────────────────────


def test_a_venvs_bin_directory_follows_the_host(host: str) -> None:
    assert bin_dir("demo", AppRuntime.PYTHON) == (
        _ROOT[host] / "apps" / "demo" / "venv" / _VENV_BIN[host]
    )


def test_a_python_entry_point_gains_an_exe_only_on_windows(host: str) -> None:
    assert executable_path("demo", AppRuntime.PYTHON, "demo") == (
        _ROOT[host] / "apps" / "demo" / "venv" / _VENV_BIN[host] / f"demo{_SUFFIX[host]}"
    )


# ── the node layout ───────────────────────────────────────────────────────


def test_a_node_app_keeps_the_same_bin_layout_on_every_host(host: str) -> None:
    """The prefix is the deployment's own layout, not the interpreter's."""
    assert executable_path("demo", AppRuntime.NODE, "demo") == (
        _ROOT[host] / "apps" / "demo" / "node" / "bin" / "demo"
    )


# ── entry-point validation ────────────────────────────────────────────────


@pytest.mark.parametrize("entry_point", ["../bad", "a/b", "a\\b", "", "."])
def test_an_unsafe_entry_point_is_refused_before_any_suffix(host: str, entry_point: str) -> None:
    """``a\\b`` must not survive on nt by growing into ``Scripts\\a\\b.exe``."""
    with pytest.raises(ValueError, match="entry point"):
        executable_path("demo", AppRuntime.PYTHON, entry_point)


# ── the install argv ──────────────────────────────────────────────────────


def test_pip_is_driven_through_the_venvs_own_python_for_the_host(host: str) -> None:
    """``_steps`` only assembles argv — calling it runs nothing."""
    env_dir = _ROOT[host] / "apps" / "demo" / "venv"
    steps = _steps(_python_entry(), env_dir)

    create, _ = steps[0]
    assert create == [sys.executable, "-m", "venv", str(env_dir)]

    pip, _ = steps[1]
    assert pip[0] == str(env_dir / _VENV_BIN[host] / _VENV_PYTHON[host])
    assert pip[1:3] == ["-m", "pip"]
    assert pip[-1] == _TARGET
