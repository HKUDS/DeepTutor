"""Exam center: bank versioning, blueprints, submission, immutability.

The roadmap's acceptance criteria are mostly about what must **not** happen :

* submitting twice must not create a second attempt or a second score;
* an old score must not change when the bank or the policy changes;
* a broken question must not be graded definitively.

Each of those is tested by doing the forbidden thing and asserting nothing
moved, because a test that only checks the happy path cannot distinguish "the
guard works" from "the situation never arose".
"""

from __future__ import annotations

import json

import pytest

from deeptutor.db.repositories import exam as repo
from deeptutor.services.exam.scoring import Policy


@pytest.fixture
def bank(db):
    return db


def _question(db, qid="q1", **kwargs):
    defaults = dict(
        question_id=qid,
        body="۲+۲ چند است؟",
        choices=["۳", "۴", "۵", "۶"],
        answer_key="1",
        points=3.0,
        chapter_title="فصل ۱: اعداد",
        topic="جمع",
        review_status="reviewed",
    )
    defaults.update(kwargs)
    return repo.create_question(db, repo.QuestionInput(**defaults))


@pytest.fixture
def exam_with_policy(bank):
    q1 = _question(bank, "q1")
    _question(
        bank,
        "q2",
        body="پایتخت ایران؟",
        choices=["تهران", "شیراز", "تبریز", "یزد"],
        answer_key="0",
        chapter_title="فصل ۲",
    )
    _question(bank, "q3", body="۱+۱؟", choices=["۱", "۲", "۳", "۴"], answer_key="1")
    policy = repo.create_policy(bank, name="کنکور", negative_ratio=1 / 3)
    exam = repo.create_exam(
        bank,
        title="آزمون ریاضی",
        items=[repo.ExamItemInput("q1"), repo.ExamItemInput("q2"), repo.ExamItemInput("q3")],
        policy_id=policy["id"],
        grade_number=10,
    )
    repo.publish_exam(bank, exam["id"])
    return bank, exam, policy


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------


def test_a_second_question_with_the_same_id_is_a_new_version(bank):
    """Editing a question creates version 2; it does not overwrite version 1."""
    _question(bank, "q1", answer_key="1")
    second = _question(bank, "q1", answer_key="2", body="بدنهٔ جدید")
    assert second["version"] == 2
    first = repo.get_question(bank, "q1", 1)
    assert first["answer_key"] == "1", "version 1 must be untouched"
    assert repo.get_question(bank, "q1")["version"] == 2


def test_a_multiple_choice_question_needs_an_answer_key(bank):
    with pytest.raises(repo.ExamError) as exc:
        repo.create_question(
            bank,
            repo.QuestionInput(question_id="x", body="بدون کلید", choices=["a", "b"]),
        )
    assert exc.value.rule == "missing_answer_key"


def test_a_question_can_be_recorded_as_missing_its_key_explicitly(bank):
    """The escape hatch: 'I know it has no key' is a state, not an error."""
    question = repo.create_question(
        bank,
        repo.QuestionInput(
            question_id="x",
            body="بدون کلید",
            choices=["a", "b"],
            key_status="missing",
        ),
    )
    assert question["key_status"] == "missing"


def test_a_choice_containing_a_newline_is_refused(bank):
    """The delimiter would split one choice into two and change the key's meaning."""
    with pytest.raises(repo.ExamError) as exc:
        repo.create_question(
            bank,
            repo.QuestionInput(
                question_id="x", body="بدنه", choices=["بله\nخیر", "شاید"], answer_key="0"
            ),
        )
    assert exc.value.rule == "choice_contains_delimiter"


def test_a_single_choice_question_is_refused(bank):
    with pytest.raises(repo.ExamError) as exc:
        repo.create_question(
            bank, repo.QuestionInput(question_id="x", body="ب", choices=["فقط یکی"], answer_key="0")
        )
    assert exc.value.rule == "too_few_choices"


@pytest.mark.parametrize(
    "field,value,rule",
    [
        ("question_type", "matching", "invalid_question_type"),
        ("key_status", "maybe", "invalid_key_status"),
        ("difficulty", "extreme", "invalid_difficulty"),
        ("review_status", "published", "invalid_review_status"),
        ("points", 0.0, "invalid_points"),
    ],
)
def test_invalid_question_fields_are_refused(bank, field, value, rule):
    kwargs = {
        "question_id": "x",
        "body": "ب",
        "choices": ["a", "b"],
        "answer_key": "0",
        field: value,
    }
    with pytest.raises(repo.ExamError) as exc:
        repo.create_question(bank, repo.QuestionInput(**kwargs))
    assert exc.value.rule == rule


def test_questions_can_be_listed_by_scope_and_review_status(bank):
    _question(bank, "q1", grade_number=10, review_status="reviewed")
    _question(bank, "q2", grade_number=12, review_status="draft")
    assert len(repo.list_questions(bank, grade_number=10)) == 1
    assert len(repo.list_questions(bank, review_status="draft")) == 1
    assert len(repo.list_questions(bank)) == 2


def test_listing_returns_only_the_latest_version_by_default(bank):
    _question(bank, "q1", answer_key="1")
    _question(bank, "q1", answer_key="2")
    latest = repo.list_questions(bank)
    assert len(latest) == 1
    assert latest[0]["version"] == 2
    assert len(repo.list_questions(bank, latest_only=False)) == 2


# ---------------------------------------------------------------------------
# Blueprint and Gate 6 validation
# ---------------------------------------------------------------------------


def test_an_exam_pins_question_versions_at_creation(bank):
    """An exam built from v1 must keep using v1 after v2 exists."""
    _question(bank, "q1", answer_key="1")
    exam = repo.create_exam(bank, title="t", items=[repo.ExamItemInput("q1")])
    _question(bank, "q1", answer_key="3")  # v2 published later
    reread = repo.get_exam(bank, exam["id"])
    assert reread["items"][0]["question_version"] == 1


def test_publishing_is_refused_while_a_question_is_unreviewed(bank):
    """Gate 6, enforced rather than reported."""
    _question(bank, "q1", review_status="draft")
    exam = repo.create_exam(bank, title="t", items=[repo.ExamItemInput("q1")])
    with pytest.raises(repo.ExamError) as exc:
        repo.publish_exam(bank, exam["id"])
    assert exc.value.rule == "unreviewed_questions"
    assert "q1@1" in exc.value.detail


def test_validation_reports_every_problem_not_just_the_first(bank):
    _question(bank, "q1", review_status="draft")
    _question(bank, "q2", key_status="missing", body="بی‌کلید", review_status="draft")
    exam = repo.create_exam(
        bank, title="t", items=[repo.ExamItemInput("q1"), repo.ExamItemInput("q2")]
    )
    report = repo.validate_exam(bank, exam["id"])
    kinds = {issue["kind"] for issue in report["issues"]}
    assert "unreviewed_question" in kinds
    assert "invalid_answer_key" in kinds
    assert report["valid"] is False


def test_a_blueprint_mismatch_is_reported(bank):
    _question(bank, "q1", difficulty="easy", chapter_title="فصل ۱")
    exam = repo.create_exam(
        bank,
        title="t",
        items=[repo.ExamItemInput("q1")],
        blueprint=[repo.Blueprint(difficulty="hard", count=1)],
    )
    report = repo.validate_exam(bank, exam["id"])
    assert any(issue["kind"] == "blueprint_mismatch" for issue in report["issues"])


def test_a_matching_blueprint_validates(bank):
    _question(bank, "q1", difficulty="easy", chapter_title="فصل ۱")
    exam = repo.create_exam(
        bank,
        title="t",
        items=[repo.ExamItemInput("q1")],
        blueprint=[repo.Blueprint(difficulty="easy", count=1)],
    )
    assert repo.validate_exam(bank, exam["id"])["valid"] is True


def test_an_exam_with_a_duplicate_question_is_refused(bank):
    _question(bank, "q1")
    with pytest.raises(repo.ExamError) as exc:
        repo.create_exam(
            bank, title="t", items=[repo.ExamItemInput("q1"), repo.ExamItemInput("q1")]
        )
    assert exc.value.rule == "duplicate_question"


def test_an_exam_with_no_items_is_refused(bank):
    with pytest.raises(repo.ExamError) as exc:
        repo.create_exam(bank, title="t", items=[])
    assert exc.value.rule == "empty_exam"


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def test_submitting_grades_immediately(exam_with_policy):
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "1", "q2": "0", "q3": ""}
    )
    assert attempt["status"] == "graded"
    assert attempt["score"] == 6.0
    assert attempt["max_score"] == 9.0
    assert attempt["correct_count"] == 2
    assert attempt["blank_count"] == 1
    assert len(attempt["items"]) == 3


def test_a_duplicate_submission_returns_the_same_attempt(exam_with_policy):
    """The roadmap's 'repeated submission must not create a second attempt'."""
    db, exam, _ = exam_with_policy
    answers = {"q1": "1", "q2": "0", "q3": "1"}
    first = repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers=answers)
    second = repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers=answers)

    assert second["id"] == first["id"]
    assert second["duplicate_submission"] is True
    assert second["score"] == first["score"]
    with db.read() as conn:
        count = conn.scalar(
            "SELECT COUNT(*) FROM exam_attempts WHERE exam_id = ? AND user_id = ?",
            (exam["id"], "u1"),
        )
    assert count == 1, "a retry must not create a second attempt"


def test_a_duplicate_submission_does_not_duplicate_item_rows(exam_with_policy):
    db, exam, _ = exam_with_policy
    answers = {"q1": "1", "q2": "0", "q3": "1"}
    first = repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers=answers)
    repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers=answers)
    with db.read() as conn:
        count = conn.scalar(
            "SELECT COUNT(*) FROM exam_attempt_items WHERE attempt_id = ?", (first["id"],)
        )
    assert count == 3


def test_different_answers_on_the_same_attempt_are_refused(exam_with_policy):
    """A second *different* submission is a conflict, not a silent overwrite."""
    db, exam, _ = exam_with_policy
    repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "1", "q2": "0", "q3": "1"}
    )
    with pytest.raises(repo.ExamError) as exc:
        repo.submit_exam(
            db, exam_id=exam["id"], user_id="u1", answers={"q1": "0", "q2": "0", "q3": "1"}
        )
    assert exc.value.rule == "attempt_already_submitted"


def test_a_deliberate_retake_uses_a_new_attempt_number(exam_with_policy):
    db, exam, _ = exam_with_policy
    first = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "0", "q2": "0", "q3": "0"}
    )
    second = repo.submit_exam(
        db,
        exam_id=exam["id"],
        user_id="u1",
        answers={"q1": "1", "q2": "0", "q3": "1"},
        attempt_no=2,
    )
    assert second["id"] != first["id"]
    assert second["attempt_no"] == 2
    assert second["score"] == 9.0
    assert first["score"] != second["score"]


def test_two_students_get_separate_attempts(exam_with_policy):
    db, exam, _ = exam_with_policy
    a = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "1", "q2": "0", "q3": "1"}
    )
    b = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u2", answers={"q1": "1", "q2": "0", "q3": "1"}
    )
    assert a["id"] != b["id"]


def test_an_archived_exam_cannot_be_attempted(exam_with_policy):
    db, exam, _ = exam_with_policy
    with db.transaction() as conn:
        conn.execute("UPDATE exams SET status = 'archived' WHERE id = ?", (exam["id"],))
    with pytest.raises(repo.ExamError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers={})
    assert exc.value.rule == "exam_not_open"


def test_an_invalid_attempt_number_is_refused(exam_with_policy):
    db, exam, _ = exam_with_policy
    with pytest.raises(repo.ExamError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers={}, attempt_no=0)
    assert exc.value.rule == "invalid_attempt"


# ---------------------------------------------------------------------------
# THE immutability criterion
# ---------------------------------------------------------------------------


def test_a_past_score_does_not_change_when_the_bank_changes(exam_with_policy):
    """The roadmap's hardest criterion, tested by attacking it.

    A new version of every question is published with different answer keys and
    different point values, and the stored attempt is re-read. If grading ever
    consulted the bank instead of the snapshot, this is the test that fails.
    """
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "1", "q2": "0", "q3": "1"}
    )
    original = attempt["score"]
    assert original == 9.0

    # Rewrite the whole bank: every key points somewhere else, every weight
    # changes, and the body text is replaced.
    _question(db, "q1", answer_key="3", points=10.0, body="بدنهٔ عوض‌شده")
    _question(db, "q2", answer_key="3", points=10.0, body="بدنهٔ عوض‌شده")
    _question(db, "q3", answer_key="3", points=10.0, body="بدنهٔ عوض‌شده")

    reread = repo.get_attempt(db, attempt["id"])
    assert reread["score"] == original
    assert reread["max_score"] == attempt["max_score"]


def test_a_past_score_does_not_change_when_the_policy_changes(exam_with_policy):
    """A new scoring policy must not retroactively penalise an old attempt."""
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "0", "q2": "0", "q3": "1"}
    )
    original = attempt["score"]  # one wrong at -1, two right at 3 each = 5

    harsh = repo.create_policy(db, name="سخت‌گیرانه", negative_ratio=1.0)
    with db.transaction() as conn:
        conn.execute("UPDATE exams SET policy_id = ? WHERE id = ?", (harsh["id"], exam["id"]))

    reread = repo.get_attempt(db, attempt["id"])
    assert reread["score"] == original


def test_regrading_uses_the_snapshot_not_the_live_bank(exam_with_policy):
    """Regrade reproduces the original numbers even after the bank moved."""
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "1", "q2": "0", "q3": "1"}
    )
    original = attempt["score"]
    _question(db, "q1", answer_key="3", points=10.0)

    regraded = repo.regrade_attempt(db, attempt_id=attempt["id"], actor="admin", reason="بازبینی")
    assert regraded["score"] == original


def test_the_snapshot_records_the_answer_key_that_was_used(exam_with_policy):
    """Visible evidence: the frozen snapshot holds the key, so an audit can explain the score."""
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "1", "q2": "0", "q3": "1"}
    )
    snapshot = json.loads(attempt["question_snapshot"])
    assert len(snapshot) == 3
    first = next(item for item in snapshot if item["question_id"] == "q1")
    assert first["answer_key"] == "1"
    assert first["points"] == 3.0


# ---------------------------------------------------------------------------
# Essays: human review and the change log
# ---------------------------------------------------------------------------


@pytest.fixture
def essay_exam(bank):
    repo.create_question(
        bank,
        repo.QuestionInput(
            question_id="e1",
            body="توضیح دهید چرا آب در ۱۰۰ درجه می‌جوشد.",
            question_type="essay",
            answer_key="به دلیل فشار بخار برابر با فشار جو",
            rubric="دقت ۵ نمره، ساختار ۵ نمره",
            points=10.0,
            review_status="reviewed",
        ),
    )
    _question(bank, "q1")
    policy = repo.create_policy(bank, name="تشریحی", negative_ratio=1 / 3)
    exam = repo.create_exam(
        bank,
        title="آزمون تشریحی",
        items=[repo.ExamItemInput("e1"), repo.ExamItemInput("q1")],
        policy_id=policy["id"],
    )
    repo.publish_exam(bank, exam["id"])
    return bank, exam, policy


def test_an_essay_attempt_needs_review(essay_exam):
    db, exam, _ = essay_exam
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"e1": "پاسخ من", "q1": "1"}
    )
    assert attempt["grading_status"] == "needs_review"
    assert attempt["review_required"] == 1


def test_a_human_score_resolves_the_review_and_is_logged(essay_exam):
    db, exam, _ = essay_exam
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"e1": "پاسخ من", "q1": "1"}
    )
    regraded = repo.regrade_attempt(
        db,
        attempt_id=attempt["id"],
        essay_scores={"e1": 0.5},
        actor="teacher",
        reason="ارزیابی دستی",
    )
    assert regraded["grading_status"] == "graded"
    assert regraded["score"] == pytest.approx(5.0 + 3.0)

    changes = repo.grade_changes(db, attempt["id"])
    assert len(changes) == 1
    assert changes[0]["score_before"] == attempt["score"]
    assert changes[0]["score_after"] == regraded["score"]


def test_an_item_override_is_recorded_with_before_and_after(essay_exam):
    """The appeal path: a human overrules one item, and the change is auditable."""
    db, exam, _ = essay_exam
    attempt = repo.submit_exam(
        db,
        exam_id=exam["id"],
        user_id="u1",
        answers={"e1": "پاسخ من", "q1": "0"},
        essay_scores={"e1": 0.3},
    )
    before = attempt["score"]

    after = repo.override_item_score(
        db,
        attempt_id=attempt["id"],
        question_id="e1",
        points_awarded=8.0,
        actor="teacher",
        reason="اعتراض پذیرفته شد",
        change_kind="appeal_upheld",
    )
    assert after["score"] == pytest.approx(before + 5.0)
    changes = repo.grade_changes(db, attempt["id"])
    assert any(c["change_kind"] == "appeal_upheld" for c in changes)
    assert changes[-1]["reason"] == "اعتراض پذیرفته شد"


def test_an_override_cannot_award_more_than_the_item_is_worth(essay_exam):
    db, exam, _ = essay_exam
    attempt = repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers={"e1": "p", "q1": "1"})
    with pytest.raises(repo.ExamError) as exc:
        repo.override_item_score(
            db,
            attempt_id=attempt["id"],
            question_id="e1",
            points_awarded=99.0,
            actor="x",
            reason="y",
        )
    assert exc.value.rule == "score_above_maximum"


def test_an_override_on_a_missing_item_is_refused(essay_exam):
    db, exam, _ = essay_exam
    attempt = repo.submit_exam(db, exam_id=exam["id"], user_id="u1", answers={"e1": "p", "q1": "1"})
    with pytest.raises(repo.ExamError) as exc:
        repo.override_item_score(
            db,
            attempt_id=attempt["id"],
            question_id="nope",
            points_awarded=1.0,
            actor="x",
            reason="y",
        )
    assert exc.value.rule == "item_not_found"


def test_the_total_always_equals_the_sum_of_the_items(essay_exam):
    """A stored total that disagrees with its own breakdown is an audit bug."""
    db, exam, _ = essay_exam
    attempt = repo.submit_exam(
        db,
        exam_id=exam["id"],
        user_id="u1",
        answers={"e1": "پاسخ", "q1": "0"},
        essay_scores={"e1": 0.6},
    )
    item_sum = sum(item["points_awarded"] for item in attempt["items"])
    assert attempt["score"] == pytest.approx(round(item_sum, 6))


# ---------------------------------------------------------------------------
# Mistake report
# ---------------------------------------------------------------------------


def test_the_mistake_report_groups_by_topic(exam_with_policy):
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "0", "q2": "0", "q3": "1"}
    )
    report = repo.mistake_report(db, attempt["id"])
    assert report["score"] == attempt["score"]
    topics = {bucket["topic"] for bucket in report["topics"]}
    assert "جمع" in topics
    assert len(report["wrong_items"]) == 1
    assert report["wrong_items"][0]["question_id"] == "q1"


def test_the_mistake_report_ranks_topics_needing_review(exam_with_policy):
    db, exam, _ = exam_with_policy
    attempt = repo.submit_exam(
        db, exam_id=exam["id"], user_id="u1", answers={"q1": "0", "q2": "2", "q3": "3"}
    )
    report = repo.mistake_report(db, attempt["id"])
    assert report["needs_review"][0]["needs_review"] >= report["needs_review"][-1]["needs_review"]
    assert len(report["wrong_items"]) == 3
