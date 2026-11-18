-- Phase 7: mastery, flashcards and personalised review.
--
-- Two rules shape this schema, and both are about what must NOT happen.
--
-- 1. **A card is an artefact, not a rendering.** The flash cards that existed
--    before this migration were produced by the book generator, held in a
--    response body, and forgotten. Nothing could answer "which cards does this
--    student have", "when did they last see this one", or "did they get it
--    right". A review system cannot be built on output that was never stored,
--    so cards here are rows with an owner, a due date and a history.
--
-- 2. **A card must be able to say where it came from.** Every card carries the
--    provenance it was derived from -- a book chapter, a grounding chunk, or a
--    specific wrong answer on a specific attempt. Without that, a card is an
--    unsourced assertion, and the roadmap's "evidence, not a model estimate"
--    requirement cannot be checked by anyone, including the learner.
--
-- Deduplication is a unique index over a content key rather than a
-- deduplication pass, for the same reason Phase 6 made the unique index the
-- arbiter of submission: a periodic sweep only deduplicates the rows that
-- already escaped.

-- @@ UP @@

-- One deck per (owner, subject). Students do not curate decks; decks are the
-- scope a card lives in, derived from where the card came from. A student who
-- wants their own grouping will get an explicit "collections" concept later,
-- and it should not be this table wearing a different label.
CREATE TABLE IF NOT EXISTS flashcard_decks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    -- The scope the deck's cards belong to. Nullable because an unscoped deck
    -- is legitimate (a general deck), not because scope is optional.
    grade_number INTEGER,
    major_code TEXT,
    subject_code TEXT,
    title TEXT NOT NULL,
    -- 'book' | 'exam_mistake' | 'manual'
    origin_kind TEXT NOT NULL DEFAULT 'manual',
    -- Where the whole deck came from, for the book case: a source id and a
    -- chapter. Individual cards carry their own finer-grained provenance.
    origin_source_id TEXT,
    origin_chapter TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_flashcard_decks_owner ON flashcard_decks (user_id, created_at);

-- One card, owned by one deck.
--
-- `content_key` is the deduplication identity: sha256 of the normalised front
-- text plus the provenance kind. Two cards that ask the same thing from the
-- same place are the same card, and inserting the second one is a no-op rather
-- than an error -- regenerating a deck from the same chapter must be safe to
-- repeat.
CREATE TABLE IF NOT EXISTS flashcards (
    id TEXT PRIMARY KEY,
    deck_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    hint TEXT NOT NULL DEFAULT '',
    -- sha256(deck scope | normalised front | provenance kind | provenance id)
    content_key TEXT NOT NULL,
    -- 'book_chapter' | 'grounding_chunk' | 'exam_mistake' | 'manual'
    provenance_kind TEXT NOT NULL DEFAULT 'manual',
    -- Which book chapter this came from, when it came from one.
    source_id TEXT,
    chapter_title TEXT NOT NULL DEFAULT '',
    -- Citation as rendered for the learner, copied at creation so a later
    -- re-ingest cannot silently change what a card claims to be based on.
    citation TEXT NOT NULL DEFAULT '',
    -- The wrong answer this card was built from, when that is the origin.
    -- Nullable: most cards are not mistake cards.
    origin_attempt_id TEXT,
    origin_question_id TEXT,
    knowledge_point_id TEXT,
    -- 'memory' | 'concept' | 'procedure' | 'design' -- the scheduler's own
    -- taxonomy, so review scheduling reuses the existing policy instead of
    -- inventing a second one beside it.
    knowledge_type TEXT NOT NULL DEFAULT 'concept',
    -- Review state, denormalised onto the card because it is read on every
    -- queue build. The authoritative history is `flashcard_reviews`.
    due_at TEXT NOT NULL,
    interval_index INTEGER NOT NULL DEFAULT 0,
    consecutive_correct INTEGER NOT NULL DEFAULT 0,
    consecutive_wrong INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    lapse_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,
    -- 'active' | 'suspended' | 'archived'
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (deck_id) REFERENCES flashcard_decks (id) ON DELETE CASCADE
);
-- The dedup rule. Scoped by owner as well as content so two students who were
-- both wrong on the same question each get their own card, which is what makes
-- the history meaningful.
CREATE UNIQUE INDEX IF NOT EXISTS uq_flashcards_owner_content
    ON flashcards (user_id, content_key);
CREATE INDEX IF NOT EXISTS ix_flashcards_deck ON flashcards (deck_id, created_at);
CREATE INDEX IF NOT EXISTS ix_flashcards_due ON flashcards (user_id, status, due_at);

-- Append-only. A review event is a fact about a moment; rewriting it would
-- destroy the evidence the progress dashboard rests on. Corrections are new
-- rows with a later timestamp, not updates.
CREATE TABLE IF NOT EXISTS flashcard_reviews (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    -- The learner's own verdict, before scheduling. 'again' | 'hard' | 'good'
    -- | 'easy'. Kept distinct from the normalised quality below so the raw
    -- signal survives any future change to how quality is inferred.
    rating TEXT NOT NULL,
    -- Normalised 0..1 strength fed to the scheduler.
    quality REAL NOT NULL,
    interval_index_before INTEGER NOT NULL,
    interval_index_after INTEGER NOT NULL,
    due_at_before TEXT NOT NULL,
    due_at_after TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    -- Where this review happened, for the "evidence, not estimate" audit.
    -- 'flashcard' for a self-review here, or the exam attempt that settled it.
    source TEXT NOT NULL DEFAULT 'flashcard',
    FOREIGN KEY (card_id) REFERENCES flashcards (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_flashcard_reviews_card ON flashcard_reviews (card_id, reviewed_at);
CREATE INDEX IF NOT EXISTS ix_flashcard_reviews_owner ON flashcard_reviews (user_id, reviewed_at);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_flashcard_reviews_owner;
DROP INDEX IF EXISTS ix_flashcard_reviews_card;
DROP TABLE IF EXISTS flashcard_reviews;
DROP INDEX IF EXISTS ix_flashcards_due;
DROP INDEX IF EXISTS ix_flashcards_deck;
DROP INDEX IF EXISTS uq_flashcards_owner_content;
DROP TABLE IF EXISTS flashcards;
DROP INDEX IF EXISTS ix_flashcard_decks_owner;
DROP TABLE IF EXISTS flashcard_decks;
