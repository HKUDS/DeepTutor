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
