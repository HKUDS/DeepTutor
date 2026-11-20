"""Decks, cards and reviews: scope, deduplication, provenance, persistence.

These tests are organised around the roadmap's acceptance criteria rather than
around the functions, so that a rewrite of the storage layer that keeps the
promises keeps the tests.
"""

from __future__ import annotations

import threading

import pytest

from deeptutor.db.repositories import flashcards as repo
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.services import scope

NOW = 1_700_000_000.0


def _learner(db, user_id, *, grade_number=10, major_code=None):
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


def _deck(db, user_id="u1", **kwargs):
    return repo.create_deck(db, user_id=user_id, deck=repo.DeckInput(title="ریاضی", **kwargs))


def _card(db, deck_id, user_id="u1", *, now=None, **kwargs):
    payload = dict(front="۲+۲ چند است؟", back="۴", provenance_kind="manual")
    payload.update(kwargs)
    return repo.add_card(
        db, deck_id=deck_id, user_id=user_id, card=repo.CardInput(**payload), now=now
    )


# ---------------------------------------------------------------------------
# No deck or card outside the owner's scope
# ---------------------------------------------------------------------------


def test_a_deck_is_created_for_its_owner(db):
    deck = _deck(db, "u1")
    assert deck["user_id"] == "u1"


def test_another_students_deck_is_not_found(db):
    deck = _deck(db, "u1")
    with pytest.raises(repo.CardError) as exc:
        repo.get_deck(db, deck["id"], user_id="u2")
    assert exc.value.rule == "deck_not_found"


def test_another_students_card_is_not_found(db):
    deck = _deck(db, "u1")
    card = _card(db, deck["id"])
    with pytest.raises(repo.CardError) as exc:
        repo.get_card(db, card["id"], user_id="u2")
    assert exc.value.rule == "card_not_found"


def test_listing_another_students_cards_is_refused(db):
    """A read that takes a deck id must check ownership before reading."""
    deck = _deck(db, "u1")
    _card(db, deck["id"])
    with pytest.raises(repo.CardError):
        repo.list_cards(db, user_id="u2", deck_id=deck["id"])


def test_a_card_cannot_be_added_to_someone_elses_deck(db):
    deck = _deck(db, "u1")
    with pytest.raises(repo.CardError):
        _card(db, deck["id"], user_id="u2")


def test_a_grade_scoped_deck_cannot_be_created_outside_the_enrolment(db):
    """The same rule Phase 6 put on exams, applied to decks."""
    _learner(db, "grade7", grade_number=7)
    enrolment = scope.resolve_enrolment(db, user_id="grade7")

    with pytest.raises(scope.ScopeError) as exc:
        repo.create_deck(
            db,
            user_id="grade7",
            deck=repo.DeckInput(title="دوازدهم", grade_number=12),
            enrolment=enrolment,
        )

    assert exc.value.rule == "scope_mismatch"
    assert exc.value.field == "grade_number"


def test_a_matching_deck_is_allowed(db):
    _learner(db, "grade12", grade_number=12, major_code="math_physics")
    enrolment = scope.resolve_enrolment(db, user_id="grade12")

    deck = repo.create_deck(
        db,
        user_id="grade12",
        deck=repo.DeckInput(title="ریاضی", grade_number=12, major_code="math_physics"),
        enrolment=enrolment,
    )
    assert deck["grade_number"] == 12


def test_deleting_a_deck_requires_ownership(db):
    deck = _deck(db, "u1")
    with pytest.raises(repo.CardError):
        repo.delete_deck(db, deck["id"], user_id="u2")
    assert repo.get_deck(db, deck["id"], user_id="u1")["id"] == deck["id"]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_the_same_card_twice_is_one_card(db):
    deck = _deck(db)
    first = _card(db, deck["id"], front="پایتخت ایران؟", back="تهران")
    second = _card(db, deck["id"], front="پایتخت ایران؟", back="تهران")

    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(repo.list_cards(db, user_id="u1", deck_id=deck["id"])) == 1


def test_deduplication_ignores_spacing_and_arabic_letters(db):
    """Otherwise a deck regenerated from the same chapter doubles in size.

    The folding covers whitespace, case, Persian/Arabic digits and the yeh/kaf
    variants -- the differences that come from *how* text was typed, not from
    what it says.
    """
    deck = _deck(db)
    _card(db, deck["id"], front="می‌شود چند است؟", back="۱")
    same = _card(db, deck["id"], front="ميشود   چند  است؟", back="۱")

    assert same["duplicate"] is True
    assert len(repo.list_cards(db, user_id="u1", deck_id=deck["id"])) == 1


def test_the_same_question_from_two_chapters_is_two_cards(db):
    """Provenance is part of identity, so a cross-chapter repeat is meaningful."""
    deck = _deck(db)
    a = _card(db, deck["id"], front="مشتق چیست؟", back="آهنگ تغییر", source_id="chapter-1")
    b = _card(db, deck["id"], front="مشتق چیست؟", back="آهنگ تغییر", source_id="chapter-2")

    assert a["id"] != b["id"]
    assert b["duplicate"] is False


def test_two_students_wrong_on_the_same_question_each_get_a_card(db):
    """Dedup is scoped by owner: a shared card would share a history."""
    deck_a = _deck(db, "u1")
    deck_b = _deck(db, "u2")
    _learner(db, "u1")
    _learner(db, "u2")

    card_a = _card(db, deck_a["id"], user_id="u1", front="سوال", back="جواب")
    card_b = _card(db, deck_b["id"], user_id="u2", front="سوال", back="جواب")

    assert card_a["id"] != card_b["id"]


def test_concurrent_identical_adds_all_succeed(db):
    """Two racing adds of the same card must both return, not raise.

    This is the race Phase 6 fixed in exam submission, in its new home: the
    unique index is the arbiter and the loser reads the winner.
    """
    deck = _deck(db)
    results: list[tuple] = []
    barrier = threading.Barrier(5)

    def add() -> None:
        barrier.wait(timeout=10)
        try:
            row = _card(db, deck["id"], front="رقابتی", back="پاسخ")
            results.append(("ok", row["id"]))
        except Exception as exc:  # noqa: BLE001 - the failure is the assertion
            results.append(("err", f"{type(exc).__name__}: {exc}"))

    threads = [threading.Thread(target=add) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    errors = [row for row in results if row[0] == "err"]
    assert not errors, f"concurrent adds raised: {errors}"
    assert len({row[1] for row in results}) == 1
    with db.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM flashcards") == 1


def test_bulk_add_reports_created_and_duplicates(db):
    deck = _deck(db)
    first = repo.add_cards(
        db,
        deck_id=deck["id"],
        user_id="u1",
        cards=[repo.CardInput(front="الف", back="1"), repo.CardInput(front="ب", back="2")],
    )
    assert first["created"] == 2 and first["duplicates"] == 0

    second = repo.add_cards(
        db,
        deck_id=deck["id"],
        user_id="u1",
        cards=[repo.CardInput(front="الف", back="1"), repo.CardInput(front="ج", back="3")],
    )
    assert second["created"] == 1 and second["duplicates"] == 1


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_a_card_records_where_it_came_from(db):
    deck = _deck(db)
    card = _card(
        db,
        deck["id"],
        front="فصل ۱: مجموعه چیست؟",
        back="گردایه‌ای از اشیاء",
        provenance_kind="book_chapter",
        source_id="src_1",
        chapter_title="فصل ۱",
        citation="[ریاضی دهم، فصل ۱]",
    )

    assert card["provenance_kind"] == "book_chapter"
    assert card["source_id"] == "src_1"
    assert card["citation"] == "[ریاضی دهم، فصل ۱]"
    assert card["chapter_title"] == "فصل ۱"


def test_an_invalid_provenance_kind_is_refused(db):
    deck = _deck(db)
    with pytest.raises(repo.CardError) as exc:
        _card(db, deck["id"], provenance_kind="made_up")
    assert exc.value.rule == "invalid_provenance"


def test_a_card_needs_a_front_and_a_back(db):
    deck = _deck(db)
    with pytest.raises(repo.CardError) as exc:
        _card(db, deck["id"], front="   ")
    assert exc.value.rule == "empty_front"


# ---------------------------------------------------------------------------
# Review and progress continuity
# ---------------------------------------------------------------------------


def test_a_review_is_recorded_and_reschedules_the_card(db):
    deck = _deck(db)
    # The card is created at the same pinned instant it is reviewed at, so the
    # test measures rescheduling rather than "reviewing before the card existed".
    card = _card(db, deck["id"], now=NOW)

    result = repo.review_card(db, card_id=card["id"], user_id="u1", rating="good", now=NOW)

    assert result["review"]["rating"] == "good"
    assert result["card"]["review_count"] == 1
    assert result["due_at"] > card["due_at"]


def test_every_review_leaves_a_history_row(db):
    deck = _deck(db)
    card = _card(db, deck["id"])
    moment = NOW
    for rating in ("good", "hard", "again", "easy"):
        repo.review_card(db, card_id=card["id"], user_id="u1", rating=rating, now=moment)
        moment += 86400

    history = repo.review_history(db, card["id"], user_id="u1")
    assert [row["rating"] for row in history] == ["good", "hard", "again", "easy"]
    assert all(row["due_at_after"] for row in history)


def test_the_history_row_explains_the_schedule_change(db):
    """Evidence means the stored before/after, not just the new due date."""
    deck = _deck(db)
    card = _card(db, deck["id"])
    repo.review_card(db, card_id=card["id"], user_id="u1", rating="good", now=NOW)

    row = repo.review_history(db, card["id"], user_id="u1")[0]
    assert row["interval_index_before"] == 0
    assert row["due_at_before"] == card["due_at"]
    assert row["due_at_after"] != row["due_at_before"]


def test_a_review_cannot_be_recorded_for_someone_elses_card(db):
    deck = _deck(db, "u1")
    card = _card(db, deck["id"])
    with pytest.raises(repo.CardError):
        repo.review_card(db, card_id=card["id"], user_id="u2", rating="good")


def test_an_archived_card_cannot_be_reviewed(db):
    deck = _deck(db)
    card = _card(db, deck["id"])
    repo.update_card(db, card["id"], user_id="u1", changes={"status": "archived"})

    with pytest.raises(repo.CardError) as exc:
        repo.review_card(db, card_id=card["id"], user_id="u1", rating="good")
    assert exc.value.rule == "card_not_active"


def test_an_unknown_rating_is_refused_by_the_repository(db):
    deck = _deck(db)
    card = _card(db, deck["id"])
    with pytest.raises(ValueError):
        repo.review_card(db, card_id=card["id"], user_id="u1", rating="maybe")


def test_review_state_cannot_be_edited_through_the_update_path(db):
    """Letting an edit set review_count would make the history deniable."""
    deck = _deck(db)
    card = _card(db, deck["id"])
    updated = repo.update_card(
        db,
        card["id"],
        user_id="u1",
        changes={"review_count": 99, "due_at": "2099-01-01", "front": "متن تازه"},
    )

    assert updated["front"] == "متن تازه"
    assert updated["review_count"] == 0
    assert updated["due_at"] == card["due_at"]


def test_separate_students_accumulate_separate_progress(db):
    _learner(db, "u1")
    _learner(db, "u2")
    deck1 = _deck(db, "u1")
    deck2 = _deck(db, "u2")
    card1 = _card(db, deck1["id"], user_id="u1", front="سوال")
    _card(db, deck2["id"], user_id="u2", front="سوال")

    repo.review_card(db, card_id=card1["id"], user_id="u1", rating="good", now=NOW)

    assert repo.review_summary(db, user_id="u1")["reviews"] == 1
    assert repo.review_summary(db, user_id="u2")["reviews"] == 0


def test_the_summary_counts_only_stored_facts(db):
    deck = _deck(db)
    card = _card(db, deck["id"])
    repo.review_card(db, card_id=card["id"], user_id="u1", rating="again", now=NOW)

    summary = repo.review_summary(db, user_id="u1", now=NOW)
    assert summary["cards"] == 1
    assert summary["reviews"] == 1
    assert summary["lapses"] == 1
    assert summary["by_rating"] == {"again": 1}


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------


def test_a_new_card_is_due_immediately(db):
    deck = _deck(db)
    _card(db, deck["id"])
    assert len(repo.due_cards(db, user_id="u1")) == 1


def test_a_reviewed_card_leaves_the_queue_until_it_is_due(db):
    deck = _deck(db)
    card = _card(db, deck["id"])
    repo.review_card(db, card_id=card["id"], user_id="u1", rating="good", now=NOW)

    assert repo.due_cards(db, user_id="u1", now=NOW) == []
    later = NOW + 30 * 86400
    assert len(repo.due_cards(db, user_id="u1", now=later)) == 1


def test_the_queue_is_ordered_deterministically(db):
    deck = _deck(db)
    for index in range(4):
        _card(db, deck["id"], front=f"سوال {index}", back="پاسخ")

    first = [row["id"] for row in repo.due_cards(db, user_id="u1", now=NOW)]
    second = [row["id"] for row in repo.due_cards(db, user_id="u1", now=NOW)]
    assert first == second


def test_suspended_cards_do_not_appear_in_the_queue(db):
    deck = _deck(db)
    card = _card(db, deck["id"])
    repo.update_card(db, card["id"], user_id="u1", changes={"status": "suspended"})
    assert repo.due_cards(db, user_id="u1") == []
