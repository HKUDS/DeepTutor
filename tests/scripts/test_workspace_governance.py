from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "workspace_governance.py"


def load_module():
    spec = importlib.util.spec_from_file_location("workspace_governance_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def repository(path: Path) -> Path:
    path.mkdir()
    git(["init", "-b", "main"], path)
    git(["config", "user.name", "Tester"], path)
    git(["config", "user.email", "tester@example.com"], path)
    marker = path / "README.md"
    marker.write_text("# Test\n", encoding="utf-8")
    git(["add", "README.md"], path)
    git(["commit", "-m", "initial"], path)
    return path


def test_branch_names_use_short_task_prefixes() -> None:
    module = load_module()
    assert module.normalize_branch("fix/player-clock") == "codex/fix/player-clock"
    assert module.normalize_branch("codex/feat/kids") == "codex/feat/kids"
    with pytest.raises(ValueError, match="branch must match"):
        module.normalize_branch("player-clock")


def test_create_refuses_a_dirty_primary_checkout(tmp_path: Path) -> None:
    module = load_module()
    repo = repository(tmp_path / "repo")
    (repo / "README.md").write_text("# Dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="primary checkout must be clean"):
        module.create_worktree("fix/example", repo, tmp_path / "worktrees")


def test_archive_snapshots_tracked_and_untracked_work(tmp_path: Path) -> None:
    module = load_module()
    repo = repository(tmp_path / "repo")
    worktree = tmp_path / "task"
    git(["worktree", "add", "-b", "codex/fix/example", worktree], repo)
    (worktree / "README.md").write_text("# Changed\n", encoding="utf-8")
    (worktree / "notes.txt").write_text("untracked note\n", encoding="utf-8")

    archive = module.archive_worktree(worktree, repo, tmp_path / "archives", label="example")

    assert (archive / "tracked-changes.patch").is_file()
    assert (archive / "untracked.tar.gz").is_file()
    assert module.verify_archive(archive) is True
    metadata = json.loads((archive / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["branch"] == "codex/fix/example"
    assert metadata["untracked_names"] == ["notes.txt"]

    (archive / "metadata.json").write_text("corrupted\n", encoding="utf-8")
    assert module.verify_archive(archive) is False


def test_retire_requires_clean_remotely_backed_up_worktree(tmp_path: Path) -> None:
    module = load_module()
    repo = repository(tmp_path / "repo")
    remote = tmp_path / "myfork.git"
    remote.mkdir()
    git(["init", "--bare", "-b", "main"], remote)
    git(["remote", "add", "myfork", str(remote)], repo)
    git(["push", "myfork", "main"], repo)

    worktree = tmp_path / "task"
    git(["worktree", "add", "-b", "codex/fix/example", worktree], repo)
    dirty = module.inspect_worktree(worktree, repo)
    assert dirty.retirement_ready is False
    assert "branch head is not present on myfork or origin" in dirty.blockers
    with pytest.raises(RuntimeError, match="not safe to retire"):
        module.retire_worktree(worktree, repo)

    git(["push", "myfork", "codex/fix/example"], repo)
    clean = module.inspect_worktree(worktree, repo)
    assert clean.retirement_ready is True
    module.retire_worktree(worktree, repo)
    assert worktree.exists() is False


def test_strict_audit_governs_primary_and_stashes(tmp_path: Path) -> None:
    module = load_module()
    repo = repository(tmp_path / "repo")
    states, stash_count = module.audit(repo)
    assert stash_count == 0
    assert module._strict_failure(states, stash_count) is None

    (repo / "README.md").write_text("# WIP\n", encoding="utf-8")
    dirty_states, _ = module.audit(repo)
    dirty_failure = module._strict_failure(dirty_states, 0)
    assert dirty_failure is not None
    assert "primary checkout is dirty" in dirty_failure

    git(["stash", "push", "-m", "temporary"], repo)
    dirty_states, one_stash = module.audit(repo)
    failure = module._strict_failure(dirty_states, one_stash)
    assert failure is not None
    assert "1 stash entries remain" in failure

    git(["stash", "pop"], repo)
    git(["restore", "README.md"], repo)
    clean_states, no_stashes = module.audit(repo)
    assert module._strict_failure(clean_states, no_stashes) is None
