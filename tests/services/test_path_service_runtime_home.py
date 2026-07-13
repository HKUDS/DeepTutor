from __future__ import annotations

from pathlib import Path

from deeptutor.services.path_service import PathService


def test_path_service_defaults_to_deeptutor_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()

    service = PathService.get_instance()

    assert service.project_root == tmp_path.resolve()
    assert service.workspace_root == (tmp_path / "data").resolve()
    assert service.get_settings_dir() == (tmp_path / "data" / "user" / "settings").resolve()

    PathService.reset_instance()
