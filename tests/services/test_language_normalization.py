from __future__ import annotations

from pathlib import Path

from deeptutor.services.config import parse_language
from deeptutor.services.prompt.language import append_language_directive, language_directive
from deeptutor.services.prompt.manager import PromptManager


def test_parse_language_preserves_german_aliases() -> None:
    assert parse_language("de") == "de"
    assert parse_language("de-DE") == "de"
    assert parse_language("Deutsch") == "de"
    assert parse_language("German") == "de"


def test_parse_language_keeps_existing_english_and_chinese_aliases() -> None:
    assert parse_language("en") == "en"
    assert parse_language("English") == "en"
    assert parse_language("zh") == "zh"
    assert parse_language("cn") == "zh"
    assert parse_language("") == "en"
    assert parse_language(None) == "en"


def test_language_directive_supports_german() -> None:
    directive = language_directive("de")

    assert "Deutsch" in directive
    assert "Write ALL reader-facing text strictly in Deutsch" in directive


def test_append_language_directive_is_idempotent_for_german() -> None:
    once = append_language_directive("System prompt", "de")
    twice = append_language_directive(once, "de")

    assert twice == once
    assert once.count("Deutsch") == 1


def test_prompt_manager_falls_german_back_to_english(tmp_path: Path) -> None:
    prompt_root = tmp_path / "deeptutor" / "agents" / "chat" / "prompts" / "en"
    prompt_root.mkdir(parents=True)
    (prompt_root / "agentic_chat.yaml").write_text(
        "system: English chat prompt\n",
        encoding="utf-8",
    )

    manager = PromptManager()
    manager.clear_cache()
    original_candidate_prompt_dirs = manager._candidate_prompt_dirs
    try:
        manager._candidate_prompt_dirs = lambda _module_name: [  # type: ignore[method-assign]
            tmp_path / "deeptutor" / "agents" / "chat" / "prompts"
        ]

        prompts = manager.load_prompts("chat", "agentic_chat", language="de")
    finally:
        manager._candidate_prompt_dirs = original_candidate_prompt_dirs  # type: ignore[method-assign]
        manager.clear_cache()

    assert prompts["system"] == "English chat prompt"
