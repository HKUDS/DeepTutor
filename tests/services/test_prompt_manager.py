"""Prompt manager path resolution tests."""

from __future__ import annotations

from deeptutor.services.prompt import get_prompt_manager


def test_prompt_manager_loads_prompts_from_deeptutor_tree() -> None:
    manager = get_prompt_manager()
    manager.clear_cache()

    prompts = manager.load_prompts(
        module_name="question",
        agent_name="pipeline",
        language="en",
    )

    assert "explore" in prompts
