from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


def _load_workspace_hygiene_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_workspace_hygiene.py"
    module_name = "workspace_hygiene_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> object:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_passes_when_checkout_and_tracked_hygiene_are_clean(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []
    module = _load_workspace_hygiene_module()

    def fake_run(command: list[str], **_kwargs: object) -> object:
        calls.append(command)
        if command[:2] == ["git", "status"]:
            return _completed()
        if command[1:2] == ["scripts/check_repo_hygiene.py"]:
            return _completed()
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert module.main() == 0
    assert "Repository hygiene check passed." not in capsys.readouterr().out
    assert calls[0] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]


def test_rejects_dirty_checkout_before_running_tracked_hygiene(monkeypatch, capsys) -> None:
    module = _load_workspace_hygiene_module()

    def fake_run(command: list[str], **_kwargs: object) -> object:
        if command[:2] == ["git", "status"]:
            return _completed(stdout=" M README.md\n?? scratch.py\n")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert module.main() == 1

    captured = capsys.readouterr()
    assert "Dirty checkout found" in captured.err
    assert " M README.md" in captured.err
    assert "?? scratch.py" in captured.err


def test_propagates_tracked_hygiene_failure(monkeypatch) -> None:
    module = _load_workspace_hygiene_module()

    monkeypatch.setattr(
        f"{module.__name__}.dirty_entries",
        lambda: [],
    )
    monkeypatch.setattr(
        f"{module.__name__}.tracked_hygiene",
        lambda: 2,
    )

    assert module.main() == 2
