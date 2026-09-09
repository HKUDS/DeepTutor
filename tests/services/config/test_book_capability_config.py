"""Tests for the book capability's LLM parameters via agents.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from deeptutor.services.config import loader as loader_module
from deeptutor.services.config.loader import get_agent_params
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS


def _write_agents_yaml(tmp_path: Path, content: dict[str, Any]) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    agents_file = settings_dir / "agents.yaml"
    agents_file.write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


class TestGetAgentParamsBook:
    """Verify get_agent_params("book") resolves capabilities.book from agents.yaml."""

    def test_reads_configured_max_tokens_and_temperature(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {"capabilities": {"book": {"max_tokens": 32000, "temperature": 0.6}}},
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

        params = get_agent_params("book")

        assert params["max_tokens"] == 32000
        assert params["temperature"] == 0.6

    def test_uses_seeded_default_when_book_section_absent(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {"capabilities": {"solve": {"temperature": 0.3}}},
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

        params = get_agent_params("book")

        assert params["max_tokens"] == 4096
        assert params["temperature"] == 0.5


def test_default_agents_settings_seeds_book_capability():
    """DEFAULT_AGENTS_SETTINGS must carry a "book" entry, like its sibling
    capabilities, so get_agent_params("book") has a module default to seed
    from instead of silently falling through to the bare global default.
    """
    assert DEFAULT_AGENTS_SETTINGS["capabilities"]["book"] == {
        "temperature": 0.5,
        "max_tokens": 4096,
    }
