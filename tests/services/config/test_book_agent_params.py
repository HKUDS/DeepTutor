"""The Book module's token budget must be resolvable and user-overridable.

``get_agent_params("book")`` returned the 4096 source-level fallback because
``book`` was absent from ``section_map`` — the function returned *before*
opening agents.yaml, so adding a ``capabilities.book`` block did nothing. A
reasoning model spends that budget on hidden tokens and leaves the spine stage
an empty response, which degrades a whole book to one "Overview" chapter
(#1316).
"""

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
    (settings_dir / "agents.yaml").write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


def test_book_falls_back_to_the_shipped_default_not_the_global_4096(
    tmp_path: Path, monkeypatch
) -> None:
    """A stale agents.yaml (no ``book`` block) still gets the real budget."""
    project_root = _write_agents_yaml(tmp_path, {"capabilities": {"solve": {"temperature": 0.3}}})
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

    params = get_agent_params("book")

    assert params["max_tokens"] == DEFAULT_AGENTS_SETTINGS["capabilities"]["book"]["max_tokens"]
    assert params["max_tokens"] > 4096


def test_book_budget_is_overridable_from_agents_yaml(tmp_path: Path, monkeypatch) -> None:
    project_root = _write_agents_yaml(
        tmp_path,
        {"capabilities": {"book": {"temperature": 0.2, "max_tokens": 32000}}},
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

    assert get_agent_params("book") == {"temperature": 0.2, "max_tokens": 32000}
