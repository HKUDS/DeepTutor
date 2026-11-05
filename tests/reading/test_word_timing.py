"""Word-timing alignment for NaturalReader-style read-along highlighting."""

from __future__ import annotations

from deeptutor.reading.word_timing import (
    TICKS_PER_SECOND,
    align_words_to_text,
)


def test_ticks_scale_matches_windows_file_time() -> None:
    # Edge reports 10,000,000 ticks per second; one second must read as 1.0.
    assert TICKS_PER_SECOND == 10_000_000


def test_every_source_token_gets_a_timing() -> None:
    text = "The **quick** brown fox jumps."
    boundaries = [
        ("The", 0.10, 0.17),
        ("quick", 0.29, 0.30),
        ("brown", 0.60, 0.30),
        ("fox", 0.91, 0.46),
        ("jumps", 1.39, 0.31),
    ]

    words = align_words_to_text(text, boundaries)

    assert [word.word for word in words] == ["The", "**quick**", "brown", "fox", "jumps."]
    assert words[0].start == 0.10
    # Markup is preserved so the client can match the rendered text.
    assert words[1].word == "**quick**"
    assert [word.start for word in words] == sorted(word.start for word in words)


def test_unmatched_boundary_does_not_shift_later_words() -> None:
    # The voice says "twelve dollars" where the page shows "$12"; alignment must
    # keep "today" anchored to its own boundary rather than drifting.
    text = "It costs $12 today."
    boundaries = [
        ("It", 0.10, 0.20),
        ("costs", 0.30, 0.30),
        ("twelve", 0.60, 0.40),
        ("dollars", 1.00, 0.40),
        ("today", 1.40, 0.40),
    ]

    words = align_words_to_text(text, boundaries)
    by_word = {word.word: word.start for word in words}

    assert by_word["It"] == 0.10
    assert by_word["today."] == 1.40


def test_trailing_tokens_still_appear() -> None:
    # A truncated boundary list must not drop visible words.
    words = align_words_to_text("one two three", [("one", 0.0, 0.2), ("two", 0.2, 0.2)])

    assert [word.word for word in words] == ["one", "two", "three"]


def test_empty_inputs_are_safe() -> None:
    assert align_words_to_text("   \n\t ", [("x", 0.0, 0.1)]) == []
    assert align_words_to_text("Hello", []) == [
        # No boundaries: the token is kept at position zero so the reader can
        # still render it, and the client falls back to its estimate.
        type(align_words_to_text("Hello", [])[0])(word="Hello", start=0.0, duration=0.0)
    ]


def test_multiple_windows_per_second() -> None:
    """Offsets are ticks, not milliseconds — a 0.5 s word is 5,000,000 ticks."""
    ticks = 5_000_000
    assert ticks / TICKS_PER_SECOND == 0.5
