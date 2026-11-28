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


def test_composed_route_prompt_keeps_the_target_language_under_a_strict_directive() -> None:
    """What the model actually reads: the strict zh directive comes last, and it
    must still leave a studied language in its own language."""
    system_prompt, _ = topic_generation_prompts(
        "zh", name="英语", goal="通过四级考试", sources_json="[]"
    )
    naming_rule = system_prompt.index("「英语反义词」")
    directive = system_prompt.index("[语言要求 / Language]")
    assert naming_rule < directive
    assert "所学的科目本身就是一门语言" in system_prompt[directive:]


def test_composed_tutor_prompt_keeps_the_target_language_under_a_fixed_reply_language() -> None:
    """A conversation pinned to Chinese renders the strict directive after the
    playbook; the carve-out has to survive that render, not only the source."""
    from deeptutor.agents.loop.prompt_blocks import LoopPromptAssembler, PromptBlock

    assembler = LoopPromptAssembler(prompts={}, language="zh")
    rendered = assembler.render(
        [PromptBlock(name="mastery_tutor", content=_load_playbook("zh"))],
        allow_user_override=False,
    )
    directive = rendered.index("[语言要求 / Language]")
    assert rendered.index("**语言课程要守住它的目标语言。**") < directive
    assert "所学的科目本身就是一门语言" in rendered[directive:]
    assert "明确要求" not in rendered[directive:]
