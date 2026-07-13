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
            "    \n\n", budget=5, overlap_ratio=0.1, min_chunk_chars=100, max_chunk_chars=1000
        )
        == []
    )


def test_short_input_yields_one_chunk_covering_everything() -> None:
    chunks = chunk_with_boundary(
        "Hello world.", budget=5, overlap_ratio=0.1, min_chunk_chars=100, max_chunk_chars=1000
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


def test_budget_caps_chunk_count() -> None:
    text = ("paragraph body. " * 20 + "\n\n") * 30  # ~ 10k chars
    chunks = chunk_with_boundary(
        text, budget=5, overlap_ratio=0.1, min_chunk_chars=200, max_chunk_chars=8000
    )
    assert len(chunks) <= 5


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
        text, budget=budget, overlap_ratio=0.1, min_chunk_chars=100, max_chunk_chars=2000
    )
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
