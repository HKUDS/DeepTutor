"""Deterministic scoring: the arithmetic, tested as arithmetic.

The roadmap asks for "unit and property tests for the score formula and its edge
cases", and the property tests carry most of the weight here. A unit test checks
one example; a property test checks a statement that must hold for *every*
input, which is what a score formula actually needs to be trustworthy.

The three properties that matter:

1. **Boundedness** — a score can never exceed the maximum, however the student
   answers, and can never fall below the worst case the policy allows.
2. **Monotonicity** — replacing a wrong answer with the right one never lowers
   the score, under any policy.
3. **Snapshot determinism** — the same snapshot always produces the same score,
   independent of how many times it is graded.
"""

from __future__ import annotations

import itertools
import random

import pytest

from deeptutor.services.exam.scoring import (
    Policy,
    ScoringError,
    grade_exam,
    grade_multiple_choice,
)


def _q(qid="q1", *, key="1", points=3.0, choices="a\nb\nc\nd", key_status="valid", position=0):
    return {
        "question_id": qid,
        "version": 1,
        "position": position,
        "question_type": "multiple_choice",
        "choices": choices,
        "answer_key": key,
        "key_status": key_status,
        "points": points,
    }


# ---------------------------------------------------------------------------
# The four basic cases the roadmap names
# ---------------------------------------------------------------------------


def test_a_correct_answer_earns_full_points():
    result = grade_exam([_q()], {"q1": "1"}, policy=Policy(negative_ratio=1 / 3))
    assert result.score == 3.0
    assert result.correct_count == 1
    assert result.items[0].outcome == "correct"


def test_a_wrong_answer_costs_a_third_under_konkur():
    result = grade_exam([_q()], {"q1": "0"}, policy=Policy(negative_ratio=1 / 3))
    assert result.score == pytest.approx(-1.0)
    assert result.wrong_count == 1
    assert result.items[0].outcome == "wrong"


def test_a_blank_answer_is_neutral_by_default():
    """Konkur leaves a blank alone; it is not a wrong answer."""
    result = grade_exam([_q()], {"q1": ""}, policy=Policy(negative_ratio=1 / 3))
    assert result.score == 0.0
    assert result.blank_count == 1
    assert result.items[0].outcome == "blank"


def test_a_blank_answer_can_be_penalised_when_the_policy_says_so():
    """Off by default, available when a policy wants it."""
    result = grade_exam(
        [_q()],
        {"q1": ""},
        policy=Policy(negative_ratio=1 / 3, blank_is_neutral=False),
    )
    assert result.score == pytest.approx(-1.0)
    assert result.wrong_count == 1


def test_a_question_with_no_valid_key_is_voided():
    """Not wrong, not correct: excluded, because nobody could answer it."""
    result = grade_exam([_q(key_status="broken")], {"q1": "1"})
    assert result.voided_count == 1
    assert result.score == 0.0
    assert result.max_score == 0.0
    assert result.review_required is True


def test_a_missing_key_voids_the_item():
    result = grade_exam([_q(key_status="missing")], {"q1": "1"})
    assert result.voided_count == 1
    assert result.items[0].outcome == "voided"


def test_an_unresolvable_key_voids_the_item():
    """A key that is not one of the choices cannot be a key."""
    result = grade_exam([_q(key="9")], {"q1": "1"})
    assert result.voided_count == 1
    assert "does not resolve" in result.items[0].detail


def test_broken_question_policy_fail_exam_marks_the_attempt_for_review():
    result = grade_exam(
        [_q(key_status="broken"), _q("q2", key="0", position=1)],
        {"q1": "1", "q2": "0"},
        policy=Policy(broken_question_policy="fail_exam"),
    )
    assert result.grading_status == "needs_review"
    assert result.review_required is True
    assert result.score == 3.0  # the good question still counts


# ---------------------------------------------------------------------------
# Answer forms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    ["1", "b", "B", " b ", "ب"],
)
def test_every_accepted_answer_form_resolves_identically(answer):
    """An index, a letter, the choice text and Persian digits all mean b.

    Real clients send all of these: a web form sends the index, a printed answer
    sheet sends a letter, and a Persian answer sheet sends «ب». (Persian digits
    are covered separately: ۲ means index 2, which is not the key here.)
    """
    result = grade_exam([_q()], {"q1": answer})
    assert result.correct_count == 1, answer


def test_a_choice_that_is_not_a_choice_does_not_match():
    result = grade_exam([_q()], {"q1": "z"})
    assert result.wrong_count == 1


def test_answers_by_position_work_for_clients_that_send_a_list():
    questions = [_q("q1", position=0), _q("q2", key="0", position=1)]
    result = grade_exam(questions, ["1", "0"])
    assert result.correct_count == 2
    assert result.score == 6.0


def test_a_short_answer_list_leaves_the_rest_blank():
    questions = [_q("q1", position=0), _q("q2", key="0", position=1)]
    result = grade_exam(questions, ["1"])
    assert result.correct_count == 1
    assert result.blank_count == 1


# ---------------------------------------------------------------------------
# Negative marking: the specific rule the roadmap calls out
# ---------------------------------------------------------------------------


def test_three_wrong_and_one_right_only_works_when_the_policy_is_active():
    """The roadmap's explicit case.

    With negative marking off, one right out of four is a positive score. With
    it on at 1/3, one right and three wrong nets to zero -- and the difference
    between those two numbers is the whole reason the policy is per-exam.
    """
    # Four *distinct* questions. The first draft reused the id "q1", which made
    # the duplicate overwrite its twin and left only three items -- the test
    # then failed for a reason unrelated to what it was checking.
    questions = [_q(f"q{i}", key="0", position=i) for i in range(4)]
    answers = {"q0": "0", "q1": "1", "q2": "1", "q3": "1"}  # 1 right, 3 wrong

    no_penalty = grade_exam(questions, answers, policy=Policy(negative_ratio=0.0))
    assert no_penalty.score == 3.0

    konkur = grade_exam(questions, answers, policy=Policy(negative_ratio=1 / 3))
    assert konkur.score == pytest.approx(0.0)


def test_negative_marking_scales_with_the_item_weight():
    """The penalty is a ratio, so a heavier question costs proportionally more."""
    light = grade_exam([_q(points=1.0)], {"q1": "0"}, policy=Policy(negative_ratio=1 / 3))
    heavy = grade_exam([_q(points=9.0)], {"q1": "0"}, policy=Policy(negative_ratio=1 / 3))
    assert light.score == pytest.approx(-1 / 3)
    assert heavy.score == pytest.approx(-3.0)


def test_a_two_choice_question_can_use_a_half_penalty():
    """The rule is not hard-coded to thirds."""
    result = grade_exam(
        [_q(choices="بله\nخیر", key="0", points=2.0)],
        {"q1": "1"},
        policy=Policy(negative_ratio=0.5),
    )
    assert result.score == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# Essays
# ---------------------------------------------------------------------------


def _essay(**kwargs):
    base = {
        "question_id": "e1",
        "version": 1,
        "position": 0,
        "question_type": "essay",
        "body": "توضیح دهید",
        "choices": "",
        "answer_key": "پاسخ مرجع",
        "key_status": "valid",
        "rubric": "دقت: ۵ / ساختار: ۵",
        "points": 10.0,
    }
    base.update(kwargs)
    return base


def test_an_essay_without_a_score_needs_review():
    """Never a definitive verdict on open text without a human or a rubric."""
    result = grade_exam([_essay()], {"e1": "پاسخ دانش‌آموز"})
    assert result.needs_review_count == 1
    assert result.grading_status == "needs_review"
    assert result.review_required is True


def test_an_essay_with_a_rubric_ratio_gets_partial_credit():
    result = grade_exam([_essay()], {"e1": "پاسخ"}, essay_scores={"e1": 0.7})
    assert result.score == pytest.approx(7.0)
    assert result.items[0].outcome == "partial"


def test_a_full_mark_essay_is_correct():
    result = grade_exam([_essay()], {"e1": "پاسخ"}, essay_scores={"e1": 1.0})
    assert result.items[0].outcome == "correct"
    assert result.score == 10.0


def test_a_zero_mark_essay_is_wrong_not_blank():
    """The student wrote something; a zero from the rubric is a verdict, not silence."""
    result = grade_exam([_essay()], {"e1": "پاسخ"}, essay_scores={"e1": 0.0})
    assert result.items[0].outcome == "wrong"
    assert result.blank_count == 0


def test_a_blank_essay_is_blank():
    result = grade_exam([_essay()], {"e1": "   "})
    assert result.blank_count == 1


def test_the_essay_floor_and_ceiling_clamp_the_rubric():
    """A rubric may not award more than the policy allows, nor less than its floor."""
    policy = Policy(essay_min_ratio=0.2, essay_max_ratio=0.8)
    high = grade_exam([_essay()], {"e1": "پاسخ"}, policy=policy, essay_scores={"e1": 1.0})
    low = grade_exam([_essay()], {"e1": "پاسخ"}, policy=policy, essay_scores={"e1": 0.0})
    assert high.score == pytest.approx(8.0)
    assert low.score == pytest.approx(2.0)


def test_partial_credit_can_be_forbidden():
    policy = Policy(allow_partial_credit=False)
    with pytest.raises(ScoringError) as exc:
        grade_exam([_essay()], {"e1": "پاسخ"}, policy=policy, essay_scores={"e1": 0.5})
    assert exc.value.rule == "partial_credit_disabled"


def test_a_broken_essay_key_is_voided_not_graded():
    result = grade_exam([_essay(key_status="broken")], {"e1": "پاسخ"}, essay_scores={"e1": 1.0})
    assert result.voided_count == 1


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,rule",
    [
        ({"negative_ratio": -0.1}, "invalid_negative_ratio"),
        ({"negative_ratio": 1.5}, "invalid_negative_ratio"),
        ({"essay_min_ratio": 0.9, "essay_max_ratio": 0.5}, "invalid_essay_bounds"),
        ({"essay_max_ratio": 2.0}, "invalid_essay_bounds"),
        ({"broken_question_policy": "ignore"}, "invalid_broken_policy"),
    ],
)
def test_an_invalid_policy_is_refused(kwargs, rule):
    with pytest.raises(ScoringError) as exc:
        Policy.from_mapping(kwargs)
    assert exc.value.rule == rule


def test_scoring_refuses_a_non_positive_point_value():
    with pytest.raises(ScoringError) as exc:
        grade_exam([_q(points=0.0)], {"q1": "1"})
    assert exc.value.rule == "invalid_points"


def test_scoring_refuses_an_unknown_question_type():
    question = {**_q(), "question_type": "matching"}
    with pytest.raises(ScoringError) as exc:
        grade_exam([question], {"q1": "1"})
    assert exc.value.rule == "unknown_question_type"


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def _random_exam(rng: random.Random, count: int) -> list[dict]:
    return [
        _q(
            f"q{i}",
            key=str(rng.randrange(4)),
            points=rng.choice([1.0, 2.0, 3.0, 4.0]),
            position=i,
        )
        for i in range(count)
    ]


def test_property_score_never_exceeds_the_maximum():
    """For every combination of answers, score <= max_score.

    Exhaustive for small exams rather than random: the space of answers for a
    3-question 4-choice exam is 5^3 (including blank), which is small enough to
    prove rather than sample.
    """
    questions = [_q(f"q{i}", key="0", position=i, points=3.0) for i in range(3)]
    options = ["0", "1", ""]
    for combo in itertools.product(options, repeat=3):
        answers = {f"q{i}": combo[i] for i in range(3)}
        result = grade_exam(questions, answers, policy=Policy(negative_ratio=0.0))
        assert result.score <= result.max_score + 1e-9, combo
        assert result.max_score == 9.0


def test_property_a_right_answer_never_scores_worse_than_a_wrong_one():
    """Monotonicity, under every negative ratio.

    This is the property that makes negative marking safe: it changes the
    *magnitude* of the difference between right and wrong, never the *direction*.
    """
    for ratio in (0.0, 1 / 4, 1 / 3, 1 / 2, 1.0):
        policy = Policy(negative_ratio=ratio)
        questions = [_q(key="1")]
        right = grade_exam(questions, {"q1": "1"}, policy=policy).score
        wrong = grade_exam(questions, {"q1": "0"}, policy=policy).score
        blank = grade_exam(questions, {"q1": ""}, policy=policy).score
        assert right >= wrong, ratio
        assert right >= blank, ratio


def test_property_the_worst_possible_score_is_bounded():
    """A student cannot lose more than the penalty for every question."""
    rng = random.Random(1234)
    for _ in range(50):
        questions = _random_exam(rng, rng.randrange(1, 6))
        ratio = rng.choice([0.0, 1 / 3, 0.5])
        answers = {q["question_id"]: str((int(q["answer_key"]) + 1) % 4) for q in questions}
        result = grade_exam(questions, answers, policy=Policy(negative_ratio=ratio))
        # The reported score is rounded to 6 places, so a bound computed in full
        # float precision can differ by up to 5e-7. Comparing at 1e-6 is a
        # tolerance on the *reporting*, not a weakening of the bound.
        worst = -sum(q["points"] for q in questions) * ratio
        assert result.score >= worst - 1e-6, (questions, ratio)


def test_property_grading_is_deterministic():
    """The same snapshot graded repeatedly gives the same numbers.

    This is the property the immutability requirement ultimately rests on: if
    grading were not a function of its input, a stored score could not be
    reproduced and "regrade" would silently mean "recompute differently".
    """
    rng = random.Random(99)
    for _ in range(30):
        questions = _random_exam(rng, rng.randrange(1, 5))
        answers = {q["question_id"]: rng.choice(["0", "1", "2", "3", ""]) for q in questions}
        policy = Policy(negative_ratio=rng.choice([0.0, 1 / 3]))
        first = grade_exam(questions, answers, policy=policy)
        second = grade_exam(questions, answers, policy=policy)
        assert first.as_dict() == second.as_dict()


def test_property_the_order_of_questions_does_not_change_the_score():
    """Position affects order, never the total."""
    questions = [
        _q("q1", key="1", position=0, points=2.0),
        _q("q2", key="3", position=1, points=5.0),
    ]
    answers = {"q1": "1", "q2": "0"}
    forward = grade_exam(questions, answers, policy=Policy(negative_ratio=1 / 3))
    backward = grade_exam(list(reversed(questions)), answers, policy=Policy(negative_ratio=1 / 3))
    assert forward.score == backward.score
    assert forward.max_score == backward.max_score


def test_property_item_points_sum_to_the_total():
    """The reported total equals the sum of the items, always.

    A total that disagrees with its own breakdown is the kind of bug that is
    only found by an audit, so it is asserted rather than assumed.
    """
    rng = random.Random(7)
    for _ in range(40):
        questions = _random_exam(rng, rng.randrange(1, 6))
        answers = {q["question_id"]: rng.choice(["0", "1", "2", "3", ""]) for q in questions}
        result = grade_exam(questions, answers, policy=Policy(negative_ratio=1 / 3))
        item_sum = sum(item.points_awarded for item in result.items)
        assert result.score == pytest.approx(round(item_sum, 6))


# ---------------------------------------------------------------------------
# Mixed exams
# ---------------------------------------------------------------------------


def test_a_mixed_exam_counts_each_outcome_once():
    questions = [
        _q("q1", key="0", position=0),
        _q("q2", key="0", position=1),
        _q("q3", key="0", position=2),
        {**_essay(), "question_id": "e1", "position": 3},
        _q("q4", key="0", position=4, key_status="broken"),
    ]
    result = grade_exam(
        questions,
        {"q1": "0", "q2": "1", "q3": "", "e1": "پاسخ"},
        policy=Policy(negative_ratio=1 / 3),
    )
    assert result.correct_count == 1
    assert result.wrong_count == 1
    assert result.blank_count == 1
    assert result.needs_review_count == 1
    assert result.voided_count == 1
    assert result.review_required is True


def test_a_partially_credited_essay_is_not_counted_as_correct_or_wrong():
    """A partial verdict is not a binary one; counting it either way misreports accuracy."""
    questions = [{**_essay(), "question_id": "e1"}]
    result = grade_exam(questions, {"e1": "پاسخ"}, essay_scores={"e1": 0.5})
    assert result.correct_count == 0
    assert result.wrong_count == 0
    assert result.items[0].outcome == "partial"
    assert result.score == pytest.approx(5.0)


def test_a_negative_total_is_reported_as_is():
    """Konkur allows a negative score; clamping it to zero would hide the penalty."""
    questions = [_q("q1", key="0", position=0, points=3.0)]
    result = grade_exam(questions, {"q1": "2"}, policy=Policy(negative_ratio=1.0))
    assert result.score == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# Regressions found by a live end-to-end run, not by unit tests
# ---------------------------------------------------------------------------


def test_a_numeric_choice_text_wins_over_a_numeric_index():
    """Choices that are themselves numerals, which is the normal maths case.

    With choices ["۳","۴","۵","۶"] an answer of "۳" means *the first choice*.
    Reading it as "index 3" marks a correct answer wrong, and that is exactly
    what happened: the live exam scored 2.0001 where 6.0 was expected, because
    text lookup ran after index lookup. Found by exercising the HTTP endpoint,
    not by any unit test -- the unit tests used letters as choices.
    """
    question = _q(choices="۳\n۴\n۵\n۶", key="0")
    result = grade_exam([question], {"q1": "۳"})
    assert result.correct_count == 1
    assert result.score == 3.0


def test_a_numeric_text_answer_is_not_read_as_a_position():
    question = _q(choices="۳\n۴\n۵\n۶", key="3")
    # "۶" is the fourth choice; index 3 is also the fourth. Reading it as a
    # position would coincidentally pass here, so the key is chosen to make the
    # two readings differ: ۶ is index 3, but as a bare number 6 is out of range.
    assert grade_exam([question], {"q1": "۶"}).correct_count == 1


def test_a_persian_spelled_out_first_label_resolves():
    """«الف» is three characters and is the first label on a Persian paper."""
    question = _q(choices="تهران\nشیراز\nتبریز\nیزد", key="0")
    assert grade_exam([question], {"q1": "الف"}).correct_count == 1


def test_every_persian_label_resolves_in_order():
    question = _q(choices="a\nb\nc\nd", key="0")
    for index, label in enumerate("ابجد"):
        candidate = {**question, "answer_key": str(index)}
        assert grade_exam([candidate], {"q1": label}).correct_count == 1, label


def test_an_ascii_digit_answer_still_works_when_choices_are_letters():
    question = _q(choices="a\nb\nc\nd", key="2")
    assert grade_exam([question], {"q1": "2"}).correct_count == 1
