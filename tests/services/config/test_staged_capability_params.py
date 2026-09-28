"""Every LLM budget is addressable from agents.yaml, and only from there.

``question`` and ``research`` used to keep their per-step budgets as module
constants, so ``capabilities.question.max_tokens`` governed exactly one of
that capability's six LLM calls (the follow-up agent) and a user who wanted a
longer plan had to edit source. That is how #1318 shipped a plan step budgeted
below the capability's own ceiling.

These tests pin the two properties that keep it fixed: the stage a pipeline
asks for exists, and the number it gets is the one the project shipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from deeptutor.services.config import loader as loader_module
from deeptutor.services.config.loader import (
    _STAGED_CAPABILITY_DEFAULTS,
    get_capability_params,
)

# The values these pipelines ran on before the budgets moved into agents.yaml.
# Written out rather than derived: a test that recomputes the table from the
# table cannot notice the table changing. An intentional retune edits this map
# in the same commit and says why.
SHIPPED_BUDGETS: dict[str, dict[str, int]] = {
    "question": {
        "answering": 4000,
        "planning": 6000,
        "quiz_finish": 3000,
        "repair": 2500,
        "tool_summarizer": 800,
    },
    "research": {
        "note": 1500,
        "block": 6000,
        "outline": 2000,
        "report_outline": 2000,
        "report_intro": 3000,
        "report_section": 12000,
        "report_conclusion": 3000,
    },
    "explore_context": {
        "loop": 2000,
        "briefing": 1400,
    },
}


def _write_agents_yaml(tmp_path: Path, content: dict[str, Any]) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "agents.yaml").write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("capability", sorted(SHIPPED_BUDGETS))
def test_defaults_are_the_budgets_the_pipelines_shipped_with(capability: str) -> None:
    """Moving a budget into config must not quietly change it."""
    table = _STAGED_CAPABILITY_DEFAULTS[capability]
    actual = {stage: values["max_tokens"] for stage, values in table.items()}
    assert actual == SHIPPED_BUDGETS[capability]


def test_every_staged_capability_seeds_every_stage_it_defines() -> None:
    """A default nobody seeds is a default no user can discover or edit.

    ``get_agent_params`` reads the shipped settings as its per-module defaults,
    so a stage present in code but absent from the seed is exactly the #1316
    shape: a number that governs a run and lives nowhere the user can reach.
    """
    from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS

    seeded = DEFAULT_AGENTS_SETTINGS["capabilities"]
    for capability, stages in SHIPPED_BUDGETS.items():
        section = seeded.get(capability)
        assert isinstance(section, dict), f"{capability} is not seeded at all"
        for stage, max_tokens in stages.items():
            assert section.get(stage) == {"max_tokens": max_tokens}, (
                f"{capability}.{stage} is missing from the shipped agents.yaml"
            )


def test_a_user_override_reaches_the_stage(tmp_path: Path, monkeypatch) -> None:
    project_root = _write_agents_yaml(
        tmp_path,
        {"capabilities": {"question": {"planning": {"max_tokens": 20000}}}},
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

    params = get_capability_params("question")
    assert params["planning"]["max_tokens"] == 20000
    # Stages the user did not mention keep their shipped value rather than
    # disappearing — callers index without checks.
    assert params["repair"]["max_tokens"] == SHIPPED_BUDGETS["question"]["repair"]


def test_unknown_keys_in_the_users_file_are_dropped(tmp_path: Path, monkeypatch) -> None:
    """A misspelled stage must not become a stage.

    Merging it in would give a silent no-op that reads like a setting, which
    is the failure this whole seam exists to remove.
    """
    project_root = _write_agents_yaml(
        tmp_path,
        {"capabilities": {"question": {"planing": {"max_tokens": 1}, "max_tokens": 4096}}},
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

    params = get_capability_params("question")
    assert "planing" not in params
    # ``max_tokens`` at the capability level belongs to get_agent_params, not
    # to the staged table; it must not leak in as a pseudo-stage either.
    assert "max_tokens" not in params
    assert params["planning"]["max_tokens"] == SHIPPED_BUDGETS["question"]["planning"]


def test_an_unstaged_capability_raises_rather_than_inventing_a_budget() -> None:
    """Adding a stage means adding it to the table — that is the point."""
    with pytest.raises(KeyError):
        get_capability_params("no_such_capability")
