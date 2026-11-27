"""Decks, cards and review events, stored durably.

Why durability was the first problem
------------------------------------
The flash cards that already existed were a *book generation block*: the model
wrote cards into a response, the reader saw them, and they were gone. That is a
fine way to render a page and a useless way to run a review system, because
every acceptance criterion Phase 7 has -- progress that survives a restart, a
deduplicated deck, a review history -- needs the card to outlive the response.

Why the scope check is here and not in the router
------------------------------------------------
Phase 6 shipped its scope check in the repository for a specific reason: a guard
in a router protects the routes that router knows about, and the next endpoint
someone adds is unprotected. The same reasoning applies to cards, and more
acutely -- a card carries an *owner* as well as a scope, so a single missed check
does not leak a curriculum, it leaks one student's mistakes to another. Every
read and write below takes the caller's enrolment or user id and refuses rather
than filters where a refusal is possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from deeptutor.db.connection import Database, DatabaseError
from deeptutor.services.review.schedule import (
    Rating,
    ReviewState,
    knowledge_type_for,
    schedule,
)
from deeptutor.services.scope import Enrolment, require_scope_reaches

#: Statuses a card can be in. ``suspended`` is a learner choice; ``archived`` is
#: a maintenance state. Both stay reviewable later, which is why they are not
#: deletes.
CARD_STATUSES = frozenset({"active", "suspended", "archived"})

#: How a card came to exist. Recorded so the dashboard can say *why* a card is
#: in the deck, which is the difference between evidence and a model suggestion.
PROVENANCE_KINDS = frozenset(
    {"book_chapter", "grounding_chunk", "exam_mistake", "manual"}
)


class CardError(RuntimeError):
    """A deck, card or review rule was violated."""

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _timestamp(moment: float | None = None) -> str:
    """An ISO-8601 UTC string for a scheduling moment (seconds since epoch)."""
    return datetime.fromtimestamp(
        _epoch(moment), tz=timezone.utc
    ).isoformat()


def _epoch(moment: float | None = None) -> float:
    """Seconds since epoch for *moment*, or now.

    ``moment=None`` means "now" and is the only place this module reads a clock.
    Everything downstream takes the value it was given, so a test can pin time.
    """
    import time

    return time.time() if moment is None else float(moment)


def _parse_epoch(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


def normalize_front(front: str) -> str:
    """The comparison form of a card's front, used for deduplication.

    Whitespace collapsed, case folded, Persian/Arabic digits and the Arabic
    yeh/kaf folded to their Persian forms. Without the script folding, "چند
    است؟" typed two ways is two cards, and a deck regenerated from the same
    chapter doubles in size -- which is exactly the failure the roadmap's
    deduplication criterion is about.
    """
    text = " ".join(str(front or "").split())
    text = text.translate(_FOLD_TABLE).lower()
    return text


#: Character folding for deduplication. Kept as an explicit table rather than
#: relying on ``unicodedata.normalize`` because these are *semantic* equivalences
#: in Persian, not compatibility decompositions.
_FOLD_TABLE = str.maketrans(
    {
        # Arabic yeh / alef maqsura -> Persian yeh
        "\u064a": "\u06cc",
        "\u0649": "\u06cc",
        # Arabic kaf -> Persian kaf
        "\u0643": "\u06a9",
        # Arabic-Indic digits -> ASCII
        "\u0660": "0",
        "\u0661": "1",
        "\u0662": "2",
        "\u0663": "3",
        "\u0664": "4",
        "\u0665": "5",
        "\u0666": "6",
        "\u0667": "7",
        "\u0668": "8",
        "\u0669": "9",
        # Persian digits -> ASCII
        "\u06f0": "0",
        "\u06f1": "1",
        "\u06f2": "2",
        "\u06f3": "3",
        "\u06f4": "4",
        "\u06f5": "5",
        "\u06f6": "6",
        "\u06f7": "7",
        "\u06f8": "8",
        "\u06f9": "9",
        # ZWNJ/ZWJ are orthographic, not semantic: drop them so
        # "می\u200cشود" and "میشود" are one card.
        "\u200c": "",
        "\u200d": "",
    }
)


def content_key(
    *,
    front: str,
    provenance_kind: str,
    provenance_id: str = "",
) -> str:
    """The deduplication identity of a card.

    Front text plus provenance *kind and id*: two cards asking the same question
    about two different chapters are genuinely different cards (one may be a
    simplification of the other), while the same question from the same chapter
    is a duplicate no matter how many times it is generated.
    """
    payload = "\x1f".join(
        [normalize_front(front), str(provenance_kind), str(provenance_id)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeckInput:
    title: str
    origin_kind: str = "manual"
    grade_number: int | None = None
    major_code: str | None = None
    subject_code: str | None = None
    origin_source_id: str | None = None
    origin_chapter: str = ""


def create_deck(
    db: Database,
    *,
    user_id: str,
    deck: DeckInput,
    enrolment: Enrolment | None = None,
) -> dict[str, Any]:
    """Create a deck for *user_id*, refusing one outside their enrolment.

    A deck carries a scope because the cards inside it will. Creating a grade-12
    deck as a grade-7 student is the same act as creating a grade-12 exam, and it
    is refused the same way -- at the write, not at the read.
    """
    if not str(user_id or "").strip():
        raise CardError("missing_user", "a deck needs an owner", field="user_id")
    if not str(deck.title or "").strip():
        raise CardError("empty_title", "a deck needs a title", field="title")
    if deck.origin_kind not in {"book", "exam_mistake", "manual"}:
        raise CardError(
            "invalid_origin",
            f"origin_kind must be book, exam_mistake or manual; got {deck.origin_kind!r}",
            field="origin_kind",
        )

    if enrolment is not None:
        require_scope_reaches(
            enrolment,
            grade_number=deck.grade_number,
            major_code=deck.major_code,
            what="این دستهٔ کارت",
        )

    deck_id = _new_id("deck")
    stamp = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO flashcard_decks "
            "(id, user_id, grade_number, major_code, subject_code, title, origin_kind, "
            " origin_source_id, origin_chapter, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                deck_id,
                user_id,
                deck.grade_number,
                deck.major_code,
                deck.subject_code,
                deck.title.strip(),
                deck.origin_kind,
                deck.origin_source_id,
                deck.origin_chapter,
                stamp,
                stamp,
            ),
        )
    return get_deck(db, deck_id, user_id=user_id)


def get_deck(db: Database, deck_id: str, *, user_id: str) -> dict[str, Any]:
    """One deck, only for its owner."""
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,))
    if row is None or row["user_id"] != user_id:
        # Same choice as attempts in Phase 6: not-found and not-yours are one
        # answer, so a guessed id confirms nothing.
        raise CardError("deck_not_found", f"no deck {deck_id!r}", field="deck_id")
    return dict(row)


def list_decks(db: Database, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """This owner's decks, with a card count and a due count.

    The counts are computed here rather than by the caller so every surface
    shows the same number, and so the due count uses the same ``status =
    'active'`` rule the review queue uses.
    """
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT d.*, "
                "  (SELECT COUNT(*) FROM flashcards c WHERE c.deck_id = d.id) AS card_count, "
                "  (SELECT COUNT(*) FROM flashcards c WHERE c.deck_id = d.id "
                "     AND c.status = 'active' AND c.due_at <= ?) AS due_count "
                "FROM flashcard_decks d WHERE d.user_id = ? "
                "ORDER BY d.created_at DESC LIMIT ?",
                (_now(), user_id, limit),
            )
        )
    return [dict(row) for row in rows]


def delete_deck(db: Database, deck_id: str, *, user_id: str) -> bool:
    """Delete a deck and its cards. Ownership checked before the delete."""
    get_deck(db, deck_id, user_id=user_id)
    with db.transaction() as conn:
        conn.execute("DELETE FROM flashcards WHERE deck_id = ?", (deck_id,))
        conn.execute("DELETE FROM flashcard_decks WHERE id = ?", (deck_id,))
    return True


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardInput:
    front: str
    back: str
    hint: str = ""
    provenance_kind: str = "manual"
    source_id: str | None = None
    chapter_title: str = ""
    citation: str = ""
    origin_attempt_id: str | None = None
    origin_question_id: str | None = None
    knowledge_point_id: str | None = None
    knowledge_type: str = "concept"
    #: For mistake cards: the dedup identity should be the question, not the
    #: chapter, so retaking the same exam does not add the card again.
    provenance_id: str = ""


def add_card(
    db: Database,
    *,
    deck_id: str,
    user_id: str,
    card: CardInput,
    now: float | None = None,
) -> dict[str, Any]:
    """Add one card, or return the existing card with the same content key.

    Deduplication is **not** an error: regenerating a deck from the same chapter
    is a normal, repeated action, and failing the second run would make the
    feature unusable. The returned payload says which happened via
    ``duplicate``, so a caller can report "3 new, 12 already present" instead of
    guessing.
    """
    deck = get_deck(db, deck_id, user_id=user_id)

    if not str(card.front or "").strip():
        raise CardError("empty_front", "a card needs a front", field="front")
    if not str(card.back or "").strip():
        raise CardError("empty_back", "a card needs a back", field="back")
    if card.provenance_kind not in PROVENANCE_KINDS:
        raise CardError(
            "invalid_provenance",
            f"provenance_kind must be one of {sorted(PROVENANCE_KINDS)}",
            field="provenance_kind",
        )

    key = content_key(
        front=card.front,
        provenance_kind=card.provenance_kind,
        provenance_id=card.provenance_id or card.source_id or card.origin_question_id or "",
    )
    moment = _epoch(now)
    stamp = _timestamp(moment)

    with db.read() as conn:
        existing = conn.query_one(
            "SELECT * FROM flashcards WHERE user_id = ? AND content_key = ?",
            (user_id, key),
        )
    if existing is not None:
        return {**dict(existing), "duplicate": True}

    card_id = _new_id("card")
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO flashcards "
                "(id, deck_id, user_id, front, back, hint, content_key, provenance_kind, "
                " source_id, chapter_title, citation, origin_attempt_id, origin_question_id, "
                " knowledge_point_id, knowledge_type, due_at, interval_index, "
                " consecutive_correct, consecutive_wrong, review_count, lapse_count, "
                " last_reviewed_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, "
                "        NULL, 'active', ?, ?)",
                (
                    card_id,
                    deck_id,
                    user_id,
                    card.front.strip(),
                    card.back.strip(),
                    card.hint,
                    key,
                    card.provenance_kind,
                    card.source_id,
                    card.chapter_title,
                    card.citation,
                    card.origin_attempt_id,
                    card.origin_question_id,
                    card.knowledge_point_id,
                    str(knowledge_type_for(card.knowledge_type).value),
                    stamp,
                    stamp,
                    stamp,
                ),
            )
    except DatabaseError as exc:
        # The same race Phase 6 fixed: two concurrent adds both pass the read
        # and the loser hits uq_flashcards_owner_content. A duplicate is the
        # intended outcome, so return the winner instead of surfacing an error.
        if "uq_flashcards_owner_content" not in str(exc) and "UNIQUE" not in str(exc):
            raise
        with db.read() as conn:
            winner = conn.query_one(
                "SELECT * FROM flashcards WHERE user_id = ? AND content_key = ?",
                (user_id, key),
            )
        if winner is None:  # pragma: no cover - the collision implies a row
            raise
        return {**dict(winner), "duplicate": True}

    return {**get_card(db, card_id, user_id=user_id), "duplicate": False}


def add_cards(
    db: Database,
    *,
    deck_id: str,
    user_id: str,
    cards: Sequence[CardInput],
    now: float | None = None,
) -> dict[str, Any]:
    """Add many cards, reporting what was new and what was already there."""
    created: list[dict[str, Any]] = []
    existing = 0
    for card in cards:
        row = add_card(db, deck_id=deck_id, user_id=user_id, card=card, now=now)
        if row.get("duplicate"):
            existing += 1
        else:
            created.append(row)
    return {"cards": created, "created": len(created), "duplicates": existing}


def get_card(db: Database, card_id: str, *, user_id: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM flashcards WHERE id = ?", (card_id,))
    if row is None or row["user_id"] != user_id:
        raise CardError("card_not_found", f"no card {card_id!r}", field="card_id")
    return dict(row)


def list_cards(
    db: Database,
    *,
    user_id: str,
    deck_id: str | None = None,
    status: str | None = "active",
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if deck_id is not None:
        get_deck(db, deck_id, user_id=user_id)  # ownership, before the read
        clauses.append("deck_id = ?")
        params.append(deck_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    params.append(limit)
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM flashcards WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )
        )
    return [dict(row) for row in rows]


def update_card(
    db: Database, card_id: str, *, user_id: str, changes: Mapping[str, Any]
) -> dict[str, Any]:
    """Edit a card's text or status. Review state is not editable here.

    Deliberately narrow: letting a caller set ``due_at`` or ``review_count``
    through an edit endpoint would make the review history deniable -- the
    stored events would no longer explain the stored state. Those fields move
    only through :func:`review_card`.
    """
    get_card(db, card_id, user_id=user_id)
    allowed = {"front", "back", "hint", "status"}
    updates = {key: value for key, value in changes.items() if key in allowed}
    if not updates:
        raise CardError("no_changes", "nothing to update", field=None)
    if "status" in updates and updates["status"] not in CARD_STATUSES:
        raise CardError(
            "invalid_status",
            f"status must be one of {sorted(CARD_STATUSES)}",
            field="status",
        )
    for field in ("front", "back"):
        if field in updates and not str(updates[field] or "").strip():
            raise CardError(f"empty_{field}", f"a card needs a {field}", field=field)

    assignments = ", ".join(f"{key} = ?" for key in updates)
    params = [updates[key] for key in updates]
    params.extend([_now(), card_id])
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE flashcards SET {assignments}, updated_at = ? WHERE id = ?",
            tuple(params),
        )
    return get_card(db, card_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def _state_of(card: Mapping[str, Any]) -> ReviewState:
    return ReviewState(
        interval_index=int(card.get("interval_index") or 0),
        consecutive_correct=int(card.get("consecutive_correct") or 0),
        consecutive_wrong=int(card.get("consecutive_wrong") or 0),
        review_count=int(card.get("review_count") or 0),
        lapse_count=int(card.get("lapse_count") or 0),
        due_at=_parse_epoch(card.get("due_at")),
        last_reviewed_at=(
            _parse_epoch(card.get("last_reviewed_at"))
            if card.get("last_reviewed_at")
            else None
        ),
    )


def review_card(
    db: Database,
    *,
    card_id: str,
    user_id: str,
    rating: Rating | str,
    now: float | None = None,
) -> dict[str, Any]:
    """Record one review and move the card's due date.

    The card update and the history row are written in **one transaction**. A
    review that rescheduled the card but lost its event would leave a due date
    nothing can explain, which is precisely the "evidence, not estimate"
    property the roadmap asks for.
    """
    card = get_card(db, card_id, user_id=user_id)
    if card["status"] != "active":
        raise CardError(
            "card_not_active",
            f"card is {card['status']!r}; only active cards can be reviewed",
            field="status",
        )

    moment = _epoch(now)
    state = _state_of(card)
    outcome = schedule(
        state,
        knowledge_type_for(card.get("knowledge_type")),
        rating,  # type: ignore[arg-type]
        now=moment,
    )

    due_after = _timestamp(outcome.state.due_at)
    due_before = str(card.get("due_at") or "")

    with db.transaction() as conn:
        conn.execute(
            "UPDATE flashcards SET due_at = ?, interval_index = ?, "
            "consecutive_correct = ?, consecutive_wrong = ?, review_count = ?, "
            "lapse_count = ?, last_reviewed_at = ?, updated_at = ? WHERE id = ?",
            (
                due_after,
                outcome.state.interval_index,
                outcome.state.consecutive_correct,
                outcome.state.consecutive_wrong,
                outcome.state.review_count,
                outcome.state.lapse_count,
                _timestamp(moment),
                _now(),
                card_id,
            ),
        )
        conn.execute(
            "INSERT INTO flashcard_reviews "
            "(id, card_id, user_id, rating, quality, interval_index_before, "
            " interval_index_after, due_at_before, due_at_after, reviewed_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'flashcard')",
            (
                _new_id("rev"),
                card_id,
                user_id,
                outcome.rating,
                outcome.quality,
                state.interval_index,
                outcome.state.interval_index,
                due_before,
                due_after,
                _timestamp(moment),
            ),
        )

    updated = get_card(db, card_id, user_id=user_id)
    return {
        "card": updated,
        "review": outcome.as_evidence(),
        "due_at": due_after,
        "interval_days": outcome.interval_days,
    }


def due_cards(
    db: Database, *, user_id: str, now: float | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Cards due at ``now``, most overdue first.

    Ordering is deterministic -- due time, then id -- so two callers asking at
    the same instant see the same queue. A queue that reshuffles between calls
    makes "I reviewed everything" unverifiable.
    """
    moment = _timestamp(_epoch(now))
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT c.*, d.title AS deck_title FROM flashcards c "
                "JOIN flashcard_decks d ON d.id = c.deck_id "
                "WHERE c.user_id = ? AND c.status = 'active' AND c.due_at <= ? "
                "ORDER BY c.due_at ASC, c.id ASC LIMIT ?",
                (user_id, moment, limit),
            )
        )
    return [dict(row) for row in rows]


def review_history(db: Database, card_id: str, *, user_id: str) -> list[dict[str, Any]]:
    """Every review of one card, oldest first. Ownership checked first."""
    get_card(db, card_id, user_id=user_id)
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM flashcard_reviews WHERE card_id = ? "
                "ORDER BY reviewed_at ASC, id ASC",
                (card_id,),
            )
        )
    return [dict(row) for row in rows]


def all_reviews(db: Database, *, user_id: str, limit: int = 2000) -> list[dict[str, Any]]:
    """Every review this owner has recorded, newest first.

    Used by the mastery dashboard to turn reviews into chapter evidence. Bounded
    by ``limit`` because the dashboard needs recent signal, not an archive; a
    learner with more rows than this sees their recent history, which is what
    mastery weighting uses anyway.
    """
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM flashcard_reviews WHERE user_id = ? "
                "ORDER BY reviewed_at DESC, id DESC LIMIT ?",
                (user_id, limit),
            )
        )
    return [dict(row) for row in rows]


def cards_by_id(db: Database, *, user_id: str, card_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Fetch a set of cards the caller owns, keyed by id.

    Missing ids are simply absent: this is a join helper for a dashboard, not an
    authorisation check. Ownership is part of the query, so a card belonging to
    someone else can never appear in the result.
    """
    wanted = [str(card_id) for card_id in card_ids]
    if not wanted:
        return {}
    placeholders = ", ".join("?" for _ in wanted)
    with db.read() as conn:
        rows = list(
            conn.query(
                f"SELECT * FROM flashcards WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *wanted),
            )
        )
    return {str(row["id"]): dict(row) for row in rows}


def review_summary(db: Database, *, user_id: str, now: float | None = None) -> dict[str, Any]:
    """Counts for the dashboard, all from stored rows.

    Everything here is a count of facts (cards, reviews, lapses), never a model
    estimate. That distinction is the roadmap's acceptance criterion and it is
    also the only kind of number a learner can act on.
    """
    moment = _timestamp(_epoch(now))
    with db.read() as conn:
        total = conn.scalar(
            "SELECT COUNT(*) FROM flashcards WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        due = conn.scalar(
            "SELECT COUNT(*) FROM flashcards WHERE user_id = ? AND status = 'active' "
            "AND due_at <= ?",
            (user_id, moment),
        )
        reviewed = conn.scalar(
            "SELECT COUNT(*) FROM flashcard_reviews WHERE user_id = ?", (user_id,)
        )
        lapses = conn.scalar(
            "SELECT COUNT(*) FROM flashcard_reviews WHERE user_id = ? AND rating = 'again'",
            (user_id,),
        )
        by_rating = list(
            conn.query(
                "SELECT rating, COUNT(*) AS count FROM flashcard_reviews "
                "WHERE user_id = ? GROUP BY rating ORDER BY rating",
                (user_id,),
            )
        )
    return {
        "cards": int(total or 0),
        "due": int(due or 0),
        "reviews": int(reviewed or 0),
        "lapses": int(lapses or 0),
        "by_rating": {row["rating"]: int(row["count"]) for row in by_rating},
    }


# ---------------------------------------------------------------------------
# Building cards from evidence
# ---------------------------------------------------------------------------


def cards_from_mistakes(
    db: Database,
    *,
    user_id: str,
    attempt_id: str,
    deck_id: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Turn an attempt's wrong answers into review cards.

    This is the roadmap's "cards from exam mistakes", and the whole point is
    that a card is built from **what the student actually answered**, not from
    what a model guesses they might not know. Each card therefore carries the
    attempt id and question id it came from, which is what makes the provenance
    checkable after the fact.

    Idempotent by construction: the content key includes the question id, so
    re-running this for the same attempt adds nothing and reports how many cards
    already existed.
    """
    from deeptutor.db.repositories import exam as exam_repo

    attempt = exam_repo.get_attempt(db, attempt_id)
    if attempt["user_id"] != user_id:
        raise CardError("attempt_not_found", "no such attempt", field="attempt_id")

    report = exam_repo.mistake_report(db, attempt_id)
    snapshot = {
        str(item["question_id"]): item
        for item in json.loads(attempt.get("question_snapshot") or "[]")
    }

    cards: list[CardInput] = []
    for wrong in report["wrong_items"]:
        question_id = str(wrong["question_id"])
        meta = snapshot.get(question_id, {})
        body = str(meta.get("body") or "").strip()
        if not body:
            # A card with no question text cannot be reviewed; generating an
            # empty front would create a row the learner can never answer.
            continue
        choices = _choices_of(meta.get("choices"))
        answer_key = str(meta.get("answer_key") or "").strip()
        back = _answer_text(answer_key, choices)
        if not back:
            # Same rule as Phase 6 grading: a question with no resolvable key is
            # not gradeable, so it is not reviewable either. Skipping is the
            # honest outcome; inventing an answer would be a fabrication.
            continue
        cards.append(
            CardInput(
                front=body,
                back=back,
                hint=str(meta.get("chapter_title") or ""),
                provenance_kind="exam_mistake",
                chapter_title=str(meta.get("chapter_title") or ""),
                citation=f"آزمون {attempt_id} · سؤال {question_id}",
                origin_attempt_id=attempt_id,
                origin_question_id=question_id,
                knowledge_point_id=str(meta.get("topic") or "") or None,
                knowledge_type="concept",
                provenance_id=f"{attempt_id}:{question_id}",
            )
        )

    result = add_cards(db, deck_id=deck_id, user_id=user_id, cards=cards, now=now)
    return {**result, "attempt_id": attempt_id, "considered": len(report["wrong_items"])}


def _choices_of(raw: Any) -> list[str]:
    """Split a snapshot's choices into a list.

    The snapshot stores choices newline-delimited (the Phase 6 decision: both
    engines store TEXT and a delimiter that cannot appear in a choice is simpler
    than JSON). Iterating a string directly yields characters, so a choice list
    read naively would turn "تهران" into "ت" -- which is exactly the bug this
    helper exists to prevent from being written a second time.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(choice) for choice in raw if str(choice).strip()]
    return [part for part in str(raw).split("\n") if part.strip()]


def _answer_text(answer_key: str, choices: Sequence[str]) -> str:
    """Render an answer key as the text a learner should recall.

    The key is stored as a bare index more often than not, and a card whose back
    says "1" teaches nothing -- the learner has to remember what choice 1 was.
    The resolution order matches Phase 6's scorer (choice text first, then
    index) so the card and the grade agree about what the answer is.
    """
    key = str(answer_key or "").strip()
    if not key:
        return ""
    if key in choices:
        return key
    try:
        index = int(key)
    except ValueError:
        return key
    if 0 <= index < len(choices):
        return str(choices[index])
    return key
