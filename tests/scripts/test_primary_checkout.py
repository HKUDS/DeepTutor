from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


def _load_primary_checkout_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_primary_checkout.py"
    module_name = "primary_checkout_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _temporary_repository(path: Path) -> None:
    path.mkdir()
    _git(["init", "-b", "main"], path)
    _git(["config", "user.name", "Tester"], path)
    _git(["config", "user.email", "tester@example.com"], path)
    marker = path / "marker.txt"
    marker.write_text("initial\n", encoding="utf-8")
    _git(["add", "marker.txt"], path)
    _git(["commit", "-m", "initial"], path)


def test_rejects_dirty_primary_checkout_without_flooding_output(tmp_path: Path, capsys) -> None:
    module = _load_primary_checkout_module()
    repository = tmp_path / "primary"
    _temporary_repository(repository)
    for index in range(35):
        (repository / f"generated-{index}.txt").write_text("wip\n", encoding="utf-8")

    script = Path(__file__).resolve().parents[2] / "scripts" / "check_primary_checkout.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Primary checkout is dirty (35 entries)" in completed.stderr
    assert "generated-29.txt" in completed.stderr
    assert "?? generated-9.txt" not in completed.stderr
    assert "5 additional entries omitted" in completed.stderr
    assert module.MAX_DIRTY_DETAILS == 30


def test_rejects_task_branch_in_primary_and_allows_linked_worktree(
    tmp_path: Path,
) -> None:
    _load_primary_checkout_module()
    repository = tmp_path / "primary"
    _temporary_repository(repository)
    worktree = tmp_path / "task"
    _git(["worktree", "add", "-b", "codex/fix/example", str(worktree)], repository)
    _git(["switch", "-c", "codex/fix/forbidden"], repository)

    script = Path(__file__).resolve().parents[2] / "scripts" / "check_primary_checkout.py"
    primary = subprocess.run(
        [sys.executable, str(script)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    linked = subprocess.run(
        [sys.executable, str(script)],
        cwd=worktree,
        check=False,
        capture_output=True,
        text=True,
    )

    assert primary.returncode != 0
    assert "Primary checkout is on task branch" in primary.stderr
    assert linked.returncode == 0
