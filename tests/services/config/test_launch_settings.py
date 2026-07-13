from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.config.launch_settings import load_launch_settings


def _settings_dir(root: Path) -> Path:
    path = root / "data" / "user" / "settings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_launch_settings_reads_ports_from_system_json_and_ignores_env_json(
    monkeypatch, tmp_path: Path
) -> None:
    for key in ("BACKEND_PORT", "FRONTEND_PORT", "UI_LANGUAGE", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)

    settings_dir = _settings_dir(tmp_path)
    (settings_dir / "system.json").write_text(
        json.dumps({"backend_port": 9001, "frontend_port": 4000}),
        encoding="utf-8",
    )
    (settings_dir / "env.json").write_text(
        json.dumps({"ports": {"backend": 8101, "frontend": 4100}}),
        encoding="utf-8",
    )
    (settings_dir / "interface.json").write_text(
        json.dumps({"language": "zh"}),
        encoding="utf-8",
    )

    settings = load_launch_settings(tmp_path)

    assert settings.backend_port == 9001
    assert settings.frontend_port == 4000
    assert settings.language == "zh"
    assert "system.json" in settings.source
    assert "env.json" not in settings.source
    assert "interface.json" in settings.source


def test_launch_settings_creates_default_system_json_without_dotenv_migration(
    monkeypatch, tmp_path: Path
) -> None:
    for key in ("BACKEND_PORT", "FRONTEND_PORT", "UI_LANGUAGE", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)

    (tmp_path / ".env").write_text(
        "BACKEND_PORT=9101\nFRONTEND_PORT=4200\nUI_LANGUAGE=zh\n",
        encoding="utf-8",
    )

    settings = load_launch_settings(tmp_path)

    assert settings.backend_port == 8001
    assert settings.frontend_port == 3782
    assert settings.system_json_path.exists()
    assert settings.language == "en"


def test_launch_settings_allows_process_env_as_deployment_override(
    monkeypatch, tmp_path: Path
) -> None:
    for key in ("BACKEND_PORT", "FRONTEND_PORT", "UI_LANGUAGE", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BACKEND_PORT", "9201")
    monkeypatch.setenv("FRONTEND_PORT", "4300")

    settings = load_launch_settings(tmp_path)

    assert settings.backend_port == 9201
    assert settings.frontend_port == 4300
    assert "environment" in settings.source
