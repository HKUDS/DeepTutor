"""Phase 5 acceptance: no grade/track leakage, adversarially.

The roadmap asks for "no grade/track leakage in an adversarial test". A
happy-path test cannot show this, because the failure mode is a chunk that
*should* be excluded being returned. So every test here builds a corpus that
contains a tempting wrong answer and asserts it is absent.

The four leak families, one test each plus a combined one:

1. grade: a grade-12 book served to a grade-10 student;
2. track: a ریاضی‌فیزیک book served to a تجربی student;
3. no-major: a major-scoped book served to a grade-7 student (who has no major);
4. rights: a chunk served after its source was archived.

The fifth test is the one that would have caught the original bug if the rules
had been expressed as ``COALESCE(grade, requested)``: a chunk with a NULL grade
must not be admitted to every grade.
"""

from __future__ import annotations

import pytest

from deeptutor.db.repositories import catalog as catalog_repo
from deeptutor.db.repositories import grounding
from deeptutor.db.repositories import sources as sources_repo
from deeptutor.services.ingestion import pipeline


@pytest.fixture
def world(db):
    """A catalog with two grades, two majors, and books in each corner."""
    catalog_repo.create_system(db, code="current", title="نظام فعلی")
    for grade in range(1, 13):
        stage = (
            "elementary" if grade <= 6 else "lower_secondary" if grade <= 9 else "upper_secondary"
        )
        catalog_repo.add_grade(
            db,
            system_code="current",
            grade_number=grade,
            title=f"پایه {grade}",
            stage_code=stage,
            requires_track=grade >= 10,
        )
    catalog_repo.create_track(db, code="theoretical", title="نظری")
    for code, title in (
        ("math_physics", "ریاضی‌فیزیک"),
        ("experimental", "علوم تجربی"),
        ("humanities", "علوم انسانی"),
    ):
        catalog_repo.create_major(
            db, track_code="theoretical", code=code, title=title, selectable_grades=(10, 11, 12)
        )
    return db


def _approved_source(db, **kwargs) -> str:
    return sources_repo.create_source(
        db,
        source_type="official_book",
        rights_status="cleared",
        review_status="approved",
        **kwargs,
    )


def _ingest(db, source_id: str, markdown: str) -> pipeline.IngestionOutcome:
    return pipeline.run_ingestion(db, source_id=source_id, markdown=markdown, document_key="d1")


@pytest.fixture
def corpus(world):
    """One book per corner of the scope space, all ingested and approved."""
    texts = (
        "فصل ۱: مقدمه\n\nاین متن آزمایشی برای سنجش دامنه بازیابی است و به اندازه کافی طولانی است."
    )

    grade10_math = _approved_source(
        world,
        title="ریاضی دهم ریاضی‌فیزیک",
        grade_number=10,
        major_code="math_physics",
        subject_code="math",
        edition="g10m",
    )
    _ingest(world, grade10_math, texts)

    grade10_exp = _approved_source(
        world,
        title="ریاضی دهم تجربی",
        grade_number=10,
        major_code="experimental",
        subject_code="math",
        edition="g10e",
    )
    _ingest(world, grade10_exp, texts)

    grade12_math = _approved_source(
        world,
        title="ریاضی دوازدهم",
        grade_number=12,
        major_code="math_physics",
        subject_code="math",
        edition="g12m",
    )
    _ingest(world, grade12_math, texts)

    grade7_shared = _approved_source(
        world,
        title="ریاضی هفتم",
        grade_number=7,
        subject_code="math",
        edition="g7",
    )
    _ingest(world, grade7_shared, texts)

    return {
        "grade10_math": grade10_math,
        "grade10_exp": grade10_exp,
        "grade12_math": grade12_math,
        "grade7_shared": grade7_shared,
    }


def _titles(chunks) -> set[str]:
    return {chunk["source_title"] for chunk in chunks}


# ---------------------------------------------------------------------------
# 1. grade
# ---------------------------------------------------------------------------


def test_a_grade_10_student_cannot_see_a_grade_12_book(corpus, world):
    chunks = grounding.retrievable(
        world, enrolment={"grade_number": 10, "major_code": "math_physics"}
    )
    titles = _titles(chunks)
    assert "ریاضی دهم ریاضی‌فیزیک" in titles
    assert "ریاضی دوازدهم" not in titles


def test_a_grade_12_student_cannot_see_a_grade_10_book(corpus, world):
    """The check must not be one-directional. 'at least my grade' leaks upward."""
    chunks = grounding.retrievable(
        world, enrolment={"grade_number": 12, "major_code": "math_physics"}
    )
    titles = _titles(chunks)
    assert "ریاضی دوازدهم" in titles
    assert "ریاضی دهم ریاضی‌فیزیک" not in titles


# ---------------------------------------------------------------------------
# 2. track
# ---------------------------------------------------------------------------


def test_a_math_physics_student_does_not_see_the_experimental_book(corpus, world):
    """Both are grade 10, both are 'ریاضی'. Only the track differs."""
    math_chunks = grounding.retrievable(
        world, enrolment={"grade_number": 10, "major_code": "math_physics"}
    )
    exp_chunks = grounding.retrievable(
        world, enrolment={"grade_number": 10, "major_code": "experimental"}
    )
    assert "ریاضی دهم تجربی" not in _titles(math_chunks)
    assert "ریاضی دهم ریاضی‌فیزیک" not in _titles(exp_chunks)
    # And each sees its own, so the exclusion is not "everything filtered out".
    assert "ریاضی دهم ریاضی‌فیزیک" in _titles(math_chunks)
    assert "ریاضی دهم تجربی" in _titles(exp_chunks)


# ---------------------------------------------------------------------------
# 3. no major
# ---------------------------------------------------------------------------


def test_a_grade_7_student_sees_only_shared_books(corpus, world):
    """Grades 1-9 have no track, so any major-scoped chunk must be invisible."""
    chunks = grounding.retrievable(world, enrolment={"grade_number": 7, "major_code": None})
    titles = _titles(chunks)
    assert titles == {"ریاضی هفتم"}, titles


def test_a_grade_7_student_never_sees_a_major_scoped_book(corpus, world):
    """Regression for the 'shared means matches everything' misreading."""
    chunks = grounding.retrievable(world, enrolment={"grade_number": 7, "major_code": None})
    assert all(chunk["major_code"] is None for chunk in chunks)


# ---------------------------------------------------------------------------
# 4. rights
# ---------------------------------------------------------------------------


def test_archiving_a_source_removes_its_chunks_immediately(corpus, world):
    """A revoked licence must stop serving without re-ingestion.

    The chunks stay in the table -- they are evidence of what was served -- but
    the live join on ``catalog_sources.publicly_retrievable`` excludes them.
    """
    enrolment = {"grade_number": 10, "major_code": "math_physics"}
    assert "ریاضی دهم ریاضی‌فیزیک" in _titles(grounding.retrievable(world, enrolment=enrolment))

    sources_repo.review_source(
        world,
        source_id=corpus["grade10_math"],
        decision="archive",
        reviewer="admin",
        reason="licence withdrawn",
    )

    titles = _titles(grounding.retrievable(world, enrolment=enrolment))
    assert "ریاضی دهم ریاضی‌فیزیک" not in titles
    # The chunks still exist, so the audit can show what was served.
    with world.read() as conn:
        assert (
            conn.scalar(
                "SELECT COUNT(*) FROM ingestion_chunks WHERE source_id = ?",
                (corpus["grade10_math"],),
            )
            > 0
        )


# ---------------------------------------------------------------------------
# 5. the NULL trap
# ---------------------------------------------------------------------------


def test_a_chunk_with_no_grade_is_visible_to_nobody(world):
    """The COALESCE trap: an unscoped chunk must not be admitted everywhere.

    ``COALESCE(grade_number, 10) = 10`` would make an unscoped chunk visible at
    grade 10, and only at grade 10 -- which is worse than it sounds, because it
    is invisible in every test that only checks grade 10.
    """
    source_id = _approved_source(world, title="کتاب بی‌پایه", grade_number=10, edition="nograde")
    _ingest(world, source_id, "فصل ۱\n\n" + "متن " * 40)
    # Force a chunk with no grade, which the pipeline never produces but a
    # future backfill or a direct write could.
    with world.transaction() as conn:
        conn.execute(
            "UPDATE ingestion_chunks SET grade_number = NULL WHERE source_id = ?", (source_id,)
        )

    for grade in (1, 7, 10, 12):
        assert grounding.count_visible(world, {"grade_number": grade, "major_code": None}) == 0, (
            grade
        )


# ---------------------------------------------------------------------------
# Structural: the filter cannot be skipped
# ---------------------------------------------------------------------------


def test_retrievable_has_no_way_to_disable_the_scope(world):
    """The signature is the guarantee: there is no ignore_scope parameter."""
    with pytest.raises(TypeError):
        grounding.retrievable(  # type: ignore[call-arg]
            world,
            enrolment={"grade_number": 10, "major_code": None},
            ignore_scope=True,
        )


def test_an_enrolment_without_a_grade_is_refused(world):
    """Unscoped retrieval is not a supported state."""
    with pytest.raises(grounding.ScopeViolation) as exc:
        grounding.retrievable(world, enrolment={"major_code": "math_physics"})
    assert exc.value.field == "grade_number"


def test_a_non_integer_grade_is_refused(world):
    with pytest.raises(grounding.ScopeViolation):
        grounding.retrievable(world, enrolment={"grade_number": "10", "major_code": None})


def test_two_students_see_disjoint_corpora(corpus, world):
    """The end-to-end statement of the acceptance criterion."""
    a = grounding.retrievable(world, enrolment={"grade_number": 10, "major_code": "math_physics"})
    b = grounding.retrievable(world, enrolment={"grade_number": 10, "major_code": "experimental"})
    keys_a = {chunk["chunk_key"] for chunk in a}
    keys_b = {chunk["chunk_key"] for chunk in b}
    assert keys_a and keys_b
    assert keys_a.isdisjoint(keys_b), keys_a & keys_b
