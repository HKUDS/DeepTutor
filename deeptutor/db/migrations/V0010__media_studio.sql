-- Phase 8: learning studio, media jobs and the asset library.
--
-- The problem this schema exists to solve is accounting, not generation. A
-- video job costs money in a way chat does not: it runs for minutes, it can be
-- cancelled halfway, and it may fail after the provider has already done the
-- expensive part. Charging on submit means a cancelled job is charged for work
-- nobody received; charging at the end means a run of failing jobs costs the
-- operator real money with no record and no ceiling.
--
-- So the model is **reserve, then settle or refund**, which is the same shape
-- a payment authorisation takes:
--
--   1. Submit reserves an estimate. The wallet is not touched -- `user_wallets`
--      carries `CHECK (tokens_remaining = tokens_total - tokens_used)`, and a
--      hold that wrote to `tokens_used` would either break that invariant or
--      have to be netted out of `tokens_total`, which would corrupt the ledger
--      for every other reader. A reservation is therefore its own row.
--   2. Success settles against the *actual* cost and releases the rest.
--   3. Failure or cancellation refunds the reservation in full.
--
-- The invariant that makes this honest: at every moment, the tokens a user can
-- still commit equal `tokens_remaining - sum(open reservations)`. Every
-- admission decision reads it, so two concurrent submits cannot both pass a
-- check that only one of them can afford.

-- @@ UP @@

-- One generated artefact: an audio overview, a video lesson, a slide deck, a
-- mind map or an infographic.
--
-- `content_hash` is the cache identity (see `media_cache_key` below). Two runs
-- with the same script, scope and licence produce the same hash, so the second
-- reuses the first instead of paying a provider twice. It is not a uniqueness
-- constraint on its own: two *different* users are entitled to their own copy
-- of the same lesson, and deduplicating across owners would share a file behind
-- one owner's storage quota.
CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    -- 'audio_overview' | 'video_lesson' | 'slide_deck' | 'mind_map' | 'infographic'
    kind TEXT NOT NULL,
    -- The job that produced it. Nullable because an asset can outlive its job
    -- row (and because a future import path may create one without a job).
    job_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    -- Where the bytes are, relative to the storage backend root -- the same
    -- convention `user_files.storage_path` uses so a backend swap stays a
    -- config change.
    storage_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    -- Seconds, for audio and video only.
    duration_seconds REAL,
    -- sha256 of the inputs. Same key means the same output, which is what
    -- makes reuse safe rather than merely convenient.
    content_hash TEXT NOT NULL,
    -- Provenance, copied at creation: what source the script was drawn from and
    -- under what licence. A generated lesson that cannot name its source is a
    -- rights problem waiting to be discovered in production.
    source_id TEXT,
    chapter_title TEXT NOT NULL DEFAULT '',
    licence_code TEXT NOT NULL DEFAULT '',
    -- The script or outline the artefact was rendered from, kept so a later
    -- re-render does not need the model again. Text, not a pointer: the script
    -- IS the expensive part.
    script TEXT NOT NULL DEFAULT '',
    -- 'ready' | 'deleted'
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (size_bytes >= 0),
    CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    CHECK (status IN ('ready', 'deleted'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_media_assets_storage_path ON media_assets (storage_path);
-- The library view: one user's ready assets, newest first.
CREATE INDEX IF NOT EXISTS ix_media_assets_owner ON media_assets (user_id, kind, created_at);
-- The cache lookup: same owner, same kind, same inputs.
CREATE INDEX IF NOT EXISTS ix_media_assets_hash ON media_assets (user_id, content_hash, status);

-- A hold on a user's token balance while a job runs.
--
-- Deliberately a separate table from `user_wallets`: see the header comment.
-- `state` moves open -> settled | refunded and never back, so a double settle
-- is a detectable no-op rather than a double charge.
CREATE TABLE IF NOT EXISTS media_reservations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    job_id TEXT,
    -- The estimate taken at submit time.
    reserved_tokens INTEGER NOT NULL,
    -- The real cost, filled in on settle. Null while open.
    settled_tokens INTEGER,
    state TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    settled_at TEXT,
    CHECK (reserved_tokens >= 0),
    CHECK (settled_tokens IS NULL OR settled_tokens >= 0),
    CHECK (state IN ('open', 'settled', 'refunded'))
);
CREATE INDEX IF NOT EXISTS ix_media_reservations_user ON media_reservations (user_id, state);
CREATE INDEX IF NOT EXISTS ix_media_reservations_job ON media_reservations (job_id);

-- What one job actually cost, in tokens and in money.
--
-- Two rows per job at most: an `estimate` written at submit and an `actual`
-- written at settle. Keeping both is what lets `Gate 8`'s cost claim be checked
-- after the fact instead of asserted -- an estimate that was 40% low is a
-- finding, and it is invisible if the estimate is overwritten by the actual.
--
-- `non_token_cost_toman` exists because not every provider bills in tokens:
-- a video render is priced per second of output. Folding that into a token
-- count would invent an exchange rate at charge time and lose the real figure.
CREATE TABLE IF NOT EXISTS media_job_costs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    -- 'estimate' | 'actual'
    phase TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    non_token_units REAL NOT NULL DEFAULT 0,
    non_token_unit TEXT NOT NULL DEFAULT '',
    non_token_cost_toman INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK (tokens >= 0),
    CHECK (non_token_units >= 0),
    CHECK (non_token_cost_toman >= 0),
    CHECK (phase IN ('estimate', 'actual')),
    -- One row per phase per job: a re-run of the settle step updates nothing
    -- and reports the existing row, so a retried job cannot double-bill.
    UNIQUE (job_id, phase)
);
CREATE INDEX IF NOT EXISTS ix_media_job_costs_user ON media_job_costs (user_id, created_at);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_media_job_costs_user;
DROP TABLE IF EXISTS media_job_costs;
DROP INDEX IF EXISTS ix_media_reservations_job;
DROP INDEX IF EXISTS ix_media_reservations_user;
DROP TABLE IF EXISTS media_reservations;
DROP INDEX IF EXISTS ix_media_assets_hash;
DROP INDEX IF EXISTS ix_media_assets_owner;
DROP INDEX IF EXISTS uq_media_assets_storage_path;
DROP TABLE IF EXISTS media_assets;
