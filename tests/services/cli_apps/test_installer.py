"""Installing: the one action in this feature that runs code outside the sandbox.

Every step's argv is asserted, because the point of the parser is that we build
these commands rather than executing a catalog field. The subprocess itself is
stubbed — a test that really ran ``pip install git+…`` would be a network test
with a several-minute worst case.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.cli_apps import get_entry
from deeptutor.services.cli_apps.installer import install_app, uninstall_app
from deeptutor.services.cli_apps.models import (
    AppRuntime,
    AppTrust,
    CliAppEntry,
    InstallKind,
    InstallPlan,
)
from deeptutor.services.cli_apps.paths import (
    abi_stamp,
    app_dir,
    bin_dir,
    install_log_path,
    runtime_dir,
)
from deeptutor.services.cli_apps.state import load_installed


def _entry(
    *,
    app_id: str = "demo",
    kind: InstallKind = InstallKind.PINNED_HARNESS,
    runtime: AppRuntime = AppRuntime.PYTHON,
    target: str = "git+https://example.invalid/x.git@abc#subdirectory=demo/agent-harness",
    reason: str = "",
) -> CliAppEntry:
    return CliAppEntry(
        id=app_id,
        display_name="Demo",
        description="A demo app",
        category="utility",
        origin="harness",
        entry_point="cli-anything-demo" if kind is not InstallKind.UNSUPPORTED else "",
        install=InstallPlan(
            kind=kind,
            runtime=runtime,
            trust=AppTrust.FIRST_PARTY,
            target=target,
            reason=reason,
        ),
    )


class _Recorder:
    """Stands in for the subprocess, and creates what a real install would."""

    def __init__(self, *, fail_at: int | None = None, make_executable: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self._fail_at = fail_at
        self._make_executable = make_executable

    def __call__(self, argv: list[str], *, env: dict[str, str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        self.envs.append(dict(env))
        index = len(self.calls) - 1
        if self._fail_at == index:
            return 1, "boom"
        if self._make_executable and ("pip" in argv or "npm" in argv[0]):
            self._create_entry_point(argv)
        return 0, "ok"

    @staticmethod
    def _create_entry_point(argv: list[str]) -> None:
        for token in argv:
            path = Path(token)
            if path.name in {"venv", "node"}:
                (path / "bin").mkdir(parents=True, exist_ok=True)
                (path / "bin" / "cli-anything-demo").write_text("#!/bin/sh\n", encoding="utf-8")
                return
        # `pip install` addresses the venv through its own python.
        for token in argv:
            if token.endswith("/bin/python"):
                Path(token).parent.mkdir(parents=True, exist_ok=True)
                (Path(token).parent / "cli-anything-demo").write_text(
                    "#!/bin/sh\n", encoding="utf-8"
                )
                return


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr("deeptutor.services.cli_apps.installer._run", recorder)
    return recorder


# ── what actually gets executed ───────────────────────────────────────────


def test_a_python_app_gets_its_own_venv_and_the_pinned_requirement(run: _Recorder) -> None:
    entry = _entry()
    outcome = asyncio.run(install_app(entry))

    assert outcome.ok, outcome.message
    venv = runtime_dir("demo", AppRuntime.PYTHON)
    assert run.calls[0][1:] == ["-m", "venv", str(venv)]
    # Installed with the venv's own python, so no global pip is involved.
    assert run.calls[1][0] == str(venv / "bin" / "python")
    assert run.calls[1][-1] == entry.install.target


def test_an_npm_app_is_prefixed_into_its_own_directory(run: _Recorder) -> None:
    outcome = asyncio.run(
        install_app(_entry(kind=InstallKind.NPM, runtime=AppRuntime.NODE, target="@sentry/cli"))
    )

    assert outcome.ok, outcome.message
    argv = run.calls[0]
    assert argv[:3] == ["npm", "install", "-g"]
    assert argv[3:5] == ["--prefix", str(runtime_dir("demo", AppRuntime.NODE))]
    assert argv[-1] == "@sentry/cli"


def test_npm_install_scripts_are_refused(run: _Recorder) -> None:
    """A postinstall hook is arbitrary code shipped alongside — but not described
    by — the package being installed."""
    asyncio.run(install_app(_entry(kind=InstallKind.NPM, runtime=AppRuntime.NODE, target="thing")))
    assert run.envs[0]["npm_config_ignore_scripts"] == "1"


def test_an_install_step_never_sees_the_applications_environment(
    run: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third-party ``setup.py`` runs here. It must not be handed the deployment's
    provider API keys."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")

    asyncio.run(install_app(_entry()))

    for env in run.envs:
        assert "OPENAI_API_KEY" not in env
        # Proxy settings are deployment infrastructure: without them an install
        # behind a corporate proxy cannot reach the index at all.
        assert env["HTTPS_PROXY"] == "http://proxy.internal:3128"


# ── refusals and failures ─────────────────────────────────────────────────


def test_an_unsupported_entry_is_refused_before_anything_runs(run: _Recorder) -> None:
    outcome = asyncio.run(
        install_app(_entry(kind=InstallKind.UNSUPPORTED, reason="installs with brew"))
    )

    assert not outcome.ok
    assert outcome.code == "cli.not_installable"
    assert "brew" in outcome.message
    assert run.calls == []


def test_a_failed_install_records_nothing_and_leaves_no_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder(fail_at=1)
    monkeypatch.setattr("deeptutor.services.cli_apps.installer._run", recorder)

    outcome = asyncio.run(install_app(_entry()))

    assert not outcome.ok
    assert outcome.code == "cli.install_failed"
    assert load_installed() == {}
    assert not runtime_dir("demo", AppRuntime.PYTHON).exists()


def test_an_install_that_produces_no_entry_point_is_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pip exiting 0 does not mean the command we promised the model exists."""
    monkeypatch.setattr(
        "deeptutor.services.cli_apps.installer._run", _Recorder(make_executable=False)
    )

    outcome = asyncio.run(install_app(_entry()))

    assert not outcome.ok
    assert "not in the app's bin directory" in outcome.message
    assert load_installed() == {}


def test_a_failed_update_puts_the_working_install_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venv's console scripts hard-code their own absolute path, so the rollback
    has to restore *that* path — promoting a staging directory would leave every
    shebang pointing at a directory that no longer exists."""
    monkeypatch.setattr("deeptutor.services.cli_apps.installer._run", _Recorder())
    assert asyncio.run(install_app(_entry())).ok
    executable = bin_dir("demo", AppRuntime.PYTHON) / "cli-anything-demo"
    executable.write_text("#!/bin/sh\necho original\n", encoding="utf-8")

    monkeypatch.setattr("deeptutor.services.cli_apps.installer._run", _Recorder(fail_at=1))
    outcome = asyncio.run(install_app(_entry()))

    assert not outcome.ok
    assert executable.exists()
    assert "echo original" in executable.read_text(encoding="utf-8")
    assert "demo" in load_installed(), "the app it could still run was still installed"


def test_no_backup_directory_survives_a_successful_install(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.services.cli_apps.installer._run", _Recorder())
    asyncio.run(install_app(_entry()))
    asyncio.run(install_app(_entry()))

    assert not list(app_dir("demo").glob("*.old"))


# ── recorded state ────────────────────────────────────────────────────────


def test_a_successful_install_records_what_it_can_be_checked_against(run: _Recorder) -> None:
    asyncio.run(install_app(_entry()))

    app = load_installed()["demo"]
    assert app.entry_point == "cli-anything-demo"
    assert app.runtime is AppRuntime.PYTHON
    assert app.abi == abi_stamp(), "so a base-image bump is a clear refusal, not an ENOENT"
    assert app.installed_at
    assert app.pin, "a first-party install records the commit it came from"


def test_a_floating_third_party_install_records_no_pin(run: _Recorder) -> None:
    asyncio.run(install_app(_entry(kind=InstallKind.PIP, target="some-package")))
    assert load_installed()["demo"].pin == ""


def test_the_install_log_is_kept_and_returned(run: _Recorder) -> None:
    outcome = asyncio.run(install_app(_entry()))

    assert "venv" in outcome.log
    assert install_log_path("demo").exists()


def test_a_failed_installs_log_travels_with_the_refusal(monkeypatch) -> None:
    """It is the only actionable thing about a failed install."""
    monkeypatch.setattr("deeptutor.services.cli_apps.installer._run", _Recorder(fail_at=1))
    outcome = asyncio.run(install_app(_entry()))

    assert "boom" in outcome.log
    assert "FAILED" in outcome.log


# ── removal ───────────────────────────────────────────────────────────────


def test_uninstall_removes_the_environment_and_the_record(run: _Recorder) -> None:
    asyncio.run(install_app(_entry()))

    asyncio.run(uninstall_app("demo"))

    assert load_installed() == {}
    assert not app_dir("demo").exists()


def test_uninstalling_something_never_installed_is_not_an_error() -> None:
    outcome = asyncio.run(uninstall_app("never-there"))
    assert outcome.ok


def test_a_real_catalog_entry_installs_through_the_same_path(run: _Recorder) -> None:
    """Guards the seam between the catalog and the installer, which the synthetic
    entries above would not catch on their own."""
    entry = get_entry("jumpserver")
    assert entry is not None and entry.install.kind is InstallKind.PINNED_HARNESS

    asyncio.run(install_app(entry))

    assert run.calls[0][1:3] == ["-m", "venv"]
    assert run.calls[1][-1] == entry.install.target
    assert "@" in run.calls[1][-1].partition("#")[0], "the pin has to reach pip"
