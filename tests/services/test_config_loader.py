from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config.loader import (
    PROJECT_ROOT,
    load_config_with_main,
    resolve_config_path,
)


def test_resolve_config_path_returns_existing_config(tmp_path: Path) -> None:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "custom.yaml").write_text("system:\n  language: en\n", encoding="utf-8")

    resolved, used_alias = resolve_config_path("custom.yaml", tmp_path)

    assert resolved == settings_dir / "custom.yaml"
    assert used_alias is False


def test_load_config_with_main_loads_config_file(tmp_path: Path) -> None:
    """``load_config_with_main`` reads the requested config file and injects
    runtime paths. It no longer auto-merges main.yaml — callers that need
    layered defaults are expected to do that explicitly.
    """
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "custom.yaml").write_text(
        "solve:\n  max_replans: 5\nlogging:\n  level: INFO\n",
        encoding="utf-8",
    )

    config = load_config_with_main("custom.yaml", tmp_path)

    assert config["solve"]["max_replans"] == 5
    assert config["logging"]["level"] == "INFO"


def test_load_config_with_main_raises_for_unknown_missing_config(tmp_path: Path) -> None:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "main.yaml").write_text("system:\n  language: en\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        load_config_with_main("nonexistent_module.yaml", tmp_path)


def test_load_config_with_main_uses_explicit_project_root() -> None:
    config = load_config_with_main("main.yaml", PROJECT_ROOT)

    assert "system" in config
    assert (
        Path(config["paths"]["solve_output_dir"])
        .as_posix()
        .endswith("data/user/workspace/chat/deep_solve")
    )
