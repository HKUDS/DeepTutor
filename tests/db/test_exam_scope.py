"""Scope enforcement for exams, and idempotency under concurrency.

Two bugs were found by reviewing Phase 6 adversarially rather than by running
its acceptance tests, because both are invisible to a well-behaved sequential
client:

1. ``submit_exam`` read the existing attempt outside the insert transaction, so
   two concurrent identical submissions both saw "no attempt" and the loser
   died on the unique index. A student who double-tapped got a server error
   instead of "already submitted".
2. No endpoint compared an exam's grade or major with the caller's enrolment,
   so a grade-7 student could be *graded* on a grade-12 paper. Every read path
   applied a scope filter; the write path applied none.

The tests below are written against the observable promises -- a 403 for an
out-of-scope exam, and N concurrent submissions producing exactly one attempt --
rather than against the implementation, so a later refactor that keeps the
promise keeps the test.
"""

from __future__ import annotations

import threading

import pytest

from deeptutor.db.repositories import exam as repo
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.services import scope


def _learner(db, user_id, *, grade_number, major_code=None):
    IdentityRepository(db).save(
        user_id,
        {
            "id": user_id,
            "hash": "x",
            "role": "user",
            "learner_profile": {"grade_number": grade_number, "major_code": major_code},
        },
    )
    return user_id


def _question(db, qid, **kwargs):
    defaults = dict(
        question_id=qid,
        body="۲+۲ چند است؟",
        choices=["۳", "۴", "۵", "۶"],
        answer_key="1",
        points=3.0,
        review_status="reviewed",
    )
    defaults.update(kwargs)
    return repo.create_question(db, repo.QuestionInput(**defaults))


def _exam(db, *, grade_number=None, major_code=None, qid="q1"):
    _question(db, qid)
    exam = repo.create_exam(
        db,
        title="آزمون",
        items=[repo.ExamItemInput(qid)],
        grade_number=grade_number,
        major_code=major_code,
    )
    repo.publish_exam(db, exam["id"])
    return exam


# ---------------------------------------------------------------------------
# Bug 2 — scope
# ---------------------------------------------------------------------------


def test_a_grade_seven_student_cannot_sit_a_grade_eleven_exam(db):
    """The exact reproduction: the exam's grade was ignored on submission."""
    _learner(db, "grade7", grade_number=7)
    exam = _exam(db, grade_number=11)

    with pytest.raises(scope.ScopeError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="grade7", answers={"q1": "1"})

    assert exc.value.rule == "scope_mismatch"
    assert exc.value.field == "grade_number"


def test_the_refused_submission_leaves_no_attempt_behind(db):
    """A refused submission must not be a half-write the student is graded on."""
    _learner(db, "grade7", grade_number=7)
    exam = _exam(db, grade_number=11)
    with pytest.raises(scope.ScopeError):
        repo.submit_exam(db, exam_id=exam["id"], user_id="grade7", answers={"q1": "1"})

    with db.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM exam_attempts") == 0


def test_a_student_from_another_major_is_refused(db):
    _learner(db, "bio", grade_number=11, major_code="experimental_sciences")
    exam = _exam(db, grade_number=11, major_code="math_physics")

    with pytest.raises(scope.ScopeError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="bio", answers={"q1": "1"})

    assert exc.value.rule == "scope_mismatch"
    assert exc.value.field == "major_code"


def test_a_major_scoped_exam_is_not_open_to_a_student_with_no_major(db):
    """The asymmetry that makes the rule real.

    Grades 1-9 have no majors, so "no major" is the *normal* state of a seventh
    grader. If an unscoped student could sit a major-scoped paper, the major
    filter would protect nobody.
    """
    _learner(db, "grade9", grade_number=9, major_code=None)
    exam = _exam(db, grade_number=9, major_code="math_physics")

    with pytest.raises(scope.ScopeError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="grade9", answers={"q1": "1"})

    assert exc.value.field == "major_code"


def test_the_matching_student_is_graded(db):
    """The guard must not be a wall: the right student still gets a score."""
    _learner(db, "grade11", grade_number=11, major_code="math_physics")
    exam = _exam(db, grade_number=11, major_code="math_physics")

    attempt = repo.submit_exam(db, exam_id=exam["id"], user_id="grade11", answers={"q1": "1"})

    assert attempt["status"] == "graded"
    assert attempt["score"] == 3.0


def test_an_unscoped_exam_is_open_to_everyone(db):
    """A paper with no grade is a general paper, not a locked one."""
    _learner(db, "anyone", grade_number=7)
    exam = _exam(db)

    attempt = repo.submit_exam(db, exam_id=exam["id"], user_id="anyone", answers={"q1": "1"})
    assert attempt["status"] == "graded"


def test_an_account_with_no_profile_is_refused_when_auth_is_on(db, monkeypatch):
    monkeypatch.setattr(scope, "_auth_enabled", lambda: True)
    IdentityRepository(db).save("noprofile", {"id": "noprofile", "hash": "x", "role": "user"})
    exam = _exam(db, grade_number=10)

    with pytest.raises(scope.ScopeError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="noprofile", answers={"q1": "1"})

    assert exc.value.rule == "missing_enrolment"


def test_the_requested_grade_is_ignored_when_a_profile_exists(db):
    """The claim is discarded, not compared.

    Comparing would make the field an error and teach callers to keep sending
    it; discarding it means the value can never widen scope.
    """
    _learner(db, "grade7", grade_number=7)
    enrolment = scope.resolve_enrolment(db, user_id="grade7", grade_number=12, major_code=None)

    assert enrolment.grade_number == 7
    assert enrolment.unverified is False


def test_a_dev_caller_with_no_profile_is_flagged_unverified(db, monkeypatch):
    """The local single-operator mode is usable, but never silently trusted."""
    monkeypatch.setattr(scope, "_auth_enabled", lambda: False)

    enrolment = scope.resolve_enrolment(db, user_id="a", grade_number=10, major_code=None)

    assert enrolment.grade_number == 10
    assert enrolment.unverified is True


def test_the_stored_profile_is_authoritative_even_with_auth_off(db, monkeypatch):
    """A profile, once recorded, is never overridden by a query parameter."""
    monkeypatch.setattr(scope, "_auth_enabled", lambda: False)
    _learner(db, "grade7", grade_number=7)

    enrolment = scope.resolve_enrolment(db, user_id="grade7", grade_number=12, major_code=None)

    assert enrolment.grade_number == 7
    assert enrolment.unverified is False


def test_a_scope_failure_maps_to_403_not_404(db):
    """403 deliberately: the exam is publicly listed, so 404 would be a lie."""
    _learner(db, "grade7", grade_number=7)
    exam = _exam(db, grade_number=11)
    with pytest.raises(scope.ScopeError) as caught:
        repo.submit_exam(db, exam_id=exam["id"], user_id="grade7", answers={"q1": "1"})

    http = scope.as_http(caught.value)
    assert http.status_code == 403
    assert http.detail["rule"] == "scope_mismatch"


def test_the_scoped_listing_hides_other_grades(db):
    _learner(db, "grade7", grade_number=7)
    _exam(db, grade_number=7, qid="q7")
    _exam(db, grade_number=11, qid="q11")

    enrolment = scope.resolve_enrolment(db, user_id="grade7")
    listed = repo.list_exams_in_scope(db, enrolment)

    assert [row["grade_number"] for row in listed] == [7]


def test_the_scoped_listing_hides_other_majors(db):
    _learner(db, "bio", grade_number=11, major_code="experimental_sciences")
    _exam(db, grade_number=11, major_code="math_physics", qid="qm")
    _exam(db, grade_number=11, major_code="experimental_sciences", qid="qe")

    enrolment = scope.resolve_enrolment(db, user_id="bio")
    listed = repo.list_exams_in_scope(db, enrolment)

    assert [row["major_code"] for row in listed] == ["experimental_sciences"]


def test_a_caller_with_no_grade_sees_only_unscoped_exams(db):
    """Not "everything": an unknown grade must narrow, never widen."""
    _exam(db, grade_number=7, qid="q7")
    _exam(db, qid="qany", grade_number=None)

    enrolment = scope.Enrolment(user_id="x", grade_number=None, major_code=None)
    listed = repo.list_exams_in_scope(db, enrolment)

    assert [row["grade_number"] for row in listed] == [None]


# ---------------------------------------------------------------------------
# Bug 1 — concurrent submission
# ---------------------------------------------------------------------------


def test_concurrent_identical_submissions_all_succeed(db):
    """Six threads, one attempt.

    Before the fix this produced one ``DatabaseError: UNIQUE constraint failed``:
    the unique index was doing the work of an idempotency check, and losing that
    race surfaced to the student as a 500.
    """
    _learner(db, "racer", grade_number=10)
    exam = _exam(db, grade_number=10)

    results: list[tuple] = []
    barrier = threading.Barrier(6)

    def submit() -> None:
        barrier.wait(timeout=10)
        try:
            attempt = repo.submit_exam(
                db, exam_id=exam["id"], user_id="racer", answers={"q1": "1"}
            )
            results.append(("ok", attempt["id"]))
        except Exception as exc:  # noqa: BLE001 - the failure is the assertion
            results.append(("err", f"{type(exc).__name__}: {exc}"))

    threads = [threading.Thread(target=submit) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    errors = [row for row in results if row[0] == "err"]
    assert not errors, f"concurrent submissions raised: {errors}"
    assert len({row[1] for row in results}) == 1, "exactly one attempt must be recorded"

    with db.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM exam_attempts") == 1


def test_a_lost_race_still_reports_duplicate(db):
    """The loser returns the winner's attempt, flagged as a duplicate."""
    _learner(db, "racer", grade_number=10)
    exam = _exam(db, grade_number=10)

    first = repo.submit_exam(db, exam_id=exam["id"], user_id="racer", answers={"q1": "1"})
    second = repo.submit_exam(db, exam_id=exam["id"], user_id="racer", answers={"q1": "1"})

    assert second["id"] == first["id"]
    assert second["duplicate_submission"] is True


def test_different_answers_on_the_same_attempt_still_conflict(db):
    """Idempotency must not quietly accept a different submission as the same."""
    _learner(db, "racer", grade_number=10)
    exam = _exam(db, grade_number=10)

    repo.submit_exam(db, exam_id=exam["id"], user_id="racer", answers={"q1": "1"})
    with pytest.raises(repo.ExamError) as exc:
        repo.submit_exam(db, exam_id=exam["id"], user_id="racer", answers={"q1": "2"})

    assert exc.value.rule == "attempt_already_submitted"
