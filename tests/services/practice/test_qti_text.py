"""Scorer metadata is not part of the learner's explanation."""

from deeptutor.services.practice.qti_text import readable_explanation


def test_explanation_preserves_prose_without_reference_or_private_json():
    text = (
        "Reference answer: 12.2877\n"
        "Scoring guidance: 把 9.99 看作 10−0.01。\n"
        'Reactutor scorer guidance v1: {"author":{"correctAnswer":"wrong"}}'
    )
    assert readable_explanation(text) == "把 9.99 看作 10−0.01。"


def test_fill_score_summary_is_not_explanation():
    text = "Blank blank-1: = = 1.00000/1.00000 (comparison_v1)\nScoring guidance: 两边相等。"
    assert readable_explanation(text) == "两边相等。"


def test_ordinary_explanation_is_unchanged():
    assert readable_explanation("First step.\n\nSecond step.") == "First step.\n\nSecond step."
