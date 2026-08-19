"""The visual blocks must take their brief from YAML, like every other block.

figure / interactive / animation used to build their prompt in Python with
English f-strings, so a Chinese book asked the shared visualize pipeline for a
figure in English — the one part of the book whose prompt ignored the book's
language. These check both that the prompts exist for every block/language pair
and that they interpolate without spacing artefacts in either direction.
"""

from __future__ import annotations

import pytest

from deeptutor.book.blocks._prompts import get_book_prompt, load_book_prompts

VISUAL_BLOCKS = ("figure", "interactive", "animation")
LANGUAGES = ("en", "zh")

# Every placeholder any of the three briefs might use.
FILLERS = {
    "chapter_title": "Matrix factorisation",
    "variant": "schematic",
    "interaction": "explorable",
}


@pytest.mark.parametrize("block", VISUAL_BLOCKS)
@pytest.mark.parametrize("language", LANGUAGES)
def test_every_visual_block_has_a_brief_in_every_language(block: str, language: str) -> None:
    prompts = load_book_prompts(block, language)
    for key in ("brief", "focus_clause", "context_summary", "context_objectives"):
        assert get_book_prompt(prompts, key).strip(), f"{block}/{language} missing {key}"


@pytest.mark.parametrize("block", VISUAL_BLOCKS)
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_brief_renders_with_and_without_a_focus(block: str, language: str) -> None:
    prompts = load_book_prompts(block, language)
    brief = get_book_prompt(prompts, "brief").strip()

    focused = brief.format(
        **FILLERS,
        focus_clause=get_book_prompt(prompts, "focus_clause").rstrip().format(focus="SVD"),
    )
    assert "SVD" in focused
    assert "{" not in focused, "an unfilled placeholder survived"
    assert "  " not in focused, "double space — the focus clause spacing is off"

    unfocused = brief.format(**FILLERS, focus_clause="")
    assert "{" not in unfocused
    assert "  " not in unfocused, "empty focus clause left a dangling space"


def test_the_english_focus_clause_keeps_its_leading_space() -> None:
    """A YAML block scalar would strip it; the file uses a quoted scalar."""
    clause = get_book_prompt(load_book_prompts("figure", "en"), "focus_clause")
    assert clause.startswith(" "), "English clause must separate itself from the title"


def test_a_chinese_book_gets_a_chinese_brief() -> None:
    zh = get_book_prompt(load_book_prompts("figure", "zh"), "brief")
    assert any("一" <= ch <= "鿿" for ch in zh), "expected Chinese text"
    assert "figure for the chapter" not in zh
