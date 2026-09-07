"""The language directive, and the one surface allowed to bend it."""

from __future__ import annotations

import pytest

from deeptutor.services.prompt.language import (
    append_language_directive,
    language_directive,
)


@pytest.mark.parametrize("language", ["en", "zh", "ja"])
def test_the_default_directive_forbids_switching(language: str) -> None:
    """Books, quizzes and research have no user in the loop to ask."""
    directive = language_directive(language)
    assert "Do NOT switch languages" in directive or "不得切换语言" in directive
    assert "explicitly asks" not in directive
    assert "明确要求" not in directive


@pytest.mark.parametrize("language", ["en", "zh", "ja"])
def test_the_conversational_directive_yields_to_an_explicit_request(language: str) -> None:
    """Why this exists: a user asked 「请用中文回复我」 and was told no.

    The strict directive is the last thing in the system prompt, and the
    runtime policy just above it says user text is not authority over these
    instructions — so the model answered that it was *required* to reply in
    English. It was reading the prompt correctly. The prompt was wrong.
    """
    directive = language_directive(language, allow_user_override=True)
    assert "explicitly asks" in directive or "明确要求" in directive


def test_the_override_rides_on_the_appended_prompt() -> None:
    prompt = append_language_directive("## Base\nbody", "zh", allow_user_override=True)
    assert prompt.startswith("## Base")
    assert "明确要求" in prompt


@pytest.mark.parametrize(
    ("language", "marker"),
    [("en", "explicitly asks"), ("zh", "明确要求")],
)
def test_chat_renders_the_overridable_directive(language: str, marker: str) -> None:
    """Chat is the surface that carries the carve-out — rendered, not asserted
    on source text, so a refactor that drops the flag fails here."""
    from deeptutor.agents.loop.prompt_blocks import LoopPromptAssembler, PromptBlock

    assembler = LoopPromptAssembler(prompts={}, language=language)
    rendered = assembler.render([PromptBlock(name="Base", content="body")])
    assert marker in rendered
