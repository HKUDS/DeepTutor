from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from deeptutor.update import Installation, InstallMode
from deeptutor.update.source import (
    CommandResult,
    SourceUpdateError,
    SourceUpdater,
)


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _source_checkout(tmp_path: Path, *, lock_changed: bool = True) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "--initial-branch=main", str(seed))
    _git(seed, "config", "user.email", "tests@example.com")
    _git(seed, "config", "user.name", "DeepTutor Tests")
    (seed / "deeptutor").mkdir()
    (seed / "deeptutor" / "__init__.py").write_text("", encoding="utf-8")
    (seed / "pyproject.toml").write_text("[project]\nname='deeptutor'\n", encoding="utf-8")
    cli_project = seed / "packaging" / "deeptutor-cli"
    cli_project.mkdir(parents=True)
    (cli_project / "pyproject.toml").write_text(
        "[project]\nname='deeptutor-cli'\n",
        encoding="utf-8",
    )
    (seed / "web").mkdir()
    (seed / "web" / "package-lock.json").write_text("base\n", encoding="utf-8")
    (seed / "release.txt").write_text("base\n", encoding="utf-8")
    _commit(seed, "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", str(remote), str(checkout))

    (seed / "release.txt").write_text("stable\n", encoding="utf-8")
    if lock_changed:
        (seed / "web" / "package-lock.json").write_text("stable\n", encoding="utf-8")
    target = _commit(seed, "stable release")
    _git(seed, "tag", "v1.6.0")
    _git(seed, "push", "origin", "main", "v1.6.0")
    return checkout, target


class _Runner:
    def __init__(self, *, fail_fast_forward: bool = False) -> None:
        self.commands: list[tuple[list[str], Path]] = []
        self.fail_fast_forward = fail_fast_forward

    def run(self, command: list[str], *, cwd: Path) -> CommandResult:
        self.commands.append((command, cwd))
        if command[:2] == ["git", "pull"] and self.fail_fast_forward:
            return CommandResult(1, stderr="simulated fast-forward failure")
        if command[0] != "git":
            return CommandResult(0)
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _installation(checkout: Path, mode: InstallMode) -> Installation:
    return Installation(
        mode=mode,
        current_version="1.5.4",
        package_name="deeptutor" if mode is InstallMode.SOURCE_WEB else "deeptutor-cli",
        source_root=checkout,
        detail="editable source installation",
    )


def test_full_source_update_fast_forwards_and_refreshes_changed_dependencies(
    tmp_path: Path,
) -> None:
    checkout, target = _source_checkout(tmp_path)
    runner = _Runner()

    result = SourceUpdater(
        runner=runner,
        python_executable="python-under-test",
        bun_executable="bun",
    ).update(_installation(checkout, InstallMode.SOURCE_WEB), "1.6.0")

    assert _git(checkout, "rev-parse", "HEAD") == target
    assert result.frontend_dependencies_refreshed is True
    assert (
        [
            "python-under-test",
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--editable",
            str(checkout.resolve()),
        ],
        checkout.resolve(),
    ) in runner.commands
    assert (["bun", "install", "--no-save"], checkout.resolve() / "web") in runner.commands
    git_verbs = {command[1] for command, _cwd in runner.commands if command[0] == "git"}
    assert git_verbs.isdisjoint({"stash", "reset", "rebase", "merge"})


def test_cli_source_update_refreshes_only_the_existing_cli_editable(
    tmp_path: Path,
) -> None:
    checkout, target = _source_checkout(tmp_path)
    runner = _Runner()

    result = SourceUpdater(
        runner=runner,
        python_executable="python-under-test",
        bun_executable="bun",
    ).update(_installation(checkout, InstallMode.SOURCE_CLI), "1.6.0")

    assert _git(checkout, "rev-parse", "HEAD") == target
    assert result.frontend_dependencies_refreshed is False
    editable = checkout.resolve() / "packaging" / "deeptutor-cli"
    assert (
        [
            "python-under-test",
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--editable",
            str(editable),
        ],
        editable,
    ) in runner.commands
    assert not any(command[0][0] == "bun" for command in runner.commands)


def test_source_update_rejects_a_dirty_worktree(tmp_path: Path) -> None:
    checkout, _ = _source_checkout(tmp_path)
    original = _git(checkout, "rev-parse", "HEAD")
    (checkout / "untracked.txt").write_text("local work\n", encoding="utf-8")

    with pytest.raises(SourceUpdateError, match="working tree is not clean"):
        SourceUpdater(runner=_Runner()).update(
            _installation(checkout, InstallMode.SOURCE_WEB),
            "1.6.0",
        )

    assert _git(checkout, "rev-parse", "HEAD") == original


def test_source_update_rejects_detached_head(tmp_path: Path) -> None:
    checkout, _ = _source_checkout(tmp_path)
    _git(checkout, "checkout", "--detach")

    with pytest.raises(SourceUpdateError, match="detached HEAD"):
        SourceUpdater(runner=_Runner()).update(
            _installation(checkout, InstallMode.SOURCE_WEB),
            "1.6.0",
        )


def test_source_update_rejects_a_branch_without_configured_upstream(
    tmp_path: Path,
) -> None:
    checkout, _ = _source_checkout(tmp_path)
    original = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "branch", "--unset-upstream")

    with pytest.raises(SourceUpdateError, match="configured upstream branch"):
        SourceUpdater(runner=_Runner()).update(
            _installation(checkout, InstallMode.SOURCE_WEB),
            "1.6.0",
        )

    assert _git(checkout, "rev-parse", "HEAD") == original


def test_source_update_rejects_a_diverged_branch(tmp_path: Path) -> None:
    checkout, _ = _source_checkout(tmp_path)
    _git(checkout, "config", "user.email", "tests@example.com")
    _git(checkout, "config", "user.name", "DeepTutor Tests")
    (checkout / "local.txt").write_text("local\n", encoding="utf-8")
    original = _commit(checkout, "local work")

    with pytest.raises(SourceUpdateError, match="branch has diverged"):
        SourceUpdater(runner=_Runner()).update(
            _installation(checkout, InstallMode.SOURCE_WEB),
            "1.6.0",
        )

    assert _git(checkout, "rev-parse", "HEAD") == original


def test_source_update_rejects_a_non_fast_forward_release_tag(tmp_path: Path) -> None:
    checkout, _ = _source_checkout(tmp_path)
    _git(checkout, "config", "user.email", "tests@example.com")
    _git(checkout, "config", "user.name", "DeepTutor Tests")
    _git(checkout, "pull", "--ff-only")
    (checkout / "local.txt").write_text("published branch work\n", encoding="utf-8")
    original = _commit(checkout, "branch advanced beyond release")
    _git(checkout, "push", "origin", "main")

    with pytest.raises(SourceUpdateError, match="cannot be fast-forwarded"):
        SourceUpdater(runner=_Runner()).update(
            _installation(checkout, InstallMode.SOURCE_WEB),
            "1.6.0",
        )

    assert _git(checkout, "rev-parse", "HEAD") == original


def test_failed_fast_forward_leaves_the_checkout_unchanged(tmp_path: Path) -> None:
    checkout, _ = _source_checkout(tmp_path, lock_changed=False)
    original = _git(checkout, "rev-parse", "HEAD")
    runner = _Runner(fail_fast_forward=True)

    with pytest.raises(SourceUpdateError, match="simulated fast-forward failure"):
        SourceUpdater(runner=runner).update(
            _installation(checkout, InstallMode.SOURCE_WEB),
            "1.6.0",
        )

    assert _git(checkout, "rev-parse", "HEAD") == original
    assert not any("install" in command for command, _cwd in runner.commands)
