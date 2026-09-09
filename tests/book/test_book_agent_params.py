from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from deeptutor.book.agents.spine_synthesizer import SpineSynthesizer
from deeptutor.services.config import loader as loader_module


def _write_agents_yaml(tmp_path: Path, content: dict[str, Any]) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    agents_file = settings_dir / "agents.yaml"
    agents_file.write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


def test_spine_synthesizer_uses_book_default_in_stale_agents_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _write_agents_yaml(
        tmp_path,
        {"capabilities": {"solve": {"temperature": 0.3, "max_tokens": 8192}}},
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

    agent = SpineSynthesizer()

    assert agent.get_temperature() == 0.5
    assert agent.get_max_tokens() == 16384


def test_agents_yaml_overrides_book_token_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _write_agents_yaml(
        tmp_path,
        {"capabilities": {"book": {"temperature": 0.2, "max_tokens": 24576}}},
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

    agent = SpineSynthesizer()

    assert agent.get_temperature() == 0.2
    assert agent.get_max_tokens() == 24576
