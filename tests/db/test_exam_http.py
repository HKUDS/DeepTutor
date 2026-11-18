"""The exam HTTP surface.

Two things here are security-relevant and get their own tests rather than being
folded into the happy path:

* a student must never receive an answer key **before** submitting;
* a student must never read another student's attempt.

Both are tested by attempting the disclosure, because a route that *happens* not
to leak today is not the same as a route that cannot leak.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import exam as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories import exam as repo


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    # A student with a recorded enrolment: scope comes from the profile, so the
    # API tests must have one or every submission would be refused.
    from deeptutor.db.repositories.identity import IdentityRepository

    IdentityRepository(db).save(
        "u1",
        {
            "id": "u1",
            "hash": "x",
            "role": "user",
            "learner_profile": {"grade_number": 10, "major_code": None},
        },
    )
    return db


@pytest.fixture
def published(live):
    db = live
    repo.create_question(
        db,
        repo.QuestionInput(
            question_id="q1",
            body="۲+۲ چند است؟",
            choices=["۳", "۴", "۵", "۶"],
            answer_key="1",
            points=3.0,
            review_status="reviewed",
            chapter_title="فصل ۱",
            topic="جمع",
        ),
    )
    repo.create_question(
        db,
        repo.QuestionInput(
            question_id="q2",
            body="پایتخت ایران؟",
            choices=["تهران", "شیراز"],
            answer_key="0",
            points=3.0,
            review_status="reviewed",
            chapter_title="فصل ۲",
            topic="جغرافیا",
        ),
    )
    policy = repo.create_policy(db, name="کنکور", negative_ratio=1 / 3)
    exam = repo.create_exam(
        db,
        title="آزمون نمونه",
        items=[repo.ExamItemInput("q1"), repo.ExamItemInput("q2")],
        policy_id=policy["id"],
        grade_number=10,
    )
    repo.publish_exam(db, exam["id"])
    return db, exam["id"]


# ---------------------------------------------------------------------------
# Student surface
# ---------------------------------------------------------------------------


def test_a_student_sees_published_exams(published):
    db, exam_id = published
    payload = _run(api.list_published(user_id="u1", grade_number=10, major_code=None, limit=50))
    assert payload["count"] == 1
    assert payload["exams"][0]["id"] == exam_id


def test_a_draft_exam_is_hidden_from_students(published):
    """Gate 6 depends on this: a draft may contain unreviewed questions."""
    db, exam_id = published
    with db.transaction() as conn:
        conn.execute("UPDATE exams SET status = 'draft' WHERE id = ?", (exam_id,))
    assert _run(api.list_published(user_id="u1", grade_number=None, major_code=None, limit=50))["count"] == 0


def test_a_draft_exam_cannot_be_fetched_by_a_student(published):
    db, exam_id = published
    with db.transaction() as conn:
        conn.execute("UPDATE exams SET status = 'draft' WHERE id = ?", (exam_id,))
    with pytest.raises(HTTPException) as exc:
        _run(api.get_published_exam(exam_id, user_id="u1"))
    assert exc.value.status_code == 404


def test_the_exam_a_student_receives_contains_no_answer_keys(published):
    """The single most important disclosure rule in this router.

    If the key ships with the paper, the exam is trivially gameable and every
    score from it is worthless. Checked on the serialised response, not on the
    model, so a future field cannot reintroduce it unnoticed.
    """
    db, exam_id = published
    payload = _run(api.get_published_exam(exam_id, user_id="u1"))
    serialised = str(payload)
    assert "answer_key" not in serialised
    for item in payload["items"]:
        assert "answer_key" not in item
        assert item["choices"], "the choices must be present"


def test_the_exam_a_student_receives_has_choices_as_a_list(published):
    db, exam_id = published
    payload = _run(api.get_published_exam(exam_id, user_id="u1"))
    first = payload["items"][0]
    assert isinstance(first["choices"], list)
    assert len(first["choices"]) == 4


def test_submitting_returns_a_graded_attempt(published):
    db, exam_id = published
    payload = _run(
        api.submit(
            exam_id,
            api.SubmitRequest(user_id="u1", answers={"q1": "1", "q2": "0"}),
        )
    )
    assert payload["status"] == "graded"
    assert payload["score"] == 6.0
    assert payload["duplicate_submission"] is False


def test_submitting_twice_returns_the_same_attempt(published):
    db, exam_id = published
    request = api.SubmitRequest(user_id="u1", answers={"q1": "1", "q2": "0"})
    first = _run(api.submit(exam_id, request))
    second = _run(api.submit(exam_id, request))
    assert second["id"] == first["id"]
    assert second["duplicate_submission"] is True
    assert second["score"] == first["score"]


def test_a_conflicting_resubmission_is_409(published):
    db, exam_id = published
    _run(api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "1", "q2": "0"})))
    with pytest.raises(HTTPException) as exc:
        _run(api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "0", "q2": "0"})))
    assert exc.value.status_code == 409
    assert exc.value.detail["rule"] == "attempt_already_submitted"


def test_the_owner_can_read_their_attempt(published):
    db, exam_id = published
    attempt = _run(
        api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "1", "q2": "0"}))
    )
    payload = _run(api.get_attempt(attempt["id"], user_id="u1"))
    assert payload["id"] == attempt["id"]


def test_a_stranger_cannot_read_an_attempt(published):
    """An attempt id is opaque, but not a capability. Guessing one must not work."""
    db, exam_id = published
    attempt = _run(
        api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "1", "q2": "0"}))
    )
    with pytest.raises(HTTPException) as exc:
        _run(api.get_attempt(attempt["id"], user_id="u2"))
    assert exc.value.status_code == 404


def test_a_stranger_cannot_read_another_students_mistakes(published):
    db, exam_id = published
    attempt = _run(
        api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "0", "q2": "0"}))
    )
    with pytest.raises(HTTPException) as exc:
        _run(api.get_mistakes(attempt["id"], user_id="u2"))
    assert exc.value.status_code == 404


def test_the_mistake_report_names_the_wrong_topics(published):
    db, exam_id = published
    attempt = _run(
        api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "0", "q2": "0"}))
    )
    report = _run(api.get_mistakes(attempt["id"], user_id="u1"))
    assert len(report["wrong_items"]) == 1
    assert report["wrong_items"][0]["question_id"] == "q1"


def test_listing_attempts_omits_the_snapshot(published):
    """The snapshot is internal evidence, not part of a list response."""
    db, exam_id = published
    _run(api.submit(exam_id, api.SubmitRequest(user_id="u1", answers={"q1": "1", "q2": "0"})))
    payload = _run(api.list_my_attempts(user_id="u1", limit=50))
    assert payload["count"] == 1
    assert "question_snapshot" not in payload["attempts"][0]


def test_an_unknown_attempt_is_404(published):
    db, exam_id = published
    with pytest.raises(HTTPException) as exc:
        _run(api.get_attempt("nope", user_id="u1"))
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Operator surface
# ---------------------------------------------------------------------------


def test_an_operator_can_create_a_question(live):
    payload = _run(
        api.create_question(
            api.QuestionPayload(
                question_id="newq",
                body="پرسش تازه",
                choices=["الف", "ب"],
                answer_key="0",
            )
        )
    )
    assert payload["version"] == 1
    assert payload["review_status"] == "draft"


def test_a_question_without_a_key_is_422(live):
    with pytest.raises(HTTPException) as exc:
        _run(
            api.create_question(api.QuestionPayload(question_id="x", body="ب", choices=["a", "b"]))
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["rule"] == "missing_answer_key"


def test_a_question_can_be_reviewed(live):
    _run(
        api.create_question(
            api.QuestionPayload(question_id="q", body="ب", choices=["a", "b"], answer_key="0")
        )
    )
    payload = _run(
        api.review_question(
            "q", api.ReviewQuestionPayload(version=1, review_status="reviewed", actor="admin")
        )
    )
    assert payload["review_status"] == "reviewed"


def test_an_invalid_review_status_is_422(live):
    _run(
        api.create_question(
            api.QuestionPayload(question_id="q", body="ب", choices=["a", "b"], answer_key="0")
        )
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            api.review_question(
                "q", api.ReviewQuestionPayload(version=1, review_status="published")
            )
        )
    assert exc.value.status_code == 422


def test_publishing_an_unreviewed_exam_is_409(live):
    repo.create_question(
        live,
        repo.QuestionInput(
            question_id="q1", body="ب", choices=["a", "b"], answer_key="0", review_status="draft"
        ),
    )
    exam = repo.create_exam(live, title="t", items=[repo.ExamItemInput("q1")])
    with pytest.raises(HTTPException) as exc:
        _run(api.publish_exam(exam["id"], actor="admin"))
    assert exc.value.status_code == 409
    assert exc.value.detail["rule"] == "unreviewed_questions"


def test_validation_endpoint_reports_issues(live):
    repo.create_question(
        live,
        repo.QuestionInput(
            question_id="q1", body="ب", choices=["a", "b"], answer_key="0", review_status="draft"
        ),
    )
    exam = repo.create_exam(live, title="t", items=[repo.ExamItemInput("q1")])
    report = _run(api.validate_exam(exam["id"]))
    assert report["valid"] is False
    assert report["issues"]


def test_a_policy_can_be_created(live):
    payload = _run(api.create_policy(api.PolicyPayload(name="کنکور", negative_ratio=1 / 3)))
    assert payload["negative_ratio"] == pytest.approx(1 / 3)


def test_an_invalid_policy_is_422(live):
    with pytest.raises(HTTPException) as exc:
        _run(
            api.create_policy(
                api.PolicyPayload(name="bad", essay_min_ratio=0.9, essay_max_ratio=0.1)
            )
        )
    assert exc.value.status_code == 422


def test_creating_an_exam_through_the_api(published):
    db, exam_id = published
    payload = _run(
        api.create_exam(
            api.ExamPayload(
                title="آزمون تازه",
                items=[api.ExamItemPayload(question_id="q1")],
                grade_number=10,
            )
        )
    )
    assert payload["title"] == "آزمون تازه"
    assert len(payload["items"]) == 1


def test_creating_an_exam_with_an_unknown_question_is_404(live):
    with pytest.raises(HTTPException) as exc:
        _run(
            api.create_exam(
                api.ExamPayload(title="t", items=[api.ExamItemPayload(question_id="nope")])
            )
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Review surface
# ---------------------------------------------------------------------------


def test_a_regrade_is_allowed_and_logged(live):
    repo.create_question(
        live,
        repo.QuestionInput(
            question_id="e1",
            body="شرح دهید",
            question_type="essay",
            answer_key="پاسخ",
            points=10.0,
            review_status="reviewed",
        ),
    )
    exam = repo.create_exam(live, title="t", items=[repo.ExamItemInput("e1")])
    repo.publish_exam(live, exam["id"])
    attempt = _run(
        api.submit(exam["id"], api.SubmitRequest(user_id="u1", answers={"e1": "پاسخ من"}))
    )
    assert attempt["review_required"] == 1

    regraded = _run(
        api.regrade(
            attempt["id"],
            api.RegradePayload(essay_scores={"e1": 0.5}, actor="teacher", reason="دستی"),
        )
    )
    assert regraded["score"] == 5.0
    changes = _run(api.changes(attempt["id"]))
    assert changes["count"] == 1


def test_an_override_without_a_reason_is_refused(essay_attempt):
    """An unexplained score change is a bug, so a reason is required.

    The rejection happens at *request validation*, before the route body runs:
    ``OverridePayload.reason`` has ``min_length=1``, so FastAPI returns 422
    without ever reaching the database. Asserting here that construction fails
    is asserting the guarantee at the layer that provides it -- asserting a 422
    would only pass because the exception happened to surface as one.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        api.OverridePayload(question_id="e1", points_awarded=5.0, actor="t", reason="")
    assert "reason" in str(exc.value)


@pytest.fixture
def essay_attempt(live):
    repo.create_question(
        live,
        repo.QuestionInput(
            question_id="e1",
            body="شرح دهید",
            question_type="essay",
            answer_key="پاسخ",
            points=10.0,
            review_status="reviewed",
        ),
    )
    exam = repo.create_exam(live, title="t", items=[repo.ExamItemInput("e1")])
    repo.publish_exam(live, exam["id"])
    attempt = _run(
        api.submit(exam["id"], api.SubmitRequest(user_id="u1", answers={"e1": "پاسخ من"}))
    )
    return attempt["id"]


def test_an_override_changes_the_score_and_is_logged(essay_attempt):
    payload = _run(
        api.override(
            essay_attempt,
            api.OverridePayload(
                question_id="e1", points_awarded=7.0, actor="teacher", reason="اعتراض پذیرفته شد"
            ),
        )
    )
    assert payload["score"] == pytest.approx(7.0)
    changes = _run(api.changes(essay_attempt))
    assert changes["changes"][-1]["reason"] == "اعتراض پذیرفته شد"


def test_an_override_above_the_maximum_is_422(essay_attempt):
    with pytest.raises(HTTPException) as exc:
        _run(
            api.override(
                essay_attempt,
                api.OverridePayload(question_id="e1", points_awarded=99.0, actor="t", reason="x"),
            )
        )
    assert exc.value.status_code == 422


def test_the_database_being_disabled_is_503(monkeypatch):
    disabled = DatabaseSettings(app_url="", backend="sqlite")
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: disabled)
    reset_database_settings()
    with pytest.raises(HTTPException) as exc:
        _run(api.list_published(user_id="u1", grade_number=None, major_code=None, limit=50))
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Scope at the API boundary
# ---------------------------------------------------------------------------


def _other_learner(db, user_id, *, grade_number, major_code=None):
    from deeptutor.db.repositories.identity import IdentityRepository

    IdentityRepository(db).save(
        user_id,
        {
            "id": user_id,
            "hash": "x",
            "role": "user",
            "learner_profile": {"grade_number": grade_number, "major_code": major_code},
        },
    )


def test_submitting_outside_your_grade_is_403_not_a_score(published):
    db, exam_id = published
    _other_learner(db, "grade7", grade_number=7)

    with pytest.raises(HTTPException) as exc:
        _run(
            api.submit(
                exam_id,
                api.SubmitRequest(user_id="grade7", answers={"q1": "1", "q2": "0"}),
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["rule"] == "scope_mismatch"


def test_the_listing_only_shows_your_own_grade(published):
    db, exam_id = published
    _other_learner(db, "grade7", grade_number=7)

    payload = _run(
        api.list_published(user_id="grade7", grade_number=10, major_code=None, limit=50)
    )

    # The grade-10 exam exists and is published, but a grade-7 caller must not
    # see it -- and the ?grade_number=10 they passed must not widen the listing.
    assert payload["count"] == 0
    assert payload["scope"]["grade_number"] == 7


def test_the_listing_reports_whether_the_scope_was_verified(published):
    db, exam_id = published
    payload = _run(api.list_published(user_id="u1", grade_number=None, major_code=None, limit=50))
    assert payload["scope"]["unverified"] is False


def test_an_account_with_no_profile_falls_back_to_an_unverified_scope(published, monkeypatch):
    """With authentication off there is no session to read, so the query is used.

    The point of the test is that the fallback is *labelled*: the response says
    ``unverified`` so a dev deployment cannot be mistaken for a scoped one.
    """
    db, exam_id = published
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.services.exam import scope

    monkeypatch.setattr(scope, "_auth_enabled", lambda: False)
    IdentityRepository(db).save("noprofile", {"id": "noprofile", "hash": "x", "role": "user"})

    payload = _run(
        api.list_published(user_id="noprofile", grade_number=10, major_code=None, limit=50)
    )
    assert payload["scope"]["unverified"] is True
    assert payload["scope"]["grade_number"] == 10


def test_an_account_with_no_profile_is_403_when_authentication_is_on(published, monkeypatch):
    """With authentication on there is nothing to fall back to, so refuse."""
    db, exam_id = published
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.services.exam import scope

    monkeypatch.setattr(scope, "_auth_enabled", lambda: True)
    IdentityRepository(db).save("noprofile", {"id": "noprofile", "hash": "x", "role": "user"})

    with pytest.raises(HTTPException) as exc:
        _run(api.list_published(user_id="noprofile", grade_number=10, major_code=None, limit=50))
    assert exc.value.status_code == 403
    assert exc.value.detail["rule"] == "missing_enrolment"


def test_reading_another_grades_exam_is_403(published):
    """The listing hid the id; reading it directly must not be the way around."""
    db, exam_id = published
    _other_learner(db, "grade7", grade_number=7)

    with pytest.raises(HTTPException) as exc:
        _run(api.get_published_exam(exam_id, user_id="grade7"))

    assert exc.value.status_code == 403
