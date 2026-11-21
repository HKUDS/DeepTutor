"""Focused tests for the mastery study composer's ask-hint sanitizer."""

from __future__ import annotations

from deeptutor.services import mastery_hints


def test_sanitize_strips_list_markers_but_keeps_leading_text() -> None:
    assert mastery_hints._sanitize("• Why does it converge?", "en") == "Why does it converge?"
    assert mastery_hints._sanitize("-2 times -3 is positive?", "en") == "-2 times -3 is positive?"
