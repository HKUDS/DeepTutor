from __future__ import annotations

from deeptutor.agents.math_animator.utils import (
    build_repair_error_message,
    describe_unusable_output,
    escalated_max_tokens,
    extract_json_object,
)
from deeptutor.services.llm import StreamOutcome


def test_build_repair_error_message_adds_targeted_3d_point_hint() -> None:
    error_message = (
        "vectorized_mobject.py:855 in append_points\n"
        "ValueError: could not broadcast input array from shape (1,2) into shape (1,3)"
    )

    enriched = build_repair_error_message(error_message)

    assert "Targeted repair hints" in enriched
    assert "[x, y, 0]" in enriched
    assert "axes.c2p" in enriched


def test_build_repair_error_message_keeps_unknown_errors_plain() -> None:
    error_message = "NameError: name 'FadeInn' is not defined"
    assert build_repair_error_message(error_message) == error_message


def test_extract_json_object_accepts_trailing_extra_data() -> None:
    raw = (
        '{"code":"from manim import *\\nclass A(Scene):\\n    pass","rationale":"fix syntax"}\n'
        "```python\n# extra trailing block from model\n```"
    )

    parsed = extract_json_object(raw)

    assert parsed["rationale"] == "fix syntax"
    assert "class A(Scene)" in parsed["code"]


def test_extract_json_object_accepts_prefixed_text_before_json() -> None:
    raw = (
        "Here is the repaired JSON:\n"
        '{"code":"from manim import *\\nclass B(Scene):\\n    pass","rationale":"repair"}'
    )

    parsed = extract_json_object(raw)

    assert parsed["rationale"] == "repair"
    assert "class B(Scene)" in parsed["code"]


def test_escalated_max_tokens_stops_at_twice_the_configured_budget() -> None:
    """Growth is bounded: a max_tokens above the model's own output limit is
    rejected outright, which would turn a truncated answer into none (#1547)."""
    assert escalated_max_tokens(8000, 0) == 8000
    assert escalated_max_tokens(8000, 1) == 12000
    assert [escalated_max_tokens(8000, n) for n in (2, 3, 9)] == [16000, 16000, 16000]
    assert escalated_max_tokens(0, 3) == 0


def test_describe_unusable_output_separates_the_three_failures() -> None:
    truncated = StreamOutcome(finish_reason="length", usage={"completion_tokens": 8000})
    assert "cut off at the 8000-token output cap" in describe_unusable_output(
        error=ValueError("x"),
        raw_response='<think>long</think>{"code": "from man',
        outcome=truncated,
        max_tokens=8000,
    )
    assert "no text at all" in describe_unusable_output(
        error=ValueError("x"),
        raw_response="   ",
        outcome=StreamOutcome(finish_reason="stop"),
        max_tokens=8000,
    )
    assert "no usable JSON object" in describe_unusable_output(
        error=ValueError("x"),
        raw_response="Sorry, I cannot.",
        outcome=StreamOutcome(finish_reason="stop"),
        max_tokens=8000,
    )
