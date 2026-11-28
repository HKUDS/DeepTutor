"""Focused tests for the mastery study composer's ask-hint sanitizer."""

from __future__ import annotations

from deeptutor.services import mastery_hints


def test_sanitize_keeps_apostrophes_and_inner_quotes() -> None:
    assert (
        mastery_hints._sanitize("What's the difference between a list and a tuple?", "en")
        == "What's the difference between a list and a tuple?"
    )
    assert (
        mastery_hints._sanitize('Why is "-1" not a root here?', "en")
        == 'Why is "-1" not a root here?'
    )


def test_sanitize_unwraps_quoted_or_fenced_question() -> None:
    assert mastery_hints._sanitize('"Why does it converge?"', "en") == "Why does it converge?"
    assert mastery_hints._sanitize("“为什么会收敛？”", "zh") == "为什么会收敛？"
    assert mastery_hints._sanitize("```\nWhy does it converge?\n```", "en") == (
        "Why does it converge?"
    )
