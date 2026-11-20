-- Phase 8 sweep: explicit access grants on media assets.
--
-- Phase 8 shipped with exactly one rule: an asset belongs to one user and only
-- that user can read it. The phase's acceptance criterion says "only by its
-- owner **or someone authorized**", so the second half needs a way to exist.
--
-- Why a grant table and not a `visibility` column
-- ----------------------------------------------
-- A visibility flag answers "can everyone see this?" and nothing else. The
-- cases a class actually produces are narrower than that: a teacher shares one
-- lesson with one student, a group shares with a study circle, and the same
-- asset may be shared with two different people for two different reasons.
-- A row per (asset, grantee) records *who* and *when*, which is what a "why can
-- this person open my file" question needs. A flag records only "yes".
--
-- Why `granted_by` and `expires_at`
-- --------------------------------
-- `granted_by` matters the moment there is more than one way to become
-- authorized: without it, a revoked grant cannot be traced to the person who
-- made it. `expires_at` is nullable and null means "no expiry" -- a temporary
-- share is a different promise from a permanent one, and the difference has to
-- be representable before it can be enforced.
--
-- The owner is never written into this table. Ownership is a fact about the
-- asset row (`media_assets.user_id`); duplicating it here would create a second
-- source of truth and, worse, a grant row that could be revoked *against* the
-- actual owner.

-- @@ UP @@

CREATE TABLE IF NOT EXISTS media_asset_grants (
    id            TEXT PRIMARY KEY,
    asset_id      TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
    grantee_id    TEXT NOT NULL,
    granted_by    TEXT NOT NULL,
    granted_at    TEXT NOT NULL,
    expires_at    TEXT,
    revoked_at    TEXT,
    CHECK (grantee_id <> granted_by)
);

-- The hot query is "may this person read this asset", so the index is on the
-- pair, not on either column alone.
CREATE UNIQUE INDEX IF NOT EXISTS uq_media_asset_grants
    ON media_asset_grants (asset_id, grantee_id);
CREATE INDEX IF NOT EXISTS ix_media_asset_grants_grantee
    ON media_asset_grants (grantee_id, asset_id);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_media_asset_grants_grantee;
DROP INDEX IF EXISTS uq_media_asset_grants;
DROP TABLE IF EXISTS media_asset_grants;
