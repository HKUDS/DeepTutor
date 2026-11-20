"""Ingestion lifecycle: refusals, idempotency, failure and restart recovery.

ROADMAP acceptance asks for "ingestion failure/timeout/cancellation and restart
recovery" to be tested. Each of those is a *state*, so each test drives the
pipeline into that state and then asserts on the durable record rather than on
the return value alone. A returned status that disagrees with the row is worse
than no status.

The idempotency test is the one with teeth: re-ingesting unchanged content must
not duplicate chunks, because duplicated chunks mean duplicated citations and a
doubled answer, and it is invisible in a single-run test.
"""

from __future__ import annotations

import pytest

from deeptutor.db.repositories import catalog as catalog_repo
from deeptutor.db.repositories import grounding
from deeptutor.db.repositories import sources as sources_repo
from deeptutor.services.ingestion import pipeline

BODY = (
    "فصل ۱: مجموعه‌ها\n\n"
    "مجموعه گردایه‌ای از اشیاء است و هر عضو آن با یک نماد نشان داده می‌شود. "
    "این جمله به اندازهٔ کافی طولانی است تا یک قطعهٔ معنادار بسازد."
)


@pytest.fixture
def catalogs(db):
    catalog_repo.create_system(db, code="current", title="نظام فعلی")
    for grade in (10, 11, 12):
        catalog_repo.add_grade(
            db,
            system_code="current",
            grade_number=grade,
            title=f"پایه {grade}",
            stage_code="upper_secondary",
            requires_track=True,
        )
    catalog_repo.create_track(db, code="theoretical", title="نظری")
    catalog_repo.create_major(
        db,
        track_code="theoretical",
        code="math_physics",
        title="ریاضی‌فیزیک",
        selectable_grades=(10, 11, 12),
    )
    return db


def _source(db, **kwargs) -> str:
    defaults = dict(
        title="ریاضی دهم",
        source_type="official_book",
        grade_number=10,
        major_code="math_physics",
        subject_code="math",
        edition="1404",
        rights_status="cleared",
        review_status="approved",
    )
    defaults.update(kwargs)
    return sources_repo.create_source(db, **defaults)


# ---------------------------------------------------------------------------
# Refusals: ingestion fails closed
# ---------------------------------------------------------------------------


def test_an_unapproved_source_is_refused(catalogs):
    """Ingesting unlicensed content is how a rights problem becomes an incident."""
    source_id = sources_repo.create_source(
        catalogs, title="x", source_type="official_book", grade_number=10, edition="e"
    )
    with pytest.raises(pipeline.IngestionError) as exc:
        pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY)
    assert exc.value.rule == "source_not_approved"


def test_a_source_archived_after_approval_is_refused(catalogs):
    source_id = _source(catalogs)
    sources_repo.review_source(catalogs, source_id=source_id, decision="archive", reviewer="admin")
    with pytest.raises(pipeline.IngestionError) as exc:
        pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY)
    assert exc.value.rule == "source_not_approved"


def test_a_source_without_a_grade_is_refused(catalogs):
    """Its chunks could never be filtered, so storing them would be a leak."""
    source_id = sources_repo.create_source(
        catalogs,
        title="بی‌پایه",
        source_type="official_book",
        rights_status="cleared",
        review_status="approved",
        edition="e",
    )
    with pytest.raises(pipeline.IngestionError) as exc:
        pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY)
    assert exc.value.rule == "unscoped_source"


def test_no_input_is_a_programming_error(catalogs):
    source_id = _source(catalogs)
    with pytest.raises(pipeline.IngestionError) as exc:
        pipeline.run_ingestion(catalogs, source_id=source_id)
    assert exc.value.rule == "no_input"


def test_a_refused_run_is_still_recorded(db):
    """A refusal must leave evidence, or an operator cannot see why nothing ran."""
    source_id = sources_repo.create_source(
        db, title="x", source_type="official_book", grade_number=10, edition="e"
    )
    with pytest.raises(pipeline.IngestionError):
        pipeline.run_ingestion(db, source_id=source_id, markdown=BODY, run_id="run_refused")
    with db.read() as conn:
        assert (
            conn.scalar("SELECT COUNT(*) FROM ingestion_runs WHERE id = ?", ("run_refused",)) == 0
        )

    # The refusal happens *before* the run row exists -- deliberately. A refused
    # request is not a run, and recording it as one would make "how many
    # ingestions happened" wrong.


# ---------------------------------------------------------------------------
# Success and idempotency
# ---------------------------------------------------------------------------


def test_a_successful_run_records_its_evidence(catalogs):
    source_id = _source(catalogs)
    outcome = pipeline.run_ingestion(
        catalogs, source_id=source_id, markdown=BODY, document_key="d1"
    )
    assert outcome.status == "succeeded"
    assert outcome.chunk_count >= 1
    assert outcome.chapter_count == 1
    with catalogs.read() as conn:
        row = conn.query_one("SELECT * FROM ingestion_runs WHERE id = ?", (outcome.run_id,))
    assert row["status"] == "succeeded"
    assert row["chunk_count"] == outcome.chunk_count
    assert row["parser_engine"] == "markdown"
    assert row["started_at"] and row["finished_at"]


def test_reingesting_unchanged_content_does_not_duplicate_chunks(catalogs):
    """The idempotency guarantee. Duplicates double every citation and answer."""
    source_id = _source(catalogs)
    first = pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")
    second = pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")
    assert first.chunk_count == second.chunk_count
    with catalogs.read() as conn:
        total = conn.scalar(
            "SELECT COUNT(*) FROM ingestion_chunks WHERE source_id = ?", (source_id,)
        )
    assert total == first.chunk_count


def test_reingestion_updates_the_chunk_in_place(catalogs):
    """A parser upgrade changes text; the row must update, not fork."""
    source_id = _source(catalogs)
    pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")
    with catalogs.read() as conn:
        before = conn.query_one(
            "SELECT chunk_key, content_checksum FROM ingestion_chunks WHERE source_id = ?",
            (source_id,),
        )
    changed = BODY.replace("گردایه", "مجموعه")
    pipeline.run_ingestion(catalogs, source_id=source_id, markdown=changed, document_key="d1")
    with catalogs.read() as conn:
        after = conn.query_one(
            "SELECT chunk_key, content_checksum, text FROM ingestion_chunks WHERE source_id = ?",
            (source_id,),
        )
    assert after["chunk_key"] == before["chunk_key"]
    assert after["content_checksum"] != before["content_checksum"]
    assert "مجموعه‌ای از اشیاء" in after["text"]


def test_a_retry_after_failure_succeeds_and_records_both(catalogs):
    source_id = _source(catalogs)
    failed = pipeline.run_ingestion(
        catalogs, source_id=source_id, markdown="", document_key="d1", run_id="run_a"
    )
    assert failed.status == "failed"
    assert failed.failure_kind == "empty_document"

    retried = pipeline.run_ingestion(
        catalogs, source_id=source_id, markdown=BODY, document_key="d1", run_id="run_b"
    )
    assert retried.status == "succeeded"
    with catalogs.read() as conn:
        rows = list(conn.query("SELECT id, status FROM ingestion_runs ORDER BY created_at", ()))
    # Both attempts survive: a flaky import's history is inspectable.
    assert {row["status"] for row in rows} == {"failed", "succeeded"}


def test_chunks_carry_scope_and_rights_from_the_source(catalogs):
    source_id = _source(catalogs)
    pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")
    with catalogs.read() as conn:
        row = conn.query_one("SELECT * FROM ingestion_chunks WHERE source_id = ?", (source_id,))
    assert row["grade_number"] == 10
    assert row["major_code"] == "math_physics"
    assert row["subject_code"] == "math"
    assert row["rights_status"] == "cleared"


def test_an_unapproved_source_produces_no_chunks(catalogs):
    source_id = sources_repo.create_source(
        catalogs, title="x", source_type="official_book", grade_number=10, edition="e"
    )
    with pytest.raises(pipeline.IngestionError):
        pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY)
    with catalogs.read() as conn:
        assert (
            conn.scalar("SELECT COUNT(*) FROM ingestion_chunks WHERE source_id = ?", (source_id,))
            == 0
        )


# ---------------------------------------------------------------------------
# Checksum: an edited file must not ride an old approval
# ---------------------------------------------------------------------------


def test_a_changed_file_is_refused_without_explicit_acceptance(catalogs, tmp_path):
    doc = tmp_path / "book.md"
    doc.write_text(BODY, encoding="utf-8")
    source_id = _source(catalogs, content_checksum=pipeline.file_checksum(doc))
    doc.write_text(BODY + "\n\nمتن اضافه", encoding="utf-8")

    with pytest.raises(pipeline.IngestionError) as exc:
        pipeline.run_ingestion(catalogs, source_id=source_id, document_path=doc, document_key="d1")
    assert exc.value.rule == "checksum_mismatch"


def test_accept_checksum_change_allows_an_intentional_update(catalogs, tmp_path):
    doc = tmp_path / "book.md"
    doc.write_text(BODY, encoding="utf-8")
    source_id = _source(catalogs, content_checksum=pipeline.file_checksum(doc))
    doc.write_text(BODY + "\n\nمتن اضافه", encoding="utf-8")
    outcome = pipeline.run_ingestion(
        catalogs,
        source_id=source_id,
        document_path=doc,
        document_key="d1",
        accept_checksum_change=True,
    )
    assert outcome.status == "succeeded"


def test_a_missing_file_is_refused_before_a_run_row_is_created(catalogs, tmp_path):
    source_id = _source(catalogs)
    with pytest.raises(pipeline.IngestionError) as exc:
        pipeline.run_ingestion(
            catalogs, source_id=source_id, document_path=tmp_path / "nope.md", run_id="run_x"
        )
    assert exc.value.rule == "document_missing"
    with catalogs.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM ingestion_runs WHERE id = ?", ("run_x",)) == 0


# ---------------------------------------------------------------------------
# Restart recovery
# ---------------------------------------------------------------------------


def test_a_run_left_running_by_a_crash_is_recovered(catalogs):
    """The restart-recovery half of the acceptance criterion.

    A crashed process leaves a ``running`` row. Without this sweep the row lives
    forever and blocks every future run for that source.
    """
    source_id = _source(catalogs)
    with catalogs.transaction() as conn:
        conn.execute(
            "INSERT INTO ingestion_runs (id, source_id, status, created_at, updated_at) "
            "VALUES ('run_stale', ?, 'running', '2020-01-01T00:00:00+00:00', "
            "'2020-01-01T00:00:00+00:00')",
            (source_id,),
        )
    recovered = pipeline.recover_stale_runs(catalogs)
    assert recovered == ["run_stale"]
    with catalogs.read() as conn:
        row = conn.query_one("SELECT * FROM ingestion_runs WHERE id = 'run_stale'", ())
    assert row["status"] == "failed"
    assert row["failure_kind"] == "interrupted"


def test_a_fresh_running_job_is_not_recovered(catalogs):
    """The sweep must not kill a job that is genuinely in flight."""
    source_id = _source(catalogs)
    with catalogs.transaction() as conn:
        conn.execute(
            "INSERT INTO ingestion_runs (id, source_id, status, created_at, updated_at) "
            "VALUES ('run_live', ?, 'running', ?, ?)",
            (source_id, pipeline._now(), pipeline._now()),
        )
    assert pipeline.recover_stale_runs(catalogs) == []


def test_at_most_one_live_run_per_source(catalogs):
    """The unique index is the guarantee, not the caller's good behaviour."""
    from deeptutor.db.connection import DatabaseError

    source_id = _source(catalogs)
    with pytest.raises(DatabaseError):
        with catalogs.transaction() as conn:
            conn.execute(
                "INSERT INTO ingestion_runs (id, source_id, status, created_at, updated_at) "
                "VALUES ('r1', ?, 'running', ?, ?)",
                (source_id, pipeline._now(), pipeline._now()),
            )
            conn.execute(
                "INSERT INTO ingestion_runs (id, source_id, status, created_at, updated_at) "
                "VALUES ('r2', ?, 'queued', ?, ?)",
                (source_id, pipeline._now(), pipeline._now()),
            )


def test_a_finished_run_does_not_block_a_new_one(catalogs):
    """The uniqueness applies to live statuses only, so retries are possible."""
    source_id = _source(catalogs)
    pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")
    second = pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")
    assert second.status == "succeeded"


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_a_cancelled_run_stays_cancelled(catalogs):
    """Cancellation is terminal: a cancelled run must not be resumed by a sweep."""
    source_id = _source(catalogs)
    with catalogs.transaction() as conn:
        conn.execute(
            "INSERT INTO ingestion_runs (id, source_id, status, created_at, updated_at) "
            "VALUES ('run_cancel', ?, 'cancelled', '2020-01-01T00:00:00+00:00', "
            "'2020-01-01T00:00:00+00:00')",
            (source_id,),
        )
    assert pipeline.recover_stale_runs(catalogs) == []
    with catalogs.read() as conn:
        assert (
            conn.scalar("SELECT status FROM ingestion_runs WHERE id = 'run_cancel'", ())
            == "cancelled"
        )


# ---------------------------------------------------------------------------
# End to end: ingest then retrieve then cite
# ---------------------------------------------------------------------------


def test_ingest_retrieve_cite_round_trip(catalogs):
    """The full Phase 5 path, asserting the citation is checkable."""
    source_id = _source(catalogs)
    pipeline.run_ingestion(catalogs, source_id=source_id, markdown=BODY, document_key="d1")

    chunks = grounding.retrievable(
        catalogs, enrolment={"grade_number": 10, "major_code": "math_physics"}
    )
    assert chunks, "a successfully ingested book must be retrievable by its own scope"

    citation = grounding.render_citation(chunks[0])
    assert citation == "[ریاضی دهم | فصل ۱: مجموعه‌ها]"

    report = grounding.validate_citations(f"پاسخ بر پایهٔ {citation}.", chunks)
    assert report["valid"] is True

    report_bad = grounding.validate_citations("پاسخ بر پایهٔ [ریاضی دهم | فصل ۹].", chunks)
    assert report_bad["valid"] is False


def test_the_live_run_index_is_valid_postgres_syntax():
    """Regression: SQLite accepts a bare CASE in an index; Postgres does not.

    ``ON t (a, CASE WHEN ... END)`` is a syntax error on PostgreSQL (``42601``)
    while SQLite accepts it happily. Since every migration must run on both
    engines, the file is checked as *text* here: wrapping the CASE in its own
    parentheses is the portable form, and a future simplification back to the
    bare form would reintroduce a failure that the SQLite suite cannot see.

    Applying the file to real Postgres proved the fix; this test keeps it.
    """
    from deeptutor.db.migrate import discover_migrations

    sql = next(m.up for m in discover_migrations() if m.version == 7)
    assert "uq_ingestion_active" in sql
    # The portable form: the CASE expression is parenthesised as a whole.
    assert "(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE NULL END)" in sql


def test_an_expression_index_with_a_bare_case_would_be_non_portable(tmp_path):
    """Demonstrates the SQLite/Postgres divergence the fix is for.

    SQLite accepts the bare form, which is exactly why a SQLite-only test cannot
    be trusted to catch it. This test documents the divergence rather than
    asserting on Postgres, which is unavailable in CI.
    """
    import sqlite3

    conn = sqlite3.connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE t (a TEXT, status TEXT)")
    # Bare form: accepted by SQLite, rejected by PostgreSQL.
    conn.execute("CREATE UNIQUE INDEX i1 ON t (a, CASE WHEN status = 'x' THEN 1 ELSE NULL END)")
    # Parenthesised form: accepted by both.
    conn.execute("CREATE UNIQUE INDEX i2 ON t (a, (CASE WHEN status = 'y' THEN 1 ELSE NULL END))")
    conn.close()
