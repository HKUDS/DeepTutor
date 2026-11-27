-- V0006 — academic catalog and source rights.
--
-- The curriculum tree Phase 4 needs, built data-driven so that grades, tracks,
-- majors and subjects are rows rather than code branches (D-006, D-007).
--
-- Two design points worth stating up front:
--
-- 1. **Current vs archive is a column, not a separate database.**
--    D-007 puts pre-university (پیش‌دانشگاهی) and the retired systems in a
--    separate archive. "Separate" here means a `curriculum_system` row with
--    `status='archived'` and an `effective_*` window, not a parallel set of
--    tables. A parallel schema would double every query and make a cross-system
--    comparison impossible; a status column keeps one tree and makes the
--    exclusion a single predicate the repository always applies.
--
-- 2. **Rights are a first-class row, not a boolean on the source.**
--    `rights_status` on a source records the *current* verdict; the
--    `source_rights_reviews` table records *who decided what, when, and on what
--    basis*. The audit trail is the thing that survives a dispute, and Phase 4
--    acceptance requires the approve/reject decision to be auditable.
--
-- Portability: no JSONB, no partial indexes inside CREATE TABLE bodies, no
-- ENUM types. Everything is TEXT/INTEGER so the same file applies to SQLite and
-- Postgres; enumeration is enforced in the repository, which is the only writer.

-- @@ UP @@

-- The education system tree: elementary 1-6, lower secondary 7-9, upper
-- secondary 10-12, plus archived systems that must remain queryable but must
-- never appear in a current student's path.
CREATE TABLE IF NOT EXISTS curriculum_systems (
    id TEXT PRIMARY KEY,
    -- Stable machine code: 'current', 'pre_university', 'old_secondary'.
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    -- 'current' | 'archived'. The repository refuses to resolve an archived
    -- system for a new enrolment; it stays readable for historical records.
    status TEXT NOT NULL DEFAULT 'current',
    -- Inclusive year bounds. NULL on a current system means "still in force".
    effective_from_year INTEGER,
    effective_to_year INTEGER,
    -- Ordering hint so 'current' sorts before archives in listings.
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS curriculum_stages (
    id TEXT PRIMARY KEY,
    -- 'elementary' (1-6) | 'lower_secondary' (7-9) | 'upper_secondary' (10-12)
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- Grades belong to a system, because grade 1..12 exists in the current system
-- while the archived systems have their own numbering. The pre-existing `grades`
-- table is untouched: it is the *current* system's grade list and is referenced
-- by `books.grade_id`, which is a foreign key we must not break.
CREATE TABLE IF NOT EXISTS curriculum_grades (
    id TEXT PRIMARY KEY,
    system_id TEXT NOT NULL,
    grade_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    -- Denormalised stage code so a lookup does not need a join for the common
    -- "which stage is this grade" question.
    stage_code TEXT NOT NULL,
    -- Whether a track/major choice is mandatory at this grade (D-006: from 10 up).
    requires_track INTEGER NOT NULL DEFAULT 0,
    UNIQUE (system_id, grade_number),
    FOREIGN KEY (system_id) REFERENCES curriculum_systems (id) ON DELETE RESTRICT
);

-- A track is the broad branch (نظری / هنرستان). A major is the specific field
-- inside a track (ریاضی‌فیزیک، علوم تجربی، انسانی). They are separate rows
-- because a vocational track has majors that do not follow the theoretical
-- branches at all, and collapsing them would make the vocational case a
-- special case in code.
CREATE TABLE IF NOT EXISTS curriculum_tracks (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    -- 'theoretical' | 'vocational'
    kind TEXT NOT NULL DEFAULT 'theoretical',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS curriculum_majors (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    -- Grade numbers at which this major is selectable, as a comma-separated
    -- list of integers ('10,11,12'). Denormalised on purpose: it is read as a
    -- whole and never queried by member, so a join table would add a join for
    -- no benefit. Validated by the repository.
    selectable_grades TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (track_id) REFERENCES curriculum_tracks (id) ON DELETE RESTRICT
);

-- One row per concrete subject-in-a-grade. `code` is deliberately unique across
-- the whole catalog: two subjects with the same code in the same curriculum
-- version would make retrieval scope ambiguous, which is exactly the
-- grade/track leakage Phase 5 must prevent.
--
-- The unique key is *not* declared inline as UNIQUE (code, grade, major_code).
-- That constraint does nothing when major_code is NULL, because SQL treats
-- NULL as distinct from NULL, so the same shared subject could be inserted
-- twice at the same grade. Verified on both engines: with an inline UNIQUE the
-- duplicate is accepted. COALESCE folds NULL to '' so the key is total.
CREATE TABLE IF NOT EXISTS curriculum_subjects (
    id TEXT PRIMARY KEY,
    curriculum_version_id TEXT,
    grade_number INTEGER NOT NULL,
    -- NULL means "available to every major at this grade" (typically grades 1-9).
    major_code TEXT,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    -- Language of instruction; 'fa' for the Iranian curriculum.
    language TEXT NOT NULL DEFAULT 'fa',
    -- Whether the subject is mandatory or elective at this grade/major.
    requirement TEXT NOT NULL DEFAULT 'mandatory',
    weekly_hours INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0
);
-- Separate statement, not inline: an index inside CREATE TABLE ... IF NOT
-- EXISTS is skipped wholesale when the table pre-exists (the V0005 lesson).
CREATE UNIQUE INDEX IF NOT EXISTS uq_curriculum_subjects_identity
    ON curriculum_subjects (code, grade_number, COALESCE(major_code, ''));
CREATE INDEX IF NOT EXISTS ix_curriculum_subjects_grade ON curriculum_subjects (grade_number);
CREATE INDEX IF NOT EXISTS ix_curriculum_subjects_major ON curriculum_subjects (major_code);

-- A curriculum version lets the same subject code be reissued for a new school
-- year without rewriting history. Retrieval always resolves through a version,
-- so an answer given last year can be reproduced.
CREATE TABLE IF NOT EXISTS curriculum_versions (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    -- Iranian school year, e.g. '1404-1405'.
    school_year TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    published_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (school_year, label)
);

-- ---------------------------------------------------------------------------
-- Sources and their rights.
-- ---------------------------------------------------------------------------

-- One row per catalogue decision. Sources are *never* deleted by the interface:
-- a rights problem resolves to status='archived'. Phase 4 acceptance says an
-- unreviewed or rights-unknown source must be absent from public retrieval, so
-- the column the retrieval filter reads is the one the review writes.
CREATE TABLE IF NOT EXISTS catalog_sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    -- 'official_book' | 'study_aid' | 'notes' | 'sample_exam' | 'konkur' | 'supplement'
    source_type TEXT NOT NULL,
    -- Denormalised scope. NULL grade means "not yet scoped", which is a state
    -- that must block publication rather than silently widen the scope.
    grade_number INTEGER,
    major_code TEXT,
    subject_code TEXT,
    -- Versioning: a new edition is a new row pointing at its predecessor.
    supersedes_id TEXT,
    edition TEXT,
    -- Integrity: the checksum of the ingested artefact. A source whose content
    -- changed without a new version is detectable because the checksum no
    -- longer matches.
    content_checksum TEXT,
    page_count INTEGER,
    -- Provenance: where it came from, and under what claim.
    provenance_kind TEXT NOT NULL DEFAULT 'unknown',
    provenance_note TEXT NOT NULL DEFAULT '',
    -- 'unknown' | 'pending' | 'cleared' | 'restricted' | 'rejected'
    rights_status TEXT NOT NULL DEFAULT 'unknown',
    -- 'draft' | 'in_review' | 'approved' | 'rejected' | 'archived'
    review_status TEXT NOT NULL DEFAULT 'draft',
    -- The single column retrieval filters on. Kept as a stored value rather
    -- than a computed expression so an index can serve it and so the rule
    -- lives in one place (the repository that writes it).
    publicly_retrievable INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (supersedes_id) REFERENCES catalog_sources (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_catalog_sources_scope
    ON catalog_sources (grade_number, major_code, subject_code);
CREATE INDEX IF NOT EXISTS ix_catalog_sources_retrievable
    ON catalog_sources (publicly_retrievable);
-- Duplicate detection: the same title in the same scope at the same edition is
-- a duplicate, and the importer needs the database to say so rather than
-- relying on a pre-check that races.
--
-- Every scope column is nullable, so each one needs COALESCE. A unique index
-- over nullable columns is not a constraint at all for the rows that omit them:
-- SQL treats NULL as distinct from NULL, so two indistinguishable unscoped
-- sources would both be accepted and the importer's duplicate check -- which
-- uses ``IS NULL`` and does match them -- would disagree with the index. That
-- disagreement is worse than no index, because it makes the duplicate report
-- look authoritative while the data quietly doubles.
CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_sources_identity
    ON catalog_sources (
        title,
        source_type,
        COALESCE(grade_number, 0),
        COALESCE(major_code, ''),
        COALESCE(subject_code, ''),
        COALESCE(edition, '')
    );

-- Append-only decision log. One row per review transition, with the reviewer
-- and the reason. Never deleted; an archived source keeps its full history.
CREATE TABLE IF NOT EXISTS source_rights_reviews (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    -- 'approve' | 'reject' | 'archive' | 'restore'
    decision TEXT NOT NULL,
    rights_status_before TEXT NOT NULL,
    rights_status_after TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES catalog_sources (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_source_rights_reviews_source
    ON source_rights_reviews (source_id, reviewed_at);

-- Version history for a source's metadata. The current values live on
-- `catalog_sources`; this table records what they were before each accepted
-- change, so "version history" is answerable without diffing timestamps.
CREATE TABLE IF NOT EXISTS source_versions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    version_label TEXT NOT NULL,
    title TEXT NOT NULL,
    content_checksum TEXT,
    rights_status TEXT NOT NULL,
    review_status TEXT NOT NULL,
    snapshot TEXT NOT NULL DEFAULT '{}',
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES catalog_sources (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_source_versions_source
    ON source_versions (source_id, recorded_at);

-- @@ DOWN @@

-- Reverse order, children before parents. Nothing here is referenced by a
-- pre-Phase-4 table, so dropping is safe and complete: no Phase 3 table gains a
-- foreign key into the catalog, which is what keeps this migration reversible
-- without a coordinated multi-table drop.
DROP INDEX IF EXISTS ix_source_versions_source;
DROP TABLE IF EXISTS source_versions;
DROP INDEX IF EXISTS ix_source_rights_reviews_source;
DROP TABLE IF EXISTS source_rights_reviews;
DROP INDEX IF EXISTS uq_catalog_sources_identity;
DROP INDEX IF EXISTS ix_catalog_sources_retrievable;
DROP INDEX IF EXISTS ix_catalog_sources_scope;
DROP TABLE IF EXISTS catalog_sources;
DROP TABLE IF EXISTS curriculum_versions;
DROP INDEX IF EXISTS ix_curriculum_subjects_major;
DROP INDEX IF EXISTS ix_curriculum_subjects_grade;
DROP TABLE IF EXISTS curriculum_subjects;
DROP TABLE IF EXISTS curriculum_majors;
DROP TABLE IF EXISTS curriculum_tracks;
DROP TABLE IF EXISTS curriculum_grades;
DROP TABLE IF EXISTS curriculum_stages;
DROP TABLE IF EXISTS curriculum_systems;
