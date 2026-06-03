from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from deeptutor.services.settings import interface_settings


def _patch_settings_file(monkeypatch, tmp_path: Path) -> Path:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    settings_file = settings_dir / "interface.json"
    monkeypatch.setattr(
        interface_settings,
        "get_path_service",
        lambda: SimpleNamespace(
            get_settings_file=lambda _name: settings_file,
        ),
    )
    return settings_file


def test_get_ui_settings_accepts_german_language_alias(monkeypatch, tmp_path: Path) -> None:
    settings_file = _patch_settings_file(monkeypatch, tmp_path)
    settings_file.write_text(
        json.dumps({"theme": "snow", "language": "de-DE"}),
        encoding="utf-8",
    )

    settings = interface_settings.get_ui_settings()

    assert settings["theme"] == "snow"
    assert settings["language"] == "de"


def test_get_ui_language_accepts_german_default_when_file_is_missing(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_settings_file(monkeypatch, tmp_path)

    assert interface_settings.get_ui_language(default="Deutsch") == "de"
