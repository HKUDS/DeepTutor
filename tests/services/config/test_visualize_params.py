"""The visualize loop's output budget must be readable from agents.yaml.

``visualize`` built its pipeline with ``max_tokens=16000`` written into the call,
so a reasoning model that spends most of a round inside ``<think>`` truncated the
``submit_visualization`` arguments mid-JSON and the canvas came back empty — with
no setting anywhere that changed it (#1546).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from deeptutor.services.config import capabilities_settings as module
from deeptutor.services.config.capabilities_settings import get_visualize_params
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS


def _settings_root(tmp_path: Path, content: dict[str, Any]) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "agents.yaml").write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


def test_visualize_defaults_match_the_previously_hardcoded_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An install that never touched this keeps exactly the old behaviour."""
    monkeypatch.setattr(module, "PROJECT_ROOT", _settings_root(tmp_path, {"capabilities": {}}))

    assert get_visualize_params() == {"temperature": 0.15, "max_tokens": 16000}


def test_fresh_setup_keeps_the_visualize_runtime_default() -> None:
    """Seeding agents.yaml must not change a fresh install's visualize budget."""
    assert (
        DEFAULT_AGENTS_SETTINGS["capabilities"]["visualize"]
        == module._SIMPLE_LLM_DEFAULTS["visualize"]
    )


def test_visualize_budget_is_overridable_from_agents_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "PROJECT_ROOT",
        _settings_root(
            tmp_path,
            {"capabilities": {"visualize": {"temperature": 0.4, "max_tokens": 48000}}},
        ),
    )

    assert get_visualize_params() == {"temperature": 0.4, "max_tokens": 48000}


def test_visualize_is_exposed_to_the_settings_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same block the UI reads and writes, so the page cannot drift."""
    monkeypatch.setattr(module, "PROJECT_ROOT", _settings_root(tmp_path, {"capabilities": {}}))

    payload = module.capabilities_settings_dict()

    assert payload["visualize"] == {"temperature": 0.15, "max_tokens": 16000}

    module.save_capabilities_settings({"visualize": {"max_tokens": 32000}})

    assert get_visualize_params()["max_tokens"] == 32000
