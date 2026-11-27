"""Deterministic scoring: the arithmetic of an exam, and nothing else.

Why this module is pure
-----------------------
Nothing here touches a database, a clock, or a model. Every function takes the
frozen snapshot of what was asked and what was answered, and returns numbers.
That is what makes the roadmap's hardest acceptance criterion provable:

    "a previous score must not change when the question bank or the scoring
    policy changes"

If scoring reads live rows, that criterion is a promise. If scoring is a pure
function of a snapshot, it is a property of the code -- and a test can hand it
the same snapshot twice, with the bank rewritten in between, and assert the
output is identical.

Why negative marking is a ratio, not a number
---------------------------------------------
The Konkur rule is "one third of the question's points per wrong answer". Stored
as a fixed 0.33 it would be wrong for a question worth 2 points, and wrong again
for a 4-choice question scored by a different rule. As a ratio it is correct for
any weight, which is why `negative_ratio` is a fraction of the item's points.

Why a broken question is voided, not failed
-------------------------------------------
A question with no valid answer key cannot be graded. Failing the entire exam
over it punishes the student for the bank's defect; grading it as wrong is
worse, because it is a fabricated verdict. Voiding removes it from both the
numerator and the denominator, so the remaining score is still meaningful, and
the attempt is flagged for review rather than silently cleaned up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: Outcomes a single item can reach.
OUTCOME_CORRECT = "correct"
OUTCOME_WRONG = "wrong"
OUTCOME_BLANK = "blank"
OUTCOME_VOIDED = "voided"
OUTCOME_NEEDS_REVIEW = "needs_review"
OUTCOME_PARTIAL = "partial"

#: Question types this scorer understands.
TYPE_MULTIPLE_CHOICE = "multiple_choice"
TYPE_ESSAY = "essay"
TYPE_SHORT_ANSWER = "short_answer"

VALID_TYPES = frozenset({TYPE_MULTIPLE_CHOICE, TYPE_ESSAY, TYPE_SHORT_ANSWER})


class ScoringError(ValueError):
    """The snapshot cannot be scored as given."""

    def __init__(self, rule: str, detail: str) -> None:
        self.rule = rule
        self.detail = detail
        super().__init__(f"{rule}: {detail}")


@dataclass(frozen=True)
class Policy:
    """The scoring rules, frozen into an attempt at submission."""

    negative_ratio: float = 0.0
    blank_is_neutral: bool = True
    broken_question_policy: str = "void"
    essay_min_ratio: float = 0.0
    essay_max_ratio: float = 1.0
    allow_partial_credit: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Policy":
        data = data or {}
        policy = cls(
            negative_ratio=float(data.get("negative_ratio", 0.0)),
            blank_is_neutral=bool(int(data.get("blank_is_neutral", 1))),
            broken_question_policy=str(data.get("broken_question_policy", "void")),
            essay_min_ratio=float(data.get("essay_min_ratio", 0.0)),
            essay_max_ratio=float(data.get("essay_max_ratio", 1.0)),
            allow_partial_credit=bool(int(data.get("allow_partial_credit", 1))),
        )
        policy.validate()
        return policy

    def validate(self) -> None:
        if not 0.0 <= self.negative_ratio <= 1.0:
            raise ScoringError("invalid_negative_ratio", "must be between 0 and 1")
        if not 0.0 <= self.essay_min_ratio <= self.essay_max_ratio <= 1.0:
            raise ScoringError(
                "invalid_essay_bounds",
                "essay_min_ratio must be <= essay_max_ratio, both within [0, 1]",
            )
        if self.broken_question_policy not in {"void", "fail_exam"}:
            raise ScoringError("invalid_broken_policy", "must be 'void' or 'fail_exam'")


@dataclass
class ItemResult:
    question_id: str
    question_version: int
    position: int
    outcome: str
    answer: str
    points_awarded: float
    points_possible: float
    rubric_result: str = ""
    graded_by: str = "auto"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question_version": self.question_version,
            "position": self.position,
            "outcome": self.outcome,
            "answer": self.answer,
            "points_awarded": self.points_awarded,
            "points_possible": self.points_possible,
            "rubric_result": self.rubric_result,
            "graded_by": self.graded_by,
            "detail": self.detail,
        }


@dataclass
class ExamResult:
    score: float = 0.0
    max_score: float = 0.0
    correct_count: int = 0
    wrong_count: int = 0
    blank_count: int = 0
    voided_count: int = 0
    needs_review_count: int = 0
    grading_status: str = "graded"
    review_required: bool = False
    items: list[ItemResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 6),
            "max_score": round(self.max_score, 6),
            "correct_count": self.correct_count,
            "wrong_count": self.wrong_count,
            "blank_count": self.blank_count,
            "voided_count": self.voided_count,
            "needs_review_count": self.needs_review_count,
            "grading_status": self.grading_status,
            "review_required": self.review_required,
            "items": [item.as_dict() for item in self.items],
            "warnings": list(self.warnings),
        }


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_answer(value: Any) -> str:
    """A comparison key for a free-text answer.

    Collapsing whitespace and case is the minimum needed for "  B " and "b" to
    be the same answer. It deliberately does *not* try to be clever about
    synonyms: an automatic scorer that guesses at meaning is how a correct
    answer gets marked wrong.
    """
    return " ".join(str(value or "").split()).strip().lower()


def _choice_index(question: Mapping[str, Any], answer: str) -> int | None:
    """Resolve an answer to a zero-based choice index, or None if it is not one.

    Accepts the index ("2"), the letter ("C", "c"), and the choice text itself,
    because all three arrive from real clients. Persian/Arabic digits are folded
    first: a mobile keyboard emits ۲ where the bank stores 2.
    """
    if not answer:
        return None
    text = answer.strip()
    folded = text.translate(_DIGIT_FOLD).lower()
    choices = _split_choices(question.get("choices") or "")

    # 1. An exact choice text wins, before any positional reading.
    #
    # This ordering matters when the choices *are* numerals, which is normal in
    # a maths exam: with choices ["۳","۴","۵","۶"] and an answer of "۳", the
    # student selected the first choice. Reading it as "index 3" instead would
    # silently mark a correct answer wrong, and `_choice_index` looked up the
    # index before the text until a live test caught the score coming out as
    # 2.0001 instead of 6.0.
    normalised = _normalise_answer(text)
    for index, choice in enumerate(choices):
        if _normalise_answer(choice) == normalised:
            return index

    # 2. A bare index.
    if folded.isdigit():
        index = int(folded)
        return index if 0 <= index < len(choices) else None

    # 3. A bare Latin letter: A=0, B=1, ...
    if len(folded) == 1 and folded.isascii() and folded.isalpha():
        index = ord(folded) - ord("a")
        return index if 0 <= index < len(choices) else None

    # 4. A Persian answer-sheet label. A Persian-language paper is labelled
    # الف/ب/ج/د, not A/B/C/D, so a UI that renders Persian labels must be able
    # to submit them; without this every answer from such a form graded as
    # wrong, silently. «الف» is three characters, so both forms are handled.
    persian_index = _persian_letter_index(text)
    if persian_index is not None:
        return persian_index if persian_index < len(choices) else None

    return None


#: Persian answer-sheet letters. «آ» is not used as a choice label, so «الف»
#: starts the sequence. Ordered longest-first within the alternation is
#: unnecessary here because each alternative is a single distinct character.
#: Persian answer-sheet letters in order. The index in this string *is* the
#: choice index, so an ordered sequence is all the lookup needs.
_PERSIAN_LETTERS = "ابجدهوزحطیکلمنسعغفصدذثض"

#: Spelled-out forms. «الف» is the first label on a Persian answer sheet and is
#: the only one normally written in full; the rest are single letters.
_PERSIAN_SPELLED = {"الف": 0, "آ": 0}


def _persian_letter_index(text: str) -> int | None:
    """Resolve a Persian choice label to its zero-based index."""
    cleaned = text.strip()
    if cleaned in _PERSIAN_SPELLED:
        return _PERSIAN_SPELLED[cleaned]
    if len(cleaned) == 1:
        index = _PERSIAN_LETTERS.find(cleaned)
        if index >= 0:
            return index
    return None

#: Persian and Arabic-Indic digits to ASCII, so "۲" and "2" compare equal.
_DIGIT_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _split_choices(raw: str) -> list[str]:
    return [line for line in str(raw or "").split("\n") if line.strip()]


def grade_multiple_choice(
    question: Mapping[str, Any], answer: Any, *, points: float, policy: Policy
) -> ItemResult:
    """Grade one multiple-choice item.

    The four cases the roadmap names, each with its own branch and its own test:
    a right answer, a wrong answer, a blank answer, and a question with no valid
    key.
    """
    question_id = str(question.get("question_id") or "")
    version = int(question.get("version") or 1)
    position = int(question.get("position") or 0)
    submitted = _normalise_answer(answer)

    key_status = str(question.get("key_status") or "valid")
    if key_status != "valid":
        # No valid key: this question cannot be answered correctly by anybody.
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_VOIDED,
            answer=str(answer or ""),
            points_awarded=0.0,
            points_possible=0.0,
            detail=f"key_status={key_status}",
        )

    if not submitted:
        # Blank. Neutral by default; penalised only if the policy says so.
        if policy.blank_is_neutral:
            return ItemResult(
                question_id=question_id,
                question_version=version,
                position=position,
                outcome=OUTCOME_BLANK,
                answer="",
                points_awarded=0.0,
                points_possible=points,
            )
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_WRONG,
            answer="",
            points_awarded=-points * policy.negative_ratio,
            points_possible=points,
            detail="blank treated as wrong by policy",
        )

    key_index = _choice_index(question, str(question.get("answer_key") or ""))
    if key_index is None:
        # A key that cannot be resolved is not a key. Treating it as valid would
        # let a malformed bank produce confident wrong verdicts.
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_VOIDED,
            answer=str(answer or ""),
            points_awarded=0.0,
            points_possible=0.0,
            detail="answer_key does not resolve to a choice",
        )

    submitted_index = _choice_index(question, str(answer))
    if submitted_index == key_index:
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_CORRECT,
            answer=str(answer),
            points_awarded=points,
            points_possible=points,
        )

    return ItemResult(
        question_id=question_id,
        question_version=version,
        position=position,
        outcome=OUTCOME_WRONG,
        answer=str(answer),
        points_awarded=-points * policy.negative_ratio,
        points_possible=points,
    )


def grade_essay(
    question: Mapping[str, Any],
    answer: Any,
    *,
    points: float,
    policy: Policy,
    awarded_ratio: float | None = None,
    graded_by: str = "auto",
) -> ItemResult:
    """Grade one essay item.

    An essay is never graded to a *definitive* verdict automatically. Without a
    human or a rubric score it is `needs_review`, which keeps the roadmap's
    "prevent definitive grading of a broken / unkeyed question" honest for the
    open-ended case as well: an LLM guess recorded as a final score is the same
    class of defect as a missing answer key.
    """
    question_id = str(question.get("question_id") or "")
    version = int(question.get("version") or 1)
    position = int(question.get("position") or 0)

    key_status = str(question.get("key_status") or "valid")
    if key_status != "valid":
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_VOIDED,
            answer=str(answer or ""),
            points_awarded=0.0,
            points_possible=0.0,
            detail=f"key_status={key_status}",
        )

    if not str(answer or "").strip():
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_BLANK,
            answer="",
            points_awarded=0.0,
            points_possible=points,
        )

    if awarded_ratio is None:
        return ItemResult(
            question_id=question_id,
            question_version=version,
            position=position,
            outcome=OUTCOME_NEEDS_REVIEW,
            answer=str(answer),
            points_awarded=0.0,
            points_possible=points,
            graded_by=graded_by,
            detail="essay awaiting human or rubric score",
        )

    ratio = float(awarded_ratio)
    if not policy.allow_partial_credit and ratio not in {0.0, 1.0}:
        raise ScoringError(
            "partial_credit_disabled",
            f"ratio {ratio} is neither 0 nor 1 and this policy forbids partial credit",
        )
    # Clamp to the policy's floor and ceiling rather than rejecting: a rubric is
    # allowed to be generous or harsh, but the policy's bounds are absolute.
    ratio = max(policy.essay_min_ratio, min(policy.essay_max_ratio, ratio))
    awarded = points * ratio
    if ratio >= 1.0:
        outcome = OUTCOME_CORRECT
    elif ratio <= 0.0:
        outcome = OUTCOME_WRONG
    else:
        outcome = OUTCOME_PARTIAL
    return ItemResult(
        question_id=question_id,
        question_version=version,
        position=position,
        outcome=outcome,
        answer=str(answer),
        points_awarded=awarded,
        points_possible=points,
        graded_by=graded_by,
    )


def grade_exam(
    questions: Sequence[Mapping[str, Any]],
    answers: Mapping[str, Any] | Sequence[Any] | None,
    *,
    policy: Policy | Mapping[str, Any] | None = None,
    essay_scores: Mapping[str, float] | None = None,
) -> ExamResult:
    """Grade a whole exam from a frozen snapshot.

    ``questions`` is the snapshot: each item already carries its own
    ``question_id``, ``version``, ``position``, ``points`` and ``answer_key``.
    Nothing is looked up. Grading the same snapshot twice, before and after the
    bank changes, must produce the same numbers -- a test asserts exactly that.
    """
    if isinstance(policy, Mapping) or policy is None:
        policy = Policy.from_mapping(policy)
    else:
        policy.validate()

    answers = answers or {}
    if isinstance(answers, Mapping):

        def answer_for(qid: str, position: int) -> Any:
            # Position is the fallback key because a client that submits a list
            # has no question ids at all, and a position is still unambiguous
            # within one frozen snapshot.
            if qid in answers:
                return answers[qid]
            return answers.get(str(position), "")
    else:

        def answer_for(qid: str, position: int) -> Any:
            return answers[position] if position < len(answers) else ""

    result = ExamResult()
    essay_scores = essay_scores or {}

    # Sort by position so the item log reads in exam order regardless of how
    # the snapshot was assembled.
    ordered = sorted(questions, key=lambda q: int(q.get("position") or 0))

    for question in ordered:
        qid = str(question.get("question_id") or "")
        question_type = str(question.get("question_type") or TYPE_MULTIPLE_CHOICE)
        if question_type not in VALID_TYPES:
            raise ScoringError(
                "unknown_question_type",
                f"question {qid!r} has type {question_type!r}",
            )

        points = _as_float(question.get("points"), default=1.0)
        if points <= 0:
            raise ScoringError("invalid_points", f"question {qid!r} has non-positive points")

        answer = answer_for(qid, int(question.get("position") or 0))

        if question_type == TYPE_MULTIPLE_CHOICE:
            item = grade_multiple_choice(question, answer, points=points, policy=policy)
        else:
            item = grade_essay(
                question,
                answer,
                points=points,
                policy=policy,
                awarded_ratio=essay_scores.get(qid),
            )

        result.items.append(item)
        if item.outcome == OUTCOME_CORRECT:
            result.correct_count += 1
        elif item.outcome == OUTCOME_WRONG:
            result.wrong_count += 1
        elif item.outcome == OUTCOME_BLANK:
            result.blank_count += 1
        elif item.outcome == OUTCOME_VOIDED:
            result.voided_count += 1
        elif item.outcome == OUTCOME_NEEDS_REVIEW:
            result.needs_review_count += 1
        # A partially credited essay counts as neither correct nor wrong: it is
        # not a binary verdict and pretending otherwise would misreport accuracy.

        if item.outcome != OUTCOME_VOIDED:
            result.score += item.points_awarded
            result.max_score += item.points_possible

    # A voided question always needs a human to look, because a question that
    # could not be graded is a defect in the exam, not in the student's answer.
    # Under 'fail_exam' the whole attempt is ungradeable; under 'void' the score
    # is usable but the defect is still recorded. Both flag review; the
    # difference is the warning, not whether anybody is told.
    if result.voided_count:
        result.review_required = True
        result.grading_status = "needs_review"
    elif result.needs_review_count:
        result.grading_status = "needs_review"
        result.review_required = True
    else:
        result.grading_status = "graded"

    if result.voided_count and policy.broken_question_policy == "void":
        result.warnings.append(
            f"{result.voided_count} question(s) were voided and excluded from the score"
        )

    # A float sum of many thirds accumulates representation error; rounding at
    # the end keeps a reported score from reading 6.999999999.
    result.score = round(result.score, 6)
    result.max_score = round(result.max_score, 6)
    return result
