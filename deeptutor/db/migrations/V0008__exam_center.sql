-- Phase 6: exam center and deterministic assessment.
--
-- The governing constraint is that a submitted exam's score must never change
-- afterwards. Not when the question bank is edited, not when the scoring policy
-- is tuned, not when a rubric is reworded. A student's record of what they got
-- on an exam is a record of a past event, so everything the scorer read is
-- copied into the attempt at submission time and the scorer reads only the copy.
--
-- That is why there are three snapshot columns (`question_snapshot`,
-- `policy_snapshot`, `blueprint_snapshot`) rather than joins back to the live
-- bank. It duplicates data on purpose. The alternative -- joining to the live
-- question to find out what the answer key was -- means a corrected typo in the
-- bank silently changes last month's scores, and nobody would ever notice.

-- One question in the bank, at one version.
--
-- `question_id` is stable across edits; `version` increments. A question that
-- is edited after being used in an exam must not change that exam, and an exam
-- must be able to name exactly which version it used.
-- @@ UP @@
CREATE TABLE IF NOT EXISTS exam_questions (
    id TEXT PRIMARY KEY,
    -- Stable identity shared by all versions of the same question.
    question_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    -- 'multiple_choice' | 'essay' | 'short_answer'
    question_type TEXT NOT NULL DEFAULT 'multiple_choice',
    -- Retrieval scope, copied from the source the question was drawn from.
    grade_number INTEGER,
    major_code TEXT,
    subject_code TEXT,
    chapter_title TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    -- 'easy' | 'medium' | 'hard', kept as text so a future scale does not need
    -- a migration; the blueprint validates the values it accepts.
    difficulty TEXT NOT NULL DEFAULT 'medium',
    body TEXT NOT NULL,
    -- Choices are newline-delimited rather than JSON: both engines store TEXT,
    -- and a delimiter that cannot appear in a choice is simpler to query.
    -- The repository validates that no choice contains the delimiter.
    choices TEXT NOT NULL DEFAULT '',
    -- The answer key. For multiple choice this is the zero-based index as text;
    -- for essay it is the reference answer the rubric grades against.
    answer_key TEXT NOT NULL DEFAULT '',
    -- A question with no valid key must not be graded definitively.
    key_status TEXT NOT NULL DEFAULT 'valid',
    rubric TEXT NOT NULL DEFAULT '',
    -- Total points this question is worth.
    points REAL NOT NULL DEFAULT 1.0,
    -- Who authored it and whether a human has reviewed it. Gate 6 requires
    -- exam validation against a reviewed set, so this is not decorative.
    authored_by TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (version >= 1),
    CHECK (points > 0)
);

-- One question identity can have many versions, but only one of each number.
CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_questions_version
    ON exam_questions (question_id, version);
CREATE INDEX IF NOT EXISTS ix_exam_questions_scope
    ON exam_questions (grade_number, major_code, subject_code);
CREATE INDEX IF NOT EXISTS ix_exam_questions_identity
    ON exam_questions (question_id);

-- The rules an exam is graded by. Held in its own table so a policy can be
-- versioned and referenced by snapshot, rather than living as magic numbers.
CREATE TABLE IF NOT EXISTS exam_scoring_policies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    -- Points subtracted for a wrong multiple-choice answer. The Konkur rule is
    -- one third of the question's points; expressing it as a ratio rather than
    -- a fixed number keeps it correct when questions have different weights.
    negative_ratio REAL NOT NULL DEFAULT 0.0,
    -- Whether an unanswered question is neutral (Konkur: yes) or treated as a
    -- wrong answer. Defaulting to neutral is the safe choice: penalising a
    -- blank answer is a policy decision, never an accident.
    blank_is_neutral INTEGER NOT NULL DEFAULT 1,
    -- Whether a question with an invalid key is voided (excluded from the
    -- denominator) or fails the whole exam. Voiding is the default because one
    -- broken question should not destroy an otherwise valid exam.
    broken_question_policy TEXT NOT NULL DEFAULT 'void',
    -- Essay point floor per question, so a rubric cannot award below zero.
    essay_min_ratio REAL NOT NULL DEFAULT 0.0,
    essay_max_ratio REAL NOT NULL DEFAULT 1.0,
    -- Whether partial credit is allowed on an essay.
    allow_partial_credit INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (negative_ratio >= 0.0 AND negative_ratio <= 1.0),
    CHECK (essay_min_ratio >= 0.0 AND essay_min_ratio <= essay_max_ratio),
    CHECK (essay_max_ratio <= 1.0)
);

-- An exam definition: the blueprint plus the questions it draws.
CREATE TABLE IF NOT EXISTS exams (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    grade_number INTEGER,
    major_code TEXT,
    subject_code TEXT,
    policy_id TEXT,
    -- 'draft' | 'published' | 'archived'
    status TEXT NOT NULL DEFAULT 'draft',
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    -- Blueprint as authored: chapter/topic mix, difficulty counts, ordering.
    -- Stored because Gate 6 validates an exam against its blueprint, and a
    -- blueprint edited after publication would invalidate that check.
    blueprint TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (duration_minutes >= 0)
);
CREATE INDEX IF NOT EXISTS ix_exams_scope
    ON exams (grade_number, major_code, subject_code);

-- Which question versions an exam contains, in order.
CREATE TABLE IF NOT EXISTS exam_items (
    id TEXT PRIMARY KEY,
    exam_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    -- The exact version, not "latest": an exam built from v3 must keep using
    -- v3 even after v4 is published.
    question_version INTEGER NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    -- Per-item points override, so one exam can weight a section differently
    -- without editing the bank.
    points REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (exam_id) REFERENCES exams (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_items_position
    ON exam_items (exam_id, position);
CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_items_question
    ON exam_items (exam_id, question_id);
CREATE INDEX IF NOT EXISTS ix_exam_items_exam ON exam_items (exam_id);

-- One student's sitting of an exam.
--
-- `attempt_no` makes a deliberate retake a distinct attempt, while a duplicate
-- submission (a refresh, a double POST) lands on the same row. The pair
-- (exam_id, user_id, attempt_no) is what the idempotency check keys on.
CREATE TABLE IF NOT EXISTS exam_attempts (
    id TEXT PRIMARY KEY,
    exam_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    -- 'in_progress' | 'submitted' | 'graded' | 'voided'
    status TEXT NOT NULL DEFAULT 'in_progress',
    -- Everything the scorer read, frozen at submission. See the header.
    question_snapshot TEXT NOT NULL DEFAULT '',
    policy_snapshot TEXT NOT NULL DEFAULT '',
    blueprint_snapshot TEXT NOT NULL DEFAULT '',
    -- The raw submission, also frozen.
    answers_snapshot TEXT NOT NULL DEFAULT '',
    -- Computed once, at grading. Never recomputed.
    score REAL,
    max_score REAL,
    correct_count INTEGER NOT NULL DEFAULT 0,
    wrong_count INTEGER NOT NULL DEFAULT 0,
    blank_count INTEGER NOT NULL DEFAULT 0,
    voided_count INTEGER NOT NULL DEFAULT 0,
    -- 'graded' | 'needs_review' | 'voided'
    grading_status TEXT NOT NULL DEFAULT '',
    -- Set when grading is not final, e.g. an essay awaiting a human.
    review_required INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT,
    graded_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- A submission fingerprint: the same answers submitted twice must not
    -- create a second graded attempt or re-grade. Stored so a retry is a no-op.
    submission_fingerprint TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (exam_id) REFERENCES exams (id) ON DELETE CASCADE,
    CHECK (attempt_no >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_attempt_identity
    ON exam_attempts (exam_id, user_id, attempt_no);
CREATE INDEX IF NOT EXISTS ix_exam_attempts_user
    ON exam_attempts (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_exam_attempts_exam
    ON exam_attempts (exam_id, status);

-- Per-question outcome, so a report can say which topics need review without
-- re-grading anything.
CREATE TABLE IF NOT EXISTS exam_attempt_items (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    question_version INTEGER NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    -- 'correct' | 'wrong' | 'blank' | 'voided' | 'needs_review' | 'partial'
    outcome TEXT NOT NULL DEFAULT 'blank',
    -- What the student answered, frozen.
    answer TEXT NOT NULL DEFAULT '',
    -- Points awarded (may be negative under negative marking) and the maximum.
    points_awarded REAL NOT NULL DEFAULT 0.0,
    points_possible REAL NOT NULL DEFAULT 0.0,
    -- For essays: the rubric breakdown and who awarded it.
    rubric_result TEXT NOT NULL DEFAULT '',
    graded_by TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES exam_attempts (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_attempt_items_question
    ON exam_attempt_items (attempt_id, question_id);
CREATE INDEX IF NOT EXISTS ix_exam_attempt_items_attempt
    ON exam_attempt_items (attempt_id, position);

-- Append-only log of every score change after the initial grading.
--
-- "An essay: rubric, floor/ceiling, appeal, and the change is recorded" is the
-- roadmap's wording. A change that is applied but not logged would look like
-- the original grade, so this table is written in the same transaction.
CREATE TABLE IF NOT EXISTS exam_grade_changes (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    item_id TEXT,
    question_id TEXT NOT NULL DEFAULT '',
    -- 'appeal_upheld' | 'human_review' | 'regrade' | 'correction'
    change_kind TEXT NOT NULL,
    score_before REAL NOT NULL,
    score_after REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES exam_attempts (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_exam_grade_changes_attempt
    ON exam_grade_changes (attempt_id, created_at);

-- @@ DOWN @@
DROP INDEX IF EXISTS ix_exam_grade_changes_attempt;
DROP TABLE IF EXISTS exam_grade_changes;
DROP INDEX IF EXISTS ix_exam_attempt_items_attempt;
DROP INDEX IF EXISTS uq_exam_attempt_items_question;
DROP TABLE IF EXISTS exam_attempt_items;
DROP INDEX IF EXISTS ix_exam_attempts_exam;
DROP INDEX IF EXISTS ix_exam_attempts_user;
DROP INDEX IF EXISTS uq_exam_attempt_identity;
DROP TABLE IF EXISTS exam_attempts;
DROP INDEX IF EXISTS ix_exam_items_exam;
DROP INDEX IF EXISTS uq_exam_items_question;
DROP INDEX IF EXISTS uq_exam_items_position;
DROP TABLE IF EXISTS exam_items;
DROP INDEX IF EXISTS ix_exams_scope;
DROP TABLE IF EXISTS exams;
DROP TABLE IF EXISTS exam_scoring_policies;
DROP INDEX IF EXISTS ix_exam_questions_identity;
DROP INDEX IF EXISTS ix_exam_questions_scope;
DROP INDEX IF EXISTS uq_exam_questions_version;
DROP TABLE IF EXISTS exam_questions;
