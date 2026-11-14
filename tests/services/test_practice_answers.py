"""Objective true/false checks must not fall back to qualitative self-assessment."""

import pytest

from deeptutor.services.practice.answers import check_answer


@pytest.mark.parametrize("kind", ["concept", "true_false"])
@pytest.mark.parametrize(
    ("expected", "answer", "correct"),
    [
        ("true", " TRUE ", True),
        ("false", "false", True),
        ("true", "false", False),
        ("false", "true", False),
        ("正确", "对", True),
        ("错误", "错", True),
        (False, "错误", True),
        (True, "正确", True),
        ("yes", "1", True),
        ("no", "f", True),
        ("t", "y", True),
        ("0", "n", True),
        ("false", "not true", False),
        ("true", "", False),
    ],
)
def test_true_false_without_options_has_an_objective_verdict(kind, expected, answer, correct):
    entry = {"question_type": kind, "options_json": "{}", "correct_answer": expected}
    assert check_answer(entry, answer) is correct


@pytest.mark.parametrize("expected", ["", None, "maybe", "A", []])
def test_invalid_true_false_reference_remains_ungraded(expected):
    entry = {"question_type": "concept", "options": {}, "correct_answer": expected}
    assert check_answer(entry, "true") is None


@pytest.mark.parametrize("kind", ["qualitative", "short_answer", "essay", "free_response"])
def test_qualitative_answers_keep_self_assessment(kind):
    assert check_answer({"question_type": kind, "correct_answer": "true"}, "true") is None


def test_existing_option_grading_and_legacy_concept_options_are_unchanged():
    options = {"A": "false", "B": "true"}
    for kind in ["single_choice", "concept", "true_false"]:
        entry = {"question_type": kind, "options": options, "correct_answer": "B"}
        assert check_answer(entry, "B") is True
        assert check_answer(entry, "false") is False
    entry = {
        "question_type": "multi_choice",
        "options": {"A": "2", "B": "4", "C": "3"},
        "correct_answer": "A,C",
    }
    assert check_answer(entry, "CA") is True
    assert check_answer(entry, "A") is False
