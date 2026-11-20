"""The flashcards API: identity, scope and the mistake bridge.

Endpoints are called as coroutines, the same way the Phase 4/6 HTTP tests do:
the assertions are about our error mapping and response shape, not FastAPI's
plumbing.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import flashcards as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories import exam as exam_repo
from deeptutor.db.repositories import flashcards as repo
from deeptutor.db.repositories.identity import IdentityRepository


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
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
def deck(live):
    return _run(api.create_deck(api.DeckPayload(title="ریاضی"), user_id="u1"))


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------


def test_a_deck_can_be_created_and_listed(live):
    created = _run(api.create_deck(api.DeckPayload(title="ریاضی"), user_id="u1"))
    listing = _run(api.list_decks(user_id="u1", limit=100))

    assert listing["count"] == 1
    assert listing["decks"][0]["id"] == created["id"]
    assert listing["decks"][0]["card_count"] == 0


def test_another_students_deck_is_404(deck, live):
    with pytest.raises(HTTPException) as exc:
        _run(api.get_deck(deck["id"], user_id="u2"))
    assert exc.value.status_code == 404


def test_creating_a_deck_outside_your_grade_is_403(live):
    IdentityRepository(live).save(
        "grade7",
        {
            "id": "grade7",
            "hash": "x",
            "role": "user",
            "learner_profile": {"grade_number": 7},
        },
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            api.create_deck(
                api.DeckPayload(title="دوازدهم", grade_number=12), user_id="grade7"
            )
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["rule"] == "scope_mismatch"


def test_deleting_a_deck_removes_its_cards(deck, live):
    _run(
        api.add_cards(
            deck["id"],
            api.CardsPayload(cards=[api.CardPayload(front="س", back="ج")]),
            user_id="u1",
        )
    )
    _run(api.delete_deck(deck["id"], user_id="u1"))

    with live.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM flashcards") == 0


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def test_cards_can_be_added_and_listed(deck, live):
    payload = _run(
        api.add_cards(
            deck["id"],
            api.CardsPayload(
                cards=[
                    api.CardPayload(front="۲+۲؟", back="۴"),
                    api.CardPayload(front="۳+۳؟", back="۶"),
                ]
            ),
            user_id="u1",
        )
    )
    assert payload["created"] == 2

    listing = _run(api.list_cards(deck["id"], user_id="u1", status="active", limit=200))
    assert listing["count"] == 2


def test_adding_the_same_cards_again_reports_duplicates(deck, live):
    cards = api.CardsPayload(cards=[api.CardPayload(front="۲+۲؟", back="۴")])
    _run(api.add_cards(deck["id"], cards, user_id="u1"))
    second = _run(api.add_cards(deck["id"], cards, user_id="u1"))

    assert second["created"] == 0
    assert second["duplicates"] == 1


def test_a_card_can_be_edited_but_not_rescheduled(deck, live):
    created = _run(
        api.add_cards(
            deck["id"], api.CardsPayload(cards=[api.CardPayload(front="قدیم", back="ج")]), user_id="u1"
        )
    )
    card_id = created["cards"][0]["id"]

    updated = _run(api.patch_card(card_id, api.CardPatch(front="جدید"), user_id="u1"))
    assert updated["front"] == "جدید"
    assert updated["review_count"] == 0


def test_archiving_a_card_keeps_it_queryable(deck, live):
    created = _run(
        api.add_cards(
            deck["id"], api.CardsPayload(cards=[api.CardPayload(front="س", back="ج")]), user_id="u1"
        )
    )
    card_id = created["cards"][0]["id"]
    _run(api.archive_card(card_id, user_id="u1"))

    archived = _run(api.list_cards(deck["id"], user_id="u1", status="archived", limit=200))
    assert archived["count"] == 1


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def _one_card(deck, live):
    created = _run(
        api.add_cards(
            deck["id"], api.CardsPayload(cards=[api.CardPayload(front="س", back="ج")]), user_id="u1"
        )
    )
    return created["cards"][0]["id"]


def test_a_card_appears_in_the_queue_then_leaves_after_a_review(deck, live):
    card_id = _one_card(deck, live)
    assert _run(api.review_queue(user_id="u1", limit=50))["count"] == 1

    _run(api.review_card(card_id, api.ReviewPayload(rating="good"), user_id="u1"))
    assert _run(api.review_queue(user_id="u1", limit=50))["count"] == 0


def test_a_review_records_history_and_updates_the_summary(deck, live):
    card_id = _one_card(deck, live)
    _run(api.review_card(card_id, api.ReviewPayload(rating="again"), user_id="u1"))

    history = _run(api.card_history(card_id, user_id="u1"))
    summary = _run(api.summary(user_id="u1"))

    assert history["count"] == 1
    assert history["reviews"][0]["rating"] == "again"
    assert summary["reviews"] == 1
    assert summary["lapses"] == 1


def test_an_invalid_rating_is_422(deck, live):
    card_id = _one_card(deck, live)
    with pytest.raises(HTTPException) as exc:
        _run(api.review_card(card_id, api.ReviewPayload(rating="meh"), user_id="u1"))
    assert exc.value.status_code == 422


def test_reviewing_another_students_card_is_404(deck, live):
    card_id = _one_card(deck, live)
    with pytest.raises(HTTPException) as exc:
        _run(api.review_card(card_id, api.ReviewPayload(rating="good"), user_id="u2"))
    assert exc.value.status_code == 404


def test_the_queue_is_per_student(deck, live):
    _one_card(deck, live)
    IdentityRepository(live).save("u2", {"id": "u2", "hash": "x", "role": "user"})
    assert _run(api.review_queue(user_id="u2", limit=50))["count"] == 0


# ---------------------------------------------------------------------------
# Cards from exam mistakes
# ---------------------------------------------------------------------------


def _graded_attempt(db, *, user_id="u1"):
    exam_repo.create_question(
        db,
        exam_repo.QuestionInput(
            question_id="q1",
            body="پایتخت ایران کجاست؟",
            choices=["تهران", "شیراز"],
            answer_key="0",
            points=3.0,
            review_status="reviewed",
            chapter_title="فصل ۱",
            topic="جغرافیا",
        ),
    )
    exam_repo.create_question(
        db,
        exam_repo.QuestionInput(
            question_id="q2",
            body="۲+۲ چند است؟",
            choices=["۳", "۴"],
            answer_key="1",
            points=3.0,
            review_status="reviewed",
            chapter_title="فصل ۲",
            topic="جمع",
        ),
    )
    exam = exam_repo.create_exam(
        db,
        title="آزمون",
        items=[exam_repo.ExamItemInput("q1"), exam_repo.ExamItemInput("q2")],
        grade_number=10,
    )
    exam_repo.publish_exam(db, exam["id"])
    return exam_repo.submit_exam(
        db, exam_id=exam["id"], user_id=user_id, answers={"q1": "1", "q2": "1"}
    )


def test_wrong_answers_become_cards(deck, live):
    """The roadmap's "cards from exam mistakes", end to end."""
    attempt = _graded_attempt(live)

    result = _run(
        api.cards_from_mistakes(deck["id"], attempt_id=attempt["id"], user_id="u1")
    )

    assert result["created"] == 1, "only the wrong answer becomes a card"
    card = result["cards"][0]
    assert card["front"] == "پایتخت ایران کجاست؟"
    assert card["back"] == "تهران", "the back is the answer text, not the index"
    assert card["provenance_kind"] == "exam_mistake"
    assert card["origin_attempt_id"] == attempt["id"]
    assert card["origin_question_id"] == "q1"


def test_regenerating_from_the_same_attempt_adds_nothing(deck, live):
    attempt = _graded_attempt(live)
    _run(api.cards_from_mistakes(deck["id"], attempt_id=attempt["id"], user_id="u1"))
    again = _run(api.cards_from_mistakes(deck["id"], attempt_id=attempt["id"], user_id="u1"))

    assert again["created"] == 0
    assert again["duplicates"] == 1


def test_another_students_attempt_cannot_be_mined(deck, live):
    attempt = _graded_attempt(live)
    IdentityRepository(live).save("u2", {"id": "u2", "hash": "x", "role": "user"})

    with pytest.raises(HTTPException) as exc:
        _run(api.cards_from_mistakes(deck["id"], attempt_id=attempt["id"], user_id="u2"))

    assert exc.value.status_code == 404


def test_a_fully_correct_attempt_produces_no_cards(deck, live):
    exam_repo.create_question(
        live,
        exam_repo.QuestionInput(
            question_id="q1",
            body="۲+۲؟",
            choices=["۳", "۴"],
            answer_key="1",
            points=3.0,
            review_status="reviewed",
        ),
    )
    exam = exam_repo.create_exam(
        live, title="آسان", items=[exam_repo.ExamItemInput("q1")], grade_number=10
    )
    exam_repo.publish_exam(live, exam["id"])
    attempt = exam_repo.submit_exam(
        live, exam_id=exam["id"], user_id="u1", answers={"q1": "1"}
    )

    result = _run(api.cards_from_mistakes(deck["id"], attempt_id=attempt["id"], user_id="u1"))
    assert result["created"] == 0


# ---------------------------------------------------------------------------
# Mastery dashboard
# ---------------------------------------------------------------------------


def test_the_dashboard_reports_groups_from_evidence(deck, live):
    _graded_attempt(live)
    _run(api.cards_from_mistakes(deck["id"], attempt_id=_latest_attempt(live)["id"], user_id="u1"))

    payload = _run(api.mastery_dashboard(user_id="u1", by="chapter", attempt_limit=50))

    names = {group["name"] for group in payload["groups"]}
    assert "فصل ۱" in names
    assert payload["evidence_count"] > 0


def test_a_chapter_with_no_evidence_is_absent_not_zero(deck, live):
    """'Never seen' and 'always wrong' are different facts."""
    payload = _run(api.mastery_dashboard(user_id="u1", by="chapter", attempt_limit=50))
    assert payload["groups"] == []


def test_suggestions_come_from_observed_mistakes(deck, live):
    _graded_attempt(live)
    payload = _run(api.mastery_dashboard(user_id="u1", by="chapter", attempt_limit=50))

    assert payload["suggestions"]
    assert "نادرست" in payload["suggestions"][0]["reason"]


def _latest_attempt(db):
    """The most recent attempt, for tests that need its id after grading."""
    return exam_repo.list_attempts(db, limit=10)[0]
