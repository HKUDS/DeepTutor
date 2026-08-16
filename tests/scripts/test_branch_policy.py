from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def _load_branch_policy_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_branch_policy.py"
    module_name = "branch_policy_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int = 0, stdout: str = "") -> object:
    return SimpleNamespace(returncode=returncode, stdout=stdout)


def test_allows_normal_branches(monkeypatch, capsys) -> None:
    module = _load_branch_policy_module()
    monkeypatch.setattr(module, "current_branch", lambda: "dev")

    assert module.main() == 0
    assert not capsys.readouterr().err


def test_rejects_main_without_explicit_exception(monkeypatch, capsys) -> None:
    module = _load_branch_policy_module()
    monkeypatch.setattr(module, "current_branch", lambda: "main")
    monkeypatch.setattr(module, "allows_main_commit", lambda: False)

    assert module.main() == 1
    assert "Direct commits to main are forbidden" in capsys.readouterr().err


def test_allows_explicit_main_exception(monkeypatch, capsys) -> None:
    module = _load_branch_policy_module()
    monkeypatch.setattr(module, "current_branch", lambda: "main")
    monkeypatch.setattr(module, "allows_main_commit", lambda: True)

    assert module.main() == 0
    assert not capsys.readouterr().err
