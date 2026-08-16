from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


def _load_update_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "update.py"
    module_name = "update_script_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )


def _git(cwd: Path, *args: str) -> str:
    return _run(["git", *args], cwd).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def _configure_user(repo: Path) -> None:
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "DeepTutor Tests")


def _create_checkout(tmp_path: Path, branch: str = "main") -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"

    _run(["git", "init", "--bare", str(remote)], tmp_path)
    _run(["git", "init", "-b", branch, str(seed)], tmp_path)
    _configure_user(seed)
    _write(seed / "app.txt", "v1\n")
    _commit(seed, "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", branch)

    _run(["git", "clone", "--branch", branch, str(remote), str(checkout)], tmp_path)
    _configure_user(checkout)
    return seed, checkout


def _push_remote_commit(seed: Path, branch: str, text: str = "v2\n") -> None:
    _write(seed / "app.txt", text)
    _commit(seed, "remote update")
    _git(seed, "push", "origin", branch)


def test_update_fast_forwards_the_current_non_main_branch(tmp_path: Path) -> None:
    update = _load_update_module()
    seed, checkout = _create_checkout(tmp_path, branch="dev")
    _push_remote_commit(seed, "dev")

    exit_code = update.main(["--repo", str(checkout), "--yes"])

    assert exit_code == 0
    assert _git(checkout, "branch", "--show-current") == "dev"
    assert (checkout / "app.txt").read_text(encoding="utf-8") == "v2\n"
    assert _git(checkout, "rev-parse", "HEAD") == _git(checkout, "rev-parse", "origin/dev")


def test_update_refuses_tracked_local_changes(tmp_path: Path) -> None:
    update = _load_update_module()
    seed, checkout = _create_checkout(tmp_path)
    _push_remote_commit(seed, "main")
    _write(checkout / "app.txt", "local edit\n")

    exit_code = update.main(["--repo", str(checkout), "--yes"])

    assert exit_code == 1
    assert (checkout / "app.txt").read_text(encoding="utf-8") == "local edit\n"
    assert _git(checkout, "rev-parse", "HEAD") != _git(checkout, "rev-parse", "origin/main")


def test_update_refuses_diverged_branches(tmp_path: Path) -> None:
    update = _load_update_module()
    seed, checkout = _create_checkout(tmp_path)
    _push_remote_commit(seed, "main")
    _write(checkout / "app.txt", "local commit\n")
    _commit(checkout, "local update")

    exit_code = update.main(["--repo", str(checkout), "--yes"])

    assert exit_code == 1
    assert (checkout / "app.txt").read_text(encoding="utf-8") == "local commit\n"
    assert _git(checkout, "rev-parse", "HEAD") != _git(checkout, "rev-parse", "origin/main")


def test_dependency_hints_cover_backend_and_frontend_manifests() -> None:
    update = _load_update_module()

    hints = update.dependency_hints(
        ["pyproject.toml", "requirements/server.txt", "frontend/package-lock.json"]
    )

    assert len(hints) == 2
    assert "Backend dependencies changed" in hints[0]
    assert "Frontend dependencies changed" in hints[1]
