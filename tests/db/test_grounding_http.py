"""The grounding HTTP surface.

The endpoints are called directly as coroutines, the same way the Phase 4 tests
do: the assertions are about *our* error mapping (403 vs 409 vs 422) and about
the shape of the response, not about FastAPI's plumbing.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import ingestion as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories import catalog as catalog_repo
from deeptutor.db.repositories import sources as sources_repo
from deeptutor.services.ingestion import pipeline

BODY = (
    "فصل ۱: مجموعه‌ها\n\n"
    "مجموعه گردایه‌ای از اشیاء است و هر عضو آن با یک نماد نشان داده می‌شود. "
    "این جمله به اندازهٔ کافی طولانی است تا یک قطعهٔ معنادار بسازد."
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    return db


@pytest.fixture
def seeded(live):
    catalog_repo.create_system(live, code="current", title="نظام فعلی")
    catalog_repo.add_grade(
        live,
        system_code="current",
        grade_number=10,
        title="دهم",
        stage_code="upper_secondary",
        requires_track=True,
    )
    catalog_repo.create_track(live, code="theoretical", title="نظری")
    catalog_repo.create_major(
        live,
        track_code="theoretical",
        code="math_physics",
        title="ریاضی‌فیزیک",
        selectable_grades=(10,),
    )
    source_id = sources_repo.create_source(
        live,
        title="ریاضی دهم",
        source_type="official_book",
        grade_number=10,
        major_code="math_physics",
        subject_code="math",
        edition="1404",
        rights_status="cleared",
        review_status="approved",
    )
    pipeline.run_ingestion(live, source_id=source_id, markdown=BODY, document_key="d1")
    return live


def _search(**kwargs):
    params = dict(
        q="مجموعه چیست",
        grade_number=10,
        major_code="math_physics",
        subject_code=None,
        limit=20,
        min_score=0.25,
    )
    params.update(kwargs)
    return _run(api.search(**params))


def test_search_returns_citable_chunks(seeded):
    payload = _search()
    assert payload["grounded"] is True
    assert payload["count"] >= 1
    assert payload["chunks"][0]["citation"].startswith("[ریاضی دهم")


def test_search_abstains_for_an_unrelated_question(seeded):
    """The book is visible; the *question* is not in it. Search must say so.

    This is the distinction that makes abstention possible at all: a visible
    library is not an answer, and returning the whole corpus for any query is
    how a tutor ends up confidently answering questions its books never address.
    """
    payload = _search(q="انتگرال معین چگونه محاسبه می‌شود")
    assert payload["abstained"] is True
    assert payload["reason"] == "no_relevant_source"
    assert payload["citations"] == []


def test_search_abstains_for_another_track(seeded):
    """No books at all in scope is a different empty result, same shape."""
    payload = _search(q="مجموعه چیست", major_code="experimental")
    assert payload["abstained"] is True


def test_browse_lists_the_whole_visible_corpus(seeded):
    """Browsing is not searching: it returns everything in scope, unfiltered."""
    payload = _run(api.browse(grade_number=10, major_code="math_physics", limit=20))
    assert payload["count"] >= 1
    assert all("citation" in chunk for chunk in payload["chunks"])


def test_search_refuses_an_enrolment_without_a_grade(seeded):
    """Unscoped retrieval is refused at the repository, and surfaces as 403."""
    with pytest.raises(HTTPException) as exc:
        # grade_number is required by the signature, so this exercises the type
        # guard directly rather than a missing query param.
        _run(
            api.search(
                q="مجموعه",
                grade_number=None,
                major_code="math_physics",  # type: ignore[arg-type]
                subject_code=None,
                limit=20,
                min_score=0.25,
            )
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["rule"] == "scope_violation"


def test_an_empty_query_is_refused(seeded):
    """A blank question must not silently become "return everything"."""
    with pytest.raises(HTTPException) as exc:
        _run(
            api.search(
                q="   ",
                grade_number=10,
                major_code="math_physics",
                subject_code=None,
                limit=20,
                min_score=0.25,
            )
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["rule"] == "empty_query"


def test_validate_confirms_a_real_citation(seeded):
    chunks = _search()["chunks"]
    citation = chunks[0]["citation"]
    report = _run(
        api.validate(
            api.CitationRequest(answer=f"پاسخ بر پایهٔ {citation}."),
            grade_number=10,
            major_code="math_physics",
        )
    )
    assert report["valid"] is True


def test_validate_rejects_an_invented_citation(seeded):
    report = _run(
        api.validate(
            api.CitationRequest(answer="پاسخ بر پایهٔ [کتاب ساختگی | فصل ۹]."),
            grade_number=10,
            major_code="math_physics",
        )
    )
    assert report["valid"] is False
    assert report["unverified"] == [("کتاب ساختگی", " فصل ۹")] or report["unverified"]


def test_catalogue_lists_the_available_book(seeded):
    payload = _run(api.catalogue(user_id="u1", grade_number=10, major_code="math_physics"))
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["title"] == "ریاضی دهم"
    assert payload["sources"][0]["chunks"] >= 1


def test_catalogue_excludes_another_major(seeded):
    payload = _run(api.catalogue(user_id="u1", grade_number=10, major_code="experimental"))
    assert payload["sources"] == []


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


def test_ingest_endpoint_records_a_run(seeded):
    source_id = sources_repo.create_source(
        seeded,
        title="فیزیک دهم",
        source_type="official_book",
        grade_number=10,
        major_code="math_physics",
        edition="1404b",
        rights_status="cleared",
        review_status="approved",
    )
    payload = _run(
        api.ingest(api.IngestRequest(source_id=source_id, markdown=BODY, document_key="d2"))
    )
    assert payload["status"] == "succeeded"
    assert payload["chunk_count"] >= 1


def test_ingesting_an_unapproved_source_is_409(seeded):
    """409 not 422: the request is fine, the source's state forbids it."""
    source_id = sources_repo.create_source(
        seeded, title="x", source_type="official_book", grade_number=10, edition="z"
    )
    with pytest.raises(HTTPException) as exc:
        _run(api.ingest(api.IngestRequest(source_id=source_id, markdown=BODY)))
    assert exc.value.status_code == 409
    assert exc.value.detail["rule"] == "source_not_approved"


def test_list_runs_returns_history(seeded):
    payload = _run(api.list_runs(source_id=None, status=None, limit=50))
    assert payload["count"] >= 1


def test_get_run_includes_its_chunks(seeded):
    runs = _run(api.list_runs(source_id=None, status=None, limit=50))["runs"]
    run_id = runs[0]["id"]
    payload = _run(api.get_run(run_id))
    assert payload["run"]["id"] == run_id
    assert len(payload["chunks"]) >= 1


def test_unknown_run_is_404(seeded):
    with pytest.raises(HTTPException) as exc:
        _run(api.get_run("nope"))
    assert exc.value.status_code == 404


def test_recover_reports_what_it_reclaimed(seeded):
    with seeded.transaction() as conn:
        conn.execute(
            "INSERT INTO ingestion_runs (id, source_id, status, created_at, updated_at) "
            "VALUES ('stale1', 'x', 'running', '2020-01-01T00:00:00+00:00', "
            "'2020-01-01T00:00:00+00:00')"
        )
    payload = _run(api.recover(older_than_seconds=900))
    assert "stale1" in payload["recovered"]


def test_database_disabled_is_503(monkeypatch):
    disabled = DatabaseSettings(app_url="", backend="sqlite")
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: disabled)
    with pytest.raises(HTTPException) as exc:
        _run(
            api.search(
                q="مجموعه",
                grade_number=10,
                major_code=None,
                subject_code=None,
                limit=20,
                min_score=0.25,
            )
        )
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# The enrolment is resolved, not accepted
# ---------------------------------------------------------------------------


def _learner(db, user_id, *, grade_number, major_code=None):
    from deeptutor.db.repositories.identity import IdentityRepository

    IdentityRepository(db).save(
        user_id,
        {
            "id": user_id,
            "hash": "x",
            "role": "user",
            "learner_profile": {"grade_number": grade_number, "major_code": major_code},
        },
    )


def test_a_stored_profile_overrides_the_query_scope(seeded):
    """The docstring said the parameters must match the profile. Now they do.

    A grade-7 account asking with ``?grade_number=10&major_code=math_physics``
    must be answered as a grade-7 student -- that is, with nothing from the
    grade-10 book -- instead of being handed another grade's material.
    """
    _learner(seeded, "grade7", grade_number=7)

    payload = _search(user_id="grade7", grade_number=10, major_code="math_physics")

    assert payload["abstained"] is True
    assert payload["scope"]["grade_number"] == 7
    assert payload["scope"]["major_code"] is None


def test_the_scope_is_reported_so_a_client_cannot_assume(seeded):
    _learner(seeded, "grade10", grade_number=10, major_code="math_physics")

    payload = _search(user_id="grade10", grade_number=10, major_code="math_physics")

    assert payload["scope"] == {
        "grade_number": 10,
        "major_code": "math_physics",
        "unverified": False,
    }


def test_browse_is_scoped_by_the_profile_too(seeded):
    _learner(seeded, "grade7", grade_number=7)

    payload = _run(api.browse(user_id="grade7", grade_number=10, major_code="math_physics", limit=20))

    assert payload["count"] == 0
    assert payload["scope"]["grade_number"] == 7


def test_a_dev_caller_with_no_profile_is_marked_unverified(seeded, monkeypatch):
    from deeptutor.services import scope

    monkeypatch.setattr(scope, "_auth_enabled", lambda: False)

    payload = _search(user_id="anon", grade_number=10, major_code="math_physics")

    assert payload["scope"]["unverified"] is True


def test_the_catalogue_does_not_widen_when_no_major_is_given(seeded):
    """The old predicate was ``(? IS NULL OR s.major_code = ?)``.

    A caller who passed no major therefore matched every major's books -- the
    widening ``scope_sql`` forbids, reintroduced here in a single line because
    it was spelled differently. A student with no major must see only books
    with no major.
    """
    _learner(seeded, "grade7", grade_number=7)

    payload = _run(api.catalogue(user_id="grade7", grade_number=7, major_code=None))

    assert payload["sources"] == [], "a grade-7 student has no grade-10 math book"
    assert payload["major_code"] is None


def test_the_catalogue_still_shows_the_matching_major(seeded):
    _learner(seeded, "grade10", grade_number=10, major_code="math_physics")

    payload = _run(
        api.catalogue(user_id="grade10", grade_number=10, major_code="math_physics")
    )

    assert [row["title"] for row in payload["sources"]] == ["ریاضی دهم"]
