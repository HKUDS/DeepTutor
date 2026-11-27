"""Phase 4 acceptance: the academic catalog tree and its enrolment rules.

What is actually being proven
-----------------------------
The roadmap asks for "tests for valid and invalid major/subject" and "separation
of current curriculum from archive". Those two sentences hide the failure that
matters: a lookup that *silently* returns nothing (or everything) for an invalid
combination. A learner in grade 9 filtering by major should see subjects, not an
empty list; a learner in grade 10 without a major should be told to choose one,
not be handed every subject from every track.

So most tests here assert on the *refusal* and on the *scope of the result*, not
merely that a call succeeds.
"""

from __future__ import annotations

import pytest

from deeptutor.db.repositories import catalog as repo


@pytest.fixture
def seeded(db):
    """The current Iranian system: 12 grades, 2 tracks, 3 majors."""
    repo.create_system(db, code="current", title="نظام فعلی", status="current")
    for grade in range(1, 13):
        if grade <= 6:
            stage = "elementary"
        elif grade <= 9:
            stage = "lower_secondary"
        else:
            stage = "upper_secondary"
        repo.add_grade(
            db,
            system_code="current",
            grade_number=grade,
            title=f"پایه {grade}",
            stage_code=stage,
            requires_track=grade >= 10,
        )
    repo.create_track(db, code="theoretical", title="نظری", kind="theoretical")
    repo.create_track(db, code="vocational", title="هنرستان", kind="vocational")
    repo.create_major(
        db,
        track_code="theoretical",
        code="math_physics",
        title="ریاضی‌فیزیک",
        selectable_grades=(10, 11, 12),
    )
    repo.create_major(
        db,
        track_code="theoretical",
        code="experimental",
        title="علوم تجربی",
        selectable_grades=(10, 11, 12),
    )
    repo.create_major(
        db,
        track_code="vocational",
        code="accounting",
        title="حسابداری",
        selectable_grades=(10, 11, 12),
    )
    return db


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_twelve_grades_with_three_stages(seeded):
    grades = repo.list_grades(seeded, "current")
    assert [g["grade_number"] for g in grades] == list(range(1, 13))
    stages = {g["stage_code"] for g in grades}
    assert stages == {"elementary", "lower_secondary", "upper_secondary"}


def test_only_upper_secondary_requires_a_track(seeded):
    """D-006: the track choice starts at grade 10, not at a number hardcoded in code."""
    grades = {g["grade_number"]: g for g in repo.list_grades(seeded, "current")}
    for grade in range(1, 10):
        assert grades[grade]["requires_track"] == 0, grade
    for grade in (10, 11, 12):
        assert grades[grade]["requires_track"] == 1, grade


def test_stage_boundaries_are_enforced(seeded):
    """Grade 7 is not elementary. A wrong stage must be refused, not stored."""
    with pytest.raises(repo.CatalogError) as exc:
        repo.add_grade(
            seeded,
            system_code="current",
            grade_number=7,
            title="هفتم",
            stage_code="elementary",
        )
    assert exc.value.rule == "stage_mismatch"
    assert exc.value.field == "stage_code"


# ---------------------------------------------------------------------------
# Valid and invalid major / subject
# ---------------------------------------------------------------------------


def test_major_selectable_only_at_its_grades(seeded):
    assert len(repo.list_majors(seeded, grade_number=10)) == 3
    # No major is selectable below grade 10 in this seed.
    assert repo.list_majors(seeded, grade_number=9) == []


def test_vocational_major_is_reachable_through_its_track_only(seeded):
    theoretical = repo.list_majors(seeded, track_code="theoretical", grade_number=10)
    assert {m["code"] for m in theoretical} == {"math_physics", "experimental"}
    vocational = repo.list_majors(seeded, track_code="vocational", grade_number=10)
    assert {m["code"] for m in vocational} == {"accounting"}


def test_enrolment_accepts_a_complete_valid_combination(seeded):
    resolved = repo.resolve_enrolment(seeded, grade_number=10, major_code="experimental")
    assert resolved["stage_code"] == "upper_secondary"
    assert resolved["track_code"] == "theoretical"
    assert resolved["major_code"] == "experimental"


def test_enrolment_refuses_a_major_when_a_track_is_required_but_missing(seeded):
    with pytest.raises(repo.CatalogError) as exc:
        repo.resolve_enrolment(seeded, grade_number=10)
    assert exc.value.rule == "major_required"
    assert exc.value.field == "major_code"


def test_enrolment_refuses_a_major_below_grade_10(seeded):
    """Grades 1-9 have no track, so a major there is a client bug, not a preference."""
    with pytest.raises(repo.CatalogError) as exc:
        repo.resolve_enrolment(seeded, grade_number=5, major_code="math_physics")
    assert exc.value.rule == "major_not_applicable"


def test_vocational_major_resolves_with_its_own_track(seeded):
    """The track is derived from the major, not assumed to be theoretical.

    Hardcoding ``theoretical`` here would be invisible until the first هنرستان
    student enrolled and got the wrong subject list.
    """
    resolved = repo.resolve_enrolment(seeded, grade_number=11, major_code="accounting")
    assert resolved["track_code"] == "vocational"
    assert resolved["major_code"] == "accounting"


def test_enrolment_refuses_a_major_not_selectable_at_that_grade(seeded):
    """A real major, at a grade where it may not be chosen."""
    repo.create_major(
        seeded,
        track_code="theoretical",
        code="senior_only",
        title="فقط دوازدهم",
        selectable_grades=(12,),
    )
    with pytest.raises(repo.CatalogError) as exc:
        repo.resolve_enrolment(seeded, grade_number=10, major_code="senior_only")
    assert exc.value.rule == "major_not_selectable"
    assert exc.value.field == "major_code"
    # And it does resolve where it is offered, so the refusal above is about the
    # grade and not about the major being unknown.
    assert (
        repo.resolve_enrolment(seeded, grade_number=12, major_code="senior_only")["major_code"]
        == "senior_only"
    )


def test_enrolment_refuses_an_unknown_major(seeded):
    with pytest.raises(repo.CatalogError) as exc:
        repo.resolve_enrolment(seeded, grade_number=10, major_code="nope")
    assert exc.value.rule == "major_not_selectable"


def test_subject_scope_includes_shared_and_excludes_foreign_majors(seeded):
    """The boundary Phase 5 depends on to prevent track leakage."""
    repo.create_subject(
        seeded, code="math", title="ریاضی", grade_number=10, major_code="math_physics"
    )
    repo.create_subject(
        seeded, code="biology", title="زیست", grade_number=10, major_code="experimental"
    )
    repo.create_subject(seeded, code="farsi", title="فارسی", grade_number=10)

    for_math = {
        s["code"]
        for s in repo.list_grade_subjects(seeded, grade_number=10, major_code="math_physics")
    }
    # The shared subject is present; the other major's subject is absent.
    assert for_math == {"math", "farsi"}

    for_experimental = {
        s["code"]
        for s in repo.list_grade_subjects(seeded, grade_number=10, major_code="experimental")
    }
    assert for_experimental == {"biology", "farsi"}


def test_duplicate_subject_is_refused_by_the_constraint(seeded):
    repo.create_subject(seeded, code="math", title="ریاضی۱", grade_number=10)
    with pytest.raises(repo.CatalogError) as exc:
        repo.create_subject(seeded, code="math", title="ریاضی۲", grade_number=10)
    assert exc.value.rule == "duplicate_subject"


# ---------------------------------------------------------------------------
# Current vs archive (D-007)
# ---------------------------------------------------------------------------


def test_archived_system_cannot_accept_an_enrolment(seeded):
    repo.create_system(
        seeded,
        code="pre_university",
        title="پیش‌دانشگاهی",
        status="archived",
        effective_to_year=1390,
        sort_order=10,
    )
    repo.add_grade(
        seeded,
        system_code="pre_university",
        grade_number=13,
        title="پیش‌دانشگاهی",
        stage_code="upper_secondary",
    )
    with pytest.raises(repo.CatalogError) as exc:
        repo.resolve_enrolment(seeded, grade_number=13, system_code="pre_university")
    assert exc.value.rule == "archived_system"


def test_archived_system_stays_readable(seeded):
    """Archived means 'no new enrolment', not 'deleted'. History must resolve."""
    repo.create_system(
        seeded, code="old_secondary", title="نظام قدیم", status="archived", sort_order=20
    )
    repo.add_grade(
        seeded,
        system_code="old_secondary",
        grade_number=1,
        title="سال اول",
        stage_code="elementary",
    )
    archived_grades = repo.list_grades(seeded, "old_secondary")
    assert len(archived_grades) == 1

    current_grades = repo.list_grades(seeded, "current")
    # The archive's grade 1 and the current system's grade 1 are separate rows;
    # neither listing leaks into the other.
    assert len(current_grades) == 12


def test_current_and_archived_do_not_collide_on_grade_number(seeded):
    """Both systems have a grade 1; the unique key is (system, number), not number."""
    repo.create_system(seeded, code="old", title="قدیم", status="archived")
    repo.add_grade(
        seeded, system_code="old", grade_number=1, title="اول قدیم", stage_code="elementary"
    )
    # If the constraint were on grade_number alone this would have failed, and
    # the current system's grade 1 would have been shadowed.
    assert len(repo.list_grades(seeded, "current")) == 12
    assert len(repo.list_grades(seeded, "old")) == 1


def test_unknown_system_is_a_not_found_not_an_empty_list(seeded):
    with pytest.raises(repo.CatalogNotFound):
        repo.list_grades(seeded, "does_not_exist")


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def test_curriculum_versions_are_unique_per_school_year(seeded):
    repo.create_version(seeded, label="main", school_year="1404-1405")
    with pytest.raises(repo.CatalogError) as exc:
        repo.create_version(seeded, label="main", school_year="1404-1405")
    assert exc.value.rule == "duplicate_version"


def test_two_labels_in_one_school_year_are_allowed(seeded):
    repo.create_version(seeded, label="main", school_year="1404-1405")
    repo.create_version(seeded, label="revised", school_year="1404-1405")
    assert repo.create_version(seeded, label="main", school_year="1405-1406")


def test_invalid_version_status_is_refused(seeded):
    with pytest.raises(repo.CatalogError) as exc:
        repo.create_version(seeded, label="x", school_year="1404", status="live")
    assert exc.value.rule == "invalid_status"


def test_shared_subject_cannot_be_duplicated_with_a_null_major(seeded):
    """Regression: a UNIQUE over a nullable column does not constrain.

    The first version of V0006 declared ``UNIQUE (code, grade_number,
    major_code)`` inline. Because ``major_code`` is NULL for shared subjects and
    SQL treats NULL as distinct from NULL, the same shared subject could be
    inserted twice at the same grade. That is the V0005 failure mode again -- a
    constraint that looks present and enforces nothing -- so it is pinned here.
    """
    repo.create_subject(seeded, code="farsi", title="فارسی", grade_number=7)
    with pytest.raises(repo.CatalogError) as exc:
        repo.create_subject(seeded, code="farsi", title="فارسی ۲", grade_number=7)
    assert exc.value.rule == "duplicate_subject"

    # The scoped variant is still allowed, so the fix did not over-constrain.
    assert repo.create_subject(
        seeded, code="farsi", title="فارسی", grade_number=7, major_code="math_physics"
    )
