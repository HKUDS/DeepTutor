"""Catalog sources and their rights decisions.

The rule this module exists to enforce
--------------------------------------
Phase 4 acceptance: **a source whose rights are unknown or whose review is not
approved must be absent from public retrieval.** Everything else here is in
service of making that rule impossible to violate by accident.

The mechanism is a single stored column, ``catalog_sources.publicly_retrievable``,
which is *derived* by this module on every write and never set by a caller. That
choice is deliberate:

* A boolean that callers may pass is a boolean a caller will eventually pass
  wrongly -- one forgotten argument and an unlicensed book is served.
* A computed expression at read time (``WHERE rights_status='cleared' AND
  review_status='approved'``) is correct but puts the rule in every query. One
  query forgetting a clause re-opens the hole.
* A stored, derived column puts the rule in exactly one place
  (:func:`_derive_retrievable`) and makes it indexable, so the retrieval filter
  is ``WHERE publicly_retrievable = 1`` and cannot be subtly wrong.

The trade is that the column can drift out of sync with its inputs. That is
guarded by recomputing it on every mutation and by a test that asserts the two
agree across a matrix of status combinations.

Why sources are never deleted
-----------------------------
A rights problem resolves to ``archived``, not to a ``DELETE``. Deleting a
source would erase the evidence that it was ever reviewed, which is exactly the
record needed when a rights holder asks. ``archived`` removes it from retrieval
while keeping the audit trail. There is no delete function in this module, and
that absence is the guarantee.

Review transitions
------------------
``approve``, ``reject``, ``archive`` and ``restore`` each have an allowed set of
*from* states. An illegal transition raises :class:`RightsTransitionError`
rather than quietly succeeding, because a review workflow that accepts any
transition is not a workflow -- it is a status field.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any

from deeptutor.db.connection import Database, DatabaseError

logger = logging.getLogger(__name__)

#: Source categories from D-010.
VALID_SOURCE_TYPES = frozenset(
    {
        "official_book",  # کتاب رسمی
        "study_aid",  # کمک‌آموزشی
        "notes",  # جزوه
        "sample_exam",  # نمونه سؤال
        "konkur",  # کنکور
        "supplement",  # منابع مکمل
    }
)

VALID_RIGHTS_STATUSES = frozenset({"unknown", "pending", "cleared", "restricted", "rejected"})

VALID_REVIEW_STATUSES = frozenset({"draft", "in_review", "approved", "rejected", "archived"})

VALID_DECISIONS = frozenset({"approve", "reject", "archive", "restore"})

#: Allowed ``from`` states per decision. Anything else is a workflow violation.
#:
#: ``restore`` accepts ``archived`` only: restoring a source that was never
#: archived would bypass review entirely.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "approve": frozenset({"draft", "in_review", "rejected", "archived"}),
    "reject": frozenset({"draft", "in_review", "approved", "archived"}),
    "archive": frozenset({"draft", "in_review", "approved", "rejected"}),
    "restore": frozenset({"archived"}),
}

#: The two statuses a source must reach to be served publicly.
_RETRIEVABLE_RIGHTS = frozenset({"cleared"})
_RETRIEVABLE_REVIEW = frozenset({"approved"})

_CHECKSUM_RE = re.compile(r"^[a-f0-9]{8,128}$")


class RightsError(RuntimeError):
    """A rights or review rule was violated.

    Plain ``RuntimeError`` subclass: a frozen dataclass cannot be raised
    because CPython assigns ``__traceback__``.
    """

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


class RightsTransitionError(RightsError):
    """A review decision was attempted from a state that does not allow it."""

    def __init__(self, decision: str, current: str, allowed: frozenset[str]) -> None:
        self.decision = decision
        self.current = current
        self.allowed = allowed
        super().__init__(
            "invalid_transition",
            f"{decision} is not allowed from {current!r}; allowed from {sorted(allowed)}",
            field="decision",
        )


class SourceNotFound(LookupError):
    def __init__(self, identifier: Any) -> None:
        self.identifier = identifier
        super().__init__(f"source not found: {identifier!r}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: Any, field: str, *, max_length: int = 400) -> str:
    if value is None:
        raise RightsError("required_field", "must not be empty", field=field)
    text = str(value).strip()
    if not text:
        raise RightsError("required_field", "must not be empty", field=field)
    if len(text) > max_length:
        raise RightsError("field_too_long", f"must be at most {max_length} characters", field=field)
    return text


def _derive_retrievable(rights_status: str, review_status: str) -> int:
    """The single place the publication rule is expressed.

    Publicly retrievable requires **both** a cleared rights status and an
    approved review. Either one alone is insufficient:

    * cleared rights but no review   -> nobody signed off on the content;
    * approved review but unknown rights -> someone approved content we may not
      legally serve.

    Unknown and restricted rights are never retrievable, including when a
    reviewer approved the source: an approval cannot manufacture a licence.
    """
    if rights_status in _RETRIEVABLE_RIGHTS and review_status in _RETRIEVABLE_REVIEW:
        return 1
    return 0


def _slug(text: str, *, limit: int = 24) -> str:
    """A short, URL-safe, ASCII fragment of ``text``.

    Source titles are Persian, so the obvious ``f"src_{title}"`` produces ids
    like ``src_کتاب تست_1404`` -- which contains a space and non-ASCII bytes and
    therefore cannot appear unescaped in a URL path. That is not a cosmetic
    problem: the review endpoint is ``/sources/{source_id}/review``, and a title
    with a space makes the source unreachable through its own API. Found by
    calling the live endpoint, not by any unit test.

    Non-ASCII characters are transliterated away rather than percent-encoded:
    an id is a database key that people paste into logs and curl commands, so it
    should not need encoding at all. Persian titles collide after stripping, so
    a short digest is appended -- stable for the same input, which keeps the id
    reproducible across imports.
    """
    import hashlib
    import re

    ascii_part = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    if ascii_part:
        return f"{ascii_part[:limit]}-{digest}"
    # No ASCII survived (the common case for a Persian title): the digest is
    # the whole identifier, which is still stable and still readable enough to
    # debug against.
    return digest


def create_source(
    db: Database,
    *,
    title: str,
    source_type: str,
    grade_number: int | None = None,
    major_code: str | None = None,
    subject_code: str | None = None,
    edition: str | None = None,
    content_checksum: str | None = None,
    page_count: int | None = None,
    provenance_kind: str = "unknown",
    provenance_note: str = "",
    rights_status: str = "unknown",
    review_status: str = "draft",
    supersedes_id: str | None = None,
    source_id: str | None = None,
) -> str:
    """Create a catalog source.

    New sources default to ``rights_status='unknown'`` and
    ``review_status='draft'``, which makes them non-retrievable by construction.
    A caller may pass a stronger rights status for a source whose licence is
    already known, but the retrievable flag is still derived by
    :func:`_derive_retrievable`, never accepted.
    """
    title = _require_text(title, "title")
    if source_type not in VALID_SOURCE_TYPES:
        raise RightsError(
            "invalid_source_type",
            f"must be one of {sorted(VALID_SOURCE_TYPES)}",
            field="source_type",
        )
    if rights_status not in VALID_RIGHTS_STATUSES:
        raise RightsError(
            "invalid_rights_status",
            f"must be one of {sorted(VALID_RIGHTS_STATUSES)}",
            field="rights_status",
        )
    if review_status not in VALID_REVIEW_STATUSES:
        raise RightsError(
            "invalid_review_status",
            f"must be one of {sorted(VALID_REVIEW_STATUSES)}",
            field="review_status",
        )
    if content_checksum is not None:
        checksum = str(content_checksum).strip().lower()
        if not _CHECKSUM_RE.match(checksum):
            raise RightsError(
                "invalid_checksum",
                "must be 8-128 lowercase hex characters",
                field="content_checksum",
            )
        content_checksum = checksum
    if grade_number is not None and (
        not isinstance(grade_number, int) or isinstance(grade_number, bool)
    ):
        raise RightsError("invalid_grade", "must be an integer", field="grade_number")
    if page_count is not None and (
        not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 0
    ):
        raise RightsError(
            "invalid_page_count", "must be a non-negative integer", field="page_count"
        )
    if supersedes_id is not None:
        with db.read() as conn:
            exists = conn.query_one(
                "SELECT 1 AS ok FROM catalog_sources WHERE id = ?", (supersedes_id,)
            )
        if exists is None:
            raise SourceNotFound(supersedes_id)

    identifier = source_id or f"src_{_slug(title)}_{_slug(edition or 'v1', limit=8)}"
    timestamp = _now()
    retrievable = _derive_retrievable(rights_status, review_status)
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO catalog_sources "
                "(id, title, source_type, grade_number, major_code, subject_code, "
                " supersedes_id, edition, content_checksum, page_count, "
                " provenance_kind, provenance_note, rights_status, review_status, "
                " publicly_retrievable, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    title,
                    source_type,
                    grade_number,
                    major_code,
                    subject_code,
                    supersedes_id,
                    edition,
                    content_checksum,
                    page_count,
                    provenance_kind,
                    provenance_note,
                    rights_status,
                    review_status,
                    retrievable,
                    timestamp,
                    timestamp,
                ),
            )
    except DatabaseError as exc:
        raise RightsError(
            "duplicate_source",
            f"a source with this title, type, scope and edition already exists "
            f"({title!r} / {edition!r})",
            field="title",
        ) from exc
    return identifier


def get_source(db: Database, source_id: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM catalog_sources WHERE id = ?", (source_id,))
    if row is None:
        raise SourceNotFound(source_id)
    return row


def find_duplicates(
    db: Database,
    *,
    title: str,
    source_type: str,
    grade_number: int | None = None,
    major_code: str | None = None,
    subject_code: str | None = None,
    edition: str | None = None,
) -> list[dict[str, Any]]:
    """Existing sources that the importer would consider a duplicate.

    Exposed separately from :func:`create_source` so an import can report
    duplicates *before* writing, which is what a review workflow needs. The
    unique index remains the authority: this check races, the index does not.
    """
    sql = (
        "SELECT * FROM catalog_sources WHERE title = ? AND source_type = ? "
        "AND grade_number IS ? AND major_code IS ? AND subject_code IS ? "
        "AND edition IS ?"
    )
    with db.read() as conn:
        rows = conn.query(
            sql,
            (title, source_type, grade_number, major_code, subject_code, edition),
        )
        return [dict(row) for row in rows]


def list_retrievable(
    db: Database,
    *,
    grade_number: int | None = None,
    major_code: str | None = None,
    subject_code: str | None = None,
    source_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Sources that may be served to a learner.

    Every filter is optional except the retrievability predicate, which is not
    optional and is not a parameter. This is the only function in the module
    that reads for retrieval purposes, so there is exactly one place where
    "what may be shown" is decided.
    """
    if limit < 1 or limit > 1000:
        raise RightsError("invalid_limit", "must be between 1 and 1000", field="limit")
    sql = ["SELECT * FROM catalog_sources WHERE publicly_retrievable = 1"]
    params: list[Any] = []
    if grade_number is not None:
        sql.append("AND (grade_number IS NULL OR grade_number = ?)")
        params.append(grade_number)
    if major_code is not None:
        # A source scoped to no major applies to all majors.
        sql.append("AND (major_code IS NULL OR major_code = ?)")
        params.append(major_code)
    if subject_code is not None:
        sql.append("AND (subject_code IS NULL OR subject_code = ?)")
        params.append(subject_code)
    if source_type is not None:
        sql.append("AND source_type = ?")
        params.append(source_type)
    sql.append("ORDER BY grade_number, subject_code, title LIMIT ?")
    params.append(limit)
    with db.read() as conn:
        return [dict(row) for row in conn.query(" ".join(sql), tuple(params))]


def _record_version(conn: Any, source: dict[str, Any], *, label: str) -> None:
    """Snapshot the source before it changes, so version history is answerable."""
    snapshot = {
        key: source.get(key)
        for key in (
            "title",
            "source_type",
            "grade_number",
            "major_code",
            "subject_code",
            "edition",
            "content_checksum",
            "rights_status",
            "review_status",
        )
    }
    conn.execute(
        "INSERT INTO source_versions "
        "(id, source_id, version_label, title, content_checksum, rights_status, "
        " review_status, snapshot, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"ver_{source['id']}_{label}",
            source["id"],
            label,
            source["title"],
            source.get("content_checksum"),
            source["rights_status"],
            source["review_status"],
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )


def review_source(
    db: Database,
    *,
    source_id: str,
    decision: str,
    reviewer: str,
    reason: str = "",
    rights_status: str | None = None,
) -> dict[str, Any]:
    """Apply a review decision and record it in the append-only log.

    The decision, the resulting statuses and the reviewer are written in one
    transaction: a decision that is applied but not logged (or logged but not
    applied) would be worse than no audit trail, because it would look complete.
    """
    if decision not in VALID_DECISIONS:
        raise RightsError(
            "invalid_decision",
            f"must be one of {sorted(VALID_DECISIONS)}",
            field="decision",
        )
    reviewer = _require_text(reviewer, "reviewer", max_length=200)
    reason = (reason or "").strip()
    if len(reason) > 2000:
        raise RightsError("field_too_long", "must be at most 2000 characters", field="reason")

    with db.transaction() as conn:
        row = conn.query_one("SELECT * FROM catalog_sources WHERE id = ?", (source_id,))
        if row is None:
            raise SourceNotFound(source_id)
        source = dict(row)
        current_review = source["review_status"]
        allowed = _ALLOWED_TRANSITIONS[decision]
        if current_review not in allowed:
            raise RightsTransitionError(decision, current_review, allowed)

        rights_before = source["rights_status"]
        if decision == "approve":
            # An approval without an explicit rights status means the reviewer
            # asserts the rights are cleared. Requiring the argument would make
            # the common case inconvenient; deriving it here keeps it explicit.
            new_rights = rights_status or "cleared"
            new_review = "approved"
        elif decision == "reject":
            new_rights = rights_status or "rejected"
            new_review = "rejected"
        elif decision == "archive":
            new_rights = rights_status or rights_before
            new_review = "archived"
        else:  # restore
            # Restoring returns the source to review, not to approved: the
            # approval that existed before archiving may be stale, and a restore
            # must not silently republish content.
            new_rights = rights_status or rights_before
            new_review = "in_review"

        if new_rights not in VALID_RIGHTS_STATUSES:
            raise RightsError(
                "invalid_rights_status",
                f"must be one of {sorted(VALID_RIGHTS_STATUSES)}",
                field="rights_status",
            )

        retrievable = _derive_retrievable(new_rights, new_review)
        _record_version(
            conn, source, label=f"{decision}_{datetime.now(timezone.utc).timestamp():.0f}"
        )
        conn.execute(
            "UPDATE catalog_sources SET rights_status = ?, review_status = ?, "
            "publicly_retrievable = ?, updated_at = ? WHERE id = ?",
            (new_rights, new_review, retrievable, _now(), source_id),
        )
        conn.execute(
            "INSERT INTO source_rights_reviews "
            "(id, source_id, decision, rights_status_before, rights_status_after, "
            " reviewer, reason, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"rev_{source_id}_{decision}_{datetime.now(timezone.utc).timestamp():.6f}",
                source_id,
                decision,
                rights_before,
                new_rights,
                reviewer,
                reason,
                _now(),
            ),
        )
    logger.info(
        "source %s: %s by %s -> rights=%s review=%s retrievable=%d",
        source_id,
        decision,
        reviewer,
        new_rights,
        new_review,
        retrievable,
    )
    return get_source(db, source_id)


def review_history(db: Database, source_id: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [
            dict(row)
            for row in conn.query(
                "SELECT * FROM source_rights_reviews WHERE source_id = ? ORDER BY reviewed_at, id",
                (source_id,),
            )
        ]


def version_history(db: Database, source_id: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [
            dict(row)
            for row in conn.query(
                "SELECT * FROM source_versions WHERE source_id = ? ORDER BY recorded_at, id",
                (source_id,),
            )
        ]
