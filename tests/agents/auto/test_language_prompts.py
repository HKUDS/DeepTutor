from __future__ import annotations

from deeptutor.agents.auto.prompts import (
    analyzer_system_prompt,
    pick_language,
    router_system_prompt,
    synthesizer_system_prompt,
)


def test_auto_pick_language_preserves_german_aliases() -> None:
    assert pick_language("de") == "de"
    assert pick_language("de-DE") == "de"
    assert pick_language("Deutsch") == "de"


def test_auto_prompts_use_english_base_with_german_directive() -> None:
    analyzer = analyzer_system_prompt("de-DE")
    router = router_system_prompt("Deutsch")
    synthesizer = synthesizer_system_prompt("German")

    for prompt in (analyzer, router, synthesizer):
        assert "Auto Routing assistant" in prompt
        assert "Write ALL reader-facing text strictly in Deutsch" in prompt
