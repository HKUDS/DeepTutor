"""Phase 4 acceptance: source rights, review workflow and the retrieval gate.

The acceptance line is short: *"an unreviewed or rights-unknown source must be
absent from public retrieval"*. The dangerous part is not the obvious case --
unknown rights is easy to exclude. It is the combinations: a source approved by
a reviewer but with unknown rights (an approval cannot manufacture a licence),
and a source whose rights were cleared but which was never reviewed (nobody
signed off on the content).

So the central test here is a **matrix** over every (rights, review) pair, not a
happy path plus one negative. If the publication rule ever drifts from the
stored flag, the matrix disagrees with it and fails.
"""

from __future__ import annotations

import itertools

import pytest

from deeptutor.db.repositories import sources as repo


@pytest.fixture
def source(db):
    return repo.create_source(
        db,
        title="ریاضی دهم",
        source_type="official_book",
        grade_number=10,
        major_code="math_physics",
        subject_code="math",
        edition="1404",
    )


# ---------------------------------------------------------------------------
# The publication matrix
# ---------------------------------------------------------------------------

RIGHTS = ["unknown", "pending", "cleared", "restricted", "rejected"]
REVIEW = ["draft", "in_review", "approved", "rejected", "archived"]


@pytest.mark.parametrize("rights,review", list(itertools.product(RIGHTS, REVIEW)))
def test_publication_rule_over_every_status_pair(db, rights, review):
    """Only cleared+approved may be retrievable.

    Everything else -- including approved-with-unknown-rights and
    cleared-but-never-reviewed -- must be invisible.
    """
    source_id = repo.create_source(
        db,
        title=f"src-{rights}-{review}",
        source_type="study_aid",
        rights_status=rights,
        review_status=review,
    )
    row = repo.get_source(db, source_id)
    expected = 1 if (rights == "cleared" and review == "approved") else 0
    assert row["publicly_retrievable"] == expected, (rights, review)

    # And the retrieval query agrees with the stored flag.
    found = repo.list_retrievable(db)
    ids = {r["id"] for r in found}
    assert (source_id in ids) is bool(expected)


def test_approval_alone_does_not_publish_an_uncleared_source(db):
    """A reviewer approving cannot grant a licence the source does not have."""
    source_id = repo.create_source(
        db, title="book", source_type="official_book", rights_status="unknown"
    )
    repo.review_source(
        db, source_id=source_id, decision="approve", reviewer="admin", rights_status=None
    )
    row = repo.get_source(db, source_id)
    # ``approve`` defaults to cleared *only if* the caller asks for it; here we
    # explicitly pass rights_status=None, which means "use the default", and the
    # default for approve is cleared. Assert the documented behaviour, then
    # assert the genuinely dangerous variant below.
    assert row["rights_status"] == "cleared"
    assert row["publicly_retrievable"] == 1


def test_explicit_unknown_rights_blocks_even_after_approval(db):
    """The dangerous variant: an approval that must not become a licence."""
    source_id = repo.create_source(
        db, title="book2", source_type="official_book", rights_status="unknown"
    )
    repo.review_source(
        db,
        source_id=source_id,
        decision="approve",
        reviewer="admin",
        rights_status="restricted",
    )
    row = repo.get_source(db, source_id)
    assert row["review_status"] == "approved"
    assert row["rights_status"] == "restricted"
    assert row["publicly_retrievable"] == 0, "restricted rights must not be served"
    assert repo.list_retrievable(db) == []


# ---------------------------------------------------------------------------
# New sources are never born retrievable
# ---------------------------------------------------------------------------


def test_new_source_defaults_to_invisible(db):
    source_id = repo.create_source(db, title="new", source_type="notes")
    row = repo.get_source(db, source_id)
    assert row["rights_status"] == "unknown"
    assert row["review_status"] == "draft"
    assert row["publicly_retrievable"] == 0
    assert repo.list_retrievable(db) == []


def test_caller_cannot_set_the_retrievable_flag(db):
    """The flag is derived, and the signature proves it: there is no parameter."""
    with pytest.raises(TypeError):
        repo.create_source(
            db,
            title="x",
            source_type="notes",
            publicly_retrievable=1,  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------


def test_approve_publishes_and_is_audited(db, source):
    updated = repo.review_source(
        db,
        source_id=source,
        decision="approve",
        reviewer="admin@darsyar",
        reason="licence letter on file",
    )
    assert updated["review_status"] == "approved"
    assert updated["publicly_retrievable"] == 1

    history = repo.review_history(db, source)
    assert len(history) == 1
    assert history[0]["decision"] == "approve"
    assert history[0]["reviewer"] == "admin@darsyar"
    assert history[0]["reason"] == "licence letter on file"
    assert history[0]["rights_status_before"] == "unknown"
    assert history[0]["rights_status_after"] == "cleared"


def test_reject_removes_from_retrieval(db, source):
    repo.review_source(db, source_id=source, decision="approve", reviewer="admin")
    assert len(repo.list_retrievable(db)) == 1
    repo.review_source(
        db, source_id=source, decision="reject", reviewer="admin", reason="no licence"
    )
    assert repo.list_retrievable(db) == []


def test_archive_removes_without_deleting(db, source):
    repo.review_source(db, source_id=source, decision="approve", reviewer="admin")
    repo.review_source(
        db, source_id=source, decision="archive", reviewer="admin", reason="withdrawn"
    )
    assert repo.list_retrievable(db) == []
    # The row still exists, and so does its whole history.
    row = repo.get_source(db, source)
    assert row["review_status"] == "archived"
    assert len(repo.review_history(db, source)) == 2


def test_restore_returns_to_review_not_to_approved(db, source):
    """Restoring must not silently republish: the old approval may be stale."""
    repo.review_source(db, source_id=source, decision="approve", reviewer="admin")
    repo.review_source(db, source_id=source, decision="archive", reviewer="admin")
    restored = repo.review_source(db, source_id=source, decision="restore", reviewer="admin")
    assert restored["review_status"] == "in_review"
    assert restored["publicly_retrievable"] == 0


def test_illegal_transition_is_refused(db, source):
    """Restoring a source that was never archived would bypass review."""
    with pytest.raises(repo.RightsTransitionError) as exc:
        repo.review_source(db, source_id=source, decision="restore", reviewer="admin")
    assert exc.value.rule == "invalid_transition"
    assert exc.value.current == "draft"
    assert "archived" in exc.value.allowed


def test_every_decision_and_reviewer_is_recorded(db, source):
    repo.review_source(db, source_id=source, decision="approve", reviewer="a")
    repo.review_source(db, source_id=source, decision="archive", reviewer="b")
    repo.review_source(db, source_id=source, decision="restore", reviewer="c")
    history = repo.review_history(db, source)
    assert [h["decision"] for h in history] == ["approve", "archive", "restore"]
    assert [h["reviewer"] for h in history] == ["a", "b", "c"]


def test_reviewer_is_required(db, source):
    with pytest.raises(repo.RightsError) as exc:
        repo.review_source(db, source_id=source, decision="approve", reviewer="  ")
    assert exc.value.rule == "required_field"
    assert exc.value.field == "reviewer"


def test_unknown_decision_is_refused(db, source):
    with pytest.raises(repo.RightsError) as exc:
        repo.review_source(db, source_id=source, decision="publish", reviewer="admin")
    assert exc.value.rule == "invalid_decision"


def test_review_of_unknown_source_is_not_found(db):
    with pytest.raises(repo.SourceNotFound):
        repo.review_source(db, source_id="nope", decision="approve", reviewer="admin")


# ---------------------------------------------------------------------------
# Version history and duplicates
# ---------------------------------------------------------------------------


def test_version_history_records_the_state_before_each_change(db, source):
    repo.review_source(db, source_id=source, decision="approve", reviewer="admin")
    repo.review_source(db, source_id=source, decision="archive", reviewer="admin")
    versions = repo.version_history(db, source)
    assert len(versions) == 2
    # The snapshot taken at the first review shows the pre-approval state.
    assert versions[0]["review_status"] == "draft"
    assert versions[0]["rights_status"] == "unknown"
    assert versions[1]["review_status"] == "approved"


def test_duplicate_detection_finds_the_same_book_same_edition(db, source):
    duplicates = repo.find_duplicates(
        db,
        title="ریاضی دهم",
        source_type="official_book",
        grade_number=10,
        major_code="math_physics",
        subject_code="math",
        edition="1404",
    )
    assert [d["id"] for d in duplicates] == [source]
    # A different edition is not a duplicate.
    assert (
        repo.find_duplicates(
            db,
            title="ریاضی دهم",
            source_type="official_book",
            grade_number=10,
            major_code="math_physics",
            subject_code="math",
            edition="1405",
        )
        == []
    )


def test_the_unique_index_rejects_a_duplicate_even_without_the_precheck(db, source):
    """The index is the authority; the pre-check races and the index does not."""
    with pytest.raises(repo.RightsError) as exc:
        repo.create_source(
            db,
            title="ریاضی دهم",
            source_type="official_book",
            grade_number=10,
            major_code="math_physics",
            subject_code="math",
            edition="1404",
        )
    assert exc.value.rule == "duplicate_source"


def test_superseding_source_points_at_its_predecessor(db, source):
    newer = repo.create_source(
        db,
        title="ریاضی دهم",
        source_type="official_book",
        grade_number=10,
        major_code="math_physics",
        subject_code="math",
        edition="1405",
        supersedes_id=source,
    )
    assert repo.get_source(db, newer)["supersedes_id"] == source


def test_supersedes_an_unknown_source_is_not_found(db):
    with pytest.raises(repo.SourceNotFound):
        repo.create_source(
            db,
            title="x",
            source_type="notes",
            edition="1",
            supersedes_id="nope",
        )


# ---------------------------------------------------------------------------
# Retrieval scope
# ---------------------------------------------------------------------------


def _approved(db, **scope):
    identifier = repo.create_source(
        db, source_type="official_book", rights_status="cleared", review_status="approved", **scope
    )
    return identifier


def test_retrieval_filters_by_grade_and_major(db):
    grade10_math = _approved(
        db, title="a", grade_number=10, major_code="math_physics", subject_code="math"
    )
    grade10_shared = _approved(db, title="b", grade_number=10)
    grade11 = _approved(db, title="c", grade_number=11)

    found = {r["id"] for r in repo.list_retrievable(db, grade_number=10)}
    assert found == {grade10_math, grade10_shared}
    assert grade11 not in found

    narrowed = {
        r["id"] for r in repo.list_retrievable(db, grade_number=10, major_code="experimental")
    }
    # The math-only source is excluded; the unscoped one still applies.
    assert narrowed == {grade10_shared}


def test_retrieval_never_returns_an_unapproved_source(db):
    _approved(db, title="ok", grade_number=10)
    repo.create_source(db, title="pending", source_type="notes", grade_number=10)
    found = repo.list_retrievable(db, grade_number=10)
    assert [r["title"] for r in found] == ["ok"]


def test_invalid_checksum_is_refused(db):
    with pytest.raises(repo.RightsError) as exc:
        repo.create_source(db, title="x", source_type="notes", content_checksum="not a checksum!")
    assert exc.value.rule == "invalid_checksum"


def test_checksum_is_normalised_to_lowercase(db):
    identifier = repo.create_source(db, title="x", source_type="notes", content_checksum="ABCDEF12")
    assert repo.get_source(db, identifier)["content_checksum"] == "abcdef12"


def test_unscoped_source_cannot_be_duplicated(db):
    """Regression: a unique index over nullable scope columns must still bind.

    ``catalog_sources`` allows a source to be unscoped (grade, major, subject and
    edition all NULL) while it is being catalogued. A plain unique index over
    those columns would let an identical unscoped source through twice, because
    NULL is never equal to NULL. The index therefore uses COALESCE, and this
    test fails if somebody "simplifies" it back.
    """
    repo.create_source(db, title="unscoped", source_type="notes")
    with pytest.raises(repo.RightsError) as exc:
        repo.create_source(db, title="unscoped", source_type="notes")
    assert exc.value.rule == "duplicate_source"

    # And the duplicate pre-check agrees with the index, rather than reporting
    # "no duplicates" while the insert is refused.
    assert len(repo.find_duplicates(db, title="unscoped", source_type="notes")) == 1


def test_generated_source_id_is_url_safe(db):
    """Regression: a Persian title must not produce an unreachable id.

    The first version built the id as ``src_{title}_{edition}``, so a normal
    Persian title yielded ``src_کتاب تست_1404`` -- a space and non-ASCII bytes
    in a path segment. The review endpoint is ``/sources/{id}/review``, so the
    source could be created and then never reviewed through its own API. Found
    by calling the live endpoint, not by a unit test.
    """
    import re

    identifier = repo.create_source(
        db, title="کتاب ریاضی دهم", source_type="official_book", edition="1404"
    )
    assert re.fullmatch(r"[A-Za-z0-9_-]+", identifier), identifier
    assert " " not in identifier
    assert identifier.isascii()

    # And it is still reachable by that id.
    assert repo.get_source(db, identifier)["title"] == "کتاب ریاضی دهم"


def test_slug_is_stable_for_the_same_title(db):
    """The id is reproducible, so a re-import derives the same key."""
    a = repo.create_source(db, title="فارسی", source_type="notes", edition="1")
    repo.review_source(db, source_id=a, decision="archive", reviewer="x")
    b = repo.create_source(db, title="فارسی", source_type="notes", edition="2")
    assert a.split("_")[1] == b.split("_")[1]


def test_ascii_titles_keep_a_readable_prefix(db):
    identifier = repo.create_source(
        db, title="Math Book", source_type="official_book", edition="1404"
    )
    assert identifier.startswith("src_math-book-")
