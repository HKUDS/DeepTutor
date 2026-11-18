"""Post-migration schema verification.

Why this exists
---------------
``CREATE TABLE IF NOT EXISTS`` is the right primitive for a baseline that must
apply to an empty database, but it has a trap: if a table *already exists with a
different shape*, the migration silently accepts it and reports success. The
application then fails at runtime with ``no such column: password_hash`` — after
a green deploy.

:func:`verify_schema` closes that hole. It runs after every migration and
asserts that each column the repositories actually write is present. A mismatch
is a hard :class:`SchemaMismatch` naming the table, the missing column and the
remedy, so the failure surfaces at deploy time with an actionable message
instead of at 3am in a request.

This is deliberately *not* a full schema diff. A full diff would couple the
check to every column type and make an additive change (a new nullable column)
fail spuriously. The contract being enforced is narrower and more useful: "the
columns the code depends on exist".
"""

from __future__ import annotations

from deeptutor.db.connection import Connection, Database

#: ``table -> columns the repositories cannot function without``.
#:
#: Kept in sync with the repositories by ``tests/db/test_schema_check.py``,
#: which asserts every column named in a repository's INSERT appears here. That
#: test is what stops this list from rotting.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": (
        "id",
        "password_hash",
        "role",
        "disabled",
        "must_change_password",
        "avatar",
        "preset",
        "token_version",
        "created_at",
        "updated_at",
    ),
    "otp_codes": (
        "phone_number",
        "salt",
        "digest",
        "expires_at",
        "attempts",
        "max_attempts",
        "last_sent_at",
        "window_started_at",
        "sends_in_window",
    ),
    "user_sessions": (
        "id",
        "user_id",
        "token_nonce",
        "created_at",
        "last_seen_at",
        "expires_at",
        "revoked_at",
    ),
    "audit_events": (
        "id",
        "action",
        "outcome",
        "detail",
        "created_at",
    ),
    "plans": (
        "id",
        "code",
        "name",
        "price_toman",
        "token_quota",
        "duration_days",
        "is_active",
    ),
    "user_wallets": (
        "user_id",
        "tokens_total",
        "tokens_used",
        "tokens_remaining",
        "storage_used_bytes",
        "storage_quota_bytes",
    ),
    "payment_transactions": (
        "id",
        "user_id",
        "provider",
        "authority",
        "status",
        "tokens_granted",
    ),
    "token_usage_logs": (
        "id",
        "user_id",
        "action",
        "total_tokens",
        "created_at",
    ),
    "user_files": (
        "id",
        "user_id",
        "storage_path",
        "size_bytes",
        "status",
    ),
    "jobs": (
        "id",
        "kind",
        "dedupe_key",
        "payload",
        "status",
        "attempts",
        "max_attempts",
        "lease_owner",
        "lease_expires_at",
        "run_after",
    ),
    # --- Phase 4: academic catalog -------------------------------------
    "curriculum_systems": (
        "id",
        "code",
        "title",
        "status",
        "effective_from_year",
        "effective_to_year",
        "sort_order",
        "created_at",
    ),
    "curriculum_grades": (
        "id",
        "system_id",
        "grade_number",
        "title",
        "stage_code",
        "requires_track",
    ),
    "curriculum_tracks": ("id", "code", "title", "kind", "sort_order"),
    "curriculum_majors": (
        "id",
        "track_id",
        "code",
        "title",
        "selectable_grades",
        "sort_order",
    ),
    "curriculum_subjects": (
        "id",
        "curriculum_version_id",
        "grade_number",
        "major_code",
        "code",
        "title",
        "language",
        "requirement",
        "weekly_hours",
        "sort_order",
    ),
    "curriculum_versions": (
        "id",
        "label",
        "school_year",
        "status",
        "published_at",
        "created_at",
    ),
    # --- Phase 4: sources and rights -----------------------------------
    "catalog_sources": (
        "id",
        "title",
        "source_type",
        "grade_number",
        "major_code",
        "subject_code",
        "supersedes_id",
        "edition",
        "content_checksum",
        "page_count",
        "provenance_kind",
        "provenance_note",
        "rights_status",
        "review_status",
        "publicly_retrievable",
        "created_at",
        "updated_at",
    ),
    "source_rights_reviews": (
        "id",
        "source_id",
        "decision",
        "rights_status_before",
        "rights_status_after",
        "reviewer",
        "reason",
        "reviewed_at",
    ),
    "source_versions": (
        "id",
        "source_id",
        "version_label",
        "title",
        "content_checksum",
        "rights_status",
        "review_status",
        "snapshot",
        "recorded_at",
    ),
    # --- Phase 5: ingestion and grounding ------------------------------
    "ingestion_runs": (
        "id",
        "source_id",
        "status",
        "grade_number",
        "major_code",
        "subject_code",
        "document_key",
        "content_checksum",
        "page_count",
        "chunk_count",
        "parser_engine",
        "failure_kind",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    ),
    "ingestion_chunks": (
        "chunk_key",
        "source_id",
        "run_id",
        "document_key",
        "page_index",
        "page_label",
        "chapter_index",
        "chapter_title",
        "section_title",
        "grade_number",
        "major_code",
        "subject_code",
        "rights_status",
        "block_kind",
        "text",
        "content_checksum",
        "ordinal",
    ),
    "grounded_answers": (
        "id",
        "query",
        "answer",
        "retrieved_chunk_keys",
        "cited_chunk_keys",
        "grounding_status",
        "citation_count",
        "created_at",
    ),
}


#: Indexes whose absence changes *correctness*, not merely speed.
#:
#: This list exists because of a bug found against the live database on
#: 2026-11-17: a unique index declared inside ``CREATE TABLE IF NOT EXISTS`` is
#: silently skipped when the table already exists. The payment-authority index
#: was in exactly that position, so on the real project two payments with the
#: same gateway authority were both accepted — a double-credit waiting to happen
#: — while the SQLite test suite passed because there the table was created
#: fresh and the index came with it.
#:
#: Uniqueness and the wallet/exam checks are therefore verified by name, not
#: assumed from the migration text.
REQUIRED_INDEXES: dict[str, tuple[str, ...]] = {
    "users": ("uq_users_username",),
    # ``otp_codes`` enforces one live code per phone through its *primary key*
    # rather than a separately named index, so it needs no entry here.
    "user_sessions": ("uq_user_sessions_token_nonce",),
    "payment_transactions": ("uq_payment_provider_authority",),
    "user_files": ("uq_user_files_storage_path",),
    "jobs": ("uq_jobs_dedupe",),
    "plans": ("uq_plans_code",),
    # Phase 4. Both of these are duplicate detectors, and both are uniquely
    # awkward: their key columns are nullable, so a plain UNIQUE index would
    # stop enforcing anything the moment a row omits the column (SQL treats
    # NULL as distinct from NULL). They therefore use COALESCE expressions, and
    # they are asserted here by name so a future migration cannot quietly
    # simplify them back into a constraint that does not constrain.
    "catalog_sources": ("uq_catalog_sources_identity",),
    "curriculum_subjects": ("uq_curriculum_subjects_identity",),
    # Phase 5. ``uq_ingestion_chunk_identity`` is what makes re-ingestion an
    # update instead of a duplicate, and ``uq_ingestion_active`` is what stops
    # two workers ingesting the same book at once. Both use expressions, and
    # both must stay expression indexes: a plain UNIQUE over nullable columns
    # (chapter_index is nullable) constrains nothing.
    "ingestion_chunks": ("uq_ingestion_chunk_identity",),
    "ingestion_runs": ("uq_ingestion_active",),
}


class SchemaMismatch(RuntimeError):
    """A table exists but does not carry the columns the code requires.

    A plain ``RuntimeError`` subclass, not a frozen dataclass: CPython assigns
    ``__traceback__`` on raise, and a frozen dataclass forbids that, turning the
    real error into ``FrozenInstanceError``. That would hide the diagnostic
    exactly when it matters.
    """

    def __init__(
        self, table: str, missing: tuple[str, ...], present_extra: tuple[str, ...] = ()
    ) -> None:
        self.table = table
        self.missing = missing
        self.present_extra = present_extra
        super().__init__(str(self))

    def __str__(self) -> str:  # noqa: D105
        detail = f"table {self.table!r} is missing required column(s): " + ", ".join(self.missing)
        if self.present_extra:
            detail += (
                " — the table looks like a *different* schema (it has "
                + ", ".join(self.present_extra[:6])
                + "), so this is not a simple additive drift. "
            )
        return (
            detail + " Reconcile the table before deploying: either drop it (only if it "
            "is empty) or ALTER it to add the missing columns."
        )


class MissingIndex(RuntimeError):
    """A uniqueness/correctness index is absent from the live schema."""

    def __init__(self, table: str, indexes: tuple[str, ...]) -> None:
        self.table = table
        self.indexes = indexes
        super().__init__(str(self))

    def __str__(self) -> str:  # noqa: D105
        return (
            f"table {self.table!r} is missing required index(es): "
            + ", ".join(self.indexes)
            + ". A unique index declared inside CREATE TABLE IF NOT EXISTS is "
            "skipped when the table already exists, which silently permits "
            "duplicate rows. Create the index explicitly."
        )


def _columns_of(conn: Connection, table: str) -> set[str]:
    if conn.backend == "sqlite":
        rows = conn.query(f"PRAGMA table_info({table})").rows
        return {str(r["name"]) for r in rows}
    rows = conn.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).rows
    return {str(r["column_name"]) for r in rows}


def _indexes_of(conn: Connection, table: str) -> set[str]:
    if conn.backend == "sqlite":
        rows = conn.query(f"PRAGMA index_list({table})").rows
        return {str(r["name"]) for r in rows}
    rows = conn.query(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = ?",
        (table,),
    ).rows
    return {str(r["indexname"]) for r in rows}


def verify_schema(db: Database, *, required: dict[str, tuple[str, ...]] | None = None) -> None:
    """Raise :class:`SchemaMismatch` for the first table that fails the contract.

    Both columns *and* correctness-bearing indexes are checked. Indexes matter
    because a missing unique index does not produce an error — it produces
    duplicate data that is only discovered later.
    """
    contract = required or REQUIRED_COLUMNS
    with db.read() as conn:
        for table, columns in contract.items():
            present = _columns_of(conn, table)
            if not present:
                # A missing table is a migration failure, not a schema mismatch;
                # the migration runner already reported it.
                continue
            missing = tuple(c for c in columns if c not in present)
            if missing:
                extra = tuple(sorted(present - set(columns)))
                raise SchemaMismatch(table=table, missing=missing, present_extra=extra)
        for table, index_names in REQUIRED_INDEXES.items():
            if not _columns_of(conn, table):
                continue
            present_indexes = _indexes_of(conn, table)
            absent = tuple(i for i in index_names if i not in present_indexes)
            if absent:
                raise MissingIndex(table=table, indexes=absent)


def describe_schema(db: Database) -> dict[str, list[str]]:
    """Every table and its columns, for a deployment report."""
    out: dict[str, list[str]] = {}
    with db.read() as conn:
        if conn.backend == "sqlite":
            tables = [
                str(r["name"])
                for r in conn.query(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).rows
            ]
            for table in tables:
                out[table] = sorted(_columns_of(conn, table))
        else:
            rows = conn.query(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "ORDER BY table_name, ordinal_position"
            ).rows
            for row in rows:
                out.setdefault(str(row["table_name"]), []).append(str(row["column_name"]))
    return out
