"""Course API and course-state aggregation tests."""

from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

courses_router_module = importlib.import_module("deeptutor.api.routers.courses")
courses_service_module = importlib.import_module("deeptutor.services.courses")
courses_router = courses_router_module.router

from deeptutor.services.courses import COURSE_RESOURCE_KINDS, CourseService


class _FailingSubsystem:
    def __getattr__(self, _name: str):
        raise RuntimeError("subsystem unavailable")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(courses_router, prefix="/api/courses")
    return app


@pytest.fixture
def course_service(tmp_path, monkeypatch) -> CourseService:
    service = CourseService(root=tmp_path / "courses")
    monkeypatch.setattr(courses_router_module, "get_course_service", lambda: service)
    monkeypatch.setattr(courses_service_module, "get_course_service", lambda: service)
    return service


@pytest.fixture
def failing_subsystems(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.current_kb_manager",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.book.engine.get_book_engine",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.service.get_notebook_manager",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.learning.service.LearningService",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.reading.catalog_store.ReadingCatalogStore",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.services.partners.get_partner_manager",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_session_store",
        lambda: _FailingSubsystem(),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store",
        lambda: _FailingSubsystem(),
    )


def _create_course(client: TestClient, **overrides) -> dict:
    payload = {"name": "Calculus", "description": "Limits and derivatives"} | overrides
    response = client.post("/api/courses", json=payload)
    assert response.status_code == 200
    return response.json()["course"]


def test_attach_and_detach_resource_round_trip(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        attached = client.post(
            f"/api/courses/{course['id']}/resources",
            json={"kind": "book", "ref_id": "book-1", "label": "Analysis I"},
        )

        assert attached.status_code == 200
        resource = attached.json()["resource"]
        assert resource["kind"] == "book"
        assert resource["ref_id"] == "book-1"
        assert resource["label"] == "Analysis I"

        listing = client.get("/api/courses").json()["courses"]
        assert listing[0]["resources"] == [resource]

        detached = client.delete(f"/api/courses/{course['id']}/resources/{resource['id']}")
        assert detached.status_code == 200
        assert detached.json() == {"deleted": True}
        assert client.get("/api/courses").json()["courses"][0]["resources"] == []

        missing = client.delete(f"/api/courses/{course['id']}/resources/{resource['id']}")
        assert missing.status_code == 404


def test_duplicate_resource_attach_is_idempotent(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        url = f"/api/courses/{course['id']}/resources"
        payload = {"kind": "notebook", "ref_id": "nb-1", "label": "Problem notes"}

        first = client.post(url, json=payload)
        second = client.post(url, json=payload)

        assert first.status_code == second.status_code == 200
        assert first.json()["resource"]["id"] == second.json()["resource"]["id"]
        stored = client.get("/api/courses").json()["courses"][0]["resources"]
        assert len(stored) == 1


def test_unknown_resource_kind_returns_400(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        response = client.post(
            f"/api/courses/{course['id']}/resources",
            json={"kind": "video_library", "ref_id": "videos"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown resource kind"


def test_missing_course_returns_404(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        attach = client.post(
            "/api/courses/course_missing/resources",
            json={"kind": "book", "ref_id": "book-1"},
        )
        detach = client.delete("/api/courses/course_missing/resources/resource_missing")
        state = client.get("/api/courses/course_missing/state")

    assert attach.status_code == 404
    assert detach.status_code == 404
    assert state.status_code == 404


def test_state_degrades_when_every_subsystem_fails(
    course_service: CourseService,
    failing_subsystems: None,
) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client, instructions="Use epsilon-delta proofs.")
        for kind in COURSE_RESOURCE_KINDS:
            attached = client.post(
                f"/api/courses/{course['id']}/resources",
                json={"kind": kind, "ref_id": f"missing-{kind}"},
            )
            assert attached.status_code == 200
        response = client.get(f"/api/courses/{course['id']}/state")

    assert response.status_code == 200
    state = response.json()
    assert state["course"]["instructions"] == "Use epsilon-delta proofs."
    assert len(state["resources"]) == len(COURSE_RESOURCE_KINDS)
    assert all(resource["available"] is False for resource in state["resources"])
    assert all(resource["detail"] == {} for resource in state["resources"])
    assert state["sessions"] == {"active": 0, "archived": 0, "recent": []}
    assert state["mastery"] == {"paths": []}
    assert state["question_bank"] == {
        "total": 0,
        "wrong": 0,
        "weak_categories": [],
    }
    assert state["syllabus"] == {
        "total": 0,
        "covered": 0,
        "next": None,
        "units": [],
    }
    assert state["reading"] == {"workspaces": []}


def test_resource_candidates_literal_route_and_empty_fallbacks(
    course_service: CourseService,
    failing_subsystems: None,
) -> None:
    with TestClient(_build_app()) as client:
        response = client.get("/api/courses/resource-candidates")

    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert set(candidates) == set(COURSE_RESOURCE_KINDS)
    assert all(rows == [] for rows in candidates.values())


def test_create_and_patch_course_learning_defaults(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client, instructions="Show every algebra step.")
        response = client.patch(
            f"/api/courses/{course['id']}",
            json={
                "instructions": "Prefer geometric intuition.",
                "default_capability": "deep_solve",
                "default_persona": "socratic",
            },
        )

    assert response.status_code == 200
    updated = response.json()["course"]
    assert updated["name"] == "Calculus"
    assert updated["instructions"] == "Prefer geometric intuition."
    assert updated["default_capability"] == "deep_solve"
    assert updated["default_persona"] == "socratic"


def test_archive_round_trip_keeps_course_in_listing(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        _create_course(client, name="Linear Algebra")
        before = client.get("/api/courses").json()["courses"]
        before_ids = {item["id"] for item in before}

        archived_response = client.patch(
            f"/api/courses/{course['id']}",
            json={"status": "archived"},
        )
        archived = archived_response.json()["course"]
        during = client.get("/api/courses").json()["courses"]

        restored_response = client.patch(
            f"/api/courses/{course['id']}",
            json={"status": "active"},
        )
        restored = restored_response.json()["course"]
        after = client.get("/api/courses").json()["courses"]

    assert archived_response.status_code == 200
    assert archived["status"] == "archived"
    assert archived["archived_at"]
    assert len(during) == len(before)
    assert {item["id"] for item in during} == before_ids
    assert restored_response.status_code == 200
    assert restored["status"] == "active"
    assert not restored["archived_at"]
    assert len(after) == len(before)
    assert {item["id"] for item in after} == before_ids


def test_invalid_course_status_returns_400(course_service: CourseService) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        response = client.patch(
            f"/api/courses/{course['id']}",
            json={"status": "finished"},
        )

    assert response.status_code == 400
    assert "Unknown course status" in response.json()["detail"]


def test_put_syllabus_replaces_drops_blanks_and_renumbers(
    course_service: CourseService,
) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        url = f"/api/courses/{course['id']}/syllabus"
        initial = client.put(
            url,
            json={"units": [{"title": "Limits"}, {"title": "Derivatives"}]},
        )
        replacement = client.put(
            url,
            json={
                "units": [
                    {"title": "   ", "topics": ["dropped"]},
                    {"title": "Integrals", "topics": ["Riemann sums"]},
                    {"title": "Series"},
                ]
            },
        )

    assert initial.status_code == 200
    assert replacement.status_code == 200
    units = replacement.json()["course"]["syllabus"]
    assert [unit["title"] for unit in units] == ["Integrals", "Series"]
    assert [unit["position"] for unit in units] == [0, 1]
    assert all(unit["title"] not in {"Limits", "Derivatives"} for unit in units)


def test_put_syllabus_preserves_covered_for_existing_id(
    course_service: CourseService,
) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        syllabus_url = f"/api/courses/{course['id']}/syllabus"
        created = client.put(syllabus_url, json={"units": [{"title": "Limits"}]})
        unit_id = created.json()["course"]["syllabus"][0]["id"]
        toggled = client.patch(
            f"{syllabus_url}/{unit_id}",
            json={"covered": True},
        )
        replaced = client.put(
            syllabus_url,
            json={
                "units": [
                    {
                        "id": unit_id,
                        "title": "Limits and continuity",
                        "covered": False,
                    }
                ]
            },
        )

    assert toggled.status_code == 200
    assert replaced.status_code == 200
    unit = replaced.json()["course"]["syllabus"][0]
    assert unit["id"] == unit_id
    assert unit["covered"] is True


def test_patch_syllabus_unit_toggles_and_unknown_is_404(
    course_service: CourseService,
) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        syllabus_url = f"/api/courses/{course['id']}/syllabus"
        created = client.put(syllabus_url, json={"units": [{"title": "Limits"}]})
        unit_id = created.json()["course"]["syllabus"][0]["id"]

        covered = client.patch(f"{syllabus_url}/{unit_id}", json={"covered": True})
        uncovered = client.patch(f"{syllabus_url}/{unit_id}", json={"covered": False})
        missing = client.patch(f"{syllabus_url}/unit_missing", json={"covered": True})

    assert covered.status_code == 200
    assert covered.json()["unit"]["covered"] is True
    assert uncovered.status_code == 200
    assert uncovered.json()["unit"]["covered"] is False
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Syllabus unit not found"


def test_state_reports_syllabus_progress_and_next_unit(
    course_service: CourseService,
    failing_subsystems: None,
) -> None:
    with TestClient(_build_app()) as client:
        course = _create_course(client)
        syllabus_url = f"/api/courses/{course['id']}/syllabus"
        created = client.put(
            syllabus_url,
            json={
                "units": [
                    {"title": "Limits", "topics": ["Continuity"]},
                    {"title": "Derivatives", "topics": ["Chain rule"]},
                ]
            },
        )
        units = created.json()["course"]["syllabus"]
        client.patch(f"{syllabus_url}/{units[0]['id']}", json={"covered": True})
        response = client.get(f"/api/courses/{course['id']}/state")

    assert response.status_code == 200
    syllabus = response.json()["syllabus"]
    assert syllabus["total"] == 2
    assert syllabus["covered"] == 1
    assert syllabus["next"] == {
        "id": units[1]["id"],
        "title": "Derivatives",
        "position": 1,
    }
    assert [unit["covered"] for unit in syllabus["units"]] == [True, False]
    assert [unit["wrong_questions"] for unit in syllabus["units"]] == [0, 0]


def test_syllabus_wrong_questions_use_bidirectional_substring_matching(
    course_service: CourseService,
    failing_subsystems: None,
    monkeypatch,
) -> None:
    from deeptutor.services import courses_state

    async def question_bank_state(_session_ids: set[str]) -> dict:
        return {
            "total": 12,
            "wrong": 9,
            "weak_categories": [
                {"name": "LINEAR ALGEBRA", "wrong": 3},
                {"name": "Differential Equations", "wrong": 4},
                {"name": "Geometry", "wrong": 2},
            ],
        }

    monkeypatch.setattr(courses_state, "_question_bank_state", question_bank_state)

    with TestClient(_build_app()) as client:
        course = _create_course(client)
        client.put(
            f"/api/courses/{course['id']}/syllabus",
            json={
                "units": [
                    {"title": "Vectors", "topics": ["algebra"]},
                    {
                        "title": "ODEs",
                        "topics": ["Differential Equations for Engineers"],
                    },
                    {"title": "Limits", "topics": ["Calculus"]},
                ]
            },
        )
        response = client.get(f"/api/courses/{course['id']}/state")

    assert response.status_code == 200
    assert [unit["wrong_questions"] for unit in response.json()["syllabus"]["units"]] == [
        3,
        4,
        0,
    ]


def test_legacy_six_field_courses_json_still_loads(course_service: CourseService) -> None:
    course_service.root.mkdir(parents=True, exist_ok=True)
    course_service.index_file.write_text(
        json.dumps(
            {
                "courses": [
                    {
                        "id": "course_legacy",
                        "name": "Legacy physics",
                        "description": "Six-field folder",
                        "color": "#3F6F8F",
                        "created_at": 10.0,
                        "updated_at": 20.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with TestClient(_build_app()) as client:
        response = client.get("/api/courses")

    assert response.status_code == 200
    course = response.json()["courses"][0]
    assert course["id"] == "course_legacy"
    assert course["instructions"] == ""
    assert course["agent_notes"] == ""
    assert course["default_capability"] == ""
    assert course["default_persona"] == ""
    assert course["resources"] == []
