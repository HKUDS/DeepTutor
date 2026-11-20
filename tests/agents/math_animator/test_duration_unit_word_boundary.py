"""A unit letter must not be read from the start of an ordinary word."""

import pytest

from deeptutor.agents.math_animator.duration_utils import parse_target_duration_seconds


@pytest.mark.parametrize(
    "text",
    [
        "Explain the 3 main ideas of calculus",
        "Animate 4 matrices being multiplied",
        "A 2 meter rod rotating",
        "Show 3 squares on a grid",
        "Draw a polygon with 5 sides",
    ],
)
def test_number_before_a_word_is_not_a_duration(text: str) -> None:
    assert parse_target_duration_seconds(text) is None


def test_duration_next_to_ordinary_words_still_parses() -> None:
    assert parse_target_duration_seconds("Explain the 3 main ideas in 30 seconds") == 30.0
    assert parse_target_duration_seconds("Show 3 squares, about 2 min long") == 120.0
    assert parse_target_duration_seconds("1.5m video") == 90.0
    assert parse_target_duration_seconds("10s.") == 10.0
    assert parse_target_duration_seconds("做一个30秒的动画") == 30.0
    assert parse_target_duration_seconds("2分钟") == 120.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Create a 1 minute 30 seconds video", 90.0),
        ("1minute30seconds", 90.0),
        ("1m30s", 90.0),
        ("1分钟30秒", 90.0),
        ("1.5 minutes 30.5 seconds", 120.5),
        ("0.5m15.25s", 45.25),
        ("1m30s or 2m10s", 130.0),
        ("Intro 1m30s; outro 30 seconds", 90.0),
    ],
)
def test_adjacent_minutes_and_seconds_form_one_duration(text: str, expected: float) -> None:
    assert parse_target_duration_seconds(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 minute or 30 seconds", 60.0),
        ("1minuteor30seconds", 30.0),
        ("30 to 60 seconds", 60.0),
        ("30s1m", 60.0),
        ("30 seconds then 1 minute", 60.0),
        ("Intro 1 minute; outro 30 seconds", 60.0),
        ("Intro 2 minutes; outro 30 seconds", 120.0),
        ("Explain 3 main ideas with 5 sides in 500ms", None),
    ],
)
def test_distinct_duration_targets_still_use_the_largest(text: str, expected: float | None) -> None:
    assert parse_target_duration_seconds(text) == expected
