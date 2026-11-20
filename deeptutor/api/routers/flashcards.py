"""Flashcards and personalised review API.

One audience and one policy: ``learning``. Everything here is a student acting
on *their own* material, so there is no admin surface. A card is not shared
content and there is no operator view of another student's deck -- the very idea
would turn a study aid into a surveillance tool.

Identity comes from the session
-------------------------------
Every endpoint resolves the caller through :func:`deeptutor.services.scope.caller_id`
rather than trusting a ``user_id`` in the request. Phase 6 shipped with the
opposite habit in three places and it was the most serious bug of that phase;
this surface is born with the rule already applied.

Why there is a ``/summary`` endpoint at all
------------------------------------------
Because "progress" on a dashboard must be a count of stored facts -- cards,
reviews, lapses -- and not a model's impression. Returning the raw counts lets
the UI say "۱۲ مرور، ۳ فراموشی" with a straight face.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.db.repositories import flashcards as repo
from deeptutor.services.review.schedule import RATINGS
from deeptutor.services.scope import ScopeError, as_http, caller_id, resolve_enrolment

router = APIRouter()


def _database() -> Any:
    from deeptutor.db.config import get_database_settings

    settings = get_database_settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=503, detail="database is not configured; set DEEPTUTOR_DATABASE_URL"
        )
    database = open_database(settings)
    if database is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="database is unavailable")
    return database


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, repo.CardError):
        not_found = {"deck_not_found", "card_not_found", "attempt_not_found"}
        if exc.rule in not_found:
            return HTTPException(
                status_code=404,
                detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
            )
        conflict = {"card_not_active"}
        status = 409 if exc.rule in conflict else 422
        return HTTPException(
            status_code=status,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, ScopeError):
        return as_http(exc)
    if isinstance(exc, ValueError):
        # A bad rating reaches here from the scheduler's own validation. It is
        # the caller's mistake, so 422 rather than a 500.
        return HTTPException(status_code=422, detail={"rule": "invalid_input", "message": str(exc)})
    if isinstance(exc, DatabaseError):
        return HTTPException(status_code=503, detail="database unavailable")
    raise exc


def _caller(user_id: str | None) -> str:
    """The caller's id, resolved server-side, or 401 if there is none.

    With authentication on, ``caller_id`` discards whatever the request said. A
    blank result means the session resolved to nobody, and every endpoint here
    needs an owner, so it is refused rather than defaulted.
    """
    resolved = caller_id(user_id)
    if not resolved:
        raise HTTPException(
            status_code=401,
            detail={"rule": "missing_user", "message": "a caller id is required"},
        )
    return resolved


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class DeckPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    origin_kind: str = "manual"
    grade_number: int | None = Field(None, ge=1, le=20)
    major_code: str | None = None
    subject_code: str | None = None
    origin_source_id: str | None = None
    origin_chapter: str = ""


class CardPayload(BaseModel):
    front: str = Field(..., min_length=1, max_length=4000)
    back: str = Field(..., min_length=1, max_length=4000)
    hint: str = ""
    provenance_kind: str = "manual"
    source_id: str | None = None
    chapter_title: str = ""
    citation: str = ""
    origin_attempt_id: str | None = None
    origin_question_id: str | None = None
    knowledge_point_id: str | None = None
    knowledge_type: str = "concept"
    provenance_id: str = ""


class CardsPayload(BaseModel):
    cards: list[CardPayload] = Field(default_factory=list)


class ReviewPayload(BaseModel):
    rating: str = Field(..., description=f"one of {list(RATINGS)}")


class CardPatch(BaseModel):
    front: str | None = None
    back: str | None = None
    hint: str | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------


@router.get("/decks")
async def list_decks(
    user_id: str | None = Query(None), limit: int = Query(100, ge=1, le=500)
) -> dict:
    """Every deck this caller owns, with counts."""
    database = _database()
    try:
        owner = _caller(user_id)
        decks = repo.list_decks(database, user_id=owner, limit=limit)
        return {"decks": decks, "count": len(decks)}
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/decks", status_code=201)
async def create_deck(payload: DeckPayload, user_id: str | None = Query(None)) -> dict:
    """Create a deck for the caller.

    The deck's scope is checked against the caller's enrolment, so a grade-7
    student cannot create a grade-12 deck and then find it empty of anything
    they may read -- the refusal happens at the write.
    """
    database = _database()
    try:
        owner = _caller(user_id)
        enrolment = resolve_enrolment(database, user_id=owner)
        deck = repo.create_deck(
            database,
            user_id=owner,
            deck=repo.DeckInput(
                title=payload.title,
                origin_kind=payload.origin_kind,
                grade_number=payload.grade_number,
                major_code=payload.major_code,
                subject_code=payload.subject_code,
                origin_source_id=payload.origin_source_id,
                origin_chapter=payload.origin_chapter,
            ),
            enrolment=enrolment,
        )
        return deck
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/decks/{deck_id}")
async def get_deck(deck_id: str, user_id: str | None = Query(None)) -> dict:
    database = _database()
    try:
        return repo.get_deck(database, deck_id, user_id=_caller(user_id))
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.delete("/decks/{deck_id}")
async def delete_deck(deck_id: str, user_id: str | None = Query(None)) -> dict:
    database = _database()
    try:
        return {"deleted": repo.delete_deck(database, deck_id, user_id=_caller(user_id))}
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


@router.get("/decks/{deck_id}/cards")
async def list_cards(
    deck_id: str,
    user_id: str | None = Query(None),
    status: str | None = Query("active"),
    limit: int = Query(200, ge=1, le=500),
) -> dict:
    database = _database()
    try:
        cards = repo.list_cards(
            database,
            user_id=_caller(user_id),
            deck_id=deck_id,
            status=status,
            limit=limit,
        )
        return {"cards": cards, "count": len(cards)}
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/decks/{deck_id}/cards", status_code=201)
async def add_cards(
    deck_id: str, payload: CardsPayload, user_id: str | None = Query(None)
) -> dict:
    """Add cards, deduplicated.

    Returns ``created`` and ``duplicates`` rather than failing on a repeat: a
    deck regenerated from the same chapter must be safe to regenerate.
    """
    database = _database()
    try:
        owner = _caller(user_id)
        result = repo.add_cards(
            database,
            deck_id=deck_id,
            user_id=owner,
            cards=[repo.CardInput(**card.model_dump()) for card in payload.cards],
        )
        return result
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/decks/{deck_id}/from-mistakes", status_code=201)
async def cards_from_mistakes(
    deck_id: str, attempt_id: str = Query(..., min_length=1), user_id: str | None = Query(None)
) -> dict:
    """Build review cards from one attempt's wrong answers.

    This is the roadmap's "cards from exam mistakes". The cards are derived from
    what the student actually answered on that attempt, and each keeps the
    attempt and question ids as provenance.
    """
    database = _database()
    try:
        owner = _caller(user_id)
        return repo.cards_from_mistakes(
            database, user_id=owner, attempt_id=attempt_id, deck_id=deck_id
        )
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/cards/{card_id}")
async def get_card(card_id: str, user_id: str | None = Query(None)) -> dict:
    database = _database()
    try:
        return repo.get_card(database, card_id, user_id=_caller(user_id))
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.patch("/cards/{card_id}")
async def patch_card(
    card_id: str, payload: CardPatch, user_id: str | None = Query(None)
) -> dict:
    """Edit a card's text or status -- never its review state.

    Review state moves only through a recorded review, so the history always
    explains the schedule.
    """
    database = _database()
    try:
        changes = payload.model_dump(exclude_none=True)
        return repo.update_card(database, card_id, user_id=_caller(user_id), changes=changes)
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.delete("/cards/{card_id}")
async def archive_card(card_id: str, user_id: str | None = Query(None)) -> dict:
    """Archive rather than delete: the review history is evidence."""
    database = _database()
    try:
        return repo.update_card(
            database, card_id, user_id=_caller(user_id), changes={"status": "archived"}
        )
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@router.get("/review/queue")
async def review_queue(user_id: str | None = Query(None), limit: int = Query(50, ge=1, le=200)) -> dict:
    """Cards due right now, most overdue first."""
    database = _database()
    try:
        cards = repo.due_cards(database, user_id=_caller(user_id), limit=limit)
        return {"cards": cards, "count": len(cards)}
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/cards/{card_id}/review")
async def review_card(
    card_id: str, payload: ReviewPayload, user_id: str | None = Query(None)
) -> dict:
    """Record one review and schedule the next one.

    The rating is one of again/hard/good/easy. The next due date is computed by
    a pure function of the card's stored state and this review -- the same
    inputs always give the same schedule.
    """
    database = _database()
    try:
        return repo.review_card(
            database,
            card_id=card_id,
            user_id=_caller(user_id),
            rating=payload.rating,
        )
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/cards/{card_id}/history")
async def card_history(card_id: str, user_id: str | None = Query(None)) -> dict:
    """Every review of one card, oldest first."""
    database = _database()
    try:
        reviews = repo.review_history(database, card_id, user_id=_caller(user_id))
        return {"reviews": reviews, "count": len(reviews)}
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/summary")
async def summary(user_id: str | None = Query(None)) -> dict:
    """Stored counts for the dashboard: cards, due, reviews, lapses.

    Every number is a count of rows. None of it is a model's estimate of how
    well the learner knows something.
    """
    database = _database()
    try:
        return repo.review_summary(database, user_id=_caller(user_id))
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Mastery dashboard
# ---------------------------------------------------------------------------


@router.get("/mastery")
async def mastery_dashboard(
    user_id: str | None = Query(None),
    by: str = Query("chapter", pattern="^(chapter|topic)$"),
    attempt_limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Per-chapter or per-topic mastery, from stored evidence only.

    Two sources are merged and each observation keeps its label (``exam`` or
    ``review``) so a caller can weight them differently. Nothing here consults a
    model: the figures are counts and the same recency-weighted policy the
    Mastery Path already uses.

    A group with no observations is absent rather than reported as zero -- see
    :mod:`deeptutor.services.review.mastery` for why that distinction matters.
    """
    from deeptutor.db.repositories import exam as exam_repo
    from deeptutor.services.review.mastery import (
        evidence_from_exam_attempt,
        evidence_from_reviews,
        group_mastery,
        suggest_practice,
    )

    database = _database()
    try:
        owner = _caller(user_id)
        observations = []

        # Exam evidence: the attempts are the student's own, by the query.
        attempts = exam_repo.list_attempts(database, user_id=owner, limit=attempt_limit)
        for attempt in attempts:
            if attempt.get("status") not in {"graded", "submitted"}:
                continue
            import json

            snapshot = json.loads(attempt.get("question_snapshot") or "[]")
            full = exam_repo.get_attempt(database, attempt["id"])
            observations.extend(evidence_from_exam_attempt(full, snapshot))

        # Review evidence, joined back to the cards that carry the chapter.
        reviews = repo.all_reviews(database, user_id=owner)
        cards = repo.cards_by_id(
            database, user_id=owner, card_ids=[str(r["card_id"]) for r in reviews]
        )
        observations.extend(evidence_from_reviews(reviews, cards))

        if by == "topic":
            # Topic evidence is carried on exam items only; reviews are filed
            # under chapters because a card records a chapter, not a topic.
            observations = [item for item in observations if item.source == "exam"]

        groups = group_mastery(observations)
        return {
            "by": by,
            "groups": [group.as_dict() for group in groups],
            "suggestions": suggest_practice(groups),
            "evidence_count": len(observations),
        }
    except (repo.CardError, ScopeError, ValueError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()
