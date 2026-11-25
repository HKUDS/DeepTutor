"""A language course names its target language in the outline (#2933).

An outline item such as 「反义词」 in an English course carries nothing that
binds it to English, so a fresh session taught Chinese antonyms. The route
generator and the tutor's outline drafting both have to name the language.
"""

from __future__ import annotations

import pytest

from deeptutor.capabilities.mastery.loop import _load_playbook
from deeptutor.learning.prompts import topic_generation_prompts


@pytest.mark.parametrize(
    ("language", "marker"),
    [("en", '"English antonyms", not "Antonyms"'), ("zh", "「英语反义词」，不要只写「反义词」")],
)
def test_route_generation_names_the_target_language(language: str, marker: str) -> None:
    system_prompt, _ = topic_generation_prompts(
        language, name="English", goal="Pass the CET-4 exam", sources_json="[]"
    )
    assert marker in system_prompt


@pytest.mark.parametrize(
    ("language", "build_marker", "teach_marker"),
    [
        (
            "en",
            '("English antonyms", not "Antonyms")',
            "**A language course keeps its target language.**",
        ),
        (
            "zh",
            "（写「英语反义词」，不要只写「反义词」）",
            "**语言课程要守住它的目标语言。**",
        ),
    ],
)
def test_tutor_playbook_binds_a_language_course_to_its_target_language(
    language: str, build_marker: str, teach_marker: str
) -> None:
    playbook = _load_playbook(language)
    assert build_marker in playbook
    assert teach_marker in playbook
