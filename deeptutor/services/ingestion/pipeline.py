"""The ingestion runner: parse, extract, write chunks, record the run.

Why every step writes its own state
-----------------------------------
ROADMAP Phase 5 asks for "ingestion failure/timeout/cancellation and restart
recovery" to be tested. That is only testable if each step leaves durable
evidence, so the design is deliberately chatty:

* the run row is created **before** the file is opened, so a crash mid-parse
  leaves a ``running`` row that a later sweep can find and fail;
* chunks are written in one transaction with the ``succeeded`` status, so a run
  can never be ``succeeded`` with half its chunks;
* a failed run records ``failure_kind``, which distinguishes a scanned PDF that
  needs OCR from a genuine error.

Why re-ingestion is an upsert, not a truncate-and-insert
--------------------------------------------------------
``chunk_key`` is derived from position (see ``grounding.chunk_key``), so
re-ingesting an unchanged page yields the same keys. Upserting keeps citations
issued against the previous run valid. A truncate would invalidate every
citation the moment somebody re-ran the import, which is the kind of silent
breakage that only shows up in an audit months later.

Refusals that fail closed
-------------------------
* a source that is not ``publicly_retrievable`` is not ingested at all --
  ingesting unlicensed content is how a rights problem becomes a rights
  incident;
* a source whose live checksum no longer matches ``content_checksum`` is refused
  unless the caller explicitly accepts the change, so an edited file cannot slip
  through under an old approval;
* a source with no grade scope is refused, because its chunks could never be
  filtered and would have to be stored unscoped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any
import uuid

from deeptutor.db.connection import Database, DatabaseError
from deeptutor.db.repositories import sources as sources_repo
from deeptutor.services.ingestion import grounding_keys
from deeptutor.services.ingestion.extract import (
    ExtractionResult,
    extract,
    extract_from_markdown,
)

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """An ingestion refusal or failure.

    Plain ``RuntimeError`` subclass: a frozen dataclass cannot carry a
    ``__traceback__`` and would turn the real error into ``FrozenInstanceError``.
    """

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class IngestionOutcome:
    run_id: str
    source_id: str
    status: str
    chunk_count: int
    chapter_count: int
    page_count: int
    failure_kind: str = ""
    error_message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_id": self.source_id,
            "status": self.status,
            "chunk_count": self.chunk_count,
            "chapter_count": self.chapter_count,
            "page_count": self.page_count,
            "failure_kind": self.failure_kind,
            "error_message": self.error_message,
        }


def _create_run(
    db: Database,
    *,
    source: dict[str, Any],
    document_key: str,
    content_checksum: str | None,
    run_id: str,
) -> None:
    timestamp = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ingestion_runs "
            "(id, source_id, status, grade_number, major_code, subject_code, "
            " curriculum_version_id, document_key, content_checksum, started_at, "
            " created_at, updated_at) "
            "VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                source["id"],
                source.get("grade_number"),
                source.get("major_code"),
                source.get("subject_code"),
                source.get("curriculum_version_id"),
                document_key,
                content_checksum,
                timestamp,
                timestamp,
                timestamp,
            ),
        )


def _finish_run(
    db: Database,
    *,
    run_id: str,
    status: str,
    chunk_count: int = 0,
    page_count: int = 0,
    parser_engine: str = "",
    parser_signature: str = "",
    failure_kind: str = "",
    error_message: str = "",
) -> None:
    timestamp = _now()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE ingestion_runs SET status = ?, chunk_count = ?, page_count = ?, "
            "parser_engine = ?, parser_signature = ?, failure_kind = ?, "
            "error_message = ?, finished_at = ?, updated_at = ? WHERE id = ?",
            (
                status,
                chunk_count,
                page_count,
                parser_engine,
                parser_signature,
                failure_kind,
                error_message[:2000],
                timestamp,
                timestamp,
                run_id,
            ),
        )


def _write_chunks(
    db: Database,
    *,
    source: dict[str, Any],
    run_id: str,
    document_key: str,
    result: ExtractionResult,
) -> int:
    """Upsert every chunk in one transaction.

    ``ON CONFLICT DO UPDATE`` rather than ``DO NOTHING``: a parser upgrade that
    changes the text of a page must update the stored chunk, or the index keeps
    serving the old extraction forever. The key is positional, so this is an
    update-in-place of a known unit, not an overwrite of a different one.
    """
    timestamp = _now()
    written = 0
    with db.transaction() as conn:
        for chunk in result.chunks:
            key = grounding_keys.chunk_key(
                source_id=source["id"],
                document_key=document_key,
                page_index=chunk.page_index,
                ordinal=chunk.ordinal,
            )
            conn.execute(
                "INSERT INTO ingestion_chunks "
                "(chunk_key, source_id, run_id, document_key, page_index, "
                " page_label, chapter_index, chapter_title, section_title, "
                " grade_number, major_code, subject_code, rights_status, "
                " block_kind, text, content_checksum, ordinal, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (chunk_key) DO UPDATE SET "
                " run_id = excluded.run_id, text = excluded.text, "
                " content_checksum = excluded.content_checksum, "
                " chapter_index = excluded.chapter_index, "
                " chapter_title = excluded.chapter_title, "
                " section_title = excluded.section_title, "
                " block_kind = excluded.block_kind",
                (
                    key,
                    source["id"],
                    run_id,
                    document_key,
                    chunk.page_index,
                    chunk.page_label,
                    chunk.chapter_index,
                    chunk.chapter_title,
                    chunk.section_title,
                    source.get("grade_number"),
                    source.get("major_code"),
                    source.get("subject_code"),
                    source.get("rights_status") or "unknown",
                    chunk.block_kind,
                    chunk.text,
                    grounding_keys.text_checksum(chunk.text),
                    chunk.ordinal,
                    timestamp,
                ),
            )
            written += 1
    return written


def run_ingestion(
    db: Database,
    *,
    source_id: str,
    document_path: Path | str | None = None,
    markdown: str | None = None,
    parsed: Any = None,
    document_key: str = "",
    accept_checksum_change: bool = False,
    run_id: str | None = None,
) -> IngestionOutcome:
    """Ingest one source from a file, from markdown, or from an already-parsed IR.

    Exactly one input is used, in this precedence order: ``parsed`` (already
    parsed, cheapest), ``markdown`` (pre-extracted text), ``document_path``
    (parse it here). Passing none is a programming error, not a user error.
    """
    source = sources_repo.get_source(db, source_id)
    # Microseconds, not seconds, plus a random suffix. A second-precision
    # timestamp is not a unique key: a retry issued within the same second
    # collides on the primary key and fails with "UNIQUE constraint failed",
    # which turns a legitimate retry into an error. Found by a test that ran two
    # ingestions back to back.
    identifier = run_id or (
        f"run_{source_id}_{datetime.now(timezone.utc).timestamp():.6f}_{uuid.uuid4().hex[:6]}"
    )

    # --- fail closed, before writing anything -----------------------------
    if not source.get("publicly_retrievable"):
        raise IngestionError(
            "source_not_approved",
            f"source {source_id!r} is {source.get('review_status')!r} with rights "
            f"{source.get('rights_status')!r}; approving it is a prerequisite",
            field="source_id",
        )
    if source.get("grade_number") is None:
        raise IngestionError(
            "unscoped_source",
            "a source with no grade cannot be ingested: its chunks could never "
            "be filtered by grade",
            field="grade_number",
        )

    key = document_key or str(source.get("edition") or "")
    checksum: str | None = None
    if document_path is not None:
        path = Path(document_path)
        if not path.exists():
            raise IngestionError("document_missing", f"no such file: {path}", field="document_path")
        checksum = file_checksum(path)
        declared = source.get("content_checksum")
        if declared and checksum != declared and not accept_checksum_change:
            raise IngestionError(
                "checksum_mismatch",
                f"the file no longer matches the approved checksum for "
                f"{source_id!r}; re-approve the source or pass "
                f"accept_checksum_change=True",
                field="content_checksum",
            )

    _create_run(
        db,
        source=source,
        document_key=key,
        content_checksum=checksum,
        run_id=identifier,
    )

    # --- parse / extract --------------------------------------------------
    try:
        if parsed is not None:
            result = extract(parsed)
            engine = getattr(parsed, "engine", "") or "prepared"
            signature = getattr(parsed, "parser_signature", "") or ""
        elif markdown is not None:
            result = extract_from_markdown(markdown)
            engine = "markdown"
            signature = ""
        elif document_path is not None:
            from deeptutor.services.parsing.service import get_parse_service

            service = get_parse_service()
            prepared = service.parse(str(document_path))
            result = extract(prepared)
            engine = getattr(prepared, "engine", "") or "unknown"
            signature = getattr(prepared, "parser_signature", "") or ""
        else:
            raise IngestionError(
                "no_input",
                "one of parsed, markdown or document_path is required",
            )
    except IngestionError:
        _finish_run(
            db,
            run_id=identifier,
            status="failed",
            failure_kind="invalid_input",
            error_message="no ingestion input supplied",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        # A scanned PDF is not an error, it is a different pipeline. Detecting
        # it here (rather than in the parser) keeps the parser ignorant of the
        # product's vocabulary.
        kind = _classify_failure(exc)
        logger.warning("ingestion failed for %s (%s): %s", source_id, kind, exc)
        _finish_run(
            db,
            run_id=identifier,
            status="failed",
            failure_kind=kind,
            error_message=str(exc),
        )
        return IngestionOutcome(
            run_id=identifier,
            source_id=source_id,
            status="failed",
            chunk_count=0,
            chapter_count=0,
            page_count=0,
            failure_kind=kind,
            error_message=str(exc),
        )

    if not result.chunks:
        _finish_run(
            db,
            run_id=identifier,
            status="failed",
            failure_kind="empty_document",
            error_message="the document produced no retrievable text",
        )
        return IngestionOutcome(
            run_id=identifier,
            source_id=source_id,
            status="failed",
            chunk_count=0,
            chapter_count=0,
            page_count=0,
            failure_kind="empty_document",
            error_message="the document produced no retrievable text",
        )

    # --- write ------------------------------------------------------------
    try:
        written = _write_chunks(
            db,
            source=source,
            run_id=identifier,
            document_key=key,
            result=result,
        )
    except DatabaseError as exc:
        _finish_run(
            db,
            run_id=identifier,
            status="failed",
            failure_kind="storage_error",
            error_message=str(exc),
        )
        raise

    page_count = max((chunk.page_index for chunk in result.chunks), default=0) + 1
    _finish_run(
        db,
        run_id=identifier,
        status="succeeded",
        chunk_count=written,
        page_count=page_count,
        parser_engine=engine,
        parser_signature=signature,
    )
    return IngestionOutcome(
        run_id=identifier,
        source_id=source_id,
        status="succeeded",
        chunk_count=written,
        chapter_count=result.chapter_count,
        page_count=page_count,
    )


def _classify_failure(exc: Exception) -> str:
    """Distinguish a scanned book from a broken file.

    The distinction matters because the remedies differ: an OCR failure needs a
    different engine, a parse failure needs a different file. Reporting both as
    "failed" makes the operator try the wrong fix.
    """
    text = str(exc).lower()
    if "password" in text or "encrypted" in text:
        return "encrypted_document"
    if "ocr" in text or "no text" in text or "empty" in text or "scanned" in text:
        return "ocr_required"
    return "parse_error"


def recover_stale_runs(db: Database, *, older_than_seconds: int = 900) -> list[str]:
    """Fail runs that were left ``running`` by a crashed process.

    A process that dies mid-parse leaves a ``running`` row forever, and
    ``uq_ingestion_active`` then blocks every future run for that source. This
    sweep is the restart-recovery half of the roadmap's requirement: on boot,
    anything still running after the timeout is marked failed so the source can
    be retried.

    The cutoff is computed in Python and compared as an ISO string because both
    engines store ``created_at`` as TEXT and ISO-8601 sorts lexicographically.
    """
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
    recovered: list[str] = []
    with db.transaction() as conn:
        rows = list(
            conn.query(
                "SELECT id FROM ingestion_runs WHERE status = 'running' AND created_at < ?",
                (cutoff,),
            )
        )
        for row in rows:
            conn.execute(
                "UPDATE ingestion_runs SET status = 'failed', "
                "failure_kind = 'interrupted', "
                "error_message = 'the process stopped before this run finished', "
                "finished_at = ?, updated_at = ? WHERE id = ?",
                (_now(), _now(), row["id"]),
            )
            recovered.append(str(row["id"]))
    return recovered
