-- V0007 — ingestion pipeline and grounded retrieval.
--
-- Three things Phase 5 needs that the schema does not have yet:
--
-- 1. **An ingestion run is a row, not a log line.**
--    `ingestion_runs` records what was attempted, by whom, against which
--    source, and what came out. Without it, "restart recovery" and "retry"
--    have no state to recover from and no way to prove a job ran twice.
--
-- 2. **Chunks need a stable identity tied to a page and a chapter.**
--    `ingestion_chunks` gives every retrievable unit a page number, a chapter
--    title, and a deterministic key derived from the source checksum. That key
--    is what makes re-ingestion idempotent: the same page of an unchanged book
--    produces the same key, so a retry overwrites instead of duplicating.
--
-- 3. **A citation must be checkable against a real retrieval.**
--    The `cited_chunk_*` columns on `grounded_answers` let the citation
--    validator prove that every reference in an answer points at a chunk that
--    was actually retrieved for that question -- not merely at a chunk that
--    exists somewhere in the corpus. A hallucinated citation is a citation that
--    was never in the retrieved set.
--
-- Portability: TEXT/INTEGER only, no JSONB, no partial indexes inside a CREATE
-- TABLE body (the V0005 lesson), and every uniqueness index is a separate
-- statement with COALESCE where a column is nullable (the V0006 lesson).

-- @@ UP @@

-- One row per ingestion attempt. `status` moves
-- queued -> running -> {succeeded | failed | cancelled}.
--
-- `attempt` is not a retry counter on a single row: a retry is a *new* run that
-- points at the same source, so `uq_ingestion_active` (below) can guarantee at
-- most one live run per source. Keeping attempts as separate rows means the
-- history of a flaky import is inspectable rather than overwritten.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id TEXT PRIMARY KEY,
    -- The catalog source this run processes. Reuses the Phase 4 table so
    -- rights and scope are the authority, never a copy of them.
    source_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    -- The curriculum scope is denormalised onto the run because ingestion must
    -- fail closed: if a source's scope is unknown at ingest time, the run is
    -- rejected rather than producing chunks with no grade to filter on.
    grade_number INTEGER,
    major_code TEXT,
    subject_code TEXT,
    curriculum_version_id TEXT,
    -- Which file, and what was in it when we looked. The checksum is compared
    -- against `catalog_sources.content_checksum` so a changed file cannot be
    -- silently ingested under an old approval.
    document_key TEXT NOT NULL DEFAULT '',
    content_checksum TEXT,
    page_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    parser_engine TEXT NOT NULL DEFAULT '',
    parser_signature TEXT NOT NULL DEFAULT '',
    -- 'ocr_required' is a distinct outcome from 'failed': a scanned PDF is not
    -- a bug, it is a book that needs a different pipeline.
    failure_kind TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_source
    ON ingestion_runs (source_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_status
    ON ingestion_runs (status);
-- At most one non-terminal run per source. A unique index over an expression
-- that yields 1 for live statuses and NULL for terminal ones: because NULL is
-- never equal to NULL, finished runs drop out of the constraint and a retry is
-- allowed, while two live runs collide.
--
-- The CASE **must be wrapped in its own parentheses**. SQLite accepts the bare
-- form; Postgres rejects it with `42601: syntax error at or near "CASE"`.
-- Found by applying this file to the real project, not by the SQLite suite --
-- which is why the migration is exercised against both engines.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_active
    ON ingestion_runs (
        source_id,
        (CASE WHEN status IN ('queued', 'running') THEN 1 ELSE NULL END)
    );

-- One row per retrievable chunk. The chunk key is deterministic:
--   sha256(source_checksum | document_key | page_index | ordinal)
-- so re-ingesting an unchanged page produces the same key and the write is an
-- upsert, not a duplicate.
--
-- `content_checksum` is the checksum of the chunk text itself. It lets a later
-- pass detect that a page's extracted text changed even when the PDF did not
-- (a parser upgrade, an OCR re-run) without re-embedding the whole book.
CREATE TABLE IF NOT EXISTS ingestion_chunks (
    chunk_key TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    document_key TEXT NOT NULL DEFAULT '',
    -- Physical provenance: which page of the PDF this text came from.
    page_index INTEGER NOT NULL,
    -- Printed page label as it appears in the book (may be Persian numerals or
    -- a roman numeral); kept separate from page_index because a citation should
    -- show what the student sees, while the index must be machine-comparable.
    page_label TEXT NOT NULL DEFAULT '',
    -- Logical provenance: which chapter this chunk belongs to. Empty is allowed
    -- and means "chapter unknown", which downgrades the citation to the book
    -- name only rather than inventing a chapter.
    chapter_index INTEGER,
    chapter_title TEXT NOT NULL DEFAULT '',
    section_title TEXT NOT NULL DEFAULT '',
    -- Retrieval scope, denormalised so a scope filter is one predicate on one
    -- table and cannot miss a join.
    grade_number INTEGER,
    major_code TEXT,
    subject_code TEXT,
    -- The rights verdict *at ingest time*. A later rights revocation must be
    -- able to invalidate chunks without re-reading the catalog, so the value is
    -- copied and the retrieval query checks the live source too.
    rights_status TEXT NOT NULL DEFAULT 'unknown',
    -- 'text' | 'table' | 'figure' | 'formula' | 'ocr'
    block_kind TEXT NOT NULL DEFAULT 'text',
    text TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ingestion_chunks_source
    ON ingestion_chunks (source_id, page_index, ordinal);
-- The scope filter the retriever always applies. Without this index the
-- "never leak another grade" predicate becomes a table scan on every query.
CREATE INDEX IF NOT EXISTS ix_ingestion_chunks_scope
    ON ingestion_chunks (grade_number, major_code, subject_code);
-- Chunk text is deduplicated per (source, page, text) rather than globally:
-- two different books may legitimately share a sentence.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_chunk_identity
    ON ingestion_chunks (
        source_id,
        document_key,
        page_index,
        ordinal,
        COALESCE(chapter_index, -1)
    );

-- Audit of answered questions that cite sources.
--
-- The `cited_chunk_*` columns hold the *retrieved* set for that question, not
-- the cited set: this is what lets a later audit answer "was this citation ever
-- in front of the model?" A citation whose chunk key is absent here is a
-- hallucination by construction, and `citation_validator` refuses it.
CREATE TABLE IF NOT EXISTS grounded_answers (
    id TEXT PRIMARY KEY,
    -- Chat session this answer belongs to. Nullable because a grounding check
    -- can be run against an ad-hoc query in the eval harness.
    session_id TEXT,
    user_id TEXT,
    query TEXT NOT NULL,
    answer TEXT NOT NULL,
    -- The chunks returned by retrieval, as a comma-separated list of chunk_key.
    -- Denormalised for the same reason as elsewhere: it is read as a whole and
    -- never queried by member, so a join table would add a join for no benefit.
    retrieved_chunk_keys TEXT NOT NULL DEFAULT '',
    cited_chunk_keys TEXT NOT NULL DEFAULT '',
    -- 'grounded' | 'abstained' | 'unverified'
    grounding_status TEXT NOT NULL DEFAULT 'unverified',
    citation_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_grounded_answers_session
    ON grounded_answers (session_id, created_at);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_grounded_answers_session;
DROP TABLE IF EXISTS grounded_answers;
DROP INDEX IF EXISTS uq_ingestion_chunk_identity;
DROP INDEX IF EXISTS ix_ingestion_chunks_scope;
DROP INDEX IF EXISTS ix_ingestion_chunks_source;
DROP TABLE IF EXISTS ingestion_chunks;
DROP INDEX IF EXISTS uq_ingestion_active;
DROP INDEX IF EXISTS ix_ingestion_runs_status;
DROP INDEX IF EXISTS ix_ingestion_runs_source;
DROP TABLE IF EXISTS ingestion_runs;
