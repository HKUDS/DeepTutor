"""Millisecond suffixes must not be parsed as minutes."""

from deeptutor.agents.math_animator.duration_utils import parse_target_duration_seconds


def test_ms_suffix_is_not_a_minute() -> None:
    # "1ms" previously matched bare "m" and became 60s.
    assert parse_target_duration_seconds("1ms") is None
    assert parse_target_duration_seconds("500ms") is None


def test_minute_and_second_still_parse() -> None:
    assert parse_target_duration_seconds("1m") == 60.0
    assert parse_target_duration_seconds("1 min") == 60.0
    assert parse_target_duration_seconds("1s") == 1.0
