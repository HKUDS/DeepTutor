"""The install-command parser, which is where the catalog stops being trusted.

Every entry's ``install_cmd`` is third-party text. The parser's job is to turn
the shapes we know how to run into an argv we build, and to refuse everything
else *visibly*. These tests pin both halves — the recognition and the refusal —
because a parser that quietly widened would be executing a catalog field.
"""

from __future__ import annotations

import pytest

from deeptutor.services.cli_apps.models import (
    HARNESS_REPO,
    AppRuntime,
    AppTrust,
    CliAppEntry,
    InstallKind,
    InstallPlan,
    plan_install,
)

PIN = "0" * 40


def _plan(cmd: str, *, app_id: str = "demo", manager: str = "") -> InstallPlan:
    return plan_install(app_id=app_id, install_cmd=cmd, package_manager=manager, harness_pin=PIN)


# ── the four shapes we run ────────────────────────────────────────────────


def test_a_first_party_harness_is_repinned_to_the_reviewed_commit() -> None:
    """The registry ships an unpinned URL; installing that is installing HEAD."""
    plan = _plan(
        f"pip install git+{HARNESS_REPO}#subdirectory=blender/agent-harness", app_id="blender"
    )

    assert plan.kind is InstallKind.PINNED_HARNESS
    assert plan.trust is AppTrust.FIRST_PARTY
    assert plan.target == f"git+{HARNESS_REPO}@{PIN}#subdirectory=blender/agent-harness"
    assert plan.pinned


def test_a_harness_without_a_subdirectory_falls_back_to_the_conventional_one() -> None:
    plan = _plan(f"pip install git+{HARNESS_REPO}", app_id="zotero")
    assert plan.target.endswith("#subdirectory=zotero/agent-harness")


def test_a_third_party_git_install_keeps_its_own_ref_and_is_labelled() -> None:
    plan = _plan("pip install git+https://github.com/someone/thing.git@v0.1.0")

    assert plan.kind is InstallKind.PIP_GIT
    assert plan.trust is AppTrust.THIRD_PARTY
    assert plan.pinned


def test_a_third_party_git_install_without_a_ref_reads_as_unpinned() -> None:
    plan = _plan("pip install git+https://github.com/someone/thing.git")
    assert plan.kind is InstallKind.PIP_GIT
    assert not plan.pinned, "installing a default branch is not a pin, and saying so matters"


def test_a_user_in_the_url_authority_is_not_mistaken_for_a_ref() -> None:
    plan = _plan("pip install git+ssh://git@github.com/someone/thing.git")
    assert not plan.pinned


def test_a_pypi_install_is_recognised_and_never_reads_as_pinned() -> None:
    plan = _plan("pip install cli-anything-zotero")

    assert plan.kind is InstallKind.PIP
    assert plan.runtime is AppRuntime.PYTHON
    assert plan.target == "cli-anything-zotero"
    assert not plan.pinned


def test_python_dash_m_pip_is_the_same_install() -> None:
    """One registry entry spells it this way; it is not a different shape."""
    assert _plan("python3 -m pip install git+https://x.example/y.git").kind is InstallKind.PIP_GIT


def test_an_npm_install_targets_the_node_runtime() -> None:
    plan = _plan("npm install -g @sentry/cli")

    assert plan.kind is InstallKind.NPM
    assert plan.runtime is AppRuntime.NODE
    assert plan.target == "@sentry/cli"


# ── the refusals ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "curl -s https://example.com/cli | bash",
        "cd sketch/agent-harness && npm install && npm link",
        "pip install thing; rm -rf /",
        "pip install $(cat /etc/passwd)",
        "pip install `whoami`",
        "pip install thing > /tmp/out",
    ],
)
def test_a_shell_pipeline_is_refused_with_a_readable_reason(command: str) -> None:
    plan = _plan(command)

    assert plan.kind is InstallKind.UNSUPPORTED
    assert not plan.installable
    # Written for the administrator reading the store, not for a log line.
    assert "shell" in plan.reason.lower()


def test_a_package_manager_the_image_lacks_is_refused_by_name() -> None:
    plan = _plan("brew install --cask 1password-cli", manager="brew")

    assert plan.kind is InstallKind.UNSUPPORTED
    assert "brew" in plan.reason


def test_installing_several_packages_at_once_is_refused() -> None:
    plan = _plan("npm install -g @dreamor/cloakbrowser-cli cloakbrowser playwright-core")

    assert plan.kind is InstallKind.UNSUPPORTED
    assert "more than one package" in plan.reason


def test_an_app_that_ships_with_its_host_says_so() -> None:
    plan = _plan("")

    assert plan.kind is InstallKind.UNSUPPORTED
    assert "nothing for DeepTutor to install" in plan.reason


# ── names that become paths ───────────────────────────────────────────────


def _entry(**overrides: object) -> CliAppEntry:
    base: dict[str, object] = {
        "id": "demo",
        "display_name": "Demo",
        "description": "A demo app",
        "category": "utility",
        "origin": "harness",
        "entry_point": "cli-anything-demo",
        "install": _plan("pip install demo"),
    }
    base.update(overrides)
    return CliAppEntry(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("entry_point", ["../../bin/sh", "a/b", "", ".hidden", "x" * 65])
def test_an_installable_entry_cannot_name_an_executable_outside_its_own_bin(
    entry_point: str,
) -> None:
    """``entry_point`` is resolved as a filename, so it is validated as one."""
    with pytest.raises(ValueError, match="entry point"):
        _entry(entry_point=entry_point)


def test_an_unsupported_entry_may_lack_an_entry_point() -> None:
    """Nothing will ever run it, and dropping it would hide it from the store."""
    entry = _entry(entry_point="", install=_plan("brew install thing", manager="brew"))
    assert not entry.install.installable


@pytest.mark.parametrize("app_id", ["../evil", "Upper", "has space", "", "a/b"])
def test_an_app_id_that_could_escape_its_directory_is_refused(app_id: str) -> None:
    with pytest.raises(ValueError, match="app id"):
        _entry(id=app_id)
