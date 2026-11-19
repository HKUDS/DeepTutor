-- Phase 9: a plan that says what it grants, and a price with a date.
--
-- Two gaps, both found by asking the code rather than the roadmap.
--
-- 1. A plan was a label, not a set of rights
-- ------------------------------------------
-- `plans` has existed since V0002 and no line of code ever read it. `plan_code`
-- on the wallet was a free string, so an account whose plan expired ninety days
-- ago resolved to exactly the same access as one that paid this morning. There
-- was nowhere to express "this plan includes video lessons and that one does
-- not", which is the only reason to have plans at all.
--
-- `capabilities` is a comma-separated list of surface names. It is not a join
-- table because the set is small, fixed, and read on every entitlement check;
-- parsing six words is cheaper than a second query on the hot path, and an
-- unknown name is dropped at parse time rather than granting something new.
--
-- 2. A price with no date cannot be audited
-- -----------------------------------------
-- Changing a price by UPDATE rewrites history: last month's invoice can no
-- longer be explained. `plan_prices` keeps every price with the moment it took
-- effect, so a cost recorded under the old price remains reproducible. The
-- current price is the newest row that is already effective.
--
-- Why the CHECK on tokens
-- -----------------------
-- `token_quota` of a plan is granted on purchase. A negative quota would
-- subtract tokens silently, and the wallet's own CHECK would report it as a
-- balance error rather than as a bad plan.

-- @@ UP @@

ALTER TABLE plans ADD COLUMN capabilities TEXT NOT NULL DEFAULT 'studio';

-- Backfill the plans that exist. A row created before this migration granted
-- nothing specific, so it gets the base surface plus the media kinds the studio
-- shipped in Phase 8 -- the behaviour those plans had in practice, now written
-- down instead of assumed.
UPDATE plans
   SET capabilities = 'studio,media.video,media.audio'
 WHERE capabilities = 'studio' AND token_quota > 0;

CREATE TABLE IF NOT EXISTS plan_prices (
    id TEXT PRIMARY KEY,
    plan_code TEXT NOT NULL,
    price_toman INTEGER NOT NULL,
    token_quota INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    -- The moment this price became the price. Not a timestamp of the edit: an
    -- operator scheduling next month's increase must not change today's cost.
    effective_from TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (price_toman >= 0),
    CHECK (token_quota >= 0),
    CHECK (duration_days > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_prices_effective
    ON plan_prices (plan_code, effective_from);
CREATE INDEX IF NOT EXISTS ix_plan_prices_lookup
    ON plan_prices (plan_code, effective_from DESC);

-- Every entitlement decision is recorded. Not for billing -- the wallet is the
-- ledger -- but because "why was this account allowed to render video" must be
-- answerable after the fact, and a decision made from a plan row that has since
-- been edited is otherwise unrecoverable.
CREATE TABLE IF NOT EXISTS entitlement_decisions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    plan_code TEXT NOT NULL DEFAULT '',
    capability TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    -- 'active' | 'expired' | 'missing_plan' | 'unknown_plan' | 'no_expiry' |
    -- 'no_wallet' | 'plan_retired'
    reason TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    CHECK (allowed IN (0, 1))
);
CREATE INDEX IF NOT EXISTS ix_entitlement_decisions_user
    ON entitlement_decisions (user_id, decided_at DESC);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_entitlement_decisions_user;
DROP TABLE IF EXISTS entitlement_decisions;
DROP INDEX IF EXISTS ix_plan_prices_lookup;
DROP INDEX IF EXISTS uq_plan_prices_effective;
DROP TABLE IF EXISTS plan_prices;
ALTER TABLE plans DROP COLUMN capabilities;
