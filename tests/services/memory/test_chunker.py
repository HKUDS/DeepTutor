"""Tests for the character-based chunker with boundary expansion."""

from __future__ import annotations

import pytest

from deeptutor.services.memory.consolidator.chunker import (
    ChunkSpan,
    chunk_with_boundary,
)


def test_empty_input_returns_no_chunks() -> None:
    assert (
        chunk_with_boundary(
            "", budget=5, overlap_ratio=0.1, min_chunk_chars=100, max_chunk_chars=1000
        )
        == []
    )
    assert (
        chunk_with_boundary(
            "    \n\n",
            budget=5,
            overlap_ratio=0.1,
            min_chunk_chars=100,
            max_chunk_chars=1000,
        )
        == []
    )


def test_short_input_yields_one_chunk_covering_everything() -> None:
    chunks = chunk_with_boundary(
        "Hello world.",
        budget=5,
        overlap_ratio=0.1,
        min_chunk_chars=100,
        max_chunk_chars=1000,
    )
    assert len(chunks) == 1
    assert chunks[0].start == 0
    assert chunks[0].end == len("Hello world.")


def test_paragraph_boundary_extends_right_edge() -> None:
    text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
    chunks = chunk_with_boundary(
        text,
        budget=2,
        overlap_ratio=0.0,
        min_chunk_chars=50,
        max_chunk_chars=400,
        boundary="paragraph",
    )
    # First chunk's end should land at a paragraph boundary (or end of text when budget=1).
    assert chunks[0].text.endswith("\n\n") or chunks[0].end == len(text)
    # Nothing is left out across the chunks (allowing for overlap).
    assert chunks[-1].end == len(text)


def test_sentence_boundary_used_when_configured() -> None:
    sentences = " ".join(f"Sentence number {i}." for i in range(40))
    chunks = chunk_with_boundary(
        sentences,
        budget=4,
        overlap_ratio=0.05,
        min_chunk_chars=80,
        max_chunk_chars=400,
        boundary="sentence",
    )
    # Each non-last chunk ends with terminal punctuation + space (the
    # sentence boundary regex matches `.` followed by space).
    for chunk in chunks[:-1]:
        assert chunk.text[-1].isspace() or chunk.text.rstrip()[-1] in ".!?"


@pytest.mark.parametrize("punctuation", ["。", "！", "？"])
@pytest.mark.parametrize("closing_quote", ["", "」", "』", '"'])
def test_cjk_sentences_without_spaces_end_at_boundaries(
    punctuation: str, closing_quote: str
) -> None:
    sentences = [
        f"学习数学需要练习{punctuation}{closing_quote}",
        f"理解概念也很重要{punctuation}{closing_quote}",
        f"每天复习能够巩固知识{punctuation}{closing_quote}",
    ]
    text = "".join(sentences)
    chunks = chunk_with_boundary(
        text,
        budget=4,
        overlap_ratio=0.0,
        min_chunk_chars=1,
        max_chunk_chars=14,
        boundary="sentence",
    )
    assert [chunk.text for chunk in chunks] == sentences
    assert "".join(chunk.text for chunk in chunks) == text
    assert all(chunk.end - chunk.start <= 14 for chunk in chunks)


def test_cjk_sentence_boundaries_with_default_chunk_sizes() -> None:
    text = "学习数学需要练习。理解概念也很重要。每天复习能够巩固知识。" * 5000
    chunks = chunk_with_boundary(
        text,
        budget=20,
        overlap_ratio=0.1,
        min_chunk_chars=1000,
        max_chunk_chars=64000,
        boundary="sentence",
    )
    assert all(chunk.text.endswith("。") for chunk in chunks)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    assert all(chunk.end - chunk.start <= 64000 for chunk in chunks)
    assert all(left.end >= right.start for left, right in zip(chunks, chunks[1:]))


def test_ascii_period_inside_number_is_not_a_sentence_boundary() -> None:
    text = "Value is 3.14. Next sentence."
    chunks = chunk_with_boundary(
        text,
        budget=4,
        overlap_ratio=0.0,
        min_chunk_chars=1,
        max_chunk_chars=20,
        boundary="sentence",
    )
    assert chunks[0].text == "Value is 3.14."
    assert "".join(chunk.text for chunk in chunks) == text


def test_budget_caps_chunk_count() -> None:
    text = ("paragraph body. " * 20 + "\n\n") * 30  # ~ 10k chars
    chunks = chunk_with_boundary(
        text, budget=5, overlap_ratio=0.1, min_chunk_chars=200, max_chunk_chars=8000
    )
    assert len(chunks) <= 5


@pytest.mark.parametrize("budget", [5, 10, 20])
def test_budget_caps_chunk_count_when_overlap_shrinks_the_stride(budget: int) -> None:
    # Every cut loses one ``overlap`` worth of stride, so a target sized off
    # ``len(text) / budget`` only covers ``1 / (1 - overlap_ratio)`` of the
    # text: the default 10% overlap needs one chunk more than the budget.
    text = "".join(f"paragraph {i}. " + "x" * 120 + "\n\n" for i in range(200))
    chunks = chunk_with_boundary(
        text,
        budget=budget,
        overlap_ratio=0.10,
        min_chunk_chars=1000,
        max_chunk_chars=64000,
    )
    assert len(chunks) <= budget
    assert chunks[-1].end == len(text)


def test_overlap_visible_in_adjacent_chunks() -> None:
    text = ("paragraph body. " * 20 + "\n\n") * 10
    chunks = chunk_with_boundary(
        text, budget=3, overlap_ratio=0.2, min_chunk_chars=200, max_chunk_chars=2000
    )
    if len(chunks) >= 2:
        # The second chunk should start before the first ends.
        assert chunks[1].start < chunks[0].end


def test_min_chunk_chars_protects_against_tiny_chunks() -> None:
    text = "x" * 500
    chunks = chunk_with_boundary(
        text, budget=50, overlap_ratio=0.0, min_chunk_chars=400, max_chunk_chars=1000
    )
    # 500 chars / budget=50 would suggest 10-char chunks; min_chunk_chars
    # raises that to 400, so we get 1-2 chunks.
    assert len(chunks) <= 2


def test_max_chunk_chars_protects_against_huge_chunks() -> None:
    text = "x" * 100_000
    chunks = chunk_with_boundary(
        text, budget=1, overlap_ratio=0.0, min_chunk_chars=200, max_chunk_chars=5000
    )
    # 1 chunk is impossible if max=5000 and input=100k; multiple chunks expected.
    assert len(chunks) > 1
    assert all(c.end - c.start <= 5000 * 2 for c in chunks)  # boundary extension may push over


@pytest.mark.parametrize("budget", [1, 5, 20, 100])
def test_no_data_loss_chunks_cover_full_text(budget: int) -> None:
    text = "\n\n".join(f"para {i}: " + "x" * 50 for i in range(50))
    chunks = chunk_with_boundary(
        text,
        budget=budget,
        overlap_ratio=0.1,
        min_chunk_chars=100,
        max_chunk_chars=2000,
    )
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
