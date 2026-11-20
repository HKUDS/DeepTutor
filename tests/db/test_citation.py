"""Citation rendering and validation — the anti-hallucination guard.

The roadmap's acceptance line is "hallucinated citations zero in the evaluation
set", which cannot be proven by reading an answer. It is proven by *checking*
each citation against the set of chunks retrieval actually returned for that
question.

The distinction that makes this real
-----------------------------------
A model can cite a book that genuinely exists in the library but was **not
retrieved for this question**. Naive validation ("does this book exist?") passes
it, and the answer looks grounded while being fabricated. So validation is
against the retrieved set, and a citation to a real-but-unretrieved book is
correctly reported as unverified.

D-009 rules the tests also pin:
* the citation shows the book and the chapter -- never page, chunk, grade, track;
* a chunk with no chapter degrades to the book name, and invents nothing.
"""

from __future__ import annotations

import pytest

from deeptutor.db.repositories import grounding


def _chunk(title: str, chapter: str = "", **extra) -> dict:
    base = {
        "chunk_key": f"chk_{title}_{chapter}",
        "source_title": title,
        "chapter_title": chapter,
        "page_index": 7,
        "grade_number": 10,
        "major_code": "math_physics",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_citation_is_book_and_chapter():
    assert grounding.render_citation(_chunk("ریاضی دهم", "فصل ۱")) == "[ریاضی دهم | فصل ۱]"


def test_citation_without_a_chapter_is_the_book_name_only():
    """Degrade, never invent."""
    assert grounding.render_citation(_chunk("ریاضی دهم")) == "[ریاضی دهم]"


def test_citation_never_shows_page_grade_or_track():
    """D-009: page, chunk, grade and track are retrieval internals."""
    rendered = grounding.render_citation(
        _chunk("ریاضی دهم", "فصل ۱", page_index=42, grade_number=10, major_code="math_physics")
    )
    assert "42" not in rendered
    assert "10" not in rendered
    assert "math_physics" not in rendered
    assert "chk_" not in rendered


def test_a_chunk_without_a_title_cannot_be_cited():
    with pytest.raises(grounding.CitationError):
        grounding.render_citation({"chapter_title": "فصل ۱"})


# ---------------------------------------------------------------------------
# Extraction of citations from an answer
# ---------------------------------------------------------------------------


def test_extracts_every_citation_in_order():
    answer = "طبق [ریاضی دهم | فصل ۱] و همچنین [فیزیک دهم | فصل ۳] این‌طور است."
    assert grounding.extract_citations(answer) == [
        ("ریاضی دهم", "فصل ۱"),
        ("فیزیک دهم", "فصل ۳"),
    ]


def test_book_only_citations_are_extracted():
    assert grounding.extract_citations("see [ریاضی دهم] for this") == [("ریاضی دهم", "")]


def test_duplicate_citations_are_kept_once():
    answer = "[کتاب] و باز [کتاب]"
    assert grounding.extract_citations(answer) == [("کتاب", "")]


def test_plain_brackets_that_are_not_citations_are_still_parsed_as_such():
    """A bracketed word is indistinguishable from a citation, so it must validate.

    This is a deliberate strictness: the validator cannot know a bracketed note
    from a citation, and guessing in the model's favour is how a fabricated
    citation slips through.
    """
    citations = grounding.extract_citations("نکته [مهم] در اینجا")
    assert citations == [("مهم", "")]


def test_an_answer_with_no_citations_yields_nothing():
    assert grounding.extract_citations("پاسخی بدون ارجاع.") == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_citation_backed_by_a_retrieved_chunk_is_valid():
    retrieved = [_chunk("ریاضی دهم", "فصل ۱")]
    report = grounding.validate_citations("طبق [ریاضی دهم | فصل ۱] ...", retrieved)
    assert report["valid"] is True
    assert report["unverified"] == []


def test_a_citation_to_a_real_but_unretrieved_book_is_a_hallucination():
    """The important case: the book exists, but it was not retrieved here."""
    retrieved = [_chunk("ریاضی دهم", "فصل ۱")]
    report = grounding.validate_citations("طبق [فیزیک دوازدهم | فصل ۹] ...", retrieved)
    assert report["valid"] is False
    assert report["unverified"] == [("فیزیک دوازدهم", "فصل ۹")]


def test_a_citation_to_a_retrieved_book_with_the_wrong_chapter_is_unverified():
    """Naming the right book with an invented chapter is still a fabrication."""
    retrieved = [_chunk("ریاضی دهم", "فصل ۱")]
    report = grounding.validate_citations("طبق [ریاضی دهم | فصل ۷] ...", retrieved)
    assert report["valid"] is False
    assert report["unverified"] == [("ریاضی دهم", "فصل ۷")]


def test_a_chapterless_retrieved_chunk_licenses_only_the_book_only_form():
    retrieved = [_chunk("ریاضی دهم")]
    assert grounding.validate_citations("[ریاضی دهم]", retrieved)["valid"] is True
    assert grounding.validate_citations("[ریاضی دهم | فصل ۲]", retrieved)["valid"] is False


def test_a_chaptered_chunk_also_licenses_the_book_only_form():
    """Citing the book without the chapter is less precise, not dishonest."""
    retrieved = [_chunk("ریاضی دهم", "فصل ۱")]
    assert grounding.validate_citations("[ریاضی دهم]", retrieved)["valid"] is True


def test_an_answer_with_no_citations_is_not_valid():
    """Ungrounded is not the same as valid-with-zero-citations."""
    report = grounding.validate_citations("پاسخ بدون ارجاع", [_chunk("کتاب", "فصل")])
    assert report["valid"] is False
    assert report["citation_count"] == 0


def test_one_bad_citation_invalidates_the_answer():
    retrieved = [_chunk("ریاضی دهم", "فصل ۱")]
    answer = "[ریاضی دهم | فصل ۱] و [کتاب ساختگی | فصل ۱]"
    report = grounding.validate_citations(answer, retrieved)
    assert report["valid"] is False
    assert report["unverified"] == [("کتاب ساختگی", "فصل ۱")]


def test_validation_against_an_empty_retrieval_marks_everything_unverified():
    report = grounding.validate_citations("[هر کتابی]", [])
    assert report["valid"] is False
    assert report["unverified"] == [("هر کتابی", "")]


# ---------------------------------------------------------------------------
# Abstention
# ---------------------------------------------------------------------------


def test_abstention_is_structured_not_a_bare_false():
    """The caller must be able to tell 'nothing exists' from 'not for your grade'."""
    result = grounding.abstain("no_source_matched")
    assert result["abstained"] is True
    assert result["grounded"] is False
    assert result["reason"] == "no_source_matched"
    assert result["citations"] == []


def test_a_full_grounding_report_round_trips():
    retrieved = [_chunk("ریاضی دهم", "فصل ۱"), _chunk("ریاضی دهم", "فصل ۲")]
    answer = "بر پایهٔ [ریاضی دهم | فصل ۱] و [ریاضی دهم | فصل ۲]."
    report = grounding.validate_citations(answer, retrieved)
    assert report["grounded"] is True
    assert report["citation_count"] == 2
    assert report["unverified"] == []
