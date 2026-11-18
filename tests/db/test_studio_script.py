"""The Persian script layer: structure, provenance and the traps that show.

These tests are about the text a student hears or reads. They are cheap and
deterministic because the script layer is a pure function -- the Persian quality
that a model adds is reviewed by a human against ``quality_checklist``, which is
a separate thing a test cannot assert.
"""

from __future__ import annotations

import pytest

from deeptutor.services.studio.script import (
    PROVENANCE_SOURCE,
    PROVENANCE_USER_PROMPT,
    ScriptRequest,
    build_script,
    estimate_duration,
    outline_for,
    quality_checklist,
    to_persian_digits,
)

SENTENCES = (
    "مشتق نرخ تغییر است. مشتق در فیزیک معنی سرعت دارد. "
    "سرعت مشتق مکان نسبت به زمان است. شتاب مشتق سرعت است."
)


# ---------------------------------------------------------------------------
# Persian output
# ---------------------------------------------------------------------------


def test_a_script_is_persian_and_says_so():
    script = build_script(ScriptRequest(kind="audio_overview", prompt="مشتق چیست؟"))
    assert script.language == "fa"
    assert any("\u0600" <= ch <= "\u06ff" for ch in script.text)


def test_digits_are_persian():
    script = build_script(ScriptRequest(kind="slide_deck", prompt=SENTENCES))
    assert all(str(d) not in script.text for d in range(10)), script.text


def test_a_heading_does_not_get_a_doubled_stop():
    """"مشتق چیست؟." is a typo, and the kind that makes a lesson look careless."""
    script = build_script(
        ScriptRequest(kind="audio_overview", prompt="مشتق چیست؟", chapter_title="فصل ۳")
    )
    assert "؟." not in script.text


def test_a_mind_map_does_not_branch_on_a_copula():
    """A raw frequency count puts "است" first; that branch says nothing."""
    script = build_script(
        ScriptRequest(kind="mind_map", source_text=SENTENCES, source_id="s1")
    )
    assert "است" not in script.outline
    # This used to assert `"مشتق" in outline`, which required a *bare word* to
    # be a branch -- the very behaviour that made the map read
    # "مشتق / قاعده / نمودار / نرخ / تغییر". The topic belongs to the hub; what
    # the branches owe the reader is a named idea, so the assertion is that the
    # idea is present, in a label longer than one word.
    joined = " ".join(script.outline)
    assert "مشتق" in joined
    assert all(len(branch.split()) > 1 for branch in script.outline)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_a_script_from_a_source_records_the_source():
    script = build_script(
        ScriptRequest(
            kind="audio_overview",
            source_text=SENTENCES,
            source_id="src_42",
            licence_code="cc-by",
        )
    )
    assert script.provenance == PROVENANCE_SOURCE
    assert script.source_id == "src_42"
    assert script.licence_code == "cc-by"
    assert script.from_source is True


def test_a_script_from_a_prompt_is_not_labelled_as_licensed_content():
    script = build_script(ScriptRequest(kind="audio_overview", prompt="مشتق چیست؟"))
    assert script.provenance == PROVENANCE_USER_PROMPT
    assert script.source_id is None, "a prompt is not a source"
    assert script.from_source is False


def test_source_text_without_an_id_is_refused():
    """A licence that cannot be traced to anything is not a licence."""
    with pytest.raises(ValueError, match="source_id"):
        build_script(ScriptRequest(kind="audio_overview", source_text=SENTENCES))


def test_a_source_id_without_source_text_is_not_recorded():
    """Passing an id is not the same as having used the source."""
    script = build_script(
        ScriptRequest(kind="audio_overview", prompt="مشتق چیست؟", source_id="src_9")
    )
    assert script.provenance == PROVENANCE_USER_PROMPT
    assert script.source_id is None


# ---------------------------------------------------------------------------
# Per-kind structure
# ---------------------------------------------------------------------------


def test_slides_carry_one_idea_each():
    script = build_script(ScriptRequest(kind="slide_deck", source_text=SENTENCES, source_id="s1"))
    assert len(script.outline) >= 3
    for line in script.outline:
        assert len(line.split()) <= 40


def test_slides_capitalise_the_persian_section_marker():
    """Reads as "اسلاید ۱", not "اسلاید 1" -- the number is part of the label."""
    script = build_script(ScriptRequest(kind="slide_deck", source_text=SENTENCES, source_id="s1"))
    assert "اسلاید ۱:" in script.text


def test_audio_sections_are_numbered_in_persian():
    script = build_script(ScriptRequest(kind="audio_overview", prompt=SENTENCES))
    assert "بخش ۱:" in script.text


def test_a_narrative_script_respects_its_word_budget():
    long_text = " ".join(SENTENCES for _ in range(80))
    script = build_script(
        ScriptRequest(kind="audio_overview", source_text=long_text, source_id="s1")
    )
    assert len(script.text.split()) <= 900 + 2


def test_a_mind_map_keeps_only_a_few_branches():
    script = build_script(
        ScriptRequest(kind="mind_map", source_text=SENTENCES, source_id="s1")
    )
    assert 0 < len(script.outline) <= 5


def test_outline_for_video_groups_sentences_into_scenes():
    outline = outline_for("video_lesson", SENTENCES, max_sections=3)
    assert 1 <= len(outline) <= 3
    assert all(chunk.strip() for chunk in outline)


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        build_script(ScriptRequest(kind="hologram", prompt="x"))


def test_an_empty_request_is_refused():
    with pytest.raises(ValueError):
        build_script(ScriptRequest(kind="audio_overview"))


# ---------------------------------------------------------------------------
# Duration and checklist
# ---------------------------------------------------------------------------


def test_only_spoken_kinds_have_a_duration():
    assert estimate_duration("audio_overview", " ".join(["کلمه"] * 130)) == pytest.approx(60, abs=1)
    assert estimate_duration("slide_deck", "متن") is None
    assert estimate_duration("mind_map", "متن") is None


def test_the_checklist_covers_common_and_specific_criteria():
    slides = quality_checklist("slide_deck")
    video = quality_checklist("video_lesson")
    assert len(slides) >= 5 and len(video) >= 5
    # The common criteria are shared; the specific ones are not.
    assert any(item["id"] == "scene_match" for item in video)
    assert not any(item["id"] == "scene_match" for item in slides)
    assert any(item["id"] == "one_idea" for item in slides)
    assert not any(item["id"] == "one_idea" for item in video)
    # Every item carries a question a reviewer can actually answer.
    assert all(item["question"].strip() for item in slides + video)


def test_to_persian_digits_is_character_wise():
    assert to_persian_digits("1234567890") == "۱۲۳۴۵۶۷۸۹۰"
