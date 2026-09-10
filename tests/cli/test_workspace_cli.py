from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from deeptutor.services.path_service import PathService
from deeptutor_cli.main import app

runner = CliRunner()


@pytest.fixture
def workspace_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PathService:
    from deeptutor.services.workspace import service as service_module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
    return paths


def test_workspace_cli_select_show_and_reset(workspace_paths: PathService, tmp_path: Path) -> None:
    custom = tmp_path / "course-files"
    custom.mkdir()

    selected = runner.invoke(app, ["workspace", "set", str(custom)])
    shown = runner.invoke(app, ["workspace", "show"])
    reset = runner.invoke(app, ["workspace", "reset"])

    assert selected.exit_code == 0, selected.output
    assert str(custom.resolve()) in selected.output
    assert shown.exit_code == 0, shown.output
    assert f"Path: {custom.resolve()}" in shown.output
    assert reset.exit_code == 0, reset.output
    assert str(workspace_paths.get_workspace_dir().resolve()) in reset.output
