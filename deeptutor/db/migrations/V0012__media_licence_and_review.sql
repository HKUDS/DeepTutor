-- Phase 8 finish: licence enforcement and a place for the human verdict.
--
-- Two gaps this closes, both of which were the difference between "the
-- mechanism exists" and "the mechanism holds".
--
-- 1. A licence that is not required is not a licence
-- -------------------------------------------------
-- `build_script` already refused source text without a `source_id`. But an
-- asset could still be created from a source with `licence_code = ''`: the row
-- said "this came from src_9" and nothing said what we were allowed to do with
-- it. Reuse and provenance were both checking a field that could be empty and
-- therefore meant nothing.
--
-- The enforcement itself is in `services/studio/jobs.py` plus a pair of
-- triggers installed by `db/repositories/media.ensure_integrity_guards()`, not
-- here: SQLite cannot add a CHECK to an existing table without rebuilding it,
-- and a trigger body needs `BEGIN ... END`, which this migration runner's
-- statement splitter cannot express. A guarantee that silently half-applies is
-- worse than one installed where it either works or fails loudly, so the
-- triggers are created once at startup and verified by a test.
--
-- `licence_code` stays nullable-for-'' only in the user_prompt case, where
-- there is no source and therefore nothing to licence.
--
-- 2. A checklist nobody can fill is a ceremony
-- --------------------------------------------
-- `quality_checklist(kind)` returns the questions a reviewer should answer,
-- but there was nowhere to put the answers. Gate 8 says Persian quality must
-- be assessed with a human checklist; without storage, "assessed" could only
-- ever mean "we wrote some criteria down".
--
-- `media_quality_reviews` records: which checklist item, what verdict, who
-- said it, and when. The reviewer is a separate identity from the asset owner
-- on purpose -- a self-review is allowed to be recorded (pretending it never
-- happens would just push it off the record) but `reviewer_id = user_id` is
-- distinguishable, so a report can say how much of the evidence is
-- independent.
--
-- Verdicts are three-valued, not a boolean: `pass`, `fail`, and `unclear`.
-- "I looked and could not decide" is a real outcome, and forcing it into
-- pass/fail produces false confidence in whichever direction the reviewer
-- leaned.

-- @@ UP @@

CREATE TABLE IF NOT EXISTS media_quality_reviews (
    id            TEXT PRIMARY KEY,
    asset_id      TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    item_id       TEXT NOT NULL,
    verdict       TEXT NOT NULL CHECK (verdict IN ('pass', 'fail', 'unclear')),
    reviewer_id   TEXT NOT NULL,
    comment       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    -- One verdict per item per reviewer: a reviewer changing their mind is an
    -- update, not a second opinion that makes the count meaningless.
    UNIQUE (asset_id, item_id, reviewer_id)
);

CREATE INDEX IF NOT EXISTS ix_media_quality_reviews_asset
    ON media_quality_reviews (asset_id, created_at);

-- @@ DOWN @@


DROP INDEX IF EXISTS ix_media_quality_reviews_asset;
DROP TABLE IF EXISTS media_quality_reviews;
