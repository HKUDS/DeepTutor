"""Prompt manager path resolution tests."""

from __future__ import annotations

import pytest

from deeptutor.services.prompt import get_prompt_manager


def test_prompt_manager_loads_prompts_from_deeptutor_tree() -> None:
    manager = get_prompt_manager()
    manager.clear_cache()

    prompts = manager.load_prompts(
        module_name="question",
        agent_name="idea_agent",
        language="en",
    )

    assert "generate_ideas" in prompts


@pytest.mark.parametrize("language", ["en", "zh", "ja", "zh-tw"])
def test_context_summary_prompt_is_discoverable(
    language: str, capsys: pytest.CaptureFixture[str]
) -> None:
    manager = get_prompt_manager()
    manager.clear_cache()

    prompts = manager.load_prompts("chat", "context_summary_agent", language)

    assert isinstance(prompts.get("system"), str)
    assert prompts["system"].strip()
    assert "No prompt file found" not in capsys.readouterr().out
