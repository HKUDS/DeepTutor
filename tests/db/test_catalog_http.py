"""The catalog HTTP surface, exercised without a live server.

Why these exist separately from the repository tests
----------------------------------------------------
The repository guarantees the *rule*. The router guarantees that the rule is
actually reachable and that its violations come back as useful HTTP. Those are
different failures: a correct repository behind a router that returns 500 for
every validation error is a working backend nobody can use.

The tests call the endpoint functions directly rather than through a client.
That is deliberate -- they are checking our mapping (422 vs 404 vs 409), not
FastAPI's plumbing, and calling the coroutine avoids spinning up the whole app
for each case.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import catalog as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories import catalog as catalog_repo
from deeptutor.db.repositories import sources as sources_repo


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live_db(db, monkeypatch):
    """Point the router at the migrated test database.

    ``reset_database_settings`` is required because the settings are cached at
    module level; without it a previous test's DSN would leak in, which is the
    same class of bug the Phase 2 tests hit with ``AUTH_DIR``.
    """
    dsn = db.settings.app_url
    settings = DatabaseSettings(app_url=dsn, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    return db


@pytest.fixture
def seeded(live_db):
    catalog_repo.create_system(live_db, code="current", title="نظام فعلی")
    for grade in range(1, 13):
        stage = (
            "elementary" if grade <= 6 else "lower_secondary" if grade <= 9 else "upper_secondary"
        )
        catalog_repo.add_grade(
            live_db,
            system_code="current",
            grade_number=grade,
            title=f"پایه {grade}",
            stage_code=stage,
            requires_track=grade >= 10,
        )
    catalog_repo.create_track(live_db, code="theoretical", title="نظری")
    catalog_repo.create_major(
        live_db,
        track_code="theoretical",
        code="math_physics",
        title="ریاضی‌فیزیک",
        selectable_grades=(10, 11, 12),
    )
    return live_db


def test_grades_endpoint_returns_twelve(seeded):
    payload = _run(api.get_grades(system="current"))
    assert len(payload["grades"]) == 12


def test_subjects_endpoint_narrows_by_major(seeded):
    catalog_repo.create_subject(
        seeded, code="math", title="ریاضی", grade_number=10, major_code="math_physics"
    )
    catalog_repo.create_subject(seeded, code="farsi", title="فارسی", grade_number=10)

    payload = _run(api.get_subjects(grade_number=10, major="math_physics", system="current"))
    assert {s["code"] for s in payload["subjects"]} == {"math", "farsi"}

    shared_only = _run(api.get_subjects(grade_number=10, major=None, system="current"))
    assert {s["code"] for s in shared_only["subjects"]} == {"math", "farsi"}


def test_enrolment_endpoint_resolves_a_valid_combination(seeded):
    response = _run(api.get_enrolment(grade_number=10, major="math_physics", system="current"))
    assert response.grade_number == 10
    assert response.major_code == "math_physics"


def test_enrolment_endpoint_maps_a_missing_major_to_422(seeded):
    """The client needs the field name to highlight, not a generic 500."""
    with pytest.raises(HTTPException) as exc:
        _run(api.get_enrolment(grade_number=10, major=None, system="current"))
    assert exc.value.status_code == 422
    assert exc.value.detail["rule"] == "major_required"
    assert exc.value.detail["field"] == "major_code"


def test_enrolment_endpoint_maps_an_unknown_system_to_404(seeded):
    with pytest.raises(HTTPException) as exc:
        _run(api.get_enrolment(grade_number=10, major="x", system="nope"))
    assert exc.value.status_code == 404


def test_admin_creates_and_reviews_a_source(seeded):
    created = _run(
        api.create_source(
            api.SourceCreate(
                title="ریاضی دهم",
                source_type="official_book",
                grade_number=10,
                major_code="math_physics",
                edition="1404",
            )
        )
    )
    source_id = created["id"]
    assert created["source"]["publicly_retrievable"] == 0

    reviewed = _run(
        api.review_source(
            source_id,
            api.ReviewRequest(decision="approve", reviewer="admin", reason="licence on file"),
        )
    )
    assert reviewed["source"]["publicly_retrievable"] == 1
    assert len(reviewed["history"]) == 1


def test_reviewing_a_source_twice_from_the_same_state_is_409(seeded):
    created = _run(api.create_source(api.SourceCreate(title="x", source_type="notes", edition="1")))
    source_id = created["id"]
    _run(api.review_source(source_id, api.ReviewRequest(decision="approve", reviewer="a")))
    with pytest.raises(HTTPException) as exc:
        _run(api.review_source(source_id, api.ReviewRequest(decision="approve", reviewer="b")))
    # 409, not 422: nothing is wrong with the request, the state conflicts.
    assert exc.value.status_code == 409
    assert exc.value.detail["rule"] == "invalid_transition"


def test_duplicate_check_endpoint_reports_the_existing_source(seeded):
    _run(api.create_source(api.SourceCreate(title="dup", source_type="notes", edition="1")))
    payload = _run(
        api.find_duplicates(
            title="dup",
            source_type="notes",
            grade_number=None,
            major_code=None,
            subject_code=None,
            edition="1",
        )
    )
    assert len(payload["duplicates"]) == 1


def test_source_detail_includes_history(seeded):
    created = _run(api.create_source(api.SourceCreate(title="h", source_type="notes", edition="1")))
    source_id = created["id"]
    _run(api.review_source(source_id, api.ReviewRequest(decision="approve", reviewer="a")))
    detail = _run(api.get_source(source_id))
    assert len(detail["reviews"]) == 1
    assert len(detail["versions"]) == 1


def test_unknown_source_detail_is_404(seeded):
    with pytest.raises(HTTPException) as exc:
        _run(api.get_source("nope"))
    assert exc.value.status_code == 404


def test_database_disabled_returns_503(monkeypatch):
    from deeptutor.db.config import DatabaseSettings

    disabled = DatabaseSettings(app_url="", backend="sqlite")
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: disabled)
    with pytest.raises(HTTPException) as exc:
        _run(api.get_grades(system="current"))
    assert exc.value.status_code == 503


def test_invalid_transition_carries_the_allowed_states(seeded):
    """The error must tell the caller what *is* legal, not just what is not."""
    created = _run(api.create_source(api.SourceCreate(title="t", source_type="notes", edition="1")))
    with pytest.raises(HTTPException) as exc:
        _run(api.review_source(created["id"], api.ReviewRequest(decision="restore", reviewer="a")))
    assert exc.value.status_code == 409
    assert "archived" in str(exc.value.detail["message"])
